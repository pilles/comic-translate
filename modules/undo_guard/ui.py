"""Verrou d'annulation pendant le nettoyage/la segmentation, et fabriques de rappels gardés
(spec 04, jalon 3, sous-étape 3a-bis, ADR-021). Importe PySide6 — n'importer ce module que depuis
`controller.py` (`install_undo_guard`) et `app/controllers/manual_workflow.py`
(`guard_cleaning`/`guard_segmentation`), jamais depuis `modules/undo_guard/__init__.py` (qui reste
pur, voir ADR-012/ADR-014/ADR-020 pour le précédent de découplage). N'importe jamais
`app.controllers` ni `app.ui.main_window` (précédent : `modules/shell/watcher.py`,
`modules/reset/ui.py`).

Décisions de Philippe (2026-09-28) :
- Bloquer l'annulation (raccourci et boutons de la barre de titre) pendant le calcul d'un
  nettoyage ou d'une segmentation — indicateur `main._undo_locked_by`, 1 ligne `# fork:` dans
  `app/controllers/shortcuts.py`.
- **Jamais `setEnabled` sur les boutons de `undo_tool_group`** (constat du tester, 2026-09-28) :
  `MToolButton.changeEvent` (`app/ui/dayu_widgets/tool_button.py:52-59`) construit un
  `QGraphicsOpacityEffect` sur `EnabledChange` — appelé ici pendant la dépêche d'un événement
  `clicked` (le verrou est posé depuis le gestionnaire de clic « Nettoyer »/« Segmenter »), c'est
  exactement le plantage natif PySide6/Shiboken6 6.11.2 de l'ADR-018, mesuré par le tester à
  10-20 % des lancements de `tests/test_undo_guard_ui.py`. À la place : `_UndoRedoClickBlocker`,
  un filtre d'événements installé **une fois** (`install_undo_guard`) sur les deux boutons, qui
  avale silencieusement `MouseButtonPress`/`MouseButtonRelease`/`MouseButtonDblClick` et
  `KeyPress` (Espace/Entrée/Retour) tant que `main._undo_locked_by` est posé — aucun objet Qt créé
  pendant la dépêche, aucun changement d'état (`isEnabled()` reste vrai). Retour visuel : infobulle
  « Indisponible pendant le calcul » posée par `setToolTip` (vérifié : `MToolButton.changeEvent` ne
  réagit qu'à `EnabledChange`, jamais à `ToolTipChange` — aucun effet graphique créé) et restaurée
  à la levée du verrou.
- Le verrou doit être levé sur **tous** les chemins de fin : succès, erreur, worker annulé
  (`current_worker.cancel()` — `GenericWorker.run` émet `finished` dans un `finally`, y compris
  après une exception ou un flag d'annulation), et le cas non trivial : l'opération est encore
  dans la file de `task_runner_ctrl` quand `cancel_current_task` la vide **sans jamais appeler
  aucun rappel** (défaut amont n°3, ADR-019, corrigé pour les lots mais pas pour une opération
  manuelle mise en file derrière un autosave). Le filet : `install_undo_guard` installe un chien
  de garde léger qui lève le verrou si `task_runner_ctrl.is_processing_queue` est retombé à faux
  pendant que le verrou est encore posé — zéro ligne dans `task_runner.py` (`is_processing_queue`
  reste vrai tant qu'une opération tourne ou attend en file ; il ne retombe à faux hors fin
  normale que par `cancel_current_task`, précisément le cas à couvrir)."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Callable

from PySide6 import QtCore

from app.ui.dayu_widgets.message import MMessage
from modules.undo_guard import macro

if TYPE_CHECKING:
    from controller import ComicTranslate

logger = logging.getLogger(__name__)

_WATCHDOG_INTERVAL_MS = 250
_MESSAGE_DURATION_S = 6

_LOCK_CLEAN = "clean"
_LOCK_SEGMENT = "segment"
_MACRO_INPAINT = "inpaint"
_MACRO_SEGMENT = "draw_segmentation_boxes"


# --- Notification ------------------------------------------------------------------------------


def _notify_warning(main: "ComicTranslate", text: str) -> None:
    try:
        MMessage.warning(text=text, parent=main, duration=_MESSAGE_DURATION_S, closable=True)
    except Exception:
        logger.exception("modules.undo_guard.ui: affichage du message d'abandon en échec.")


def _page_label(main: "ComicTranslate") -> tuple[int, str] | None:
    idx = getattr(main, "curr_img_idx", -1)
    image_files = getattr(main, "image_files", None) or []
    if not (isinstance(idx, int) and 0 <= idx < len(image_files)):
        return None
    return idx + 1, os.path.basename(image_files[idx])


def _abandon_notifier(
    main: "ComicTranslate", message_builder: Callable[[int, str], str] | None
) -> Callable[[], None] | None:
    """Construit le rappel `notify` de `macro.page_bound` : numéro/nom de la page d'origine figés
    **maintenant** (au clic), jamais recalculés à l'abandon (la page affichée a par définition
    changé à ce moment-là — voir `macro.page_bound`)."""
    if message_builder is None:
        return None
    label = _page_label(main)
    if label is None:
        return None
    page_number, page_name = label
    text = message_builder(page_number, page_name)

    def notify() -> None:
        _notify_warning(main, text)

    return notify


# --- Verrou d'annulation ------------------------------------------------------------------------

_TOOLTIP_LOCKED = "Indisponible pendant le calcul"

_BLOCKED_KEYS = (
    QtCore.Qt.Key.Key_Space,
    QtCore.Qt.Key.Key_Return,
    QtCore.Qt.Key.Key_Enter,
)

_BLOCKED_MOUSE_EVENTS = (
    QtCore.QEvent.Type.MouseButtonPress,
    QtCore.QEvent.Type.MouseButtonRelease,
    QtCore.QEvent.Type.MouseButtonDblClick,
)


def _undo_redo_buttons(main: "ComicTranslate") -> list:
    try:
        return list(main.undo_tool_group.get_button_group().buttons())
    except Exception:
        logger.exception("modules.undo_guard.ui: lecture des boutons undo_tool_group en échec.")
        return []


class _UndoRedoClickBlocker(QtCore.QObject):
    """Voir docstring du module (ADR-018). N'appelle jamais `setEnabled` : avale les événements
    d'entrée des boutons Annuler/Rétablir tant que le verrou est posé, sans construire ni détruire
    aucun objet Qt pendant la dépêche."""

    def __init__(self, main: "ComicTranslate") -> None:
        super().__init__(main)
        self._main = main

    def _locked(self) -> bool:
        return getattr(self._main, "_undo_locked_by", None) is not None

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        try:
            event_type = event.type()
            if event_type in _BLOCKED_MOUSE_EVENTS:
                return self._locked()
            if event_type == QtCore.QEvent.Type.KeyPress and self._locked():
                return event.key() in _BLOCKED_KEYS
        except Exception:
            logger.exception("modules.undo_guard.ui: filtre de clic undo/redo en échec.")
        return False


def acquire_lock(main: "ComicTranslate", name: str) -> None:
    main._undo_locked_by = name
    for button in _undo_redo_buttons(main):
        try:
            button.setToolTip(_TOOLTIP_LOCKED)
        except Exception:
            logger.exception("modules.undo_guard.ui: pose de l'infobulle de verrouillage en échec.")


def release_lock(main: "ComicTranslate", name: str) -> None:
    """Ne lève le verrou que s'il porte encore le nom posé par cet appelant (une seule opération
    gardée à la fois en pratique — le nettoyage/la segmentation passent par
    `disable_hbutton_group`, mais la comparaison protège contre un double relâchement croisé)."""
    if getattr(main, "_undo_locked_by", None) != name:
        return
    main._undo_locked_by = None
    for button in _undo_redo_buttons(main):
        try:
            original = getattr(button, "_undo_guard_original_tooltip", "")
            button.setToolTip(original)
        except Exception:
            logger.exception("modules.undo_guard.ui: restauration de l'infobulle en échec.")


def install_undo_guard(main: "ComicTranslate") -> None:
    """`main._undo_locked_by = None`, un filtre d'événements installé une fois sur les boutons
    Annuler/Rétablir (`_UndoRedoClickBlocker`, jamais `setEnabled` — ADR-018), les infobulles
    d'origine mémorisées pour la restauration, puis un chien de garde léger (250 ms, précédent :
    `modules/reset/ui.py::_AvailabilityWatcher`) qui lève le verrou si l'opération qui l'a posé
    n'est plus en cours ni en file (`task_runner_ctrl.is_processing_queue` retombé à faux) —
    filet pour la file vidée par une annulation avant que l'opération n'ait jamais démarré, sans
    aucun rappel (défaut amont n°3, ADR-019)."""
    main._undo_locked_by = None

    blocker = _UndoRedoClickBlocker(main)
    main._undo_guard_click_blocker = blocker
    for button in _undo_redo_buttons(main):
        try:
            button._undo_guard_original_tooltip = button.toolTip()
            button.installEventFilter(blocker)
        except Exception:
            logger.exception("modules.undo_guard.ui: installation du filtre de clic en échec.")

    watchdog = QtCore.QTimer(main)
    watchdog.setInterval(_WATCHDOG_INTERVAL_MS)

    def _tick() -> None:
        try:
            locked_by = getattr(main, "_undo_locked_by", None)
            if locked_by is None:
                return
            if getattr(main.task_runner_ctrl, "is_processing_queue", False):
                return
            logger.warning(
                "modules.undo_guard.ui: verrou %r levé par le filet (file vidée sans rappel).",
                locked_by,
            )
            release_lock(main, locked_by)
        except Exception:
            logger.exception("modules.undo_guard.ui: chien de garde du verrou en échec.")

    watchdog.timeout.connect(_tick)
    watchdog.start()
    main._undo_guard_watchdog = watchdog


# --- Fabriques de rappels gardés ----------------------------------------------------------------


def _guard(
    main: "ComicTranslate",
    *,
    lock_name: str,
    macro_name: str,
    result_callback: Callable[..., Any],
    finished_callback: Callable[..., Any],
    page_bound: bool,
    abandoned_message: Callable[[int, str], str] | None,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    acquire_lock(main, lock_name)

    if page_bound:
        notify = _abandon_notifier(main, abandoned_message)
        guarded_result = macro.page_bound(main, macro_name, result_callback, notify=notify)
    else:
        guarded_result = macro.in_macro(main, macro_name, result_callback)

    def guarded_finished(*args: Any, **kwargs: Any) -> Any:
        try:
            return finished_callback(*args, **kwargs)
        finally:
            release_lock(main, lock_name)

    return guarded_result, guarded_finished


def guard_cleaning(
    main: "ComicTranslate",
    result_callback: Callable[..., Any],
    finished_callback: Callable[..., Any],
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Nettoyage page seule uniquement (le nettoyage multi-pages ferme déjà sa macro par pile,
    synchrone, sans risque d'orpheline — hors périmètre 3a-bis)."""
    return _guard(
        main,
        lock_name=_LOCK_CLEAN,
        macro_name=_MACRO_INPAINT,
        result_callback=result_callback,
        finished_callback=finished_callback,
        page_bound=True,
        abandoned_message=macro.cleaning_abandoned_message,
    )


def guard_segmentation(
    main: "ComicTranslate",
    result_callback: Callable[..., Any],
    finished_callback: Callable[..., Any],
    *,
    page_bound: bool = True,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """`page_bound=True` (défaut) pour les rappels page seule (résultat abandonné si la page
    affichée a changé) ; `page_bound=False` pour la segmentation multi-pages (résultats répartis
    par chemin de fichier, `macro.in_macro` suffit — pas de message d'abandon associé)."""
    return _guard(
        main,
        lock_name=_LOCK_SEGMENT,
        macro_name=_MACRO_SEGMENT,
        result_callback=result_callback,
        finished_callback=finished_callback,
        page_bound=page_bound,
        abandoned_message=macro.segmentation_abandoned_message if page_bound else None,
    )
