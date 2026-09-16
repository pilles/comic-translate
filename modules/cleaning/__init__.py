"""Nettoyage additionnel des légendes hors bulles (specs/02-nettoyage-legendes.md).

Paquet pur : numpy / imkit / mahotas uniquement, aucun import Qt ni
`pipeline/inpainting.py` (`bubble_cleanup` est injecté par l'appelant).
"""

from __future__ import annotations

from .apply import clean_page, cleaning_config_from_settings_page
from .config import INERT, UI_DEFAULTS, CleaningConfig, is_inert
from .lines import run_ge
from .uniform import ComponentReport

__all__ = [
    "CleaningConfig",
    "INERT",
    "UI_DEFAULTS",
    "is_inert",
    "clean_page",
    "cleaning_config_from_settings_page",
    "run_ge",
    "ComponentReport",
]
