"""modules.history.versions — module pur (spec 03, jalon A).

Couvre : ordre de `set_text` (consigne Ma), invariant tête/champ (f),
dédoublonnage casefold, pré-état prior/manual PAR CHAMP (i, Mc), écriture du
champ dans les trois sorties (g), value="" (h), plafonds avec épinglage,
`versions_of` sur un objet sans attribut `versions`, `record_diff`, et le
warning unique pour MAX_VALUE_CHARS (j).
"""

from __future__ import annotations

import logging


from modules.history import versions


class Blk:
    """Substitut minimal de TextBlock : seul un objet avec `__dict__` et des
    attributs `text`/`translation` est nécessaire à ce module pur."""

    def __init__(self, text: str = "", translation: str = ""):
        self.text = text
        self.translation = translation


def _fields_of(entries):
    return [e["field"] for e in entries]


def test_set_text_first_write_no_prestate_when_field_empty():
    blk = Blk()
    changed = versions.set_text(blk, "text", "Hello", versions.ORIGIN_OCR, {"ocr": "Default"})

    assert changed is True
    assert blk.text == "Hello"
    entries = versions.versions_of(blk, "text")
    assert len(entries) == 1
    assert entries[0]["value"] == "Hello"
    assert entries[0]["origin"] == versions.ORIGIN_OCR
    assert entries[0]["meta"] == {"ocr": "Default"}


def test_set_text_prestate_is_prior_when_field_never_journaled():
    # Bloc rechargé depuis un projet antérieur à la spec 03 : `text` a une
    # valeur mais aucun historique.
    blk = Blk(text="Hello")
    versions.set_text(blk, "text", "World", versions.ORIGIN_MANUAL)

    entries = versions.versions_of(blk, "text")
    assert [e["value"] for e in entries] == ["Hello", "World"]
    assert entries[0]["origin"] == versions.ORIGIN_PRIOR
    assert entries[1]["origin"] == versions.ORIGIN_MANUAL
    assert blk.text == "World"


def test_set_text_prestate_is_manual_when_field_already_journaled():
    blk = Blk(text="Hello")
    versions.set_text(blk, "text", "World", versions.ORIGIN_TRANSLATION)

    # Édition non instrumentée (ex : frappe directe) entre deux appels.
    blk.text = "Edited by hand"
    versions.set_text(blk, "text", "Final", versions.ORIGIN_TRANSLATION)

    entries = versions.versions_of(blk, "text")
    assert [e["value"] for e in entries] == ["Hello", "World", "Edited by hand", "Final"]
    assert [e["origin"] for e in entries] == [
        versions.ORIGIN_PRIOR,
        versions.ORIGIN_TRANSLATION,
        versions.ORIGIN_MANUAL,
        versions.ORIGIN_TRANSLATION,
    ]


def test_prestate_decided_per_field_not_per_block():
    """Mc : un bloc dont seul `translation` a été journalisé doit quand même
    produire un pré-état `prior` (pas `manual`) pour le premier `text`."""
    blk = Blk(text="Original", translation="")
    versions.set_text(blk, "translation", "Trans1", versions.ORIGIN_TRANSLATION)
    versions.set_text(blk, "text", "NewText", versions.ORIGIN_OCR)

    text_entries = versions.versions_of(blk, "text")
    assert text_entries[0]["value"] == "Original"
    assert text_entries[0]["origin"] == versions.ORIGIN_PRIOR


def test_set_text_dedup_casefold_writes_field_no_new_entry():
    blk = Blk()
    versions.set_text(blk, "text", "hello", versions.ORIGIN_OCR)
    changed = versions.set_text(blk, "text", "HELLO", versions.ORIGIN_OCR)

    assert changed is False
    assert blk.text == "HELLO"  # champ écrit malgré le dédoublonnage (Mb)
    entries = versions.versions_of(blk, "text")
    assert len(entries) == 1
    assert entries[0]["value"] == "hello"  # la casse d'origine reste en tête


def test_invariant_head_matches_field_casefold_after_set_text():
    blk = Blk()
    for value in ("Un", "Deux", "deux", "Trois", "TROIS", "Quatre"):
        versions.set_text(blk, "text", value, versions.ORIGIN_MANUAL)
        head = versions.versions_of(blk, "text")[-1]
        assert head["value"].casefold() == (blk.text or "").casefold()


def test_set_text_writes_field_on_dedup_and_on_rejection(caplog):
    blk = Blk()
    versions.set_text(blk, "text", "short", versions.ORIGIN_OCR)

    # Dédoublonnage (g)
    assert versions.set_text(blk, "text", "SHORT", versions.ORIGIN_OCR) is False
    assert blk.text == "SHORT"

    # Rejet MAX_VALUE_CHARS (g, j)
    too_long = "x" * (versions.MAX_VALUE_CHARS + 1)
    with caplog.at_level(logging.WARNING, logger="modules.history.versions"):
        assert versions.set_text(blk, "text", too_long, versions.ORIGIN_OCR) is False
    assert blk.text == too_long
    entries = versions.versions_of(blk, "text")
    assert all(len(e["value"]) <= versions.MAX_VALUE_CHARS for e in entries)


