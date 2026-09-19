import numpy as np

from ..utils.textblock import TextBlock
from ..history import versions as history_versions  # fork: historique par bloc (jalon A)
from .base import LLMTranslation
from .factory import TranslationFactory


class Translator:
    """
    Main translator class that orchestrates the translation process.
    
    Supports multiple translation engines including:
    - Traditional translators (e.g Google, Microsoft, DeepL, Yandex)
    - LLM-based translators (e.g GPT, Claude, Gemini, Deepseek, Custom)
    """
    
    def __init__(self, main_page, source_lang: str = "", target_lang: str = ""):
        """
        Initialize translator with settings and languages.
        
        Args:
            main_page: Main application page with settings
            source_lang: Source language name (localized)
            target_lang: Target language name (localized)
        """
        self.main_page = main_page
        self.settings = main_page.settings_page
        
        self.translator_key = self._get_translator_key(self.settings.get_tool_selection('translator'))
        
        self.source_lang = source_lang
        self.source_lang_en = self._get_english_lang(main_page, self.source_lang)
        self.target_lang = target_lang
        self.target_lang_en = self._get_english_lang(main_page, self.target_lang)
        
        # Create appropriate engine using factory
        self.engine = TranslationFactory.create_engine(
            self.settings,
            self.source_lang_en,
            self.target_lang_en,
            self.translator_key
        )
        
        # Track engine type for method dispatching
        self.is_llm_engine = isinstance(self.engine, LLMTranslation)
    
    def _get_translator_key(self, localized_translator: str) -> str:
        """
        Map localized translator names to standard keys.
        
        Args:
            localized_translator: Translator name in UI language
            
        Returns:
            Standard translator key
        """
        translator_map = {
            self.settings.ui.tr("Custom"): "Custom",
            self.settings.ui.tr("Deepseek"): "Deepseek",
            self.settings.ui.tr("GPT-4.1"): "GPT-4.1",
            self.settings.ui.tr("GPT-4.1-mini"): "GPT-4.1-mini",
            self.settings.ui.tr("Claude-4.6-Sonnet"): "Claude-4.6-Sonnet",
            self.settings.ui.tr("Claude-4.5-Haiku"): "Claude-4.5-Haiku",
            self.settings.ui.tr("Gemini-3.1-Flash-Lite"): "Gemini-3.1-Flash-Lite",
            self.settings.ui.tr("Gemini-2.5-Pro"): "Gemini-2.5-Pro",
            self.settings.ui.tr("Google Translate"): "Google Translate",
            self.settings.ui.tr("Microsoft Translator"): "Microsoft Translator",
            self.settings.ui.tr("DeepL"): "DeepL",
            self.settings.ui.tr("Yandex"): "Yandex"
        }
        return translator_map.get(localized_translator, localized_translator)
    
    def _get_english_lang(self, main_page, translated_lang: str) -> str:
        """
        Get English language name from localized language name.
        
        Args:
            main_page: Main application page with language mapping
            translated_lang: Language name in UI language
            
        Returns:
            Language name in English
        """
        return main_page.lang_mapping.get(translated_lang, translated_lang)
    
    def translate(self, blk_list: list[TextBlock], image: np.ndarray = None, extra_context: str = "") -> list[TextBlock]:
        """
        Translate text in text blocks using the configured translation engine.
        
        Args:
            blk_list: List of TextBlock objects to translate
            image: Image as numpy array (for context in LLM translators)
            extra_context: Additional context information for translation
            
        Returns:
            List of updated TextBlock objects with translations
        """
        before = history_versions.snapshot(blk_list, "translation")  # fork: historique par bloc (jalon A)
        if self.is_llm_engine:
            # LLM translators need image and extra context
            result = self.engine.translate(blk_list, image, extra_context)  # fork: historique par bloc (jalon A)
        else:
            # Text-based translators only need the text blocks
            result = self.engine.translate(blk_list)  # fork: historique par bloc (jalon A)

        history_versions.record_diff(  # fork: historique par bloc (jalon A)
            blk_list, "translation", before, "translation",
            {"model": self.translator_key, "target": self.target_lang_en}
        )  # fork: historique par bloc (jalon A)
        return result  # fork: historique par bloc (jalon A)