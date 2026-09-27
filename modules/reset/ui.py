"""Bouton « Réinitialiser » la page (spec 04, jalon 3, sous-étape 3a). Importe PySide6 —
n'importer ce module que depuis `controller.py` (`attach_page_reset`), jamais depuis
`modules/reset/__init__.py` (qui reste pur, voir ADR-012 pour le précédent de découplage).
N'importe jamais `app.controllers` ni `app.ui.main_window` (précédent : `modules/shell/watcher.py`,
qui n'importe pas non plus les contrôleurs — le paquet doit rester attachable même si le shell ou
les contrôleurs sont en échec)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QKeySequence

from app.ui.dayu_widgets.message import MMessage
from app.ui.dayu_widgets.push_button import MPushButton
from modules.reset import commands, state

if TYPE_CHECKING:
    from controller import ComicTranslate

logger = logging.getLogger(__name__)

_BUTTON_TEXT = "Réinitialiser"
_BUTTON_TOOLTIP = (
    "Remet la page affichée dans son état d'origine (autres pages, langues et police intactes). "
    "Annulable."
)
_BUTTON_SPACING = 12

_ORPHAN_MACRO_TITLE = "Historique bloqué"
_ORPHAN_MACRO_PROCEED = "Réinitialiser quand même"
_ORPHAN_MACRO_CANCEL = "Annuler"

_MESSAGE_DURATION_S = 6
_UNDO_SHORTCUT_ID = "undo"

_WATCHDOG_INTERVAL_MS = 250

# Types qui volent le focus au clavier (M7 + critic MIN2) : un `QComboBox` n'est listé que s'il est
# éditable (tailles de police, interligne, épaisseur de contour) — un combo non éditable n'avale
# pas la frappe.
_FOCUS_STEALING_TYPES = (
    QtWidgets.QLineEdit,
    QtWidgets.QTextEdit,
    QtWidgets.QPlainTextEdit,
    QtWidgets.QAbstractSpinBox,
    QtWidgets.QKeySequenceEdit,
)


# --- Focus ---------------------------------------------------------------------------------


def _steals_focus(widget: QtWidgets.QWidget | None) -> bool:
    """Vrai si `widget` (ou un de ses ancêtres, jusqu'à la fenêtre) est l'un des types qui volent
    le focus, ou un `QComboBox` éditable — couvre à la fois « c'est ce widget » et « c'est un
    descendant de l'un d'eux » en une seule remontée de parenté."""
    node = widget
    while node is not None:
        if isinstance(node, _FOCUS_STEALING_TYPES):
            return True
        if isinstance(node, QtWidgets.QComboBox) and node.isEditable():
            return True
        node = node.parentWidget()
    return False


def _apply_focus_rule(main: "ComicTranslate") -> None:
    try:
        window = main.window()
        focus_widget = window.focusWidget() if window is not None else None
        if focus_widget is not None and _steals_focus(focus_widget):
            main.image_viewer.setFocus()
    except Exception:
        logger.exception("modules.reset.ui: règle de focus après réinitialisation en échec.")


# --- Message de raccourci --------------------------------------------------------------------


def _undo_shortcut_native_text(main: "ComicTranslate") -> str:
    try:
        shortcuts = main.shortcut_ctrl.get_current_shortcuts()
        sequence = shortcuts.get(_UNDO_SHORTCUT_ID, "")
        return QKeySequence(sequence).toString(QKeySequence.SequenceFormat.NativeText)
    except Exception:
        logger.exception("modules.reset.ui: lecture du raccourci Annuler en échec.")
        return ""


def _notify(main: "ComicTranslate", text: str, *, dayu_type: str = MMessage.InfoType) -> None:
    show_func = {
        MMessage.InfoType: MMessage.info,
        MMessage.SuccessType: MMessage.success,
        MMessage.WarningType: MMessage.warning,
        MMessage.ErrorType: MMessage.error,
    }.get(dayu_type, MMessage.info)
    try:
        show_func(text=text, parent=main, duration=_MESSAGE_DURATION_S, closable=True)
    except Exception:
        logger.exception("modules.reset.ui: affichage du message en échec.")


# --- Confirmation (macro orpheline) -----------------------------------------------------------


def _confirm_orphan_macro(main: "ComicTranslate") -> bool:
    box = QtWidgets.QMessageBox(main)
    box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
    box.setWindowTitle(main.tr(_ORPHAN_MACRO_TITLE))
    box.setText(main.tr(state.orphan_macro_confirmation_text()))
    proceed_btn = box.addButton(
        main.tr(_ORPHAN_MACRO_PROCEED), QtWidgets.QMessageBox.ButtonRole.DestructiveRole
    )
    cancel_btn = box.addButton(
        main.tr(_ORPHAN_MACRO_CANCEL), QtWidgets.QMessageBox.ButtonRole.RejectRole
    )
    box.setDefaultButton(cancel_btn)
    box.exec()
    return box.clickedButton() is proceed_btn


# --- Disponibilité (bouton) -------------------------------------------------------------------


class _AvailabilityWatcher(QtCore.QObject):
    """Recalcule `state.availability(main)` et met à jour `button.setEnabled(...)`. Déclencheurs :
    `EnabledChange` sur les 6 boutons d'étape (filtre d'événements, `QEvent` n'a pas de signal
    Qt natif pour ce changement), `undo_group.activeStackChanged`, `central_stack.currentChanged`,
    et un chien de garde à 250 ms (parent le bouton, sort si le bouton est caché — précédent :
    `modules/pagestate/ui.py::_install_watchdog`)."""

    def __init__(self, main: "ComicTranslate", button: QtWidgets.QPushButton) -> None:
        super().__init__(button)
        self._main = main
        self._button = button

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if event.type() == QtCore.QEvent.Type.EnabledChange:
            self.refresh()
        return False

    def refresh(self) -> None:
        try:
            available, _reason = state.availability(self._main)
            self._button.setEnabled(available)
        except Exception:
            logger.exception("modules.reset.ui: recalcul de disponibilité en échec.")

    def install(self) -> None:
        main = self._main
        try:
            for button in main.hbutton_group.get_button_group().buttons():
                button.installEventFilter(self)
        except Exception:
            logger.exception("modules.reset.ui: installation du filtre EnabledChange en échec.")
        try:
            main.undo_group.activeStackChanged.connect(lambda *_args: self.refresh())
        except Exception:
            logger.exception("modules.reset.ui: connexion à activeStackChanged en échec.")
        try:
            main.central_stack.currentChanged.connect(lambda *_args: self.refresh())
        except Exception:
            logger.exception("modules.reset.ui: connexion à central_stack.currentChanged en échec.")

        watchdog = QtCore.QTimer(self._button)
        watchdog.setInterval(_WATCHDOG_INTERVAL_MS)

        def _tick() -> None:
            try:
                if not self._button.isVisible():
                    return
            except Exception:
                return
            self.refresh()

        watchdog.timeout.connect(_tick)
        watchdog.start()
        main._page_reset_watchdog = watchdog

        self.refresh()


# --- Clic ------------------------------------------------------------------------------------


def _live_reset_inputs(main: "ComicTranslate", p: str) -> tuple[Any, dict, Any]:
    viewer_state = main.image_viewer.save_state()
    brush_strokes = main.image_viewer.save_brush_strokes()
    patches = main.image_patches.get(p)
    return viewer_state, brush_strokes, patches


def request_reset(main: "ComicTranslate") -> None:
    """Gère le clic (et toute réévaluation programmatique) : revalide la disponibilité, refuse si
    la page est déjà vierge, confirme si l'historique de la page est bloqué par une macro
    orpheline (forcément non annulable), pousse `ResetPageCommand`, puis affiche un message de
    résultat non modal."""
    try:
        available, reason = state.availability(main)
        if not available:
            _notify(main, reason, dayu_type=MMessage.WarningType)
            return

        idx = main.curr_img_idx
        p = main.image_files[idx]
        stack = main.undo_stacks.get(p)
        if stack is None or main.undo_group.activeStack() is not stack:
            _notify(main, state.REASON_STACK_MISMATCH, dayu_type=MMessage.WarningType)
            return

        page_number = idx + 1
        page_name = os.path.basename(p)

        viewer_state, brush_strokes, patches = _live_reset_inputs(main, p)
        if state.is_pristine(main.blk_list, viewer_state, brush_strokes, patches):
            _notify(main, state.already_pristine_message(page_number, page_name))
            return

        orphan_macro = state.macro_open(stack.count(), stack.index(), stack.canRedo())
        if orphan_macro:
            if not _confirm_orphan_macro(main):
                return

            # La boucle d'événements de la modale a tourné : tout revalider (critic MIN6).
            available, reason = state.availability(main)
            still_same_page = 0 <= main.curr_img_idx < len(main.image_files) and (
                main.image_files[main.curr_img_idx] == p
            )
            still_active_stack = main.undo_group.activeStack() is stack
            still_orphan = state.macro_open(stack.count(), stack.index(), stack.canRedo())
            if not (available and still_same_page and still_active_stack and still_orphan):
                _notify(
                    main, state.ABORTED_AFTER_CONFIRMATION_MESSAGE, dayu_type=MMessage.WarningType
                )
                return

            stack.push(commands.ResetPageCommand(main, p, stack))
            main.mark_project_dirty()
        else:
            main.image_viewer.deselect_all()
            main.text_ctrl._commit_pending_text_command()
            stack.push(commands.ResetPageCommand(main, p, stack))

        _apply_focus_rule(main)

        # Ne jamais accéder à la commande après `push` (critic MIN7 : obsolète -> détruite) —
        # le succès se juge en relisant l'état vivant, jamais `stack.index()` seul : une macro
        # orpheline encore ouverte ne fait pas avancer l'index bien que `redo()` ait bien agi.
        succeeded = _reset_succeeded_on_live_page(main, p)
        if succeeded and orphan_macro:
            # La confirmation l'a déjà annoncé : ne pas promettre une annulation impossible
            # (la macro reste ouverte, `stack.canUndo()` reste faux).
            _notify(
                main,
                state.success_message_non_reversible(page_number, page_name),
                dayu_type=MMessage.SuccessType,
            )
        elif succeeded:
            shortcut_text = _undo_shortcut_native_text(main)
            _notify(
                main,
                state.success_message(page_number, page_name, shortcut_text),
                dayu_type=MMessage.SuccessType,
            )
        else:
            _notify(main, state.RESET_FAILED_MESSAGE, dayu_type=MMessage.WarningType)
    except Exception:
        logger.exception("modules.reset.ui: clic sur Réinitialiser en échec.")


def _reset_succeeded_on_live_page(main: "ComicTranslate", p: str) -> bool:
    if not (0 <= main.curr_img_idx < len(main.image_files)):
        return False
    if main.image_files[main.curr_img_idx] != p:
        return False
    viewer_state, brush_strokes, patches = _live_reset_inputs(main, p)
    return state.is_pristine(main.blk_list, viewer_state, brush_strokes, patches)


# --- Attache -----------------------------------------------------------------------------------


def attach_page_reset(main: "ComicTranslate") -> QtWidgets.QPushButton | None:
    """Attache le bouton « Réinitialiser » dans le bandeau du shell, juste après `main.loading`.
    Entièrement sous `try/except` : l'application démarre sans bouton si l'attache échoue, ou si
    le shell n'est pas actif (`main._shell_header_layout` absent, repli `COMIC_SHELL=0`)."""
    try:
        header_layout = getattr(main, "_shell_header_layout", None)
        if header_layout is None:
            logger.warning(
                "modules.reset.ui: bandeau du shell absent (COMIC_SHELL=0 ou repli), "
                "bouton Réinitialiser non attaché."
            )
            return None

        button = MPushButton(main.tr(_BUTTON_TEXT))
        button.small()
        button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        button.setToolTip(main.tr(_BUTTON_TOOLTIP))
        button.setEnabled(False)
        button.clicked.connect(lambda: request_reset(main))

        insert_index = header_layout.indexOf(main.loading)
        insert_index = insert_index + 1 if insert_index >= 0 else header_layout.count()
        header_layout.insertSpacing(insert_index, _BUTTON_SPACING)
        header_layout.insertWidget(insert_index + 1, button)

        main.page_reset_button = button

        watcher = _AvailabilityWatcher(main, button)
        main._page_reset_watcher = watcher
        watcher.install()

        return button
    except Exception:
        logger.exception("modules.reset.ui: attache du bouton Réinitialiser en échec.")
        return None
