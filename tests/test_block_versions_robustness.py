"""Robustesse de `modules.history.versions` (mission tester, point 4) :
- `flush_pending` sur un objet mal formé (sans `text`/`translation`) ne doit
  jamais lever.
- `meta` avec des valeurs non-str est coercé en str (`_coerce_meta`),
  documenté et figé par un test.
- `set_text(value=None)` : corrigé (coercion en "", cohérente avec
  `cur = getattr(blk, field, "") or ""`) — voir `set_text` (~l.152).
"""

from __future__ import annotations

from modules.history import versions


class _Malformed:
    """Objet quelconque, sans attribut `text` ni `translation` (ex : bloc
    corrompu par un import tiers, ou tout objet passé par erreur)."""

    def __init__(self):
        self.some_other_attr = 42


class Blk:
    def __init__(self, text: str = "", translation: str = ""):
        self.text = text
        self.translation = translation


def test_flush_pending_on_malformed_object_without_text_or_translation_does_not_raise():
    malformed = _Malformed()

    versions.flush_pending([malformed])  # ne doit pas lever

    assert versions.versions_of(malformed) == []


def test_flush_pending_on_mixed_list_with_malformed_object_does_not_raise():
    good_blk = Blk(text="Hello")
    malformed = _Malformed()

    # `good_blk` n'a jamais été journalisé : premier flush = pré-état "prior".
    versions.flush_pending([good_blk, malformed])

    entries = versions.versions_of(good_blk, "text")
    assert entries[-1]["value"] == "Hello"
    assert entries[-1]["origin"] == versions.ORIGIN_PRIOR
    assert versions.versions_of(malformed) == []


def test_meta_with_non_str_values_is_coerced_to_str():
    """`_coerce_meta` (versions.py) applique `str(k): str(v)` — un `meta`
    avec des valeurs int/float ne lève pas et finit en str pur (contrat
    nécessaire pour rester sérialisable telle quelle par msgpack, voir
    `test_block_versions_types.py`)."""
    blk = Blk()

    versions.set_text(blk, "text", "value", versions.ORIGIN_MANUAL, meta={"count": 5, 7: "seven"})

    entry = versions.versions_of(blk, "text")[-1]
    assert entry["meta"] == {"count": "5", "7": "seven"}
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in entry["meta"].items())


def test_set_text_with_value_none_should_be_coerced_to_empty_string():
    blk = Blk(text="Hello")

    changed = versions.set_text(blk, "text", None, versions.ORIGIN_MANUAL)

    assert changed is True
    assert blk.text == ""
    entries = versions.versions_of(blk, "text")
    assert [e["value"] for e in entries] == ["Hello", ""]
    assert entries[-1]["origin"] == versions.ORIGIN_MANUAL
