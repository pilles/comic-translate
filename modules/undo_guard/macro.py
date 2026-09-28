"""Macros d'annulation sûres — module pur (spec 04, jalon 3, sous-étape 3a-bis, ADR-021).

Duck typing sur `main` (`undo_group`, `undo_stacks`, `curr_img_idx`, `image_files`) et sur la
pile qu'il renvoie (`beginMacro`/`endMacro`) : aucun import de PySide6 ni de `controller.py` ici
(même contrat que `modules.reset.state`, `modules.pagestate.collect` — importable depuis les
tests hors `--gui`).

`in_macro` ouvre/ferme une macro sur la pile active *au moment de l'appel* : pour les rappels qui
ne visent pas une page précise (segmentation multi-pages, dont les résultats sont répartis par
chemin de fichier).

`page_bound` capture la page affichée et sa pile d'annulation **au clic** (à l'appel de
`page_bound` lui-même, pas à celui du rappel qu'il enveloppe) ; au rappel, si la page affichée et
sa pile n'ont pas changé, ouvre la macro, exécute la fonction enveloppée, la referme — sinon
(page changée, page supprimée, pile remplacée) la fonction enveloppée n'est **pas appelée** :
décision D1 de Philippe (2026-09-28), un changement de page pendant un nettoyage ou une
segmentation page seule abandonne le résultat plutôt que de l'appliquer à la mauvaise page."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def _active_stack(main: Any) -> Any:
    try:
        return main.undo_group.activeStack()
    except Exception:
        logger.exception("modules.undo_guard.macro: lecture de la pile active en échec.")
        return None


def in_macro(main: Any, name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    """Enveloppe `fn` : ouvre une macro sur la pile active *à l'appel*, l'exécute, la referme dans
    un `finally` (jamais orpheline même si `fn` lève). Si aucune pile active, appelle `fn` sans
    macro plutôt que de lever."""

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        stack = _active_stack(main)
        if stack is None:
            return fn(*args, **kwargs)
        stack.beginMacro(name)
        try:
            return fn(*args, **kwargs)
        finally:
            stack.endMacro()

    return wrapped


def page_bound(
    main: Any,
    name: str,
    fn: Callable[..., Any],
    *,
    notify: Callable[[], None] | None = None,
) -> Callable[..., Any]:
    """Voir docstring du module. `notify` (optionnel, sans argument) est appelé si le résultat est
    abandonné — construit par l'appelant (`modules/undo_guard/ui.py`) avec le numéro/nom de la
    page d'origine déjà figés au clic, jamais recalculés à l'abandon (la page affichée a par
    définition changé à ce moment-là)."""
    idx = getattr(main, "curr_img_idx", -1)
    image_files = getattr(main, "image_files", None) or []
    origin_path = image_files[idx] if isinstance(idx, int) and 0 <= idx < len(image_files) else None
    origin_stack = _active_stack(main)

    def _abandon(reason: str) -> None:
        logger.info("modules.undo_guard.macro: %r abandonné (%s).", name, reason)
        if notify is not None:
            try:
                notify()
            except Exception:
                logger.exception(
                    "modules.undo_guard.macro: notification d'abandon en échec (%r).", name
                )

    def wrapped(*args: Any, **kwargs: Any) -> Any:
        if origin_path is None or origin_stack is None:
            _abandon("page ou pile d'origine indisponible au clic")
            return None

        try:
            current_stack = main.undo_group.activeStack()
            stack_for_origin = main.undo_stacks.get(origin_path)
            cur_idx = getattr(main, "curr_img_idx", -1)
            cur_files = getattr(main, "image_files", None) or []
            displayed = (
                cur_files[cur_idx]
                if isinstance(cur_idx, int) and 0 <= cur_idx < len(cur_files)
                else None
            )
        except Exception:
            logger.exception("modules.undo_guard.macro: revalidation en échec (%r).", name)
            _abandon("revalidation en échec")
            return None

        page_unchanged = (
            current_stack is origin_stack
            and stack_for_origin is origin_stack
            and displayed == origin_path
        )
        if not page_unchanged:
            _abandon("la page affichée ou sa pile a changé depuis le clic")
            return None

        origin_stack.beginMacro(name)
        try:
            return fn(*args, **kwargs)
        finally:
            origin_stack.endMacro()

    return wrapped


# --- Messages d'abandon (décision D1, texte du critic M3) ----------------------------------------


def cleaning_abandoned_message(page_number: int, page_name: str) -> str:
    return (
        f"Nettoyage de la page {page_number} ({page_name}) abandonné : la page affichée a changé "
        "pendant le calcul. Relancez Nettoyer sur cette page."
    )


def segmentation_abandoned_message(page_number: int, page_name: str) -> str:
    return (
        f"Segmentation de la page {page_number} ({page_name}) abandonnée : la page affichée a "
        "changé pendant le calcul. Les cadres effacés au lancement peuvent être rétablis par "
        "Annuler ; relancez Segmenter."
    )
