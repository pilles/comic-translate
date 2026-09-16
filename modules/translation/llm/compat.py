"""Adaptation des requêtes OpenAI-compatibles pour les serveurs type Ollama (fork, F2).

Ollama (`/v1`) accepte `reasoning_effort` mais ignore `max_completion_tokens`
(il honore `max_tokens`) ; sans indication, un modèle qui a la capacité
`thinking` réfléchit indéfiniment. Voir specs/01-socle-fork-ollama.md §3
pour les mesures qui justifient ces défauts.

Ce module n'a aucune dépendance à l'UI ni au réseau : il ne fait que
transformer un dict de payload et un dict de credentials.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TIMEOUT = 180
MIN_TIMEOUT = 10
MAX_TIMEOUT = 1800

_TRUE_STRINGS = {"true", "1"}
_FALSE_STRINGS = {"false", "0"}


def _coerce_bool(value: object, default: bool) -> bool:
    """Tolère bool natif, "true"/"false"/"1"/"0" (insensible à la casse), absent ou None."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_STRINGS:
            return True
        if normalized in _FALSE_STRINGS:
            return False
        return default
    return default


def _coerce_timeout(value: object) -> int:
    """Tolère int/str ; borne 10..1800 ; défaut 180 si absent ou aberrant."""
    try:
        timeout = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT
    if timeout < MIN_TIMEOUT or timeout > MAX_TIMEOUT:
        return DEFAULT_TIMEOUT
    return timeout


@dataclass(frozen=True)
class OpenAICompatOptions:
    """Réglages de compatibilité Ollama pour le traducteur Custom."""

    disable_reasoning: bool = True
    use_max_tokens: bool = True
    timeout: int = DEFAULT_TIMEOUT

    @classmethod
    def from_credentials(cls, creds: dict) -> "OpenAICompatOptions":
        return cls(
            disable_reasoning=_coerce_bool(creds.get("disable_reasoning"), True),
            use_max_tokens=_coerce_bool(creds.get("use_max_tokens"), True),
            timeout=_coerce_timeout(creds.get("timeout", DEFAULT_TIMEOUT)),
        )


def adapt_payload(payload: dict, opts: OpenAICompatOptions) -> dict:
    """Adapte une charge utile OpenAI-compatible pour un serveur type Ollama.

    Ne mute jamais `payload` : renvoie toujours une copie.
    """
    adapted = dict(payload)
    if opts.use_max_tokens and "max_completion_tokens" in adapted:
        adapted["max_tokens"] = adapted.pop("max_completion_tokens")
    if opts.disable_reasoning:
        adapted.setdefault("reasoning_effort", "none")
    return adapted
