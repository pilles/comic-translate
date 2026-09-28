"""Réinitialisation de page — module pur (spec 04, jalon 3, sous-étape 3a).

Aucune dépendance à PySide6 : importable depuis les tests hors `--gui` (précédent :
`modules/pagestate/collect.py`, `modules/history/versions.py`). Les fonctions qui lisent `main`
(`availability`, `page_matches`, `stack_matches`) le font par duck typing (`getattr`), sans jamais
importer PySide6 elles-mêmes — même contrat que `modules.pagestate.collect.page_progress(main, ...)`.

Décisions de Philippe (2026-09-28, cadrage validé par le critic) :
- Caches OCR/traduction de la page invalidés au reset (« refaire le travail »).
- Portée : la page affichée seule, même si plusieurs pages sont sélectionnées dans la liste.
"""

from __future__ import annotations

from typing import Any

# --- État vierge et fusion à l'annulation ----------------------------------------------------

# Clés d'`image_states[page]` que la réinitialisation vide — le reste (langues, `skip`,
# `export_group_name`, clés inconnues d'un `.ctpr` futur) survit tel quel.
PROCESSED_KEYS: tuple[str, ...] = ("blk_list", "brush_strokes")

# Sous-clés de `viewer_state` que la réinitialisation vide (en plus de retirer `push_to_stack`).
# `rectangles`/`text_items_state` doivent toujours être présentes (listes vides), jamais absentes :
# `ImageViewer.load_state` fait `state['rectangles']` sans `.get` (défaut amont n°4, ADR-014).
_VIEWER_PROCESSED_KEYS: tuple[str, ...] = ("rectangles", "text_items_state")
_PUSH_TO_STACK_KEY = "push_to_stack"


def blank_page_state(state: dict) -> dict:
    """Copie de `state` (jamais mutée) avec les clés « traitées » vidées : `blk_list`,
    `brush_strokes`, `viewer_state['rectangles']`, `viewer_state['text_items_state']`, et
    `viewer_state['push_to_stack']` retirée (un lot resterait sinon en attente d'un macro de rendu
    qui ne viendra jamais, `app/controllers/image.py:1091-1097`). Tout le reste — langues, `skip`,
    `export_group_name`, transformation/centre de vue (`viewer_state['transform'/'center'/
    'scene_rect']`), clés inconnues — survit à l'identique."""
    blank = dict(state)
    for key in PROCESSED_KEYS:
        blank[key] = []

    viewer_state = dict(state.get("viewer_state") or {})
    for key in _VIEWER_PROCESSED_KEYS:
        viewer_state[key] = []
    viewer_state.pop(_PUSH_TO_STACK_KEY, None)
    blank["viewer_state"] = viewer_state

    return blank


def merge_processed(current: dict, before: dict) -> dict:
    """Renvoie une copie de `current` où les clés « traitées » (`PROCESSED_KEYS`, plus les
    sous-clés de `viewer_state` vidées par `blank_page_state`) ont été remplacées par celles de
    `before` — le reste de `current` (langues, `skip`, etc., qui ont pu changer pendant que la
    page était vierge) est conservé. Ni `current` ni `before` ne sont mutés."""
    merged = dict(current)
    for key in PROCESSED_KEYS:
        if key in before:
            merged[key] = before[key]
        else:
            merged.pop(key, None)

    current_viewer = dict(current.get("viewer_state") or {})
    before_viewer_raw = before.get("viewer_state")
    before_viewer = before_viewer_raw if isinstance(before_viewer_raw, dict) else {}
    for key in (*_VIEWER_PROCESSED_KEYS, _PUSH_TO_STACK_KEY):
        if key in before_viewer:
            current_viewer[key] = before_viewer[key]
        else:
            current_viewer.pop(key, None)
    merged["viewer_state"] = current_viewer

    return merged


