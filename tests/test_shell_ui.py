"""GUI (spec 04, jalon 2, sous-étape 2a) : nouvelle disposition (`modules/shell/layout.py`),
reparentage des widgets amont, repli visible, retour arrière, badge Original repositionné par le
shell, bouton Historique nommé.

`--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`). Précédents : `tests/test_pagestate_ui.py`
(délégué composé, `main` = vraie `ComicTranslate`) et `tests/test_original_view.py` (note
d'environnement sur la géométrie du viewport sous le pilote `offscreen`, badge/veil)."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QKeyEvent, QUndoCommand, QUndoStack

import modules.shell.layout as shell_layout_module
import modules.shell.manifest as manifest
import modules.view.original as original_module
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.dayu_widgets.alert import MAlert
from app.ui.main_window import ComicTranslateUI
from modules.history.ui import _BUTTON_TOOLTIP

_PHOTO_WIDTH = 160
_PHOTO_HEIGHT = 120

# Types considérés « interactifs » pour la garde de couverture : aucun ne doit rester dans
# `main._shell_legacy` en 2a (`PARKED` est vide), sauf l'exception documentée (`QScrollBar`
# interne d'un `QAbstractScrollArea` resté dans l'ancien contenu, `tools_scroll`).
_INTERACTIVE_TYPES = (
    QtWidgets.QAbstractButton,
    QtWidgets.QAbstractSlider,
    QtWidgets.QComboBox,
    QtWidgets.QLineEdit,
    QtWidgets.QTextEdit,
    QtWidgets.QPlainTextEdit,
    QtWidgets.QAbstractSpinBox,
    QtWidgets.QAbstractItemView,
    QtWidgets.QGraphicsView,
    QtWidgets.QTabBar,
)


def _synthetic_image(width: int = _PHOTO_WIDTH, height: int = _PHOTO_HEIGHT) -> np.ndarray:
    return np.full((height, width, 3), 120, dtype=np.uint8)


def _neutralize_side_effects(main) -> None:
    """Empêche toute écriture réelle (QSettings, disque) au démontage d'une instance
    `ComicTranslate` construite en test (consigne critic) : `_skip_close_prompt` ne saute que la
    boîte de dialogue de `closeEvent`, pas l'enchaînement qui suit
    (`controller.py:876-882` : `shutdown_autosave`, `save_settings`,
    `save_main_page_settings`) — neutralisé ici, ainsi qu'`add_recent_project` et
    `clear_recovery_checkpoint`, jamais nécessaires dans ces tests."""
    main._skip_close_prompt = True
    main.project_ctrl.shutdown_autosave = lambda *a, **k: None
    main.project_ctrl.save_main_page_settings = lambda *a, **k: None
    main.project_ctrl.clear_recovery_checkpoint = lambda *a, **k: None
    main.project_ctrl.add_recent_project = lambda *a, **k: None
    main.settings_page.save_settings = lambda *a, **k: None


@pytest.fixture
def main(qtbot):
    from controller import ComicTranslate

    instance = ComicTranslate()
    qtbot.addWidget(instance)
    _neutralize_side_effects(instance)
    yield instance
    # `qtbot` ferme (et détruit) le widget automatiquement en fin de test.


# --- Snapshot structurel (type + position + stretch, pas identité) --------------------------
#
# Compare deux arbres de widgets indépendamment construits (précédent/après retour arrière, ou
# deux instances distinctes) sans dépendre de l'identité Python des widgets — seuls comptent le
# type, l'ordre et le facteur d'étirement de chaque emplacement. `QSplitter`/`QScrollArea` gèrent
# leurs enfants hors de tout `QLayout` public : cas particuliers explicites, sans quoi la
# comparaison ignorerait silencieusement tout ce qu'ils contiennent (constat de mise au point :
# une première version de cette fonction sans ces cas particuliers jugeait `QSplitter` toujours
# identique, contenu ou non).


def _snapshot_layout(layout: QtWidgets.QLayout) -> list:
    items = []
    for i in range(layout.count()):
        item = layout.itemAt(i)
        stretch = layout.stretch(i) if hasattr(layout, "stretch") else 0
        widget = item.widget()
        if widget is not None:
            items.append(("widget", stretch, _snapshot(widget)))
            continue
        nested = item.layout()
        if nested is not None:
            items.append(("layout", stretch, _snapshot_layout(nested)))
            continue
        items.append(("spacer", stretch, None))
    return items


def _snapshot(widget: QtWidgets.QWidget):
    if isinstance(widget, QtWidgets.QSplitter):
        return (
            type(widget).__name__,
            "splitter",
            tuple(_snapshot(widget.widget(i)) for i in range(widget.count())),
        )
    if isinstance(widget, QtWidgets.QScrollArea):
        inner = widget.widget()
        return (
            type(widget).__name__,
            "scrollarea",
            _snapshot(inner) if inner is not None else None,
        )
    layout = widget.layout()
    if layout is None:
        return (type(widget).__name__,)
    return (type(widget).__name__, tuple(_snapshot_layout(layout)))


# --- Manifeste : contenu amont sous le nouveau contenu, jamais sous l'ancien -----------------


def test_shell_active_and_manifest_widgets_under_new_content(main):
    assert main._shell_active is True
    assert main._shell_failure is None
    assert main._shell_legacy is not None
    assert main._shell_legacy.parent() is main

    new_content = main.main_content_widget
    for _zone, names in manifest.MOVED_ZONES:
        for name in names:
            widget = getattr(main, name)
            assert new_content.isAncestorOf(widget), f"{name} hors du nouveau contenu"
            assert not main._shell_legacy.isAncestorOf(widget), (
                f"{name} encore dans l'ancien contenu"
            )


def test_comic_translate_ui_alone_builds_shell_without_controllers(qtbot):
    widget = ComicTranslateUI()
    qtbot.addWidget(widget)
    assert widget._shell_active is True
    assert widget._shell_failure is None


# --- Garde de couverture : aucun widget interactif oublié dans l'ancien contenu --------------


def _collect_interactive_offenders(legacy: QtWidgets.QWidget) -> list[str]:
    """Même scan que la garde de couverture réelle (`test_legacy_content_has_no_remaining_interactive_widget`),
    factorisé pour être réutilisé par `test_legacy_content_guard_catches_an_unlisted_injected_button`
    (preuve que la garde mord)."""
    offenders = []
    for widget in legacy.findChildren(QtWidgets.QWidget):
        if not isinstance(widget, _INTERACTIVE_TYPES):
            continue
        if isinstance(widget, QtWidgets.QScrollBar):
            # Exception documentée : barre interne d'un `QAbstractScrollArea` resté dans
            # l'ancien contenu (`tools_scroll`, `workspace.py:369` — ses widgets internes ont
            # été extraits un par un, le conteneur défilant lui-même n'est pas déplacé).
            continue
        parents = []
        parent = widget.parentWidget()
        while parent is not None:
            parents.append(type(parent).__name__)
            parent = parent.parentWidget()
        offenders.append(
            f"{type(widget).__name__} objectName={widget.objectName()!r} parents={parents}"
        )
    return offenders


def test_legacy_content_has_no_remaining_interactive_widget(main):
    offenders = _collect_interactive_offenders(main._shell_legacy)
    assert not offenders, "widgets interactifs oubliés dans l'ancien contenu :\n" + "\n".join(
        offenders
    )


_INJECTED_BUTTON_OBJECT_NAME = "shell_test_injected_unlisted_button"


def test_legacy_content_guard_catches_an_unlisted_injected_button(qtbot, monkeypatch):
    """Preuve que la garde de couverture mord réellement (consigne : ne pas se contenter d'un
    résultat vert par défaut). Injecte un `QPushButton` non listé dans le manifeste directement
    dans le contenu amont, avant l'appel à `build_workspace_shell` : n'appartenant à aucune zone,
    le shell ne le déplace pas — il doit rester dans `main._shell_legacy` et être signalé, nommé,
    par le même scan que la garde réelle."""
    import app.ui.main_window.builders.workspace as workspace_module

    original_create = workspace_module.WorkspaceMixin._create_main_content

    def _patched_create(self):
        content = original_create(self)
        injected = QtWidgets.QPushButton("injecté", content)
        injected.setObjectName(_INJECTED_BUTTON_OBJECT_NAME)
        return content

    monkeypatch.setattr(workspace_module.WorkspaceMixin, "_create_main_content", _patched_create)

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)

    assert widget._shell_active is True
    offenders = _collect_interactive_offenders(widget._shell_legacy)
    assert any(_INJECTED_BUTTON_OBJECT_NAME in offender for offender in offenders), offenders


# --- Repli visible : nom de manifeste inexistant ----------------------------------------------


def test_unknown_manifest_name_falls_back_to_intact_legacy_layout(qtbot, monkeypatch):
    monkeypatch.setattr(
        manifest,
        "ALL_ZONES",
        manifest.ALL_ZONES + (("BOGUS", ("nonexistent_widget_xyz",)),),
    )

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)

    assert widget._shell_active is False
    assert widget._shell_failure is not None
    assert "nonexistent_widget_xyz" in widget._shell_failure

    banners = widget.main_content_widget.findChildren(MAlert)
    assert len(banners) == 1

    # Rien n'a été déplacé (validation ratée avant la moindre modification) : tous les widgets
    # amont sont encore descendants du contenu affiché, dans son organisation d'origine.
    for _zone, names in manifest.MOVED_ZONES:
        for name in names:
            assert widget.main_content_widget.isAncestorOf(getattr(widget, name))


# --- Retour arrière : plusieurs points d'échec, même ordre qu'avant ---------------------------


def _build_baseline_legacy_content(qtbot, monkeypatch) -> QtWidgets.QWidget:
    """Instance dont le shell est neutralisé (identité) : `main_content_widget` est alors
    exactement ce que produit `_create_main_content()`, la référence « avant » pour la
    comparaison de retour arrière."""
    import app.ui.main_window.window as window_module

    monkeypatch.setattr(window_module, "build_workspace_shell", lambda m, legacy: legacy)
    widget = ComicTranslateUI()
    qtbot.addWidget(widget)
    return widget.main_content_widget


@pytest.mark.parametrize("fail_at", [1, 10, 25, 42])
def test_rollback_restores_original_legacy_layout_order(qtbot, monkeypatch, fail_at):
    baseline_content = _build_baseline_legacy_content(qtbot, monkeypatch)
    baseline_snapshot = _snapshot(baseline_content)
    monkeypatch.undo()  # restaure `build_workspace_shell` réel pour la suite de ce test

    real_locate = shell_layout_module._locate
    calls = {"n": 0}

    def _failing_locate(widget):
        calls["n"] += 1
        if calls["n"] == fail_at:
            raise RuntimeError("échec injecté pour le test de retour arrière")
        return real_locate(widget)

    monkeypatch.setattr(shell_layout_module, "_locate", _failing_locate)

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)

    assert widget._shell_active is False, f"échec non déclenché (fail_at={fail_at})"
    assert calls["n"] == fail_at

    # `_build_fallback` place l'ancien contenu (après retour arrière) en 2e position du layout
    # du conteneur de repli, juste après le bandeau `MAlert` (voir `_build_fallback`).
    rolled_back_content = widget.main_content_widget.layout().itemAt(1).widget()
    assert _snapshot(rolled_back_content) == baseline_snapshot


# --- Champs texte redimensionnables ------------------------------------------------------------


def test_text_edit_heights_unlocked(main):
    assert main.s_text_edit.maximumHeight() > 120
    assert main.s_text_edit.minimumHeight() <= 72
    assert main.t_text_edit.maximumHeight() > 120
    assert main.t_text_edit.minimumHeight() <= 72


# --- Bouton Historique nommé --------------------------------------------------------------------


def test_block_history_button_has_visible_text_and_unchanged_tooltip(main):
    assert "Historique" in main.block_history_button.text()
    assert main.block_history_button.toolTip() == main.tr(_BUTTON_TOOLTIP)


# --- Badge Original : hors scène, hors viewport, visibilité et position -----------------------


def test_badge_parent_is_not_viewport_nor_descendant_of_it(main):
    viewport = main.image_viewer.viewport()
    badge = main.original_view_button
    assert badge.parentWidget() is not viewport
    assert not viewport.isAncestorOf(badge)


def test_badge_not_in_scene(main):
    scene_items = main.image_viewer._scene.items()
    assert main.original_view_button not in scene_items


def test_badge_hidden_on_drag_browser_and_visible_on_image_viewer(main):
    # `main` doit être affichée pour que `isVisible()` (composite, dépend de la chaîne de
    # parents) reflète l'état réel plutôt que d'être `False` pour la seule raison que la fenêtre
    # de premier niveau n'est jamais montrée (précédent : `tests/test_original_view.py::_activate`).
    main.show_main_page()
    main.show()
    QtWidgets.QApplication.processEvents()

    main.central_stack.setCurrentWidget(main.drag_browser)
    QtWidgets.QApplication.processEvents()
    assert main.original_view_button.isVisible() is False

    main.central_stack.setCurrentWidget(main.image_viewer)
    QtWidgets.QApplication.processEvents()
    assert main.original_view_button.isVisible() is True


def test_badge_is_topmost_child_of_center_container(main):
    container = main._shell_center_container
    children = [c for c in container.children() if isinstance(c, QtWidgets.QWidget)]
    assert children[-1] is main.original_view_button


def test_badge_does_not_change_save_state_or_image_array(main):
    img = _synthetic_image()
    main.image_viewer.display_image_array(img, fit=False)
    main.image_viewer.add_text_item(
        TextItemProperties(text="BULLE", position=(10, 10), rotation=0, text_color=QColor("black"))
    )
    main.central_stack.setCurrentWidget(main.image_viewer)
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    arr_before = main.image_viewer.get_image_array(paint_all=True)
    state_before = main.image_viewer.save_state()

    main.original_view_button.setChecked(True)

    arr_after = main.image_viewer.get_image_array(paint_all=True)
    state_after = main.image_viewer.save_state()

    assert np.array_equal(arr_before, arr_after)
    assert state_before == state_after


def test_alt_key_still_toggles_veil_through_shell(main, monkeypatch):
    """Reprend le motif de
    `tests/test_original_view.py::test_alt_keypress_arms_and_keyrelease_disarms` : le badge
    reparenté par le shell doit rester le même objet que celui lu par le filtre Alt."""
    main.show_main_page()
    main.show()
    main.activateWindow()
    QtWidgets.QApplication.processEvents()

    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )

    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Alt, Qt.KeyboardModifier.NoModifier, autorep=False
    )
    consumed = main._original_view_filter.eventFilter(main, event)
    assert consumed is False
    assert main.image_viewer._original_view_alt_held
    assert main.original_view_button.isDown()

    event = QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Alt, Qt.KeyboardModifier.NoModifier)
    main._original_view_filter.eventFilter(main, event)
    assert not main.image_viewer._original_view_alt_held
    assert not main.original_view_button.isDown()


# --- EXTERNAL : undo_tool_group dans la barre de titre, undo/redo fonctionnels ----------------


def test_undo_tool_group_lives_in_title_bar_after_construction(main):
    assert main.title_bar.isAncestorOf(main.undo_tool_group)
    # Jamais déplacé par le shell : ni dans le nouveau contenu, ni parqué dans l'ancien.
    assert not main.main_content_widget.isAncestorOf(main.undo_tool_group)
    assert not main._shell_legacy.isAncestorOf(main.undo_tool_group)


def test_undo_redo_buttons_drive_the_active_undo_stack(main):
    stack = QUndoStack(main)
    main.undo_group.addStack(stack)
    main.undo_group.setActiveStack(stack)

    stack.push(QUndoCommand("essai shell"))
    assert stack.canUndo() is True
    assert stack.canRedo() is False

    undo_button, redo_button = main.undo_tool_group.get_button_group().buttons()
    undo_button.click()
    assert stack.canUndo() is False
    assert stack.canRedo() is True

    redo_button.click()
    assert stack.canRedo() is False
    assert stack.canUndo() is True


# --- Badge Original : repositionnement à l'apparition de la barre verticale --------------------


def test_badge_x_changes_when_zoom_reveals_vertical_scrollbar(main):
    main.show_main_page()
    main.show()
    QtWidgets.QApplication.processEvents()

    main._shell_center_container.resize(300, 300)
    main.image_viewer.resize(300, 300)
    QtWidgets.QApplication.processEvents()

    main.central_stack.setCurrentWidget(main.image_viewer)
    img = _synthetic_image(width=2000, height=2000)
    main.image_viewer.display_image_array(img, fit=False)
    QtWidgets.QApplication.processEvents()

    bar = main.image_viewer.verticalScrollBar()
    assert bar.isVisible() is False
    x_before = main.original_view_button.x()

    main.image_viewer.scale(3, 3)
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    assert bar.isVisible() is True
    x_after = main.original_view_button.x()
    assert x_after < x_before


# --- Badge Original : connexions branchées à la finalisation seulement -------------------------


def test_fallback_does_not_wire_badge_to_legacy_central_stack(qtbot, monkeypatch):
    """En repli (validation ratée), `_install_badge_wiring` n'est jamais appelé : le bouton
    « Original », resté dans l'ancienne disposition, ne doit pas être masqué par un changement de
    page de `central_stack` (consigne : c'est précisément ce que ferait `currentChanged` si le
    câblage du shell restait branché par erreur après un repli)."""
    monkeypatch.setattr(
        manifest,
        "ALL_ZONES",
        manifest.ALL_ZONES + (("BOGUS", ("nonexistent_widget_xyz",)),),
    )

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)
    assert widget._shell_active is False

    widget.show_main_page()
    widget.show()
    QtWidgets.QApplication.processEvents()

    assert widget.original_view_button.isVisible() is True
    widget.central_stack.setCurrentWidget(widget.drag_browser)
    QtWidgets.QApplication.processEvents()
    # Sans le câblage du shell (jamais installé en repli), rien ne masque le bouton.
    assert widget.original_view_button.isVisible() is True


# --- Champs Source/Traduction : hauteur réelle mesurée à deux tailles de fenêtre ---------------


@pytest.mark.parametrize("size", [(1225, 797), (1066, 693)])
def test_text_edit_measured_height_at_window_size(main, size):
    width, height = size
    main.show_main_page()
    main.resize(width, height)
    main.show()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    s_height = main.s_text_edit.height()
    t_height = main.t_text_edit.height()
    print(
        f"[mesure shell 2a] fenêtre {width}x{height} : s_text_edit={s_height}px t_text_edit={t_height}px"
    )

    # Pas d'assertion de seuil ici (rapportée telle quelle à Philippe, voir consigne de vérif) :
    # seule la mesure compte. On vérifie seulement que les deux champs restent visibles et non
    # réduits à rien.
    assert s_height > 0
    assert t_height > 0


# Fenêtre par défaut (Air 13"), seuil du jalon : au moins la hauteur d'avant (`setFixedHeight(120)`
# amont, `workspace.py:157`/`:167`) — correctif retour tester du 2026-09-26 (rangée libellé+combo
# fusionnée, espacements resserrés, voir `modules/shell/panel.py`).
_DEFAULT_WINDOW_SIZE = (1225, 797)
_MIN_TEXT_EDIT_HEIGHT_AT_DEFAULT_SIZE = 120


def test_text_edit_height_at_default_window_size_meets_pre_shell_height(main):
    width, height = _DEFAULT_WINDOW_SIZE
    main.show_main_page()
    main.resize(width, height)
    main.show()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    assert main.s_text_edit.height() >= _MIN_TEXT_EDIT_HEIGHT_AT_DEFAULT_SIZE
    assert main.t_text_edit.height() >= _MIN_TEXT_EDIT_HEIGHT_AT_DEFAULT_SIZE


# --- Nom de police non tronqué : seul sur sa rangée, pleine largeur -----------------------------


def test_font_dropdown_alone_on_its_row_has_full_panel_width(main):
    """Correctif retour tester du 2026-09-26 : partagé avec les deux menus de taille fixe
    (60 px chacun), `font_dropdown` n'avait plus assez de largeur dans les 280 px du panneau pour
    afficher un nom de police complet (« Anime Ace 2.0 BB » tronqué à l'affichage)."""
    width, height = _DEFAULT_WINDOW_SIZE
    main.show_main_page()
    main.resize(width, height)
    main.show()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    # `parentWidget()` ne distingue pas les rangées : deux `QHBoxLayout` imbriqués dans le même
    # panneau partagent le même widget parent effectif. On compare plutôt les coordonnées
    # verticales (rangées distinctes) et la largeur obtenue.
    assert main.font_size_dropdown.y() == main.line_spacing_dropdown.y()
    assert main.font_dropdown.y() != main.font_size_dropdown.y()
    # Panneau à 280 px minimum ; la rangée seule doit laisser au combo l'essentiel de cette
    # largeur (marges du panneau soustraites), bien plus que les ~140 px qu'il lui restait
    # lorsqu'il partageait sa rangée avec les deux menus de taille fixe.
    assert main.font_dropdown.width() >= 200


# --- Recherche Ctrl+F : search_panel/page_list frères, bascule d'affichage ---------------------


def test_search_panel_and_page_list_remain_siblings(main):
    assert main.search_panel.parentWidget() is main.page_list.parentWidget()


def test_show_search_sidebar_toggles_visibility_and_back(main):
    main.show_main_page()
    main.show()
    QtWidgets.QApplication.processEvents()

    assert main.page_list.isVisible() is True
    assert main.search_panel.isVisible() is False

    main.show_search_sidebar()
    QtWidgets.QApplication.processEvents()
    assert main.search_panel.isVisible() is True
    assert main.page_list.isVisible() is False

    main._set_search_sidebar_visible(False)
    QtWidgets.QApplication.processEvents()
    assert main.page_list.isVisible() is True
    assert main.search_panel.isVisible() is False


# --- Thème : dayu_theme reste appliqué aux widgets déplacés ------------------------------------


def test_moved_widgets_keep_dayu_theme_applied(qtbot, monkeypatch):
    """`dayu_theme.apply(self)` (`window.py:430`, dans `ComicTranslateUI.apply_theme`) n'est
    invoqué qu'en réaction à `settings_page.theme_changed` (`window.py:88`) — jamais automatiquement
    à la construction (`main.styleSheet()` est vide tant que ni les réglages, ni ce test, ne
    l'appellent). Appelle `apply_theme` explicitement puis compare, sur un widget déplacé
    (`translate_button`), la feuille de style racine effective entre une instance dont le shell est
    neutralisé (identité, jamais reparenté) et une instance normale : le reparentage ne doit rien
    changer à ce que `dayu_theme.apply` a posé sur `main`."""
    import app.ui.main_window.window as window_module

    monkeypatch.setattr(window_module, "build_workspace_shell", lambda m, legacy: legacy)
    baseline = ComicTranslateUI()
    qtbot.addWidget(baseline)
    baseline.apply_theme("Dark")
    baseline_stylesheet = baseline.styleSheet()
    assert baseline_stylesheet != ""  # précondition : `dayu_theme.apply` a bien posé une feuille.
    monkeypatch.undo()

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)
    widget.apply_theme("Dark")

    assert widget._shell_active is True
    assert widget.styleSheet() == baseline_stylesheet
    assert widget.main_content_widget.isAncestorOf(widget.translate_button)
    # Le bouton déplacé n'a reçu aucune feuille de style locale propre : il reste sous l'effet de
    # la feuille racine posée sur `main` par héritage de style Qt (cascade par sélecteur de type).
    assert widget.translate_button.styleSheet() == ""


