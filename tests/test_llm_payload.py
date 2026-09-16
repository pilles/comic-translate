"""Tests F2 : modules/translation/llm/compat.py, custom.py, gpt.py (spec 01 §5).

`requests.post` est monkeypatché dans `modules.translation.llm.gpt` : aucun
réseau. Couvre la charge utile envoyée par Custom (défauts / tout désactivé)
et la non-régression GPT / Deepseek / Grok.
"""

from __future__ import annotations

import json

import pytest

from modules.translation.llm.compat import OpenAICompatOptions, adapt_payload
from modules.translation.llm.custom import CustomTranslation
from modules.translation.llm.deepseek import DeepseekTranslation
from modules.translation.llm.gpt import GPTTranslation
from modules.translation.llm.grok import GrokTranslation
from modules.translation.llm import gpt as gpt_module
from modules.utils.textblock import TextBlock


class _FakeUI:
    @staticmethod
    def tr(text: str) -> str:
        return text


class _FakeSettings:
    """Substitut minimal de `SettingsPage` (indépendant de Qt)."""

    def __init__(self, credentials: dict, llm_settings: dict | None = None):
        self.ui = _FakeUI()
        self._credentials = credentials
        self._llm_settings = llm_settings or {
            "image_input_enabled": False,
            "temperature": 0.3,
            "top_p": 0.95,
            "max_tokens": 4096,
        }

    def get_credentials(self, _service: str) -> dict:
        return self._credentials

    def get_llm_settings(self) -> dict:
        return self._llm_settings


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def capture_post(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["timeout"] = timeout
        captured["payload"] = json.loads(data)
        return _FakeResponse(
            200, {"choices": [{"message": {"content": '{"block_0": "ok"}'}}]}
        )

    monkeypatch.setattr(gpt_module.requests, "post", fake_post)
    return captured


def _one_block() -> list[TextBlock]:
    return [TextBlock(text="Hello", translation="__SENTINEL__")]


def test_custom_defaults_send_max_tokens_and_reasoning_none(capture_post):
    settings = _FakeSettings(
        {"api_key": "k", "api_url": "http://127.0.0.1:9/v1", "model": "m"}
    )
    engine = CustomTranslation()
    engine.initialize(settings, "English", "French", tr_key="Custom")
    engine.translate(_one_block(), None, "")

    payload = capture_post["payload"]
    assert "max_tokens" in payload
    assert "max_completion_tokens" not in payload
    assert payload["reasoning_effort"] == "none"
    assert capture_post["timeout"] == 180


def test_custom_all_disabled_matches_gpt_shape(capture_post):
    settings = _FakeSettings(
        {
            "api_key": "k",
            "api_url": "http://127.0.0.1:9/v1",
            "model": "m",
            "disable_reasoning": False,
            "use_max_tokens": False,
            "timeout": 80,
        }
    )
    engine = CustomTranslation()
    engine.initialize(settings, "English", "French", tr_key="Custom")
    engine.translate(_one_block(), None, "")

    payload = capture_post["payload"]
    assert "max_completion_tokens" in payload
    assert "max_tokens" not in payload
    assert "reasoning_effort" not in payload
    assert capture_post["timeout"] == 80


@pytest.mark.parametrize(
    "engine_cls,service",
    [
        (GPTTranslation, "Open AI GPT"),
        (DeepseekTranslation, "Deepseek"),
        (GrokTranslation, "xAI"),
    ],
)
def test_gpt_family_non_regression(capture_post, engine_cls, service):
    settings = _FakeSettings({"api_key": "k"})
    engine = engine_cls()
    engine.initialize(settings, "English", "French", model_name="GPT-4.1")
    engine.translate(_one_block(), None, "")

    payload = capture_post["payload"]
    assert "max_completion_tokens" in payload
    assert "reasoning_effort" not in payload
    assert capture_post["timeout"] == 80


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("true", True),
        ("True", True),
        ("1", True),
        ("false", False),
        ("0", False),
        (None, True),
        ("abc", True),
    ],
)
def test_from_credentials_disable_reasoning_coercion(raw, expected):
    creds = {} if raw is None else {"disable_reasoning": raw}
    opts = OpenAICompatOptions.from_credentials(creds)
    assert opts.disable_reasoning is expected


def test_from_credentials_absent_key_defaults_true():
    opts = OpenAICompatOptions.from_credentials({})
    assert opts.disable_reasoning is True
    assert opts.use_max_tokens is True
    assert opts.timeout == 180


@pytest.mark.parametrize(
    "raw_timeout,expected",
    [
        (-5, 180),
        (99999, 180),
        ("80", 80),
        (10, 10),
        (1800, 1800),
        ("not-a-number", 180),
    ],
)
def test_from_credentials_timeout_bounds(raw_timeout, expected):
    opts = OpenAICompatOptions.from_credentials({"timeout": raw_timeout})
    assert opts.timeout == expected


def test_adapt_payload_never_mutates_input():
    payload = {"max_completion_tokens": 100, "messages": []}
    original_copy = dict(payload)
    opts = OpenAICompatOptions(disable_reasoning=True, use_max_tokens=True, timeout=180)

    adapted = adapt_payload(payload, opts)

    assert payload == original_copy
    assert adapted is not payload
    assert adapted["max_tokens"] == 100
    assert "max_completion_tokens" not in adapted