def is_pristine(
    blk_list: Any,
    viewer_state: dict | None,
    brush_strokes: Any,
    patches: Any,
) -> bool:
    """Vrai si la page vivante ne comporte aucun bloc, rectangle, texte rendu, tracé, ni patch —
    lu sur l'état vivant (`main.blk_list`, `image_viewer.save_state()`/`save_brush_strokes()`,
    `image_patches.get(p)`), jamais sur `image_states` (critic MIN4 : `image_states[p]` n'est mis à
    jour qu'à la navigation, il mentirait sur la page affichée)."""
    viewer_state = viewer_state or {}
    return (
        not blk_list
        and not viewer_state.get("rectangles")
        and not viewer_state.get("text_items_state")
        and not brush_strokes
        and not patches
    )


def drop_cache_entries(cache: dict, image_hash: Any) -> int:
    """Supprime en place les clés tuple de `cache` dont le premier élément vaut `image_hash`
    (clés OCR `(image_hash, ocr_model, source_lang, device)` et traduction `(image_hash,
    translator_key, source_lang, target_lang, context_hash)`, `pipeline/cache_manager.py`).
    Tolère les clés non-tuple (ignorées, jamais levé). Renvoie le nombre de clés supprimées."""
    keys_to_drop = [
        key for key in cache if isinstance(key, tuple) and len(key) > 0 and key[0] == image_hash
    ]
    for key in keys_to_drop:
        del cache[key]
    return len(keys_to_drop)


# --- Macro d'annulation ouverte -----------------------------------------------------------------


def macro_open(count: int, index: int, can_redo: bool) -> bool:
    """Vrai si la pile porte une macro `beginMacro`/`endMacro` non refermée : `count()` a déjà
    grandi (la macro occupe un emplacement) mais `index()` n'a pas avancé (elle n'est pas
    terminée) et on ne peut pas la refaire (`canRedo()` faux — la distingue d'une commande simple
    déjà annulée, qui elle peut être refaite)."""
    return count > index and not can_redo


# --- Gardes de page/pile (duck typées sur `main`, aucun import PySide6) -------------------------


def stack_matches(main: Any, p: str, stack: Any) -> bool:
    """Vrai si `stack` est toujours la pile d'annulation enregistrée pour `p` (une pile devient
    obsolète si la page a été supprimée puis rechargée, ou son fichier changé)."""
    return main.undo_stacks.get(p) is stack


def page_matches(main: Any, p: str) -> bool:
    """Vrai si `p` est la page actuellement affichée, chargée, et hors webtoon — condition requise
    pour agir sur l'état vivant (`main.blk_list`, `image_viewer`) sans corrompre une autre page
    (défauts amont n°1/n°2, ADR-014)."""
    idx = getattr(main, "curr_img_idx", -1)
    image_files = getattr(main, "image_files", None) or []
    if not (0 <= idx < len(image_files)):
        return False
    if image_files[idx] != p:
        return False
    if main.image_data.get(p) is None:
        return False
    if getattr(main, "webtoon_mode", False):
        return False
    return True


# --- Disponibilité du bouton ---------------------------------------------------------------------

REASON_STEPS_DISABLED = "Les six étapes sont grisées."
REASON_PROCESSING = "Un traitement est en cours sur cette page."
REASON_BATCH = "Un lot de traduction est en cours."
REASON_WEBTOON = "Le mode webtoon ne prend pas en charge la réinitialisation."
REASON_NO_WORKSPACE = "L'espace de travail n'est pas affiché."
REASON_NO_PHOTO = "Aucune page affichée."
REASON_NO_PAGE = "Aucune page sélectionnée."
REASON_STACK_MISMATCH = "La pile d'annulation de cette page n'est pas active."
REASON_OK = ""