def test_max_value_chars_warns_once_per_process(monkeypatch, caplog):
    monkeypatch.setattr(versions, "_warned_max_value_chars", False)
    blk = Blk()
    too_long = "y" * (versions.MAX_VALUE_CHARS + 1)

    with caplog.at_level(logging.WARNING, logger="modules.history.versions"):
        versions.set_text(blk, "text", too_long, versions.ORIGIN_OCR)
        versions.set_text(blk, "text", too_long + "z", versions.ORIGIN_OCR)

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


def test_set_text_value_empty_string_is_recorded():
    blk = Blk(text="Something")
    changed = versions.set_text(blk, "text", "", versions.ORIGIN_MANUAL)

    assert changed is True
    assert blk.text == ""
    entries = versions.versions_of(blk, "text")
    assert entries[-1]["value"] == ""


def test_versions_of_on_object_without_attribute():
    blk = Blk()
    assert versions.versions_of(blk) == []
    assert versions.versions_of(blk, "text") == []


def test_prune_caps_per_field_pinning_oldest_entry():
    blk = Blk()
    for i in range(versions.MAX_VERSIONS_PER_BLOCK + 1):
        versions.set_text(blk, "text", f"v{i}", versions.ORIGIN_MANUAL)

    versions.prune(blk)
    entries = versions.versions_of(blk, "text")
    assert len(entries) == versions.MAX_VERSIONS_PER_BLOCK
    assert entries[0]["value"] == "v0"  # la plus ancienne reste épinglée
    assert entries[-1]["value"] == f"v{versions.MAX_VERSIONS_PER_BLOCK}"


def test_prune_global_char_budget_respects_pins():
    blk = Blk()
    chunk = "a" * 700
    for i in range(10):
        versions.set_text(
            blk, "text" if i % 2 == 0 else "translation", f"{chunk}{i}", versions.ORIGIN_MANUAL
        )

    total_before = sum(len(e["value"]) for e in versions.versions_of(blk))
    assert total_before > versions.MAX_CHARS_PER_BLOCK

    versions.prune(blk)
    entries = versions.versions_of(blk)
    total_after = sum(len(e["value"]) for e in entries)
    assert total_after <= versions.MAX_CHARS_PER_BLOCK
    # Les entrées épinglées (la plus ancienne de chaque champ) survivent toujours.
    assert any(e["value"] == f"{chunk}0" for e in entries)
    assert any(e["value"] == f"{chunk}1" for e in entries)


def test_pop_head_if_origin_removes_only_matching_head():
    blk = Blk()
    versions.set_text(blk, "text", "A", versions.ORIGIN_OCR)
    versions.set_text(blk, "text", "B", versions.ORIGIN_RESTORE)

    assert versions.pop_head_if_origin(blk, "text", versions.ORIGIN_RESTORE) is True
    assert [e["value"] for e in versions.versions_of(blk, "text")] == ["A"]

    # Rien à retirer : la tête n'est plus "restore".
    assert versions.pop_head_if_origin(blk, "text", versions.ORIGIN_RESTORE) is False


def test_record_diff_only_journals_changed_blocks_with_meta():
    blk_a = Blk(text="A before")
    blk_b = Blk(text="B before")
    before = versions.snapshot([blk_a, blk_b], "text")

    # Simule un moteur qui écrit directement le champ (B4).
    blk_a.text = "A after"
    # blk_b inchangé (le moteur a laissé le texte intact).

    versions.record_diff(
        [blk_a, blk_b], "text", before, versions.ORIGIN_OCR, {"ocr": "Default", "lang": "English"}
    )

    entries_a = versions.versions_of(blk_a, "text")
    assert [e["value"] for e in entries_a] == ["A before", "A after"]
    assert entries_a[-1]["meta"] == {"ocr": "Default", "lang": "English"}

    assert versions.versions_of(blk_b, "text") == []


def test_record_diff_ignores_blocks_missing_from_snapshot():
    blk_a = Blk(text="A")
    before = versions.snapshot([blk_a], "text")

    blk_c = Blk(text="C")  # jamais capturé par `snapshot`
    blk_c.text = "C mutated"
    versions.record_diff([blk_c], "text", before, versions.ORIGIN_OCR)

    assert versions.versions_of(blk_c, "text") == []


def test_set_many_applies_set_text_to_each_item():
    blk_a = Blk()
    blk_b = Blk()
    results = versions.set_many(
        [(blk_a, "text", "Alpha"), (blk_b, "translation", "Beta")],
        versions.ORIGIN_MANUAL,
    )
    assert results == [True, True]
    assert blk_a.text == "Alpha"
    assert blk_b.translation == "Beta"
