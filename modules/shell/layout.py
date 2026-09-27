"""Coquille de la nouvelle disposition — assemblage (spec 04, jalon 2, sous-étapes 2a et 2b).

Point d'attache unique : `build_workspace_shell(main, legacy_content)`, appelé une fois depuis
`app/ui/main_window/window.py::ComicTranslateUI._init_ui`, juste après la construction du contenu
amont (`_create_main_content()`). Reparente les widgets amont existants (jamais de réécriture des
contrôleurs, jamais de widget dupliqué) dans une disposition neuve à trois colonnes ; dégrade en
silence vers l'interface d'origine si la moindre étape échoue (`_build_fallback`).

Ce module est le seul de `modules/shell` importé par `window.py`. Il n'importe jamais
`app.controllers` ni `app.ui.main_window` (import circulaire : `window.py` importe ce module) —
même sous `TYPE_CHECKING`, d'où l'annotation `Any` pour `main` plutôt qu'un import différé de
`ComicTranslateUI`. `app.ui.dayu_widgets` est en revanche autorisé (précédent :
`modules/history/ui.py`, `modules/view/original.py`).

Conception validée (architect + critic) : validation sans effet de bord, construction de la
nouvelle hiérarchie à vide, déplacement journalisé (capture de la position d'origine au moment de
chaque déplacement, pas à la validation — l'ordre des widgets restants dans un layout partagé
change à chaque retrait), retour arrière en ordre inverse en cas d'échec, repli visible si tout le
reste échoue."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore, QtWidgets

from app.ui.dayu_widgets.alert import MAlert
from modules.shell import manifest
from modules.shell.panel import PanelSkeleton, build_panel_skeleton

logger = logging.getLogger(__name__)

_LEFT_COLUMN_WIDTH = 168
_CENTER_COLUMN_WIDTH_HINT = 600
_RIGHT_COLUMN_WIDTH = 280

_MIN_TEXT_EDIT_HEIGHT = 60
# `QtWidgets.QWIDGETSIZE_MAX` n'existe pas dans les bindings PySide6 installés (vérifié) — repli
# sur la valeur documentée par Qt (2**24 - 1).
_QWIDGETSIZE_MAX_FALLBACK = 16777215

_BADGE_MARGIN_TOP = 14
_BADGE_MARGIN_RIGHT = 16

_FALLBACK_MESSAGE = (
    "Nouvelle disposition indisponible : interface d'origine affichée (détail dans le journal)."
)


class ShellError(Exception):
    """Échec d'une étape de construction du shell — toujours attrapée par
    `build_workspace_shell`, jamais laissée remonter à `window.py`."""


@dataclass
class _MoveRecord:
    name: str
    widget: QtWidgets.QWidget
    old_parent: QtWidgets.QWidget
    old_layout: QtWidgets.QLayout
    old_index: int


@dataclass
class _Hierarchy:
    shell_content: QtWidgets.QWidget
    shell_layout: QtWidgets.QVBoxLayout
    header_layout: QtWidgets.QHBoxLayout
    splitter: QtWidgets.QSplitter
    left_layout: QtWidgets.QVBoxLayout
    center_container: QtWidgets.QWidget
    center_layout: QtWidgets.QVBoxLayout
    panel: PanelSkeleton


# --- Localisation générique (parent, layout immédiat, index) --------------------------------


def _search_layout(layout: QtWidgets.QLayout, widget: QtWidgets.QWidget):
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if item.widget() is widget:
            return layout, i
        nested = item.layout()
        if nested is not None:
            found = _search_layout(nested, widget)
            if found is not None:
                return found
    return None


def _locate(widget: QtWidgets.QWidget):
    """Renvoie `(parent, layout, index)` du widget dans la hiérarchie amont, ou `None` si le
    widget n'est rattaché à aucun `QBoxLayout` atteignable depuis `parentWidget().layout()`
    (seul type de layout utilisé par `workspace.py`, voir CLAUDE.md)."""
    parent = widget.parentWidget()
    if parent is None:
        return None
    top_layout = parent.layout()
    if top_layout is None:
        return None
    found = _search_layout(top_layout, widget)
    if found is None:
        return None
    layout, index = found
    return parent, layout, index


# --- Étape 1 : validation, sans aucun effet de bord ------------------------------------------


def _validate_manifest(main: Any, legacy_content: QtWidgets.QWidget) -> None:
    for zone_name, names in manifest.ALL_ZONES:
        # EXTERNAL (`undo_tool_group`) n'est jamais ajouté au contenu amont : il est construit
        # sans parent dans `_create_main_content` et reparenté directement dans la barre de
        # titre par `window.py`, juste après l'appel à `build_workspace_shell` — l'exiger
        # descendant du contenu amont ferait toujours échouer la validation.
        check_ancestry = zone_name != "EXTERNAL"
        for name in names:
            widget = getattr(main, name, None)
            if not isinstance(widget, QtWidgets.QWidget):
                raise ShellError(f"{name} ({zone_name}) absent ou n'est pas un QWidget")
            try:
                widget.objectName()
            except RuntimeError as exc:
                raise ShellError(f"{name} ({zone_name}) détruit côté Qt") from exc
            if check_ancestry and not legacy_content.isAncestorOf(widget):
                raise ShellError(f"{name} ({zone_name}) n'appartient pas au contenu amont")


# --- Étape 2 : construction de la nouvelle hiérarchie, à vide --------------------------------


def _build_new_hierarchy(main: Any) -> _Hierarchy:
    shell_content = QtWidgets.QWidget()
    shell_layout = QtWidgets.QVBoxLayout(shell_content)

    header_layout = QtWidgets.QHBoxLayout()
    shell_layout.addLayout(header_layout)

    splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
    shell_layout.addWidget(splitter, 1)

    left_container = QtWidgets.QWidget()
    left_layout = QtWidgets.QVBoxLayout(left_container)
    left_layout.setContentsMargins(0, 0, 0, 0)

    center_container = QtWidgets.QWidget()
    center_layout = QtWidgets.QVBoxLayout(center_container)
    center_layout.setContentsMargins(0, 0, 0, 0)

    panel = build_panel_skeleton(main)

    splitter.addWidget(left_container)
    splitter.addWidget(center_container)
    splitter.addWidget(panel.container)
    splitter.setStretchFactor(0, 0)
    splitter.setStretchFactor(1, 1)
    splitter.setStretchFactor(2, 0)
    splitter.setSizes([_LEFT_COLUMN_WIDTH, _CENTER_COLUMN_WIDTH_HINT, _RIGHT_COLUMN_WIDTH])

    return _Hierarchy(
        shell_content=shell_content,
        shell_layout=shell_layout,
        header_layout=header_layout,
        splitter=splitter,
        left_layout=left_layout,
        center_container=center_container,
        center_layout=center_layout,
        panel=panel,
    )


# --- Étape 3 : déplacement journalisé ---------------------------------------------------------


def _move_to_layout(
    main: Any,
    journal: list[_MoveRecord],
    name: str,
    layout: QtWidgets.QLayout,
    stretch: int = 0,
    insert_index: int | None = None,
) -> None:
    widget = getattr(main, name)
    located = _locate(widget)
    if located is None:
        raise ShellError(f"impossible de localiser {name} dans le contenu amont")
    parent, old_layout, old_index = located
    journal.append(_MoveRecord(name, widget, parent, old_layout, old_index))

    widget.setParent(layout.parentWidget())
    if insert_index is None:
        layout.addWidget(widget, stretch)
    else:
        layout.insertWidget(insert_index, widget, stretch)


def _move_as_overlay_child(
    main: Any, journal: list[_MoveRecord], name: str, container: QtWidgets.QWidget
) -> None:
    widget = getattr(main, name)
    located = _locate(widget)
    if located is None:
        raise ShellError(f"impossible de localiser {name} dans le contenu amont")
    parent, old_layout, old_index = located
    journal.append(_MoveRecord(name, widget, parent, old_layout, old_index))
    widget.setParent(container)


def _move_all(main: Any, hierarchy: _Hierarchy, journal: list[_MoveRecord]) -> None:
    header = hierarchy.header_layout
    _move_to_layout(main, journal, "hbutton_group", header)
    _move_to_layout(main, journal, "loading", header)
    header.addStretch()
    _move_to_layout(main, journal, "translate_button", header)
    _move_to_layout(main, journal, "cancel_button", header)
    _move_to_layout(main, journal, "batch_report_button", header)

    # Inséré après le bandeau, avant le `QSplitter` (déjà en place, à l'index 1 dans
    # `shell_layout` depuis l'étape 2).
    _move_to_layout(main, journal, "progress_bar", hierarchy.shell_layout, insert_index=1)

    _move_to_layout(main, journal, "page_list", hierarchy.left_layout)
    _move_to_layout(main, journal, "search_panel", hierarchy.left_layout)

    _move_to_layout(main, journal, "central_stack", hierarchy.center_layout)
    _move_as_overlay_child(main, journal, "original_view_button", hierarchy.center_container)

    panel = hierarchy.panel
    _move_to_layout(main, journal, "s_combo", panel.source_combo_row, stretch=1)
    _move_to_layout(main, journal, "s_text_edit", panel.source_layout, stretch=1)
    _move_to_layout(main, journal, "t_combo", panel.target_combo_row, stretch=1)
    _move_to_layout(main, journal, "t_text_edit", panel.target_layout, stretch=1)
    _move_to_layout(main, journal, "block_history_button", panel.actions_layout)
    _move_to_layout(main, journal, "set_all_button", panel.actions_layout)
    panel.actions_layout.addStretch()

    # Nom de police seul sur sa rangée (correctif troncature, retour tester) : partagée avec les
    # deux menus de taille fixe, elle n'avait plus assez de largeur dans les 280 px du panneau.
    _move_to_layout(main, journal, "font_dropdown", panel.font_name_row_layout, stretch=1)
    _move_to_layout(main, journal, "font_size_dropdown", panel.font_size_row_layout)
    _move_to_layout(main, journal, "line_spacing_dropdown", panel.font_size_row_layout)
    panel.font_size_row_layout.addStretch()

    _move_to_layout(main, journal, "block_font_color_button", panel.style_row_layout)
    _move_to_layout(main, journal, "alignment_tool_group", panel.style_row_layout)
    _move_to_layout(main, journal, "bold_button", panel.style_row_layout)
    _move_to_layout(main, journal, "italic_button", panel.style_row_layout)
    _move_to_layout(main, journal, "underline_button", panel.style_row_layout)
    panel.style_row_layout.addStretch()

    _move_to_layout(main, journal, "outline_checkbox", panel.outline_row_layout)
    _move_to_layout(main, journal, "outline_font_color_button", panel.outline_row_layout)
    _move_to_layout(main, journal, "outline_width_dropdown", panel.outline_row_layout)
    panel.outline_row_layout.addStretch()

    _move_to_layout(main, journal, "pan_button", panel.tools_row1_pan_layout)
    _move_to_layout(main, journal, "box_button", panel.tools_row1_box_layout)
    _move_to_layout(main, journal, "delete_button", panel.tools_row1_box_layout)
    _move_to_layout(main, journal, "clear_rectangles_button", panel.tools_row1_box_layout)
    _move_to_layout(main, journal, "draw_blklist_blks", panel.tools_row1_box_layout)

    _move_to_layout(main, journal, "change_all_blocks_size_dec", panel.tools_row2_size_layout)
    _move_to_layout(main, journal, "change_all_blocks_size_diff", panel.tools_row2_size_layout)
    _move_to_layout(main, journal, "change_all_blocks_size_inc", panel.tools_row2_size_layout)
    _move_to_layout(main, journal, "brush_button", panel.tools_row2_brush_layout)
    _move_to_layout(main, journal, "eraser_button", panel.tools_row2_brush_layout)
    _move_to_layout(main, journal, "clear_brush_strokes_button", panel.tools_row2_brush_layout)

    _move_to_layout(main, journal, "brush_eraser_slider", panel.tools_row3_layout)


def _rollback(journal: list[_MoveRecord]) -> None:
    """Défait les déplacements déjà journalisés, en ordre inverse : chaque widget retourne dans
    le layout où il vivait juste avant sa propre capture, ce qui restitue l'ordre (et les
    éléments `addStretch()` jamais touchés) exactement tel qu'avant l'étape 3."""
    for record in reversed(journal):
        record.widget.setParent(record.old_parent)
        record.old_layout.insertWidget(record.old_index, record.widget)


# --- Étape 4 : finalisation --------------------------------------------------------------------


def _park_legacy_content(main: Any, legacy_content: QtWidgets.QWidget) -> None:
    legacy_content.setParent(main)
    legacy_content.hide()
    main._shell_legacy = legacy_content


def _hide_parked_widgets(main: Any) -> None:
    """Masque explicitement les widgets `manifest.PARKED` (spec 04, jalon 2, sous-étape 2b :
    plus de mode Manuel/Automatique, plus de webtoon). Jamais déplacés par `_move_all` — ils
    restent enfants du bandeau amont, dans `main._shell_legacy` (succès) ou dans le contenu amont
    réaffiché (repli, `_build_fallback`). `legacy_content.show()` en repli rendrait visible tout
    ce qui n'est pas explicitement masqué : appelée après ce `show()` autant qu'après le
    masquage du succès, pour que ces trois widgets restent invisibles dans les deux cas. Accès
    défensif (`getattr`) : ne suppose pas que chaque nom existe toujours."""
    for name in manifest.PARKED:
        widget = getattr(main, name, None)
        if isinstance(widget, QtWidgets.QWidget):
            widget.setVisible(False)


def _unlock_text_edit_heights(main: Any) -> None:
    maximum = getattr(QtWidgets, "QWIDGETSIZE_MAX", _QWIDGETSIZE_MAX_FALLBACK)
    for text_edit in (main.s_text_edit, main.t_text_edit):
        text_edit.setMinimumHeight(_MIN_TEXT_EDIT_HEIGHT)
        text_edit.setMaximumHeight(maximum)
        text_edit.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred, QtWidgets.QSizePolicy.Policy.Expanding
        )


def _update_badge_visibility(main: Any) -> None:
    """Ne lève jamais (précédent : `modules/pagestate/ui.py::_paint_track`) — appelée depuis un
    filtre d'événements et un signal Qt, une exception non rattrapée y serait silencieusement
    avalée par Qt de toute façon, autant journaliser proprement."""
    try:
        badge = main.original_view_button
        stack = main.central_stack
        badge.setVisible(stack.currentWidget() is main.image_viewer)
    except Exception:
        logger.exception(
            "modules.shell.layout: mise à jour de la visibilité du badge Original en échec."
        )


def _reposition_original_badge(main: Any) -> None:
    """Ne lève jamais (voir `_update_badge_visibility`)."""
    try:
        badge = main.original_view_button
        container = main._shell_center_container
        badge.adjustSize()
        extra = 0
        bar = main.image_viewer.verticalScrollBar()
        if bar is not None and bar.isVisible():
            extra = bar.width()
        x = container.width() - _BADGE_MARGIN_RIGHT - extra - badge.width()
        badge.move(max(0, x), _BADGE_MARGIN_TOP)
    except Exception:
        logger.exception("modules.shell.layout: repositionnement du badge Original en échec.")


def _on_central_stack_changed(main: Any, _index: int) -> None:
    _update_badge_visibility(main)
    _reposition_original_badge(main)


class _CenterContainerEventFilter(QtCore.QObject):
    """Repositionne le badge sur redimensionnement du conteneur central. `return False` toujours
    (précédent : `modules/view/original.py::_OriginalViewEventFilter`) — n'avale jamais
    d'événement."""

    def __init__(self, main: Any, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._main = main

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if event.type() in (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.Show):
            _reposition_original_badge(self._main)
        return False


class _ScrollbarEventFilter(QtCore.QObject):
    """Repositionne le badge à l'apparition/disparition de la barre de défilement verticale de
    `image_viewer` (`ScrollBarAsNeeded`, `image_viewer.py:48`)."""

    def __init__(self, main: Any, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._main = main

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if event.type() in (QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Hide):
            _reposition_original_badge(self._main)
        return False


def _install_badge_wiring(main: Any, hierarchy: _Hierarchy) -> None:
    """Connexions et filtres du badge Original — ici seulement (jamais à l'étape 3, qui ne fait
    que reparenter). `raise_()` après l'insertion de `central_stack` (déjà fait à l'étape 3) et de
    tout autre enfant du conteneur central."""
    badge = main.original_view_button
    container = hierarchy.center_container
    main._shell_center_container = container

    center_filter = _CenterContainerEventFilter(main, parent=container)
    container.installEventFilter(center_filter)
    main._shell_center_filter = center_filter

    viewer = main.image_viewer
    v_scrollbar = viewer.verticalScrollBar()
    scrollbar_filter = _ScrollbarEventFilter(main, parent=v_scrollbar)
    v_scrollbar.installEventFilter(scrollbar_filter)
    main._shell_scrollbar_filter = scrollbar_filter
    v_scrollbar.rangeChanged.connect(lambda *_args: _reposition_original_badge(main))

    main.central_stack.currentChanged.connect(lambda index: _on_central_stack_changed(main, index))

    _update_badge_visibility(main)
    _reposition_original_badge(main)
    badge.raise_()


def _finalize(
    main: Any, hierarchy: _Hierarchy, legacy_content: QtWidgets.QWidget
) -> QtWidgets.QWidget:
    _park_legacy_content(main, legacy_content)
    _hide_parked_widgets(main)
    _unlock_text_edit_heights(main)
    _install_badge_wiring(main, hierarchy)
    main._shell_active = True
    main._shell_failure = None
    return hierarchy.shell_content


# --- Étape 5 : repli visible ---------------------------------------------------------------


def _build_fallback(main: Any, legacy_content: QtWidgets.QWidget, reason: str) -> QtWidgets.QWidget:
    container = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    banner = MAlert(main.tr(_FALLBACK_MESSAGE))
    banner.error()
    banner.set_closable(False)
    layout.addWidget(banner)

    legacy_content.setParent(container)
    legacy_content.show()
    layout.addWidget(legacy_content, 1)
    _hide_parked_widgets(main)

    main._shell_active = False
    main._shell_failure = reason
    main._shell_legacy = None
    return container


# --- Point d'entrée -----------------------------------------------------------------------


def build_workspace_shell(main: Any, legacy_content: QtWidgets.QWidget) -> QtWidgets.QWidget:
    """Enveloppe `_create_main_content()` : reparente ses widgets dans la disposition à trois
    colonnes de la spec 04 (jalon 2, sous-étape 2a), ou renvoie un repli visible si une étape
    échoue. N'exige rien des contrôleurs (`app.controllers`) : `tests/test_app.py` construit
    `ComicTranslateUI` seul et doit continuer à fonctionner.

    `COMIC_SHELL=0` dans l'environnement renvoie la disposition d'origine telle quelle, sans
    bandeau : sert à départager un défaut du shell d'un défaut préexistant de l'amont."""
    if os.environ.get("COMIC_SHELL") == "0":
        main._shell_active = False
        main._shell_failure = "désactivé par COMIC_SHELL=0"
        # Le webtoon n'est plus pris en charge (spec 04 §7) : même en mode diagnostic, son
        # interrupteur reste masqué ; les radios, devenues inoffensives, restent visibles.
        toggle = getattr(main, "webtoon_toggle", None)
        if toggle is not None:
            toggle.setVisible(False)
        return legacy_content

    try:
        _validate_manifest(main, legacy_content)
    except ShellError as exc:
        logger.exception("modules.shell.layout: validation du manifeste en échec.")
        return _build_fallback(main, legacy_content, str(exc))

    try:
        hierarchy = _build_new_hierarchy(main)
    except Exception as exc:
        # Rien n'a encore été touché côté amont : les objets neufs créés jusqu'ici n'ont reçu
        # aucun parent Qt durable et ne sont référencés que par les variables locales de cette
        # pile d'appel — leur destruction (CPython, comptage de références) est automatique dès
        # que l'exception déroule la pile, sans destruction explicite nécessaire.
        logger.exception("modules.shell.layout: construction de la nouvelle disposition en échec.")
        return _build_fallback(main, legacy_content, str(exc))

    journal: list[_MoveRecord] = []
    try:
        _move_all(main, hierarchy, journal)
    except Exception as exc:
        logger.exception("modules.shell.layout: déplacement des widgets en échec, retour arrière.")
        try:
            _rollback(journal)
        except Exception:
            logger.exception("modules.shell.layout: retour arrière en échec à son tour.")
        return _build_fallback(main, legacy_content, str(exc))

    try:
        return _finalize(main, hierarchy, legacy_content)
    except Exception as exc:
        logger.exception("modules.shell.layout: finalisation en échec, retour arrière.")
        try:
            _rollback(journal)
        except Exception:
            logger.exception(
                "modules.shell.layout: retour arrière (après échec de finalisation) en échec à son tour."
            )
        return _build_fallback(main, legacy_content, str(exc))