def availability(main: Any) -> tuple[bool, str]:
    """Disponibilité du bouton (et revalidation avant action) : `(True, "")` si toutes les
    conditions du jalon 3 sous-étape 3a sont réunies, sinon `(False, raison)`. Ne lève jamais côté
    appelant : chaque lecture protégée individuellement (widgets amont potentiellement absents en
    repli `COMIC_SHELL=0` ou détruits)."""
    try:
        buttons = main.hbutton_group.get_button_group().buttons()
        if not buttons or not all(button.isEnabled() for button in buttons):
            return False, REASON_STEPS_DISABLED
    except Exception:
        return False, REASON_STEPS_DISABLED

    if getattr(main.task_runner_ctrl, "is_processing_queue", False):
        return False, REASON_PROCESSING
    if getattr(main, "_batch_active", False):
        return False, REASON_BATCH
    if getattr(main, "webtoon_mode", False):
        return False, REASON_WEBTOON

    try:
        workspace_shown = (
            main._center_stack.currentWidget() is main.main_content_widget
            and main.central_stack.currentWidget() is main.image_viewer
        )
    except Exception:
        workspace_shown = False
    if not workspace_shown:
        return False, REASON_NO_WORKSPACE

    try:
        has_photo = bool(main.image_viewer.hasPhoto())
    except Exception:
        has_photo = False
    if not has_photo:
        return False, REASON_NO_PHOTO

    idx = getattr(main, "curr_img_idx", -1)
    image_files = getattr(main, "image_files", None) or []
    if not (0 <= idx < len(image_files)):
        return False, REASON_NO_PAGE
    p = image_files[idx]
    # `is None`, jamais un test de vérité : `image_data[p]` est un tableau NumPy, dont la
    # troncature en booléen lève `ValueError` dès qu'il a plus d'un élément (précédent :
    # `modules.pagestate.collect.live_path`, même garde).
    if main.image_data.get(p) is None:
        return False, REASON_NO_PAGE

    try:
        active_stack_ok = main.undo_group.activeStack() is main.undo_stacks.get(p)
    except Exception:
        active_stack_ok = False
    if not active_stack_ok:
        return False, REASON_STACK_MISMATCH

    return True, REASON_OK


# --- Messages --------------------------------------------------------------------------------

RESET_FAILED_MESSAGE = "La réinitialisation de la page a échoué : rien n'a été changé."
ABORTED_AFTER_CONFIRMATION_MESSAGE = (
    "La situation a changé pendant la confirmation : réinitialisation annulée."
)

_ORPHAN_MACRO_CONFIRMATION_TEXT = (
    "L'historique d'annulation de cette page est bloqué par une opération interrompue. "
    "La réinitialisation ne pourra pas être annulée."
)


def already_pristine_message(page_number: int, page_name: str) -> str:
    return f"Page {page_number} ({page_name}) déjà dans son état d'origine : rien à réinitialiser"


def success_message(page_number: int, page_name: str, undo_shortcut_native_text: str) -> str:
    """`undo_shortcut_native_text` : texte natif du raccourci Annuler (`QKeySequence.NativeText`,
    ex. « ⌘Z » sur Mac), ou chaîne vide si la séquence est vide/invalide — calculé par
    `modules/reset/ui.py` (seul endroit qui importe `QKeySequence`)."""
    if undo_shortcut_native_text:
        tail = f"Annuler ({undo_shortcut_native_text}) pour revenir en arrière"
    else:
        tail = "Annuler depuis la barre de titre"
    return f"Page {page_number} ({page_name}) réinitialisée — {tail}"


def success_message_non_reversible(page_number: int, page_name: str) -> str:
    """Variante sans promesse d'annulation : la page vient d'être réinitialisée *à l'intérieur*
    d'une macro orpheline déjà ouverte (`macro_open`), donc jamais refermée — `stack.canUndo()`
    reste faux après coup, exactement comme l'annonçait la confirmation. Promettre « Annuler
    (⌘Z) » ici mentirait à l'utilisateur."""
    return f"Page {page_number} ({page_name}) réinitialisée — non annulable (historique bloqué)"


def orphan_macro_confirmation_text() -> str:
    return _ORPHAN_MACRO_CONFIRMATION_TEXT
