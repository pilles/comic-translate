#!/usr/bin/env python3
"""Banc de traduction : exerce le vrai traducteur Custom de l'app contre un
serveur OpenAI-compatible (Ollama en pratique), sans relais HTTP.

Reprend les 6 cas du banc `test_traduction.py` écrit le 2026-09-11 (phrases
inventées, cf. tools/bench_cases.py) et réutilise le code réel de l'app :
`CustomTranslation` (modules/translation/llm/custom.py), le prompt
(`build_user_prompt`) et le parsing de la réponse (`set_texts_from_json`).
Si l'app change son format de prompt ou de parsing, ce banc casse avec elle.

Usage :
    uv run python tools/bench_translation.py
    uv run python tools/bench_translation.py --model translategemma:12b --csv out.csv
    uv run python tools/bench_translation.py --cases tools/bench_cases.example.yaml
"""

from __future__ import annotations

import argparse
import csv
import errno
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402  (après l'insertion dans sys.path)

from modules.translation.llm import gpt as gpt_module  # noqa: E402
from modules.translation.llm.custom import CustomTranslation  # noqa: E402
from modules.utils.textblock import TextBlock  # noqa: E402
from modules.utils.translator_utils import set_texts_from_json  # noqa: E402
from tools.bench_cases import DEFAULT_CASES, BenchCase  # noqa: E402
from tools._common import sanitize_csv_cell as _sanitize_csv_cell  # noqa: E402

DEFAULT_URL = "http://daaminim4.local:11434/v1"
DEFAULT_MODEL = "translategemma:12b"
DEFAULT_SOURCE_LANG = "English"
DEFAULT_TARGET_LANG = "French"
BENCH_API_KEY_ENV_VAR = "BENCH_API_KEY"

SENTINEL = "__COMIC_TRANSLATE_BENCH_SENTINEL__"

# --- Statuts de classification (ordre des règles, cf. specs/01 §4) ---------
CONNEXION_REFUSEE = "CONNEXION_REFUSEE"
INJOIGNABLE = "INJOIGNABLE"
TIMEOUT = "TIMEOUT"
MODELE_ABSENT = "MODELE_ABSENT"
ERREUR_HTTP = "ERREUR_HTTP"
TRONQUE = "TRONQUE"
JSON_INVALIDE = "JSON_INVALIDE"
JSON_NON_EXTRAIT = "JSON_NON_EXTRAIT"
PAS_DE_JSON = "PAS_DE_JSON"
CLES_MANQUANTES = "CLES_MANQUANTES"
TYPE_INATTENDU = "TYPE_INATTENDU"
VIDE = "VIDE"
NON_TRADUIT = "NON_TRADUIT"
OK = "OK"
# Statut de secours, hors des 14 règles de la conception : une erreur de
# programmation ou un cas non prévu ne doit jamais faire planter tout le
# banc, mais ne doit pas non plus être maquillé en un des statuts officiels.
ERREUR_INATTENDUE = "ERREUR_INATTENDUE"

# --- Catégories d'exception (entrée `exc_type` de classify_result) ---------
EXC_CONNECTION_REFUSED = "connection_refused"
EXC_CONNECTION_ERROR = "connection_error"
EXC_TIMEOUT = "timeout"

FAILING_STATUSES = frozenset(
    {
        CONNEXION_REFUSEE,
        INJOIGNABLE,
        TIMEOUT,
        MODELE_ABSENT,
        ERREUR_HTTP,
        TRONQUE,
        JSON_INVALIDE,
        JSON_NON_EXTRAIT,
        PAS_DE_JSON,
        CLES_MANQUANTES,
        TYPE_INATTENDU,
        VIDE,
        NON_TRADUIT,
        ERREUR_INATTENDUE,
    }
)


def _normalize_for_comparison(text: str) -> str:
    return " ".join(text.split()).casefold()


def _is_allowed_unchanged(index: int, allow_unchanged: list[int] | bool | None) -> bool:
    if allow_unchanged is True:
        return True
    if isinstance(allow_unchanged, list):
        return index in allow_unchanged
    return False


def _json_extractable_elsewhere(raw: str) -> bool:
    """True si un objet JSON valide existe quelque part dans `raw`.

    Réexécute la même logique que `set_texts_from_json` (raw_decode à partir
    de chaque `{`) pour distinguer un JSON réellement malformé (JSON_INVALIDE)
    d'un JSON valide que l'extraction par regex de l'app n'a pas su isoler
    (JSON_NON_EXTRAIT, ex. deux objets JSON concaténés).
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(raw):
        if char != "{":
            continue
        try:
            decoder.raw_decode(raw, index)
        except ValueError:
            continue
        return True
    return False


def classify_result(
    *,
    exc_type: str | None,
    http_status: int | None,
    finish_reason: str | None,
    raw: str | None,
    parsed: dict | None,
    blocks: list[str],
    sources: list[str],
    allow_unchanged: list[int] | bool | None,
) -> tuple[str, str]:
    """Classe le résultat d'un cas de banc (14 règles ordonnées, cf. specs/01 §4).

    Fonction pure, sans aucune I/O ni accès réseau : importable telle quelle
    par les tests (`tests/test_bench_classification.py`).
    """
    # 1-2 : erreurs de connexion (avant tout autre signal).
    if exc_type == EXC_CONNECTION_REFUSED:
        return CONNEXION_REFUSEE, "connexion TCP refusée par le serveur"
    if exc_type == EXC_CONNECTION_ERROR:
        return INJOIGNABLE, "serveur injoignable (erreur de connexion)"
    # 3 : délai dépassé.
    if exc_type == EXC_TIMEOUT:
        return TIMEOUT, "délai dépassé avant réponse du serveur"

    # 4 : modèle absent (404, y compris un /v1 oublié dans l'URL).
    if http_status == 404:
        return MODELE_ABSENT, (raw or "")[:500]
    # 5 : toute autre erreur HTTP (detail = corps de la réponse si présent,
    # même convention que la règle 4, pour rester cohérent et diagnostique).
    if http_status is not None and http_status >= 400:
        return ERREUR_HTTP, raw[:500] if raw else f"code HTTP {http_status}"

    # 6 : réponse tronquée par le serveur.
    if finish_reason == "length":
        return TRONQUE, "réponse tronquée par le serveur (finish_reason=length)"

    # 7-8 : rien n'a pu être extrait / parsé.
    if parsed is None:
        if raw is not None and re.search(r"\{[\s\S]*\}", raw):
            if _json_extractable_elsewhere(raw):
                return (
                    JSON_NON_EXTRAIT,
                    "un objet JSON valide existe dans la réponse mais l'extraction de l'app ne l'isole pas",
                )
            return (
                JSON_INVALIDE,
                "JSON malformé (l'app aurait planté sans le correctif F3)",
            )
        return PAS_DE_JSON, "aucune accolade dans la réponse"

    # 9 : clés manquantes (whole-case).
    expected_keys = [f"block_{i}" for i in range(len(blocks))]
    actual_keys = set(parsed.keys())
    missing = [k for k in expected_keys if k not in actual_keys]
    extra = sorted(actual_keys - set(expected_keys))
    if missing:
        detail = f"manquantes : {', '.join(missing)}"
        if extra:
            detail += f" ; clés inconnues : {', '.join(extra)}"
        return CLES_MANQUANTES, detail

    # 10 : valeur non-str (dont None) — la plus sévère des vérifications par bloc.
    type_inattendu = [
        i for i in range(len(blocks)) if not isinstance(parsed[f"block_{i}"], str)
    ]
    if type_inattendu:
        return (
            TYPE_INATTENDU,
            f"{len(type_inattendu)}/{len(blocks)} bloc(s) de type inattendu : {type_inattendu}",
        )

    # 11 : chaîne vide ou blanche.
    vide = [i for i in range(len(blocks)) if not parsed[f"block_{i}"].strip()]
    if vide:
        return VIDE, f"{len(vide)}/{len(blocks)} bloc(s) vide(s) : {vide}"

    # 12 : identique à la source (hors blocs autorisés).
    non_traduit = [
        i
        for i in range(len(blocks))
        if _normalize_for_comparison(parsed[f"block_{i}"])
        == _normalize_for_comparison(sources[i])
        and not _is_allowed_unchanged(i, allow_unchanged)
    ]
    if non_traduit:
        return (
            NON_TRADUIT,
            f"{len(non_traduit)}/{len(blocks)} bloc(s) identique(s) à la source : {non_traduit}",
        )

    # 13-14 : OK, avec ou sans clés en trop.
    if extra:
        return OK, f"OK (clés inconnues ignorées : {', '.join(extra)})"
    return OK, "OK"


@dataclass
class _CapturedCall:
    payload: dict[str, Any] | None = None
    response: requests.Response | None = None
    exception: BaseException | None = None


@contextmanager
def capture_post_calls() -> Iterator[list[_CapturedCall]]:
    """Intercepte temporairement `requests.post` utilisé par gpt.py.

    `modules.translation.llm.gpt` fait `import requests` : ce module est
    littéralement le même objet que le paquet `requests` importé ici (les
    modules Python sont mis en cache par `sys.modules`). Remplacer son
    attribut `post` mute donc le paquet `requests` pour TOUT le processus,
    pas seulement pour gpt.py — ce relais n'est PAS thread-safe et ne doit
    JAMAIS être utilisé dans l'application elle-même, seulement dans ce banc
    mono-thread. La restauration a lieu dans un `finally`, y compris si
    `requests.post` lève.

    `response.raise_for_status()` est appelé par gpt.py APRÈS que ce relais
    a rendu la main : les codes HTTP se lisent donc sur la `Response`
    mémorisée (`call.response`), jamais en interceptant cet appel.
    """
    original_post = gpt_module.requests.post
    calls: list[_CapturedCall] = []

    def _patched_post(url: str, *args: Any, **kwargs: Any) -> requests.Response:
        call = _CapturedCall()
        calls.append(call)
        data = kwargs.get("data")
        if data is not None:
            try:
                call.payload = json.loads(data)
            except ValueError:
                call.payload = None
        try:
            response = original_post(url, *args, **kwargs)
        except Exception as exc:
            call.exception = exc
            raise
        call.response = response
        return response

    gpt_module.requests.post = _patched_post
    try:
        yield calls
    finally:
        gpt_module.requests.post = original_post


def _walk_exception_chain(exc: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def classify_exception(exc: BaseException | None) -> str | None:
    """Catégorise une exception réseau en exc_type pour `classify_result`."""
    if exc is None:
        return None
    chain = list(_walk_exception_chain(exc))
    for item in chain:
        if isinstance(item, ConnectionRefusedError):
            return EXC_CONNECTION_REFUSED
        if isinstance(item, OSError) and item.errno == errno.ECONNREFUSED:
            return EXC_CONNECTION_REFUSED
    for item in chain:
        if isinstance(item, requests.exceptions.ConnectionError):
            return EXC_CONNECTION_ERROR
    for item in chain:
        if isinstance(item, (requests.exceptions.Timeout, TimeoutError)):
            return EXC_TIMEOUT
    return None


class _IdentityTr:
    """Substitut minimal de `SettingsPageUI` : `tr()` = identité."""

    @staticmethod
    def tr(text: str) -> str:
        return text


@dataclass
class _BenchSettings:
    """Substitut minimal de `SettingsPage` (cf. specs/01 §4)."""

    api_key: str
    api_url: str
    model: str
    disable_reasoning: bool
    use_max_tokens: bool
    timeout: int
    temperature: float
    top_p: float
    max_tokens: int
    ui: _IdentityTr = field(default_factory=_IdentityTr)

    def get_credentials(self, service: str) -> dict[str, Any]:
        return {
            "api_key": self.api_key,
            "api_url": self.api_url,
            "model": self.model,
            "disable_reasoning": self.disable_reasoning,
            "use_max_tokens": self.use_max_tokens,
            "timeout": self.timeout,
        }

    def get_llm_settings(self) -> dict[str, Any]:
        return {
            "image_input_enabled": False,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_tokens": self.max_tokens,
        }


@dataclass
class BenchResult:
    name: str
    seconds: float
    status: str
    detail: str
    missing_keys: list[str]
    finish_reason: str | None


def check_model_available(
    url: str, model: str, api_key: str, timeout: float = 5.0
) -> None:
    """Avertit (sans jamais arrêter le banc) si /models ne liste pas le modèle."""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        response = requests.get(f"{url}/models", headers=headers, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        print(f"Avertissement : /models injoignable ({exc}), le banc continue.")
        return
    if response.status_code != 200:
        print(
            f"Avertissement : /models a répondu {response.status_code}, le banc continue."
        )
        return
    try:
        payload = response.json()
        available = {item.get("id") for item in payload.get("data", [])}
    except (ValueError, AttributeError, TypeError):
        print("Avertissement : réponse de /models illisible, le banc continue.")
        return
    if model not in available:
        print(
            f"Avertissement : modèle '{model}' absent de /models ({sorted(a for a in available if a)})."
        )


def run_case(
    case: BenchCase,
    *,
    engine: CustomTranslation,
    context: str,
    verbose: bool,
) -> BenchResult:
    blocks = case["blocks"]
    allow_unchanged = case.get("allow_unchanged", [])
    blk_list = [TextBlock(text=block, translation=SENTINEL) for block in blocks]

    start = time.monotonic()
    translate_error: Exception | None = None
    with capture_post_calls() as calls:
        try:
            engine.translate(blk_list, None, context)
        except Exception as exc:  # capté puis classé, jamais avalé silencieusement
            translate_error = exc
    seconds = time.monotonic() - start

    last_call = calls[-1] if calls else None
    http_status: int | None = None
    finish_reason: str | None = None
    raw: str | None = None
    exc_category: str | None = None
    unexpected_detail: str | None = None

    if last_call is not None and last_call.response is not None:
        http_status = last_call.response.status_code
        if http_status < 400:
            try:
                body = last_call.response.json()
                choice = body["choices"][0]
                raw = choice["message"]["content"]
                finish_reason = choice.get("finish_reason")
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                unexpected_detail = (
                    f"réponse HTTP 200 mais structure inattendue : {exc}"
                )
        else:
            raw = last_call.response.text
    elif last_call is not None and last_call.exception is not None:
        exc_category = classify_exception(last_call.exception)
        if exc_category is None:
            unexpected_detail = (
                f"{type(last_call.exception).__name__}: {last_call.exception}"
            )
    elif translate_error is not None:
        exc_category = classify_exception(
            translate_error.__context__
        ) or classify_exception(translate_error)
        if exc_category is None:
            unexpected_detail = f"{type(translate_error).__name__}: {translate_error}"

    parsed: dict[str, Any] | None = None
    if unexpected_detail is None and raw is not None:
        parsed = set_texts_from_json(list(blk_list), raw)

    if unexpected_detail is not None:
        status, detail = ERREUR_INATTENDUE, unexpected_detail
    else:
        status, detail = classify_result(
            exc_type=exc_category,
            http_status=http_status,
            finish_reason=finish_reason,
            raw=raw,
            parsed=parsed,
            blocks=blocks,
            sources=blocks,
            allow_unchanged=allow_unchanged,
        )

    missing_keys: list[str] = []
    if parsed is not None:
        missing_keys = [
            f"block_{i}" for i in range(len(blocks)) if f"block_{i}" not in parsed
        ]

    if verbose:
        payload = last_call.payload if last_call is not None else None
        print(f"--- {case['name']} : payload adapté = {payload}")
        print(f"    réponse brute = {raw!r}")

    return BenchResult(
        case["name"], seconds, status, detail, missing_keys, finish_reason
    )


def _load_cases_file(path: Path) -> tuple[str | None, str | None, list[BenchCase]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml
        except ImportError as exc:
            raise SystemExit(
                "Le fichier de cas est un .yaml : installez le groupe dev (`uv sync`) pour avoir pyyaml."
            ) from exc
        data = yaml.safe_load(text)

    raw_cases = data.get("cases")
    if not raw_cases:
        raise SystemExit(f"Aucun cas trouvé dans {path}")

    cases: list[BenchCase] = []
    for raw_case in raw_cases:
        cases.append(
            {
                "name": raw_case["name"],
                "blocks": list(raw_case["blocks"]),
                "allow_unchanged": raw_case.get("allow_unchanged", []),
            }
        )
    return data.get("source_lang"), data.get("target_lang"), cases


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Base URL OpenAI-compatible (défaut : {DEFAULT_URL})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Modèle à interroger (défaut : {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=(
            "Clé API envoyée en Bearer (défaut : variable d'environnement "
            f"{BENCH_API_KEY_ENV_VAR}, sinon vide). Préférer la variable "
            "d'environnement pour ne pas laisser la clé dans l'historique du shell."
        ),
    )
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--top-p", type=float, default=0.95)
    parser.add_argument("--max-tokens", type=int, default=4096)
    parser.add_argument(
        "--context", default="", help="extra_context envoyé au traducteur"
    )
    parser.add_argument("--source-lang", default=DEFAULT_SOURCE_LANG)
    parser.add_argument("--target-lang", default=DEFAULT_TARGET_LANG)
    parser.add_argument(
        "--timeout", type=int, default=180, help="Timeout HTTP en secondes (10..1800)"
    )

    reasoning = parser.add_mutually_exclusive_group()
    reasoning.add_argument(
        "--no-reasoning",
        dest="disable_reasoning",
        action="store_true",
        help="Envoie reasoning_effort=none (défaut)",
    )
    reasoning.add_argument(
        "--reasoning",
        dest="disable_reasoning",
        action="store_false",
        help="N'envoie pas reasoning_effort",
    )
    parser.set_defaults(disable_reasoning=True)

    compat = parser.add_mutually_exclusive_group()
    compat.add_argument(
        "--max-tokens-compat",
        dest="use_max_tokens",
        action="store_true",
        help="Renomme max_completion_tokens en max_tokens (défaut)",
    )
    compat.add_argument(
        "--no-max-tokens-compat",
        dest="use_max_tokens",
        action="store_false",
        help="Garde max_completion_tokens",
    )
    parser.set_defaults(use_max_tokens=True)

    parser.add_argument(
        "--cases",
        type=Path,
        default=None,
        help="Fichier .yaml/.json de cas (défaut : 6 cas intégrés)",
    )
    parser.add_argument(
        "--csv", type=Path, default=None, help="Export CSV des résultats"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Affiche le payload adapté et la réponse brute",
    )
    return parser


def _format_table(results: list[BenchResult]) -> str:
    name_width = max(len(r.name) for r in results) if results else 4
    status_width = max(len(r.status) for r in results) if results else 6
    lines = [f"{'Cas':<{name_width}}  {'Durée':>7}  {'Statut':<{status_width}}  Détail"]
    for r in results:
        lines.append(
            f"{r.name:<{name_width}}  {r.seconds:>6.1f}s  {r.status:<{status_width}}  {r.detail}"
        )
    return "\n".join(lines)


def _write_csv(path: Path, model: str, url: str, results: list[BenchResult]) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "timestamp",
                "model",
                "url",
                "case",
                "seconds",
                "status",
                "detail",
                "missing_keys",
                "finish_reason",
            ]
        )
        for r in results:
            row = [
                timestamp,
                model,
                url,
                r.name,
                f"{r.seconds:.3f}",
                r.status,
                r.detail,
                ";".join(r.missing_keys),
                r.finish_reason or "",
            ]
            writer.writerow(_sanitize_csv_cell(cell) for cell in row)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Priorité : --api-key explicite > variable d'environnement > "".
    api_key = args.api_key
    if api_key is None:
        api_key = os.environ.get(BENCH_API_KEY_ENV_VAR, "")

    url = args.url.rstrip("/")
    source_lang = args.source_lang
    target_lang = args.target_lang
    cases: list[BenchCase]

    if args.cases is not None:
        file_source_lang, file_target_lang, cases = _load_cases_file(args.cases)
        if args.source_lang == DEFAULT_SOURCE_LANG and file_source_lang:
            source_lang = file_source_lang
        if args.target_lang == DEFAULT_TARGET_LANG and file_target_lang:
            target_lang = file_target_lang
    else:
        cases = list(DEFAULT_CASES)

    print(f"Modèle : {args.model}  |  URL : {url}  |  {source_lang} -> {target_lang}\n")
    check_model_available(url, args.model, api_key)

    settings = _BenchSettings(
        api_key=api_key,
        api_url=url,
        model=args.model,
        disable_reasoning=args.disable_reasoning,
        use_max_tokens=args.use_max_tokens,
        timeout=args.timeout,
        temperature=args.temperature,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
    )
    engine = CustomTranslation()
    engine.initialize(settings, source_lang, target_lang, tr_key="Custom")

    results = [
        run_case(case, engine=engine, context=args.context, verbose=args.verbose)
        for case in cases
    ]

    print(_format_table(results))
    ok_count = sum(1 for r in results if r.status == OK)
    print(f"\n{ok_count}/{len(results)} OK")

    if args.csv is not None:
        _write_csv(args.csv, args.model, url, results)
        print(f"Résultats exportés vers {args.csv}")

    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
