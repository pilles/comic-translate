"""« Fork -> origine » approximé (mission tester, point 3).

On ne peut pas rejouer `TextBlock.deep_copy` d'ORIGINE (`filvyb`/`upstream`)
depuis ce dépôt sans dupliquer du code amont. On vérifie à la place que les
chemins amont qui manipulent un `TextBlock` porteur de `versions`
(`get_raw_text`, `set_texts_from_json`, `format_translations`,
`TextBlock.deep_copy`) fonctionnent sans exception avec `versions` présent,
et que l'export PSD (`app/controllers/psd_exporter.py`) ne touche jamais à
`versions` (grep, pas seulement absence de crash — un exporteur qui lirait
`versions` par accident romprait le contrat « fichier amont non modifié
pour ce champ »)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from modules.history import versions
from modules.utils.textblock import TextBlock
from modules.utils.translator_utils import format_translations, get_raw_text, set_texts_from_json

REPO_ROOT = Path(__file__).resolve().parent.parent


def _blk_with_versions() -> TextBlock:
    blk = TextBlock(text_bbox=np.array([0, 0, 100, 40]), text="Hello")
    versions.set_text(blk, "text", "Hello world", versions.ORIGIN_OCR, {"ocr": "Default"})
    versions.set_text(
        blk, "translation", "Bonjour le monde", versions.ORIGIN_TRANSLATION, {"model": "Custom"}
    )
    return blk


def test_get_raw_text_ignores_versions_attribute():
    blk = _blk_with_versions()

    raw = get_raw_text([blk])

    assert "Hello world" in raw
    assert "versions" not in raw


def test_set_texts_from_json_does_not_touch_versions():
    blk = _blk_with_versions()
    before = list(versions.versions_of(blk))

    set_texts_from_json([blk], '{"block_0": "Salut le monde"}')

    assert blk.translation == "Salut le monde"
    # set_texts_from_json (amont, non instrumenté) écrit directement le champ
    # sans passer par set_text : aucune entrée créée, journal inchangé.
    assert versions.versions_of(blk) == before


def test_format_translations_with_versions_present_does_not_raise_and_does_not_journal():
    blk = _blk_with_versions()
    blk.translation = "bonjour"
    before = list(versions.versions_of(blk))

    format_translations([blk], "fr", upper_case=True)

    assert blk.translation == "BONJOUR"
    assert versions.versions_of(blk) == before


def test_deep_copy_with_versions_present_does_not_raise_and_preserves_other_fields():
    blk = _blk_with_versions()

    copy = blk.deep_copy()

    assert copy.text == blk.text
    assert copy.translation == blk.translation
    assert versions.versions_of(copy) == versions.versions_of(blk)
    assert copy.versions is not blk.versions


def test_psd_exporter_never_references_versions_attribute():
    """Contrôle statique (grep) : `app/controllers/psd_exporter.py` est un
    fichier amont non touché par le jalon A (voir conception §F, « non
    touchés »). Si quelqu'un ajoutait par erreur une lecture de
    `blk.versions` dans l'export PSD, ce test échouerait avant tout crash
    runtime (l'export PSD n'est pas exercé hors GUI ici)."""
    psd_exporter = REPO_ROOT / "app" / "controllers" / "psd_exporter.py"
    assert psd_exporter.exists()

    content = psd_exporter.read_text(encoding="utf-8")

    assert "versions" not in content
