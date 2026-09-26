"""Couverture directe des 6 sites d'écriture instrumentés (consigne Md du
critic pass 2), sans passer par une vraie `ComicTranslate` (pas de `--gui`) :
des fakes minimaux tiennent lieu de `main_page`/`pipeline`/`settings_page`.

Sites couverts ici, absents des autres fichiers de test hors GUI :
- `pipeline/ocr_handler.py:46` (cache_ocr, bloc unique, cache rempli)
- `pipeline/ocr_handler.py:80` (ocr, bloc unique, cache manquant -> traité)
- `pipeline/cache_manager.py:339` (cache_ocr, page entière via
  `_apply_cached_ocr_to_blocks`, jamais exercé ailleurs — seul le pendant
  traduction `:346` l'était, dans `test_block_versions_integration.py::test_c`)
- `pipeline/translation_handler.py:56` (cache, bloc unique)
- `pipeline/translation_handler.py:87` (translation, bloc unique, cache
  manquant -> traduit puis mis en cache)

Chaque test vérifie l'origine ET le `meta` (jamais vide, Md).
"""

from __future__ import annotations

import numpy as np

import modules.ocr.processor as ocr_processor_module
import modules.translation.processor as translation_processor_module
from modules.history import versions
from modules.utils.textblock import TextBlock
from pipeline.cache_manager import CacheManager
from pipeline.ocr_handler import OCRHandler
from pipeline.translation_handler import TranslationHandler


# --- Fakes minimaux, sans Qt --------------------------------------------


class _FakeImageViewer:
    def __init__(self):
        self.rectangles = [object()]  # non vide -> hasPhoto()+rectangles vrai

    def hasPhoto(self):
        return True

    def get_image_array(self, paint_all=False, include_patches=True):
        return np.zeros((10, 10, 3), dtype=np.uint8)


class _FakeCombo:
    def __init__(self, text: str):
        self._text = text

    def currentText(self):
        return self._text


class _FakeCheckbox:
    def __init__(self, checked: bool = False):
        self._checked = checked

    def isChecked(self):
        return self._checked


class _FakeSettingsUi:
    def __init__(self):
        self.uppercase_checkbox = _FakeCheckbox(False)

    def tr(self, text: str) -> str:
        return text


class _FakeSettingsPage:
    def __init__(self, ocr_selection="Default", translator_selection="Custom"):
        self.ui = _FakeSettingsUi()
        self._ocr_selection = ocr_selection
        self._translator_selection = translator_selection

    def get_tool_selection(self, kind: str) -> str:
        return self._ocr_selection if kind == "ocr" else self._translator_selection

    def is_gpu_enabled(self):
        return False

    def get_llm_settings(self):
        return {"extra_context": ""}

    def get_credentials(self, translator_key: str) -> dict:
        return {}


class _FakeMainPage:
    def __init__(self, blk_list):
        self.image_viewer = _FakeImageViewer()
        self.settings_page = _FakeSettingsPage()
        self.lang_mapping: dict[str, str] = {}
        self.s_combo = _FakeCombo("English")
        self.t_combo = _FakeCombo("French")
        self.blk_list = blk_list


class _FakePipeline:
    def __init__(self, selected_block):
        self._selected_block = selected_block

    def get_selected_block(self):
        return self._selected_block


class _FakeOCREngine:
    def __init__(self, texts):
        self._texts = texts

    def process_image(self, img, blk_list):
        for blk, text in zip(blk_list, self._texts):
            blk.text = text
        return blk_list


class _FakeTranslationEngine:
    def __init__(self, translations):
        self._translations = translations

    def translate(self, blk_list):
        for blk, translation in zip(blk_list, self._translations):
            blk.translation = translation
        return blk_list


def _blk() -> TextBlock:
    return TextBlock(text_bbox=np.array([0, 0, 10, 10]))


# --- ocr_handler.py:46 (cache_ocr, bloc unique, cache rempli) -----------


def test_ocr_handler_single_block_cache_hit_records_cache_ocr_with_meta(monkeypatch):
    blk = _blk()
    main_page = _FakeMainPage([blk])
    cache_manager = CacheManager()
    pipeline = _FakePipeline(blk)
    handler = OCRHandler(main_page, cache_manager, pipeline)

    image = main_page.image_viewer.get_image_array()
    cache_key = cache_manager._get_ocr_cache_key(image, "English", "Default", "cpu")
    monkeypatch.setattr("pipeline.ocr_handler.resolve_device", lambda gpu: "cpu")
    block_id = cache_manager._get_block_id(blk)
    cache_manager.ocr_cache[cache_key] = {block_id: "Cached text"}

    handler.OCR_image(single_block=True)

    assert blk.text == "Cached text"
    entries = versions.versions_of(blk, "text")
    assert [e["origin"] for e in entries] == [versions.ORIGIN_CACHE_OCR]
    assert entries[-1]["meta"] == {"ocr": "Default"}


