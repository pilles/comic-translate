"""Tests F3 : modules/utils/translator_utils.set_texts_from_json (spec 01 §5).

Comportement historique préservé pour le cas nominal ; le correctif F3 ajoute
seulement une sortie propre (`None`, aucune exception) sur les entrées
malformées.
"""

from __future__ import annotations

import pytest

from modules.utils.textblock import TextBlock
from modules.utils.translator_utils import set_texts_from_json

SENTINEL = "__SENTINEL__"


def _blocks(n: int) -> list[TextBlock]:
    return [TextBlock(text=f"src_{i}", translation=SENTINEL) for i in range(n)]


def test_clean_json_sets_translations():
    blocks = _blocks(2)
    result = set_texts_from_json(blocks, '{"block_0": "Bonjour", "block_1": "Salut"}')
    assert result == {"block_0": "Bonjour", "block_1": "Salut"}
    assert blocks[0].translation == "Bonjour"
    assert blocks[1].translation == "Salut"


def test_markdown_fenced_json_is_extracted():
    blocks = _blocks(1)
    raw = '```json\n{"block_0": "Bonjour"}\n```'
    result = set_texts_from_json(blocks, raw)
    assert result == {"block_0": "Bonjour"}
    assert blocks[0].translation == "Bonjour"


def test_missing_key_keeps_sentinel_but_returns_dict():
    blocks = _blocks(2)
    result = set_texts_from_json(blocks, '{"block_0": "Bonjour"}')
    assert result == {"block_0": "Bonjour"}
    assert blocks[0].translation == "Bonjour"
    assert blocks[1].translation == SENTINEL  # jamais touché


def test_no_braces_returns_none_without_exception():
    blocks = _blocks(1)
    result = set_texts_from_json(blocks, "no json here at all")
    assert result is None
    assert blocks[0].translation == SENTINEL


def test_malformed_json_returns_none_without_exception():
    blocks = _blocks(1)
    result = set_texts_from_json(blocks, '{"block_0": "unterminated')
    assert result is None
    assert blocks[0].translation == SENTINEL


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_none_or_empty_input_returns_none_without_exception(raw):
    blocks = _blocks(1)
    result = set_texts_from_json(blocks, raw)
    assert result is None
    assert blocks[0].translation == SENTINEL


def test_null_value_is_assigned_as_is():
    blocks = _blocks(1)
    result = set_texts_from_json(blocks, '{"block_0": null}')
    assert result == {"block_0": None}
    assert blocks[0].translation is None


def test_two_concatenated_json_objects_returns_none():
    blocks = _blocks(2)
    raw = '{"block_0": "a"} {"block_1": "b"}'
    result = set_texts_from_json(blocks, raw)
    assert result is None
    assert blocks[0].translation == SENTINEL
    assert blocks[1].translation == SENTINEL


def test_llm_line_breaks_become_single_spaces():
    # Cas réel (page 011, 2026-09-27) : le modèle insère un saut de ligne en pleine phrase, que le
    # rendu respectait ; c'est au rendu de couper selon la largeur de la bulle, jamais au modèle.
    blocks = _blocks(2)
    raw = '{"block_0": "LES CONSEILS DE SON PÈRE\\nET VOLÉ TROP PRÈS", "block_1": "  A \\r\\n\\n  B  "}'
    set_texts_from_json(blocks, raw)
    assert blocks[0].translation == "LES CONSEILS DE SON PÈRE ET VOLÉ TROP PRÈS"
    assert blocks[1].translation == "A B"
