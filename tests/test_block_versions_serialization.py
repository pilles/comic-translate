"""Aller-retour msgpack (`ProjectEncoder`/`ProjectDecoder`, comme
`app/projects/project_state_v2.py`) d'un `TextBlock` portant `versions`.

`versions` n'a besoin d'aucun encodeur dédié (contrairement à `numpy.ndarray`,
`QColor`, etc.) : c'est une liste de dict composés uniquement de `str`/`dict`,
des types natifs msgpack — voir `test_block_versions_types.py`. Ce fichier
vérifie l'aller-retour complet du bloc (avec et sans `versions`) et mesure le
budget de volumétrie annoncé par la conception (1 920 blocs, 12 entrées de
300 caractères)."""

from __future__ import annotations

import numpy as np
import msgpack

from app.projects.parsers import ProjectDecoder, ProjectEncoder
from modules.history import versions
from modules.utils.textblock import TextBlock

_BUDGET_BLOCK_COUNT = 1920
_BUDGET_MAX_MB = 12.0


def _round_trip(payload):
    encoder = ProjectEncoder()
    decoder = ProjectDecoder()
    packed = msgpack.packb(payload, default=encoder.encode, use_bin_type=True)
    return msgpack.unpackb(packed, object_hook=decoder.decode, strict_map_key=True)


def _make_block(with_versions: bool) -> TextBlock:
    blk = TextBlock(text_bbox=np.array([0, 0, 100, 40]))
    if with_versions:
        versions.set_text(
            blk, "text", "Bonjour", versions.ORIGIN_OCR, {"ocr": "Default", "lang": "French"}
        )
        versions.set_text(
            blk, "translation", "Hello", versions.ORIGIN_TRANSLATION, {"model": "Custom"}
        )
    return blk


def test_round_trip_block_without_versions():
    blk = _make_block(with_versions=False)
    assert not hasattr(blk, "versions")

    restored = _round_trip({"blk_list": [blk]})["blk_list"][0]

    assert not hasattr(restored, "versions")
    assert versions.versions_of(restored) == []
    assert restored.text == ""


def test_round_trip_block_with_versions():
    blk = _make_block(with_versions=True)
    original_entries = list(versions.versions_of(blk))

    restored = _round_trip({"blk_list": [blk]})["blk_list"][0]

    assert versions.versions_of(restored) == original_entries
    assert restored.text == "Bonjour"
    assert restored.translation == "Hello"


def test_round_trip_preserves_entries_alongside_other_blocks():
    blk_with = _make_block(with_versions=True)
    blk_without = _make_block(with_versions=False)

    restored = _round_trip({"blk_list": [blk_with, blk_without]})["blk_list"]

    assert versions.versions_of(restored[0]) == list(versions.versions_of(blk_with))
    assert versions.versions_of(restored[1]) == []


def test_budget_1920_blocks_12_entries_of_300_chars():
    blocks = []
    for _b in range(_BUDGET_BLOCK_COUNT):
        blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
        for i in range(versions.MAX_VERSIONS_PER_BLOCK):
            field = "text" if i % 2 == 0 else "translation"
            value = f"v{i}".ljust(300, "x")
            versions.set_text(blk, field, value, versions.ORIGIN_MANUAL)
        blocks.append(blk)

    encoder = ProjectEncoder()
    packed = msgpack.packb({"blk_list": blocks}, default=encoder.encode, use_bin_type=True)
    size_mb = len(packed) / (1024 * 1024)
    print(
        f"Budget mesuré : {len(packed)} octets ({size_mb:.2f} Mo) pour "
        f"{_BUDGET_BLOCK_COUNT} blocs x {versions.MAX_VERSIONS_PER_BLOCK} entrées x 300 caractères"
    )

    assert size_mb < _BUDGET_MAX_MB

    # Aller-retour complet sur l'échantillon, pour vérifier qu'aucune entrée
    # n'est perdue à cette échelle.
    decoder = ProjectDecoder()
    restored = msgpack.unpackb(packed, object_hook=decoder.decode, strict_map_key=True)["blk_list"]
    assert len(restored) == _BUDGET_BLOCK_COUNT
    assert len(versions.versions_of(restored[0])) == versions.MAX_VERSIONS_PER_BLOCK