# --- ocr_handler.py:80 (ocr, bloc unique, cache manquant -> traité) -----


def test_ocr_handler_single_block_cache_miss_processes_and_records_ocr_with_meta(
    monkeypatch,
):
    blk = _blk()
    main_page = _FakeMainPage([blk])
    cache_manager = CacheManager()
    pipeline = _FakePipeline(blk)
    handler = OCRHandler(main_page, cache_manager, pipeline)

    monkeypatch.setattr("pipeline.ocr_handler.resolve_device", lambda gpu: "cpu")
    monkeypatch.setattr(
        ocr_processor_module.OCRFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeOCREngine(["Freshly OCR'd"])),
    )

    handler.OCR_image(single_block=True)

    assert blk.text == "Freshly OCR'd"
    entries = versions.versions_of(blk, "text")
    assert [e["origin"] for e in entries] == [versions.ORIGIN_OCR]
    assert entries[-1]["meta"] == {"ocr": "Default"}


# --- cache_manager.py:339 (cache_ocr, page entière) ----------------------


def test_apply_cached_ocr_to_blocks_records_cache_ocr_with_meta_and_dedupes():
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]), text="Edited by hand")
    cache = CacheManager()
    cache_key = ("imagehash", "Default", "English", "cpu")
    block_id = cache._get_block_id(blk)
    cache.ocr_cache[cache_key] = {block_id: "Cached OCR text"}

    cache._apply_cached_ocr_to_blocks(cache_key, [blk])

    assert blk.text == "Cached OCR text"
    entries = versions.versions_of(blk, "text")
    assert entries[-1]["origin"] == versions.ORIGIN_CACHE_OCR
    assert entries[-1]["meta"] == {"ocr": "Default"}
    assert any(e["value"] == "Edited by hand" for e in entries)  # édition écrasée présente

    # Deuxième application, valeur identique (casefold) : dédoublonnée (Mb).
    entries_len = len(entries)
    cache._apply_cached_ocr_to_blocks(cache_key, [blk])
    assert len(versions.versions_of(blk, "text")) == entries_len


# --- translation_handler.py:56 (cache, bloc unique) -----------------------


def test_translation_handler_single_block_cache_hit_records_cache_with_meta(monkeypatch):
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]), text="Hello")
    main_page = _FakeMainPage([blk])
    cache_manager = CacheManager()
    pipeline = _FakePipeline(blk)
    handler = TranslationHandler(main_page, cache_manager, pipeline)

    image = main_page.image_viewer.get_image_array()
    cache_key = cache_manager._get_translation_cache_key(image, "English", "French", "Custom", "")
    block_id = cache_manager._get_block_id(blk)
    cache_manager.translation_cache[cache_key] = {
        block_id: {"source_text": "Hello", "translation": "Cached translation"}
    }

    # `Translator.__init__` construit son moteur avant même de savoir si le
    # cache va servir la valeur : sans ce monkeypatch, la fabrique "Custom"
    # tenterait un vrai réglage réseau (hors périmètre de ce test).
    monkeypatch.setattr(
        translation_processor_module.TranslationFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeTranslationEngine([])),
    )

    handler.translate_image(single_block=True)

    assert blk.translation == "Cached translation"
    entries = versions.versions_of(blk, "translation")
    assert [e["origin"] for e in entries] == [versions.ORIGIN_CACHE]
    assert entries[-1]["meta"] == {"model": "Custom"}


# --- translation_handler.py:87 (translation, bloc unique, cache manquant) -


def test_translation_handler_single_block_cache_miss_translates_and_records_with_meta(
    monkeypatch,
):
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]), text="Hello")
    main_page = _FakeMainPage([blk])
    cache_manager = CacheManager()
    pipeline = _FakePipeline(blk)
    handler = TranslationHandler(main_page, cache_manager, pipeline)

    monkeypatch.setattr(
        translation_processor_module.TranslationFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeTranslationEngine(["Bonjour"])),
    )

    handler.translate_image(single_block=True)

    assert blk.translation == "Bonjour"
    entries = versions.versions_of(blk, "translation")
    assert [e["origin"] for e in entries] == [versions.ORIGIN_TRANSLATION]
    assert entries[-1]["meta"] == {"model": "Custom"}
