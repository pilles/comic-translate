"""Configuration pytest partagée (spec 01 §5).

- `--gui` : sans cette option, `tests/test_app.py`,
  `tests/test_manual_mask_equivalence.py`, `tests/test_history_restore.py`
  et `tests/test_legacy_ctpr_compat.py` (Qt) sont écartés de la collecte,
  pour permettre `uv run pytest` sans dépendance display/offscreen.
- Fixture `llm_server` : serveur HTTP local (`ThreadingHTTPServer`) qui imite
  un endpoint OpenAI-compatible (`/v1/models`, `/v1/chat/completions`), routes
  scriptables par test (corps, code HTTP, délai de sommeil), jamais de réseau
  externe.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--gui",
        action="store_true",
        default=False,
        help="Inclut les tests Qt (tests/test_app.py) dans la collecte.",
    )


_GUI_ONLY_FILES = {
    "test_app.py",
    "test_manual_mask_equivalence.py",
    "test_history_restore.py",
    "test_legacy_ctpr_compat.py",  # fork: historique par bloc (jalon A) — vérification tester
    "test_original_view.py",  # fork: voir l'original (spec 03 jalon B)
    "test_pagestate_ui.py",  # fork: état d'avancement par page (spec 04 jalon 1)
    "test_shell_ui.py",  # fork: nouvelle disposition (spec 04 jalon 2, 2a)
    "test_reset_ui.py",  # fork: bouton Réinitialiser la page (spec 04 jalon 3, 3a)
    "test_analysis_on_original.py",  # fork: analyse sur l'original (hotfix 2026-09-27)
    "test_undo_guard_ui.py",  # fork: verrou d'annulation nettoyage/segmentation (spec 04 jalon 3, 3a-bis)
}


def pytest_ignore_collect(collection_path, config: pytest.Config) -> bool | None:
    if collection_path.name in _GUI_ONLY_FILES and not config.getoption("--gui"):
        return True
    return None


class _RouteConfig:
    __slots__ = ("status", "body", "sleep")

    def __init__(self, status: int = 200, body: Any = None, sleep: float = 0.0):
        self.status = status
        self.body = body if body is not None else {}
        self.sleep = sleep


class _ConfigurableHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # silence : bruit inutile dans la sortie des tests

    def _handle(self) -> None:
        route = self.server.route_config.get(self.path)  # type: ignore[attr-defined]

        if self.command == "POST":
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw_body = self.rfile.read(length) if length else b""
            try:
                self.server.last_payload = json.loads(raw_body) if raw_body else None  # type: ignore[attr-defined]
            except ValueError:
                self.server.last_payload = None  # type: ignore[attr-defined]

        if route is None:
            self._send(404, {"error": f"no route configured for {self.path}"})
            return

        if route.sleep:
            time.sleep(route.sleep)

        self._send(route.status, route.body)

    def _send(self, status: int, body: Any) -> None:
        if isinstance(body, (dict, list)):
            payload = json.dumps(body).encode("utf-8")
            content_type = "application/json"
        else:
            payload = str(body).encode("utf-8")
            content_type = "text/plain"
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Le client (timeout côté test) a pu abandonner la connexion
            # pendant que ce handler dormait : sans conséquence pour le test.
            pass

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()


class LLMServerHandle:
    """Interface exposée aux tests pour piloter le serveur local."""

    def __init__(self, server: ThreadingHTTPServer):
        self._server = server
        port = server.server_address[1]
        self.base_url = f"http://127.0.0.1:{port}/v1"

    def set_route(
        self, path: str, *, status: int = 200, body: Any = None, sleep: float = 0.0
    ) -> None:
        self._server.route_config[path] = _RouteConfig(status=status, body=body, sleep=sleep)  # type: ignore[attr-defined]

    @property
    def last_payload(self) -> dict | None:
        return self._server.last_payload  # type: ignore[attr-defined]


@pytest.fixture
def llm_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ConfigurableHandler)
    server.daemon_threads = (
        True  # un handler encore endormi (test TIMEOUT) ne bloque jamais l'arrêt
    )
    server.route_config = {}  # type: ignore[attr-defined]
    server.last_payload = None  # type: ignore[attr-defined]

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    handle = LLMServerHandle(server)
    try:
        yield handle
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
