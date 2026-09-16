"""Tests F1 : modules/utils/ssl_context.py (spec 01 §5).

Aucun réseau : `ssl.get_default_verify_paths`, `os.path.isfile/isdir` et
`os.environ` sont monkeypatchés. Le cache mémoïsé du module est réinitialisé
avant/après chaque test (fixture autouse).
"""

from __future__ import annotations

import io
import ssl
from types import SimpleNamespace

import pytest

from modules.utils import download_file, ssl_context


@pytest.fixture(autouse=True)
def _reset_ssl_cache():
    ssl_context.reset_cache()
    yield
    ssl_context.reset_cache()


def _fake_verify_paths(cafile: str = "", capath: str = "") -> SimpleNamespace:
    return SimpleNamespace(openssl_cafile=cafile, openssl_capath=capath)


def _no_system_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simule l'absence totale de magasin système, pour isoler la branche certifi."""
    monkeypatch.setattr(
        ssl, "get_default_verify_paths", lambda: _fake_verify_paths("", "")
    )
    monkeypatch.setattr(ssl_context.os.path, "isfile", lambda _path: False)
    monkeypatch.setattr(ssl_context.os.path, "isdir", lambda _path: False)


def test_ssl_cert_file_env_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/some/cert.pem")
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    assert ssl_context.get_ssl_context() is None


def test_ssl_cert_dir_env_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("SSL_CERT_DIR", "/some/certs")
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    assert ssl_context.get_ssl_context() is None


def test_system_cafile_present_keeps_default_behavior(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(
        ssl,
        "get_default_verify_paths",
        lambda: _fake_verify_paths("/private/etc/ssl/cert.pem", ""),
    )
    monkeypatch.setattr(
        ssl_context.os.path, "isfile", lambda path: path == "/private/etc/ssl/cert.pem"
    )
    monkeypatch.setattr(ssl_context.os.path, "isdir", lambda _path: False)
    assert ssl_context.get_ssl_context() is None


def test_system_capath_alone_is_enough(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(
        ssl,
        "get_default_verify_paths",
        lambda: _fake_verify_paths("", "/private/etc/ssl/certs"),
    )
    monkeypatch.setattr(ssl_context.os.path, "isfile", lambda _path: False)
    monkeypatch.setattr(
        ssl_context.os.path, "isdir", lambda path: path == "/private/etc/ssl/certs"
    )
    assert ssl_context.get_ssl_context() is None


def test_falls_back_to_certifi_when_no_system_store(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    _no_system_store(monkeypatch)

    context = ssl_context.get_ssl_context()

    assert context is not None
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0


def test_no_certifi_no_system_store_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    _no_system_store(monkeypatch)
    # Truc standard pour simuler un `import certifi` qui échoue sans désinstaller
    # le paquet réellement présent dans l'environnement de test.
    monkeypatch.setitem(__import__("sys").modules, "certifi", None)

    assert ssl_context.get_ssl_context() is None


@pytest.mark.parametrize(
    "env,cafile,capath,certifi_available",
    [
        ({"SSL_CERT_FILE": "/x"}, "", "", True),
        ({"SSL_CERT_DIR": "/x"}, "", "", True),
        ({}, "/private/etc/ssl/cert.pem", "", True),
        ({}, "", "/private/etc/ssl/certs", True),
        ({}, "", "", True),
        ({}, "", "", False),
    ],
)
def test_never_produces_cert_none(
    monkeypatch: pytest.MonkeyPatch, env, cafile, capath, certifi_available
):
    """Invariante F1 : aucune combinaison ne doit produire un contexte CERT_NONE."""
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        ssl, "get_default_verify_paths", lambda: _fake_verify_paths(cafile, capath)
    )
    monkeypatch.setattr(
        ssl_context.os.path, "isfile", lambda path: path == cafile and bool(path)
    )
    monkeypatch.setattr(
        ssl_context.os.path, "isdir", lambda path: path == capath and bool(path)
    )
    if not certifi_available:
        monkeypatch.setitem(__import__("sys").modules, "certifi", None)

    context = ssl_context.get_ssl_context()
    if context is not None:
        assert context.verify_mode != ssl.CERT_NONE


def test_open_url_passes_context(monkeypatch: pytest.MonkeyPatch):
    sentinel = object()
    monkeypatch.setattr(download_file, "get_ssl_context", lambda: sentinel)

    captured = {}

    def fake_urlopen(req, timeout=None, context=None):
        captured["context"] = context
        captured["timeout"] = timeout
        return io.BytesIO(b"")

    monkeypatch.setattr(download_file.urllib.request, "urlopen", fake_urlopen)

    with download_file._open_url("http://example.invalid", timeout=5):
        pass

    assert captured["context"] is sentinel
    assert captured["timeout"] == 5
