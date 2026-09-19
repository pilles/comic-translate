"""TextBlock.deep_copy transporte `versions` en copie plate (jalon A, voir
`modules/utils/textblock.py:deep_copy`) : nouvelle liste de nouveaux dict,
`meta` copié aussi — les dict d'entrée de la copie et de l'original ne
doivent jamais être partagés (append en place dans l'un n'affecte pas
l'autre)."""

from __future__ import annotations

import numpy as np

from modules.history import versions
from modules.utils.textblock import TextBlock


def _make_block_with_versions() -> TextBlock:
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
    versions.set_text(blk, "text", "Bonjour", versions.ORIGIN_OCR, {"ocr": "Default"})
    versions.set_text(blk, "translation", "Hello", versions.ORIGIN_TRANSLATION, {"model": "Custom"})
    return blk


def test_deep_copy_without_versions_attribute():
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
    assert not hasattr(blk, "versions")

    copy = blk.deep_copy()

    assert not hasattr(copy, "versions")


def test_deep_copy_copies_versions_content():
    blk = _make_block_with_versions()
    copy = blk.deep_copy()

    assert versions.versions_of(copy) == versions.versions_of(blk)


def test_deep_copy_versions_list_is_a_new_list():
    blk = _make_block_with_versions()
    copy = blk.deep_copy()

    assert copy.versions is not blk.versions

    # Muter la copie (append direct, comme le ferait `set_text`) ne doit
    # jamais se répercuter sur l'original — sans quoi OCR/traduction en
    # mode bloc unique (qui travaillent sur des copies jetables, B4)
    # pollueraient le bloc réel.
    versions.set_text(copy, "text", "Autre chose", versions.ORIGIN_MANUAL)
    assert len(versions.versions_of(copy, "text")) == len(versions.versions_of(blk, "text")) + 1
    assert versions.versions_of(blk, "text")[-1]["value"] == "Bonjour"


def test_deep_copy_entries_and_meta_dicts_are_new_objects():
    blk = _make_block_with_versions()
    copy = blk.deep_copy()

    for original_entry, copied_entry in zip(blk.versions, copy.versions):
        assert original_entry is not copied_entry
        assert original_entry == copied_entry
        assert original_entry["meta"] is not copied_entry["meta"]
        assert original_entry["meta"] == copied_entry["meta"]

    # Muter un dict de meta sur la copie ne doit pas atteindre l'original.
    copy.versions[0]["meta"]["ocr"] = "Autre moteur"
    assert blk.versions[0]["meta"]["ocr"] == "Default"