# --- Widgets jamais dupliqués ni détruits -------------------------------------------------------


_IDENTITY_MARKER_PROPERTY = "shell_test_identity_marker"


def test_manifest_widgets_are_not_duplicated_or_recreated(qtbot, monkeypatch):
    """Marque chaque widget déplacé (`setProperty`) juste après `_create_main_content()`, avant
    l'appel à `build_workspace_shell` : si le shell recréait un widget au lieu de le reparenter
    (`setParent`), l'attribut `main.<name>` pointerait vers un objet neuf, sans la marque —
    détectable, contrairement à une comparaison `id()` entre deux instances distinctes."""
    import app.ui.main_window.builders.workspace as workspace_module

    original_create = workspace_module.WorkspaceMixin._create_main_content
    sample_names = ["translate_button", "s_text_edit", "page_list", "brush_eraser_slider"]

    def _patched_create(self):
        content = original_create(self)
        for name in sample_names:
            getattr(self, name).setProperty(_IDENTITY_MARKER_PROPERTY, True)
        return content

    monkeypatch.setattr(workspace_module.WorkspaceMixin, "_create_main_content", _patched_create)

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)

    assert widget._shell_active is True
    for name in sample_names:
        assert getattr(widget, name).property(_IDENTITY_MARKER_PROPERTY) is True, name


def test_text_controller_widgets_to_block_are_the_shell_moved_instances(main):
    """`app/controllers/text.py:34-42` (`TextController.widgets_to_block`) construit après le
    shell (`controller.py:118`, après `ComicTranslateUI.__init__`) : les widgets qu'il référence
    doivent être ceux, identiques par identité Python, que le shell a déplacés dans le panneau de
    droite — jamais une copie."""
    expected = [
        main.font_dropdown,
        main.font_size_dropdown,
        main.line_spacing_dropdown,
        main.block_font_color_button,
        main.outline_font_color_button,
        main.outline_width_dropdown,
        main.outline_checkbox,
    ]
    assert [id(w) for w in main.text_ctrl.widgets_to_block] == [id(w) for w in expected]
    for widget in expected:
        assert main.main_content_widget.isAncestorOf(widget)
