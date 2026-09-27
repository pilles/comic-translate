"""Observateur du contexte du panneau droit — Page/Bulle (spec 04, jalon 2, sous-étape 2c).

Bascule `panel.stack` (`modules/shell/panel.py`) entre la page Page et la page Bulle selon
`modules/shell/context.panel_context`, en fonction de `main.curr_tblock`/`main.curr_tblock_item`
et de la visibilité de `main.search_panel`. Aucune écriture : ne touche jamais `curr_tblock`, la
scène, `image_states`, ni le contenu des champs (`setPlainText`/`clear`/`setText`) — seuls les deux
libellés dynamiques de la page Bulle (construits par ce paquet, pas amont) et l'index de la pile
sont modifiés.

Déclencheurs regroupés par `QTimer.singleShot(0)` (un seul en attente à la fois, voir
`_ContextWatcher.schedule`) : `image_viewer.rectangle_selected`, `image_viewer.clear_text_edits`,
`page_list.currentItemChanged`, relâchement de souris sur `image_viewer.viewport()`, apparition/
disparition de `search_panel`. Un chien de garde à 200 ms rattrape le reste (undo/redo, fin de
rendu, lot, affectations directes de `curr_tblock`/`curr_tblock_item` sans signal, ex.
`app/ui/commands/box.py`) — sort immédiatement si le panneau n'est pas visible.

Importe PySide6 — n'importer ce module que depuis `modules/shell/layout.py`. Tout est sous
try/except journalisé une fois (modèle `modules/pagestate/ui.py`) : le shell ne doit jamais exiger
les contrôleurs (`tests/test_app.py` construit `ComicTranslateUI` seul), d'où l'accès défensif
(`getattr`) à `curr_tblock`/`curr_tblock_item`, qui n'existent que lorsqu'un contrôleur (`RectItem
Controller`, `TextController`, ...) les a affectés au moins une fois."""

from __future__ import annotations

import logging
from typing import Any

from PySide6 import QtCore

from modules.shell import context
from modules.shell.panel import PanelSkeleton

logger = logging.getLogger(__name__)

_WATCHDOG_INTERVAL_MS = 200

_SOURCE_CAPTION_SUFFIX = "reconnu"
_TARGET_CAPTION_SUFFIX = "traduction"

_warned: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key in _warned:
        return
    _warned.add(key)
    logger.warning(message)
    logger.debug("modules.shell.watcher: détail de %s", key, exc_info=True)


def _bubble_captions(main: Any) -> tuple[str, str]:
    s_combo = getattr(main, "s_combo", None)
    t_combo = getattr(main, "t_combo", None)
    s_text = s_combo.currentText() if s_combo is not None else ""
    t_text = t_combo.currentText() if t_combo is not None else ""
    source = context.language_caption(s_text, main.tr(_SOURCE_CAPTION_SUFFIX))
    target = context.language_caption(t_text, main.tr(_TARGET_CAPTION_SUFFIX))
    return source, target


def _target_context(main: Any) -> str:
    curr_tblock = getattr(main, "curr_tblock", None)
    curr_tblock_item = getattr(main, "curr_tblock_item", None)
    search_panel = getattr(main, "search_panel", None)
    search_visible = bool(search_panel.isVisible()) if search_panel is not None else False
    return context.panel_context(curr_tblock, curr_tblock_item, search_visible)


def _move_focus_out_of_outgoing(outgoing: Any, main: Any) -> None:
    """Règle de focus (condition du critic, spec 04 jalon 2, sous-étape 2c) : lue sur
    `stack.window().focusWidget()` — le `focus_child` de la fenêtre, **jamais**
    `QApplication.focusWidget()` (`None` quand l'application est inactive, ce qui masquerait
    précisément le cas à traiter). Vaut aussi fenêtre inactive : `QWidget.focusWidget()` renvoie
    le widget qui regagnerait le focus à la réactivation, indépendamment de l'état actif."""
    window = outgoing.window()
    focus_widget = window.focusWidget() if window is not None else None
    if focus_widget is None:
        return
    if not (outgoing is focus_widget or outgoing.isAncestorOf(focus_widget)):
        return

    viewer = getattr(main, "image_viewer", None)
    if viewer is not None and viewer.isVisible():
        viewer.setFocus()
    else:
        focus_widget.clearFocus()


