"""Tests F3 bout en bout : tools/bench_translation.py (spec 01 §5).

Lance le vrai `main(argv)` du banc contre le serveur HTTP local (fixture
`llm_server`, cf. conftest.py). Aucun réseau externe, aucun Ollama réel.
"""

from __future__ import annotations

import csv
import json
import socket
from pathlib import Path


from tools.bench_translation import main

SECRET_API_KEY = "sk-super-secret-value-should-never-leak"


def _write_case_file(tmp_path: Path, blocks: list[str]) -> Path:
    path = tmp_path / "cases.json"
    path.write_text(
        json.dumps({"cases": [{"name": "cas_test", "blocks": blocks}]}),
        encoding="utf-8",
    )
    return path


def _run(monkeypatch, capsys, argv):
    exit_code = main(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _base_args(llm_server, cases_path, csv_path, extra=None):
    args = [
        "--url",
        llm_server.base_url,
        "--api-key",
        SECRET_API_KEY,
        "--cases",
        str(cases_path),
        "--csv",
        str(csv_path),
        "--timeout",
        "10",
    ]
    if extra:
        args.extend(extra)
    return args


def _read_csv_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_ok_case(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {
                    "message": {"content": '{"block_0": "Bonjour"}'},
                    "finish_reason": "stop",
                }
            ]
        },
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))

    assert exit_code == 0
    assert "1/1 OK" in out
    payload = llm_server.last_payload
    assert "max_tokens" in payload
    assert "max_completion_tokens" not in payload
    assert payload["reasoning_effort"] == "none"

    rows = _read_csv_rows(csv_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "OK"
    assert SECRET_API_KEY not in csv_path.read_text(encoding="utf-8")


def test_ok_markdown_fenced(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {
                    "message": {"content": '```json\n{"block_0": "Bonjour"}\n```'},
                    "finish_reason": "stop",
                }
            ]
        },
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))
    assert exit_code == 0
    assert "1/1 OK" in out


def test_missing_keys(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello", "World"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {
                    "message": {"content": '{"block_0": "Bonjour"}'},
                    "finish_reason": "stop",
                }
            ]
        },
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))
    assert exit_code == 1
    assert "CLES_MANQUANTES" in out
    rows = _read_csv_rows(csv_path)
    assert rows[0]["status"] == "CLES_MANQUANTES"
    assert "block_1" in rows[0]["missing_keys"]


def test_pas_de_json(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {"message": {"content": "no braces here"}, "finish_reason": "stop"}
            ]
        },
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))
    assert exit_code == 1
    assert "PAS_DE_JSON" in out


def test_json_invalide(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {"message": {"content": '{"block_0": }'}, "finish_reason": "stop"}
            ]
        },
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))
    assert exit_code == 1
    assert "JSON_INVALIDE" in out


def test_json_non_extrait(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {
                    "message": {"content": '{"foo": "bar"} {"baz": 1}'},
                    "finish_reason": "stop",
                }
            ]
        },
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))
    assert exit_code == 1
    assert "JSON_NON_EXTRAIT" in out


def test_tronque(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {
                    "message": {"content": '{"block_0": "Bon"}'},
                    "finish_reason": "length",
                }
            ]
        },
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))
    assert exit_code == 1
    assert "TRONQUE" in out


def test_modele_absent_404(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions", status=404, body="model not found on this server"
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))
    assert exit_code == 1
    assert "MODELE_ABSENT" in out


def test_connexion_refusee(tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"

    # Port fermé : bind puis close immédiat -> plus rien n'écoute dessus.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    argv = [
        "--url",
        f"http://127.0.0.1:{port}/v1",
        "--api-key",
        SECRET_API_KEY,
        "--cases",
        str(cases),
        "--csv",
        str(csv_path),
        "--timeout",
        "10",
    ]

    exit_code, out, _err = _run(None, capsys, argv)
    assert exit_code == 1
    assert "CONNEXION_REFUSEE" in out


def test_timeout(llm_server, tmp_path, capsys):
    # NB : `OpenAICompatOptions.from_credentials` (F2) borne le timeout à
    # 10..1800s et retombe sur le défaut (180s) pour toute valeur "aberrante"
    # en dehors de cette plage (cf. modules/translation/llm/compat.py). Un
    # `--timeout 1` ne produit donc PAS un timeout à 1s : il est silencieusement
    # remplacé par 180s. 10s est la plus petite valeur qui déclenche réellement
    # un timeout HTTP ; le serveur dort un peu plus longtemps que ça.
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route(
        "/v1/chat/completions",
        body={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]},
        sleep=12,
    )

    argv = [
        "--url",
        llm_server.base_url,
        "--api-key",
        SECRET_API_KEY,
        "--cases",
        str(cases),
        "--csv",
        str(csv_path),
        "--timeout",
        "10",
    ]

    exit_code, out, _err = _run(None, capsys, argv)
    assert exit_code == 1
    assert "TIMEOUT" in out


def test_models_401_warns_but_continues(llm_server, tmp_path, capsys):
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route("/v1/models", status=401, body={"error": "unauthorized"})
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {
                    "message": {"content": '{"block_0": "Bonjour"}'},
                    "finish_reason": "stop",
                }
            ]
        },
    )

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))

    assert "Avertissement" in out
    assert exit_code == 0
    assert "1/1 OK" in out


def test_api_key_env_fallback(monkeypatch, llm_server, tmp_path, capsys):
    # Sans --api-key explicite, la clé vient de BENCH_API_KEY (priorité :
    # --api-key explicite > variable d'environnement > "").
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    monkeypatch.setenv("BENCH_API_KEY", SECRET_API_KEY)
    llm_server.set_route(
        "/v1/chat/completions",
        body={
            "choices": [
                {
                    "message": {"content": '{"block_0": "Bonjour"}'},
                    "finish_reason": "stop",
                }
            ]
        },
    )

    argv = [
        "--url",
        llm_server.base_url,
        "--cases",
        str(cases),
        "--csv",
        str(csv_path),
        "--timeout",
        "10",
    ]
    exit_code, out, _err = _run(None, capsys, argv)

    assert exit_code == 0
    assert "1/1 OK" in out
    assert SECRET_API_KEY not in csv_path.read_text(encoding="utf-8")


def test_csv_injection_is_neutralized(llm_server, tmp_path, capsys):
    # Un corps d'erreur HTTP 500 contenant une formule ne doit jamais
    # atterrir tel quel dans le CSV : la cellule "detail" doit commencer
    # par une apostrophe pour forcer une lecture en texte brut par le
    # tableur (cf. OWASP CSV Injection).
    cases = _write_case_file(tmp_path, ["Hello"])
    csv_path = tmp_path / "out.csv"
    llm_server.set_route("/v1/chat/completions", status=500, body='=HYPERLINK("x")')

    exit_code, out, _err = _run(None, capsys, _base_args(llm_server, cases, csv_path))
    assert exit_code == 1
    assert "ERREUR_HTTP" in out

    rows = _read_csv_rows(csv_path)
    assert rows[0]["status"] == "ERREUR_HTTP"
    assert rows[0]["detail"].startswith("'=")
