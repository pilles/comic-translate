"""Commande d'annulation Qt pour la restauration d'une version de bloc
(spec 03, jalon A). Importe PySide6 — n'importer ce module que depuis
`app/ui/main_window/builders/workspace.py` (via `modules/history/ui.py`),
jamais depuis `modules/history/__init__.py` (qui reste pur, voir ADR-012)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

from modules.history import versions
from modules.utils.common_utils import is_close

if TYPE_CHECKING:
    from controller import ComicTranslate
    from modules.utils.textblock import TextBlock

# Tolérances de l'appariement item<->bloc, reprises telles quelles de
# `app/controllers/text.py:384-389` (`_find_text_block_for_item`).
_ITEM_POSITION_TOLERANCE = 5
_ITEM_ROTATION_TOLERANCE = 1


def _find_item_for_block(main: "ComicTranslate", blk: "TextBlock"):
    """Inverse de `TextController._find_text_block_for_item` : part du bloc
    pour retrouver l'item de texte rendu correspondant, s'il existe."""
    for item in main.image_viewer.text_items:
        if (
            is_close(item.pos().x(), blk.xyxy[0], _ITEM_POSITION_TOLERANCE)
            and is_close(item.pos().y(), blk.xyxy[1], _ITEM_POSITION_TOLERANCE)
            and is_close(item.rotation(), blk.angle, _ITEM_ROTATION_TOLERANCE)
        ):
            return item
    return None


class RestoreVersionCommand(QUndoCommand):
    """Restaure `entry` (une entrée de `modules.history.versions`) sur `blk`.

    redo : journalise (une seule fois — origine ``restore``), écrit le champ,
    répercute sur l'item rendu (si champ traduction et item apparié) ou sur
    les widgets source/traduction sous ``blockSignals``.
    undo : réécrit l'ancienne valeur sans journaliser, retire l'entrée
    ``restore`` si elle est bien en tête (jamais le pré-état).
    """

    def __init__(self, main: "ComicTranslate", blk: "TextBlock", entry: "versions.HistoryEntry"):
        super().__init__()
        # M6 : ordre inversé possible si une TextEditCommand est en attente
        # (minuterie 400 ms) — on la fait passer avant nous sur la pile.
        main.text_ctrl._commit_pending_text_command()

        self.main = main
        self.blk = blk
        self.field = entry["field"]
        self.new_value = entry["value"]
        self.old_value = getattr(blk, self.field, "") or ""
        self._applied = False

        self.item = (
            _find_item_for_block(main, blk) if self.field == versions.FIELD_TRANSLATION else None
        )

    def redo(self) -> None:
        blk, field, value = self.blk, self.field, self.new_value
        if not self._applied:
            versions.set_text(blk, field, value, versions.ORIGIN_RESTORE)
            self._applied = True
        else:
            # Deuxième redo (après un undo) : ne pas rejournaliser, l'entrée
            # `restore` a déjà été créée une fois (et n'a pas été retirée).
            setattr(blk, field, value)
        self._apply_to_widgets(value)
        self.main.mark_project_dirty()

    def undo(self) -> None:
        blk, field, value = self.blk, self.field, self.old_value
        if self._applied:
            versions.pop_head_if_origin(blk, field, versions.ORIGIN_RESTORE)
            self._applied = False
        setattr(blk, field, value)
        self._apply_to_widgets(value)
        self.main.mark_project_dirty()

    def _apply_to_widgets(self, value: str) -> None:
        main, blk, field = self.main, self.blk, self.field

        if field == versions.FIELD_TRANSLATION and self.item is not None:
            main.text_ctrl.apply_text_from_command(self.item, value, html=None, blk=blk)
            return

        if main.curr_tblock is not blk:
            return

        # M5 : écrire dans s_text_edit sans bloquer les signaux réécrirait
        # aussi translation (`update_text_block`) ; on bloque les deux
        # champs par prudence, quel que soit celui qu'on modifie.
        main.s_text_edit.blockSignals(True)
        main.t_text_edit.blockSignals(True)
        try:
            if field == versions.FIELD_TEXT:
                main.s_text_edit.setPlainText(value)
            else:
                main.t_text_edit.setPlainText(value)
        finally:
            main.s_text_edit.blockSignals(False)
            main.t_text_edit.blockSignals(False)
