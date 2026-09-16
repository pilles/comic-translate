"""Tests F3 : contrat de prompt figé (spec 01 §5).

`build_user_prompt` doit rester au caractère près identique à l'ancien
comportement historique (partagé entre l'app et tools/bench_translation.py).
"""

from __future__ import annotations

from modules.translation.base import LLMTranslation
from modules.utils.textblock import TextBlock
from modules.utils.translator_utils import build_user_prompt, get_raw_text


def test_build_user_prompt_matches_historical_string():
    result = build_user_prompt("Some extra context", "raw text here")
    expected = (
        "Some extra context\n"
        "Make the translation sound as natural as possible.\n"
        "Translate this:\n"
        "raw text here"
    )
    assert result == expected


def test_build_user_prompt_empty_context():
    result = build_user_prompt("", "raw")
    expected = (
        "\nMake the translation sound as natural as possible.\nTranslate this:\nraw"
    )
    assert result == expected


def test_get_raw_text_uses_block_indices():
    blocks = [TextBlock(text="Hello"), TextBlock(text="World")]
    raw = get_raw_text(blocks)
    assert '"block_0": "Hello"' in raw
    assert '"block_1": "World"' in raw


class _ConcreteLLM(LLMTranslation):
    def initialize(self, settings, source_lang, target_lang, **kwargs) -> None:
        pass

    def translate(self, blk_list, image, extra_context):
        return blk_list


def test_get_system_prompt_mentions_both_languages():
    engine = _ConcreteLLM()
    prompt = engine.get_system_prompt("English", "French")
    assert "English" in prompt
    assert "French" in prompt