def apply_panel_context(main: Any, panel: PanelSkeleton) -> None:
    """Recalcule le contexte (Page/Bulle) et bascule `panel.stack` si besoin. Ne lève jamais.
    Relit les deux libellés dynamiques de la page Bulle à chaque appel : les combos de langue sont
    changés sous `blockSignals` (`app/controllers/image.py:~1077-1086`), aucun signal fiable ne
    permet de ne les relire qu'au changement."""
    try:
        source_caption, target_caption = _bubble_captions(main)
        panel.bubble_source_caption.setText(source_caption)
        panel.bubble_target_caption.setText(target_caption)
    except Exception:
        _warn_once(
            "captions", "modules.shell.watcher: mise à jour des libellés de la page Bulle en échec."
        )

    try:
        target = _target_context(main)
        target_index = panel.bubble_index if target == context.CONTEXT_BUBBLE else panel.page_index
        stack = panel.stack
        if stack.currentIndex() == target_index:
            return
        outgoing = stack.currentWidget()
        if outgoing is not None:
            _move_focus_out_of_outgoing(outgoing, main)
        stack.setCurrentIndex(target_index)
    except Exception:
        _warn_once(
            "switch", "modules.shell.watcher: bascule du panneau contextuel (Page/Bulle) en échec."
        )


class _ContextWatcher(QtCore.QObject):
    """Regroupe les déclencheurs, étranglés à un seul réévaluation en attente (`schedule`).
    `evaluate_now` (synchrone, sans passer par `QTimer.singleShot`) est utilisé par le chien de
    garde et par les tests, qui n'ont pas à faire tourner la boucle d'événements pour observer une
    bascule."""

    def __init__(
        self, main: Any, panel: PanelSkeleton, parent: QtCore.QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._main = main
        self._panel = panel
        self._pending = False

    def evaluate_now(self) -> None:
        apply_panel_context(self._main, self._panel)

    def schedule(self, *_args: Any) -> None:
        if self._pending:
            return
        self._pending = True
        QtCore.QTimer.singleShot(0, self._run_scheduled)

    def _run_scheduled(self) -> None:
        self._pending = False
        self.evaluate_now()

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        try:
            etype = event.type()
            viewer = getattr(self._main, "image_viewer", None)
            viewport = viewer.viewport() if viewer is not None else None
            if viewport is not None and watched is viewport:
                if etype == QtCore.QEvent.Type.MouseButtonRelease:
                    self.schedule()
            elif watched is getattr(self._main, "search_panel", None):
                if etype in (QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Hide):
                    self.schedule()
        except Exception:
            _warn_once("event_filter", "modules.shell.watcher: filtre d'événements en échec.")
        return False


def install_context_watcher(main: Any, panel: PanelSkeleton) -> _ContextWatcher:
    """Installe l'observateur (signaux, filtres d'événements, chien de garde) et synchronise
    immédiatement l'état initial. Précédent (attache défensive, dégradation silencieuse) :
    `modules/pagestate/ui.py::attach_page_state`."""
    watcher = _ContextWatcher(main, panel, parent=panel.stack)
    main._shell_context_watcher = watcher

    try:
        main.image_viewer.rectangle_selected.connect(watcher.schedule)
    except Exception:
        _warn_once(
            "signal:rectangle_selected",
            "modules.shell.watcher: connexion à image_viewer.rectangle_selected en échec.",
        )
    try:
        main.image_viewer.clear_text_edits.connect(watcher.schedule)
    except Exception:
        _warn_once(
            "signal:clear_text_edits",
            "modules.shell.watcher: connexion à image_viewer.clear_text_edits en échec.",
        )
    try:
        main.page_list.currentItemChanged.connect(watcher.schedule)
    except Exception:
        _warn_once(
            "signal:currentItemChanged",
            "modules.shell.watcher: connexion à page_list.currentItemChanged en échec.",
        )
    try:
        main.image_viewer.viewport().installEventFilter(watcher)
    except Exception:
        _warn_once(
            "filter:viewport",
            "modules.shell.watcher: installation du filtre sur image_viewer.viewport() en échec.",
        )
    try:
        main.search_panel.installEventFilter(watcher)
    except Exception:
        _warn_once(
            "filter:search_panel",
            "modules.shell.watcher: installation du filtre sur search_panel en échec.",
        )

    watchdog = QtCore.QTimer(panel.stack)
    watchdog.setInterval(_WATCHDOG_INTERVAL_MS)

    def _tick() -> None:
        try:
            if not panel.stack.isVisible():
                return
        except Exception:
            _warn_once("watchdog", "modules.shell.watcher: chien de garde en échec.")
            return
        watcher.evaluate_now()

    watchdog.timeout.connect(_tick)
    watchdog.start()
    main._shell_context_watchdog = watchdog

    watcher.evaluate_now()
    return watcher
