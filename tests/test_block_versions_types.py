"""Les entrées d'historique ne contiennent que des types msgpack natifs
(str, dict, list) : `ProjectEncoder` ne doit jamais être sollicité dessus, et
ne doit jamais lever de TypeError si on l'appelle quand même (spec 03,
inventaire §6 point 5 : `ProjectEncoder.encode` renvoie l'objet inchangé pour
un type inconnu — un type NON natif provoquerait un TypeError à l'emballage
msgpack, silencieux jusqu'à la sauvegarde)."""

from __future__ import annotations

import msgpack

from app.projects.parsers import ProjectEncoder
from modules.history import versions


class Blk:
    def __init__(self, text: str = "", translation: str = ""):
        self.text = text
        self.translation = translation


def _make_entries() -> list[versions.HistoryEntry]:
    blk = Blk()
    versions.set_text(
        blk, "text", "Bonjour", versions.ORIGIN_OCR, {"ocr": "Default", "lang": "French"}
    )
    versions.set_text(blk, "translation", "Hello", versions.ORIGIN_TRANSLATION, {"model": "Custom"})
    versions.set_text(blk, "translation", "", versions.ORIGIN_MANUAL)
    return versions.versions_of(blk)


def test_entries_are_only_simple_types():
    for entry in _make_entries():
        assert isinstance(entry, dict)
        assert isinstance(entry["field"], str)
        assert isinstance(entry["value"], str)
        assert isinstance(entry["origin"], str)
        assert isinstance(entry["at"], str)
        assert isinstance(entry["meta"], dict)
        for k, v in entry["meta"].items():
            assert isinstance(k, str)
            assert isinstance(v, str)


def test_project_encoder_encode_is_a_noop_on_entries():
    encoder = ProjectEncoder()
    for entry in _make_entries():
        # `encode` ne doit jamais être appelé sur ces objets en pratique
        # (msgpack les emballe nativement) ; on vérifie ici qu'un appel
        # explicite ne lève pas et renvoie l'objet inchangé (chemin de repli
        # documenté par `ProjectEncoder.encode`).
        assert encoder.encode(entry) is entry


def test_entries_pack_with_project_encoder_default_without_typeerror():
    encoder = ProjectEncoder()
    entries = _make_entries()

    packed = msgpack.packb(entries, default=encoder.encode, use_bin_type=True)
    assert isinstance(packed, bytes)

    unpacked = msgpack.unpackb(packed, raw=False, strict_map_key=True)
    assert unpacked == entries
