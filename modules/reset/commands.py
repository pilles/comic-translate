"""Commande d'annulation Qt pour la réinitialisation d'une page (spec 04, jalon 3, sous-étape 3a).
Importe PySide6 — n'importer ce module que depuis `modules/reset/ui.py`, jamais depuis
`modules/reset/__init__.py` (qui reste pur, voir ADR-012 pour le précédent de découplage)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QTimer
from PySide6.QtGui import QUndoCommand

from modules.reset import state

if TYPE_CHECKING:
    from PySide6.QtGui import QUndoStack

    from controller import ComicTranslate

logger = logging.getLogger(__name__)

_COMMAND_TEXT = "Réinitialiser la page"

# Sentinelle : `image_patches` n'a jamais eu d'entrée pour cette page — distinct d'une entrée `[]`,
# pour ne pas créer une clé qui n'existait pas au retour arrière/à l'annulation.
_ABSENT = object()


def _discard_pending_text_edit(main: "ComicTranslate") -> None:
    """Abandonne une édition de texte en attente (minuterie 400 ms, `app/controllers/text.py:43-47`,
    `:428-452`) sans la committer : elle viserait un bloc/texte que la réinitialisation va
    détruire. Écrit directement les deux attributs plutôt que d'appeler
    `_commit_pending_text_command` (qui pousserait un `TextEditCommand` inutile sur la pile)."""
    text_ctrl = main.text_ctrl
    text_ctrl._text_change_timer.stop()
    text_ctrl._pending_text_command = None


def _refresh_search(main: "ComicTranslate") -> None:
    search_ctrl = getattr(main, "search_ctrl", None)
    if search_ctrl is None:
        return
    QTimer.singleShot(0, main, search_ctrl.on_undo_redo)


def _drop_page_caches(main: "ComicTranslate", p: str) -> None:
    """Au mieux, jamais bloquant (journalisé, sans retour arrière) : invalide les caches OCR/
    traduction de cette page (décision de Philippe : « refaire le travail ») et les erreurs de
    saut de lot mémorisées, puis rafraîchit la recherche."""
    try:
        image = main.image_data.get(p)
        if image is not None:
            cache_manager = main.pipeline.cache_manager
            image_hash = cache_manager._generate_image_hash(image)
            state.drop_cache_entries(cache_manager.ocr_cache, image_hash)
            state.drop_cache_entries(cache_manager.translation_cache, image_hash)
        main.image_ctrl.clear_page_skip_errors_for_paths([p])
    except Exception:
        logger.exception(
            "modules.reset.commands: invalidation des caches après réinitialisation en échec."
        )
    _refresh_search(main)


def _same_elements(a: list, b: list) -> bool:
    return len(a) == len(b) and all(x is y for x, y in zip(a, b))


class ResetPageCommand(QUndoCommand):
    """Réinitialise `p` (page affichée au moment du `redo`) dans son état d'origine : aucun bloc,
    rectangle, texte reconnu/traduit, patch de nettoyage, tracé de pinceau/segmentation, texte
    rendu — annulable. `_reset_list` est réutilisée à chaque `redo` (identité de liste stable pour
    `main.blk_list`, précédent : `modules/history/versions.py` sur `blk.versions`)."""

    def __init__(self, main: "ComicTranslate", p: str, stack: "QUndoStack"):
        super().__init__(_COMMAND_TEXT)
        self.main = main
        self.p = p
        self._stack = stack

        self._applied = False
        self._before: dict | None = None
        self._before_patches: Any = _ABSENT
        self._live_list: list | None = None
        self._reset_list: list = []
        self._first = True

    # --- gardes ------------------------------------------------------------------------------

    def _stack_ok(self) -> bool:
        return state.stack_matches(self.main, self.p, self._stack)

    def _page_ok(self) -> bool:
        return state.page_matches(self.main, self.p)

    # --- redo --------------------------------------------------------------------------------

    def redo(self) -> None:
        if self._applied:
            return

        main, p = self.main, self.p

        if not self._stack_ok():
            logger.warning(
                "modules.reset.commands: pile obsolète pour %s, réinitialisation abandonnée.", p
            )
            self.setObsolete(True)
            return

        if not self._page_ok():
            logger.warning(
                "modules.reset.commands: %s n'est plus la page affichée, réinitialisation abandonnée.",
                p,
            )
            if self._first:
                self.setObsolete(True)
            return

        _discard_pending_text_edit(main)
        main.image_ctrl.save_image_state(p)

        # Copie protégée (critic MIN5) : un rendu multi-pages peut écrire dans
        # `image_states[p]` depuis un worker (`app/controllers/text.py:~893-895`) pendant que
        # cette commande vit sur la pile — `before` doit rester un instantané figé.
        before = dict(main.image_states[p])
        before["viewer_state"] = dict(before.get("viewer_state") or {})
        before_patches = main.image_patches.get(p, _ABSENT)
        live_list = main.blk_list

        blank = state.blank_page_state(before)

        try:
            main.image_states[p] = blank
            if p in main.image_patches:
                main.image_patches[p] = []
            main.image_ctrl.load_image_state(p)
            self._reset_list.clear()
            main.blk_list = self._reset_list
            main.image_viewer.clear_text_edits.emit()
        except Exception:
            logger.exception(
                "modules.reset.commands: réinitialisation de %s en échec, retour arrière.", p
            )
            main.image_states[p] = before
            if before_patches is _ABSENT:
                main.image_patches.pop(p, None)
            else:
                main.image_patches[p] = before_patches
            main.blk_list = live_list
            try:
                main.image_ctrl.load_image_state(p)
            except Exception:
                logger.exception(
                    "modules.reset.commands: retour arrière de %s en échec à son tour.", p
                )
            if self._first:
                self.setObsolete(True)
            return

        self._before = before
        self._before_patches = before_patches
        self._live_list = live_list
        self._applied = True
        self._first = False

        _drop_page_caches(main, p)

    # --- undo --------------------------------------------------------------------------------

    def undo(self) -> None:
        if not self._applied:
            return

        main, p = self.main, self.p

        if not self._stack_ok():
            self.setObsolete(True)
            return

        if not self._page_ok():
            logger.warning(
                "modules.reset.commands: %s n'est plus la page affichée, annulation reportée.", p
            )
            return

        _discard_pending_text_edit(main)
        main.image_ctrl.save_image_state(p)

        current = main.image_states[p]
        before = self._before
        if before is None:
            logger.error("modules.reset.commands: undo() sans état capturé pour %s.", p)
            return
        restored = state.merge_processed(current, before)

        try:
            main.image_states[p] = restored
            if self._before_patches is _ABSENT:
                main.image_patches.pop(p, None)
            else:
                main.image_patches[p] = self._before_patches
            main.image_ctrl.load_image_state(p)

            main.blk_list = self._live_list
            restored_blk_list = restored.get("blk_list", [])
            if not _same_elements(main.blk_list, restored_blk_list):
                main.blk_list[:] = restored_blk_list

            main.image_viewer.clear_text_edits.emit()
        except Exception:
            logger.exception(
                "modules.reset.commands: annulation de %s en échec, page restée réinitialisée.", p
            )
            main.image_states[p] = current
            return

        self._applied = False
        _refresh_search(main)
