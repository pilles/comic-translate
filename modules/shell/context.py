"""Fonctions pures d'habillage du panneau contextuel (spec 04, jalon 2). Aucun import PySide6 —
testé hors GUI par `tests/test_shell.py` (précédent : `modules/pagestate/progress.py`).

`panel_context` (sous-étape 2c) décide ce que le panneau de droite doit afficher : la pile
Page/Bulle (`QStackedWidget`, voir `modules/shell/panel.py`) est basculée par
`modules/shell/watcher.py`, qui appelle cette fonction à chaque évaluation — jamais l'inverse
(ce module ne connaît aucun widget Qt, ne lit jamais `main` lui-même)."""

from __future__ import annotations

from typing import Any

_CAPTION_SEPARATOR = " · "

# Valeurs renvoyées par `panel_context` — noms explicites plutôt que chaînes répétées ailleurs
# dans le paquet (`modules/shell/watcher.py`, `modules/shell/panel.py`).
CONTEXT_PAGE = "page"
CONTEXT_BUBBLE = "bubble"


def language_caption(prefix: str, combo_text: str) -> str:
    """« Source » + « English » -> « Source · English ». `combo_text` vide ou blanc -> `prefix`
    seul (pas de séparateur pendu)."""
    combo_text = combo_text.strip()
    if not combo_text:
        return prefix
    return f"{prefix}{_CAPTION_SEPARATOR}{combo_text}"


def panel_context(curr_tblock: Any, curr_tblock_item: Any, search_visible: bool) -> str:
    """`CONTEXT_BUBBLE` si un bloc de texte, un item de texte rendu, ou la recherche est
    sélectionné/visible ; `CONTEXT_PAGE` sinon (rien de sélectionné). Source de vérité :
    `main.curr_tblock`/`main.curr_tblock_item` (affectés à ~20 endroits des contrôleurs) et la
    visibilité de `main.search_panel` (règle « recherche visible => Bulle » : sélectionner un
    résultat de recherche donne le focus à `t_text_edit`/`s_text_edit`, qui doit alors être sur la
    page visible de la pile pour accepter ce focus)."""
    if curr_tblock is not None or curr_tblock_item is not None or search_visible:
        return CONTEXT_BUBBLE
    return CONTEXT_PAGE
