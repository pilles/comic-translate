from typing import Any
from .gpt import GPTTranslation
from .compat import OpenAICompatOptions, adapt_payload  # fork: F2 compat Ollama


class CustomTranslation(GPTTranslation):
    """Translation engine using custom LLM configurations with OpenAI-compatible API."""
    
    def __init__(self):
        super().__init__()
    
    def initialize(self, settings: Any, source_lang: str, target_lang: str, tr_key: str, **kwargs) -> None:
        """
        Initialize custom translation engine.
        
        Args:
            settings: Settings object with credentials
            source_lang: Source language name
            target_lang: Target language name
        """
        # Call BaseLLMTranslation's initialize, not GPTTranslation's
        # to avoid the GPT-specific credential loading
        super(GPTTranslation, self).initialize(settings, source_lang, target_lang, **kwargs)
        
        # Get custom credentials instead of OpenAI credentials
        credentials = settings.get_credentials(settings.ui.tr(tr_key))
        self.api_key = credentials.get('api_key', '')
        self.model = credentials.get('model', '')
        
        # Override the API base URL with the custom one
        self.api_base_url = credentials.get('api_url', '').rstrip('/')

        # fork: F2 réglages de compatibilité Ollama (réflexion, max_tokens, timeout dédié)
        self._compat = OpenAICompatOptions.from_credentials(credentials)  # fork: F2
        self.request_timeout = self._compat.timeout  # fork: F2 (entier, remplace le 80 de GPTTranslation)

    # fork: F2 adapte la charge utile OpenAI-compatible avant l'appel HTTP réel de GPTTranslation
    def _make_api_request(self, payload, headers):  # fork: F2
        return super()._make_api_request(adapt_payload(payload, self._compat), headers)  # fork: F2