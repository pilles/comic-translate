"""Fonctions pures d'habillage du panneau contextuel (spec 04, jalon 2). Aucun import PySide6 —
testé hors GUI par `tests/test_shell.py` (précédent : `modules/pagestate/progress.py`).

`panel_context` (calcul de ce que le panneau de droite doit afficher selon la sélection) attend la
pile Page/Bulle de la sous-étape 2c : non implémenté ici, volontairement (2a n'est qu'une
disposition, pas une bascule contextuelle)."""

from __future__ import annotations

_CAPTION_SEPARATOR = " · "


def language_caption(prefix: str, combo_text: str) -> str:
    """« Source » + « English » -> « Source · English ». `combo_text` vide ou blanc -> `prefix`
    seul (pas de séparateur pendu)."""
    combo_text = combo_text.strip()
    if not combo_text:
        return prefix
    return f"{prefix}{_CAPTION_SEPARATOR}{combo_text}"
