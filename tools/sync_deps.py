#!/usr/bin/env python3
"""Vérifie/régénère `[project.dependencies]` de pyproject.toml depuis requirements.txt.

`requirements.txt` est la seule source de vérité des dépendances du projet
(cf. specs/01-socle-fork-ollama.md §1) : ce script garde pyproject.toml en
miroir, ligne pour ligne, pour que les rebase sur `filvyb`/`upstream` (qui ne
connaissent que requirements.txt) restent simples.

Usage :
    uv run python tools/sync_deps.py                # --check implicite
    uv run python tools/sync_deps.py --check         # explicite, exit 1 si désynchronisé
    uv run python tools/sync_deps.py --write         # régénère le bloc entre les marqueurs

`--write` échoue bruyamment (exit != 0, rien n'est écrit) si les marqueurs
sont absents ou dupliqués : jamais de réécriture silencieuse d'un fichier
dont la structure a changé sous nos pieds.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"

MARKER_BEGIN = "    # --- sync_deps: begin ---"
MARKER_END = "    # --- sync_deps: end ---"

_BLOCK_RE = re.compile(
    re.escape(MARKER_BEGIN) + r"\n(?P<body>.*?)\n" + re.escape(MARKER_END),
    re.DOTALL,
)
_ITEM_RE = re.compile(r'^\s*"([^"]*)"\s*,?\s*$')

RequirementKey = tuple[str, tuple[str, ...], str, str]


class SyncDepsError(RuntimeError):
    """Erreur bloquante : ne jamais réécrire pyproject.toml dans cet état."""


def _requirement_key(req: Requirement) -> RequirementKey:
    """Clé de comparaison PEP 503 : nom normalisé, extras triés, specifier, marker."""
    return (
        canonicalize_name(req.name),
        tuple(sorted(extra.lower() for extra in req.extras)),
        str(req.specifier),
        str(req.marker) if req.marker else "",
    )


def parse_requirements(path: Path) -> list[Requirement]:
    """Parse requirements.txt dans l'ordre du fichier (extras/marqueurs tolérés)."""
    reqs: list[Requirement] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        reqs.append(Requirement(line))
    return reqs


def _find_block(text: str) -> re.Match[str]:
    matches = list(_BLOCK_RE.finditer(text))
    if not matches:
        raise SyncDepsError(
            f"Marqueurs {MARKER_BEGIN.strip()!r} / {MARKER_END.strip()!r} introuvables dans pyproject.toml"
        )
    if len(matches) > 1:
        raise SyncDepsError("Marqueurs sync_deps en double dans pyproject.toml")
    return matches[0]


def parse_pyproject_dependencies(text: str) -> list[Requirement]:
    body = _find_block(text).group("body")
    reqs: list[Requirement] = []
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ITEM_RE.match(raw_line)
        if not match:
            raise SyncDepsError(
                f"Ligne inattendue dans le bloc dependencies : {raw_line!r}"
            )
        reqs.append(Requirement(match.group(1)))
    return reqs


def build_dependency_block(reqs: list[Requirement]) -> str:
    lines = [MARKER_BEGIN]
    lines.extend(f'    "{req}",' for req in reqs)
    lines.append(MARKER_END)
    return "\n".join(lines)


def write_pyproject(reqs: list[Requirement]) -> None:
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = _find_block(
        text
    )  # lève SyncDepsError si absent/dupliqué : rien n'est écrit
    new_text = (
        text[: match.start()] + build_dependency_block(reqs) + text[match.end() :]
    )
    PYPROJECT_PATH.write_text(new_text, encoding="utf-8")


def diff_requirements(
    from_requirements: list[Requirement], from_pyproject: list[Requirement]
) -> list[str]:
    """Différences lisibles entre les deux listes, vide si synchronisé."""
    keys_a = [_requirement_key(r) for r in from_requirements]
    keys_b = [_requirement_key(r) for r in from_pyproject]
    if keys_a == keys_b:
        return []

    set_a, set_b = set(keys_a), set(keys_b)
    only_in_requirements = [
        str(r) for r, k in zip(from_requirements, keys_a) if k not in set_b
    ]
    only_in_pyproject = [
        str(r) for r, k in zip(from_pyproject, keys_b) if k not in set_a
    ]

    diffs: list[str] = []
    if only_in_requirements:
        diffs.append(
            "présentes dans requirements.txt mais absentes de pyproject.toml : "
            + ", ".join(only_in_requirements)
        )
    if only_in_pyproject:
        diffs.append(
            "présentes dans pyproject.toml mais absentes de requirements.txt : "
            + ", ".join(only_in_pyproject)
        )
    if not diffs:
        diffs.append(
            "même ensemble de dépendances mais ordre différent : "
            f"requirements.txt={[str(r) for r in from_requirements]} "
            f"pyproject.toml={[str(r) for r in from_pyproject]}"
        )
    return diffs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Vérifie la synchronisation sans rien écrire (défaut).",
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Régénère le bloc dependencies de pyproject.toml.",
    )
    args = parser.parse_args(argv)

    reqs = parse_requirements(REQUIREMENTS_PATH)

    if args.write:
        try:
            write_pyproject(reqs)
        except SyncDepsError as exc:
            print(
                f"sync_deps --write a échoué, rien n'a été écrit : {exc}",
                file=sys.stderr,
            )
            return 1
        print(
            f"pyproject.toml régénéré depuis requirements.txt ({len(reqs)} dépendances)."
        )
        return 0

    # --check est le comportement par défaut.
    try:
        pyproject_reqs = parse_pyproject_dependencies(
            PYPROJECT_PATH.read_text(encoding="utf-8")
        )
    except SyncDepsError as exc:
        print(f"sync_deps --check a échoué : {exc}", file=sys.stderr)
        return 1

    diffs = diff_requirements(reqs, pyproject_reqs)
    if diffs:
        print("pyproject.toml désynchronisé de requirements.txt :", file=sys.stderr)
        for diff in diffs:
            print(f"  - {diff}", file=sys.stderr)
        return 1

    print(
        f"pyproject.toml synchronisé avec requirements.txt ({len(reqs)} dépendances)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
