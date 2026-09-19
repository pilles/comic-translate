"""Intégration hors GUI (spec 03, jalon A) : les vrais `OCRProcessor.process`
et `Translator.translate` (moteurs remplacés par un faux via la fabrique,
B4), les vraies fonctions de casse (`modules.utils.translator_utils`,
non instrumentées, C.3), et le vrai `CacheManager` (M3/M4/(c)).

(a) faux OCR -> faux traducteur -> écriture directe (frappe simulée) ->
    seconde traduction -> une entrée `manual` de pré-état est présente.
(b) `set_upper_case`/`format_translations` ne créent aucune entrée ni
    pré-état (C.3 : la casse pure n'est pas journalisée).
(c) `_apply_cached_translations_to_blocks` : valeur différente de la tête ->
    entrée `cache`, édition écrasée présente au journal ; valeur
    casefold-égale -> aucune entrée, champ écrit.
(d) M3 : `flush_pending` n'agit que sur la liste d'objets qu'on lui donne
    (deux listes de blocs distinctes divergent indépendamment).
"""

from __future__ import annotations

import numpy as np

import modules.ocr.processor as ocr_processor_module
import modules.translation.processor as translation_processor_module
from modules.history import versions
from modules.ocr.processor import OCRProcessor
from modules.translation.processor import Translator
from modules.utils.textblock import TextBlock
from modules.utils.translator_utils import format_translations, set_upper_case
from pipeline.cache_manager import CacheManager


class _FakeUi:
    def tr(self, text: str) -> str:
        return text


class _FakeSettingsPage:
    def __init__(self, ocr_selection: str = "Default", translator_selection: str = "Custom"):
        self.ui = _FakeUi()
        self._ocr_selection = ocr_selection
        self._translator_selection = translator_selection

    def get_tool_selection(self, kind: str) -> str:
        return self._ocr_selection if kind == "ocr" else self._translator_selection


class _FakeMainPage:
    def __init__(self):
        self.settings_page = _FakeSettingsPage()
        self.lang_mapping: dict[str, str] = {}


class _FakeOCREngine:
    """Simule un moteur OCR : écrit `blk.text` lui-même (B4)."""

    def __init__(self, texts: list[str]):
        self._texts = texts

    def process_image(self, img, blk_list):
        for blk, text in zip(blk_list, self._texts):
            blk.text = text
        return blk_list


class _FakeTranslationEngine:
    """Simule un moteur de traduction non-LLM : écrit `blk.translation`."""

    def __init__(self, translations: list[str]):
        self._translations = translations

    def translate(self, blk_list):
        for blk, translation in zip(blk_list, self._translations):
            blk.translation = translation
        return blk_list


def _image() -> np.ndarray:
    return np.zeros((10, 10, 3), dtype=np.uint8)


def test_a_manual_prestate_survives_between_two_translations(monkeypatch):
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
    main_page = _FakeMainPage()

    # OCR (faux moteur, via la fabrique).
    ocr = OCRProcessor()
    ocr.initialize(main_page, "English")
    monkeypatch.setattr(
        ocr_processor_module.OCRFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeOCREngine(["Hello world"])),
    )
    ocr.process(_image(), [blk])

    assert blk.text == "Hello world"
    assert [e["origin"] for e in versions.versions_of(blk, "text")] == [versions.ORIGIN_OCR]

    # Première traduction (faux moteur non-LLM).
    monkeypatch.setattr(
        translation_processor_module.TranslationFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeTranslationEngine(["Bonjour le monde"])),
    )
    translator = Translator(main_page, "English", "French")
    translator.translate([blk], _image(), "")

    assert blk.translation == "Bonjour le monde"
    assert [e["origin"] for e in versions.versions_of(blk, "translation")] == [
        versions.ORIGIN_TRANSLATION
    ]

    # Frappe simulée : édition directe du champ, en dehors de `set_text`.
    blk.translation = "Bonjour tout le monde"

    # Seconde traduction : le moteur écrase avec une nouvelle valeur.
    monkeypatch.setattr(
        translation_processor_module.TranslationFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeTranslationEngine(["Salut la Terre"])),
    )
    translator2 = Translator(main_page, "English", "French")
    translator2.translate([blk], _image(), "")

    assert blk.translation == "Salut la Terre"
    entries = versions.versions_of(blk, "translation")
    assert [e["value"] for e in entries] == [
        "Bonjour le monde",
        "Bonjour tout le monde",
        "Salut la Terre",
    ]
    assert [e["origin"] for e in entries] == [
        versions.ORIGIN_TRANSLATION,
        versions.ORIGIN_MANUAL,  # pré-état : la frappe non instrumentée
        versions.ORIGIN_TRANSLATION,
    ]


def test_b_upper_case_and_format_translations_do_not_journal():
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
    versions.set_text(
        blk, "translation", "bonjour", versions.ORIGIN_TRANSLATION, {"model": "Custom"}
    )
    entries_before = list(versions.versions_of(blk, "translation"))

    set_upper_case([blk], True)
    assert blk.translation == "BONJOUR"
    assert versions.versions_of(blk, "translation") == entries_before

    format_translations([blk], "fr", upper_case=False)
    assert versions.versions_of(blk, "translation") == entries_before


def test_c_apply_cached_translations_records_cache_entry_and_dedupes():
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]), text="Hello")
    blk.translation = "Edited by hand"  # édition non journalisée

    cache = CacheManager()
    cache_key = ("imagehash", "Custom", "English", "French", "no_context")
    block_id = cache._get_block_id(blk)
    cache.translation_cache[cache_key] = {
        block_id: {"source_text": "Hello", "translation": "Salut"}
    }

    cache._apply_cached_translations_to_blocks(cache_key, [blk])

    assert blk.translation == "Salut"
    entries = versions.versions_of(blk, "translation")
    assert entries[-1]["value"] == "Salut"
    assert entries[-1]["origin"] == versions.ORIGIN_CACHE
    assert entries[-1]["meta"] == {"model": "Custom"}
    assert any(e["value"] == "Edited by hand" for e in entries)  # édition écrasée présente

    # Deuxième application, valeur identique (casefold) : dédoublonnée.
    entries_len = len(entries)
    cache._apply_cached_translations_to_blocks(cache_key, [blk])
    assert blk.translation == "Salut"
    assert len(versions.versions_of(blk, "translation")) == entries_len


def test_d_flush_pending_only_touches_the_list_it_is_given():
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
    versions.set_text(blk, "text", "OCR text", versions.ORIGIN_OCR, {"ocr": "Default"})

    # `main.blk_list` : édition directe (frappe), non instrumentée.
    blk.text = "Edited directly"

    # Une liste distincte d'objets (simulateur d'`image_states[...]['blk_list']`
    # capturée avant l'édition, via `deep_copy`, jamais partagée).
    other_list_blk = blk.deep_copy()
    other_list_blk.text = "Different unrelated edit"

    versions.flush_pending([blk])

    entries = versions.versions_of(blk, "text")
    assert entries[-1]["value"] == "Edited directly"
    assert entries[-1]["origin"] == versions.ORIGIN_MANUAL

    # La copie distincte n'a pas été flush : son édition reste hors journal.
    other_entries = versions.versions_of(other_list_blk, "text")
    assert other_entries[-1]["value"] == "OCR text"
