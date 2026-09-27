"""GUI (spec 04, jalon 2, sous-étape 2a) : nouvelle disposition (`modules/shell/layout.py`),
reparentage des widgets amont, repli visible, retour arrière, badge Original repositionné par le
shell, bouton Historique nommé.

`--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`). Précédents : `tests/test_pagestate_ui.py`
(délégué composé, `main` = vraie `ComicTranslate`) et `tests/test_original_view.py` (note
d'environnement sur la géométrie du viewport sous le pilote `offscreen`, badge/veil)."""

from __future__ import annotations

import inspect
import re
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QUndoCommand, QUndoStack

import app.controllers.projects as projects_module
import controller as controller_module
import modules.shell.layout as shell_layout_module
import modules.shell.manifest as manifest
import modules.shell.panel as panel_module
import modules.shell.watcher as watcher_module
import modules.view.original as original_module
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.dayu_widgets.alert import MAlert
from app.ui.main_window import ComicTranslateUI
from app.ui.messages import Messages
from modules.history.ui import _BUTTON_TOOLTIP
from modules.utils.textblock import TextBlock


def _count_expected_moves() -> int:
    """Nombre d'appels `_move_to_layout`/`_move_as_overlay_child` dans le corps de `_move_all`,
    obtenu par introspection statique du code source plutôt qu'une constante recopiée à la main
    (revérif tester, sous-étape 2b, point 7) : chaque appel journalise exactement un `_locate`, ce
    total est donc aussi le dernier index valide pour `fail_at` dans
    `test_rollback_restores_original_legacy_layout_order` — se met à jour automatiquement si
    `_move_all` gagne ou perd des déplacements."""
    source = inspect.getsource(shell_layout_module._move_all)
    return len(re.findall(r"_move_to_layout\(|_move_as_overlay_child\(", source))


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


# --- Sous-étape 2c : panneau contextuel Page/Bulle ---------------------------------------------
#
# `_fake_text_block()` : bloc minimal utilisable comme `curr_tblock`, sans dépendre d'un vrai
# `TextBlock` ni d'une vraie sélection de rectangle. `SimpleNamespace` (pas `object()`) : accepte
# les écritures `text`/`translation` que `TextController.update_text_block`/
# `update_text_block_from_edit` (connectés à `s_text_edit`/`t_text_edit.textChanged`) pourraient
# faire pendant ces tests.


def _fake_text_block() -> SimpleNamespace:
    return SimpleNamespace(text="", translation="")


def _select_fake_bubble(main) -> None:
    """Bascule le panneau droit en contexte Bulle sans passer par une vraie sélection de
    rectangle (`RectItemController.handle_rectangle_selection`) : affecte directement
    `curr_tblock`, puis demande une réévaluation synchrone (`evaluate_now`, pas besoin de faire
    tourner la boucle d'événements — précédent : `_reposition_original_badge` appelé directement
    par les tests du badge Original)."""
    main.curr_tblock = _fake_text_block()
    main._shell_context_watcher.evaluate_now()


def _deselect_to_page(main) -> None:
    main.curr_tblock = None
    main._shell_context_watcher.evaluate_now()


def _show_main_with_viewer(main) -> None:
    main.show_main_page()
    main.central_stack.setCurrentWidget(main.image_viewer)
    main.show()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()


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


# --- PARKED : radios Manuel/Automatique et interrupteur webtoon (spec 04, jalon 2, 2b) ---------
#
# Plus de mode Manuel/Automatique, plus de webtoon (§3, §7) : les trois widgets restent vivants
# dans `main._shell_legacy` (lus par `app/controllers/projects.py`, `controller.py`,
# `modules/view/original.py`, `app/controllers/webtoons.py`) mais ne doivent plus jamais
# apparaître, y compris quand le repli affiche l'ancien contenu (`legacy_content.show()`).


def test_parked_widgets_hidden_alive_and_still_under_legacy(main):
    for name in manifest.PARKED:
        widget = getattr(main, name)
        assert isinstance(widget, QtWidgets.QWidget)
        assert widget.isVisibleTo(main) is False
        assert main._shell_legacy.isAncestorOf(widget), f"{name} hors de l'ancien contenu"
        # Vivant côté Qt : `objectName()` ne lève pas `RuntimeError` (widget détruit).
        widget.objectName()


def test_parked_widgets_stay_hidden_in_fallback(qtbot, monkeypatch):
    """Repli simulé (nom de manifeste inexistant, même recette que
    `test_unknown_manifest_name_falls_back_to_intact_legacy_layout`) : `legacy_content.show()`
    rendrait les trois widgets visibles s'ils n'étaient pas masqués explicitement — c'est
    exactement ce que ce test prouve."""
    monkeypatch.setattr(
        manifest,
        "ALL_ZONES",
        manifest.ALL_ZONES + (("BOGUS", ("nonexistent_widget_xyz",)),),
    )

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)

    assert widget._shell_active is False
    for name in manifest.PARKED:
        parked_widget = getattr(widget, name)
        assert parked_widget.isVisibleTo(widget) is False


# --- Fonctions de mode neutres : plus de mode Manuel/Automatique (spec 04, jalon 2, 2b) ---------
#
# Quel que soit l'ancien réglage QSettings `main_page/mode`, l'état au repos est désormais
# identique quelle que soit la fonction appelée : 6 étapes actives, Translate All actif, Cancel
# grisé (`controller.py:472-480`).


def _assert_resting_state(main) -> None:
    for button in main.hbutton_group.get_button_group().buttons():
        assert button.isEnabled() is True
    assert main.translate_button.isEnabled() is True
    assert main.cancel_button.isEnabled() is False


def test_batch_mode_selected_reaches_resting_state(main):
    main.batch_mode_selected()
    _assert_resting_state(main)


def test_manual_mode_selected_reaches_resting_state(main):
    main.manual_mode_selected()
    _assert_resting_state(main)


# --- Lot factice : étapes grisées pendant, réactivées à la fin (spec 04, jalon 2, 2b) -----------

_FAKE_BATCH_PAGE = "fake_page_01.png"


def _neutralize_batch_side_effects(main, monkeypatch) -> None:
    """Neutralise tout ce que `_run_batch_for_paths`/`on_batch_process_finished` déclencheraient
    réellement (réglages, modèles, autosave, boîtes de dialogue) : seul l'état des boutons de
    `controller.py` nous intéresse ici. `run_threaded` est remplacé par un no-op (pas même un
    appel synchrone du callback) pour figer l'état « pendant le lot » de façon déterministe —
    `on_batch_process_finished` est ensuite appelé directement par le test qui en a besoin,
    plutôt que d'attendre un signal de fin de thread réel."""
    monkeypatch.setattr(controller_module, "validate_settings", lambda *a, **k: True)
    monkeypatch.setattr(main.pipeline, "batch_process", lambda *a, **k: None)
    monkeypatch.setattr(main.pipeline, "webtoon_batch_process", lambda *a, **k: None)
    monkeypatch.setattr(main.pipeline, "release_model_caches", lambda *a, **k: None)
    monkeypatch.setattr(main, "run_threaded", lambda *a, **k: None)
    monkeypatch.setattr(main.project_ctrl, "autosave_project", lambda *a, **k: None)
    monkeypatch.setattr(Messages, "show_translation_complete", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(Messages, "show_batch_skipped_summary", staticmethod(lambda *a, **k: None))
    main.image_files = [_FAKE_BATCH_PAGE]
    main.image_states = {_FAKE_BATCH_PAGE: {"source_lang": "English", "target_lang": "English"}}


def test_batch_run_disables_steps_enables_cancel_disables_translate(main, monkeypatch):
    _neutralize_batch_side_effects(main, monkeypatch)

    main._run_batch_for_paths([_FAKE_BATCH_PAGE])

    for button in main.hbutton_group.get_button_group().buttons():
        assert button.isEnabled() is False
    assert main.translate_button.isEnabled() is False
    assert main.cancel_button.isEnabled() is True


def test_batch_finished_reenables_steps_translate_disables_cancel(main, monkeypatch):
    _neutralize_batch_side_effects(main, monkeypatch)
    main._run_batch_for_paths([_FAKE_BATCH_PAGE])

    main.on_batch_process_finished()

    for button in main.hbutton_group.get_button_group().buttons():
        assert button.isEnabled() is True
    assert main.translate_button.isEnabled() is True
    assert main.cancel_button.isEnabled() is False


# --- Webtoon non pris en charge : `update_ui_from_project` remet `webtoon_mode` à False ---------
#
# Aucun `.ctpr` webtoon réel disponible (tranché le 2026-09-25, spec 04 §7) : la fixture `main`
# fraîche n'a aucun projet chargé (`image_files` vide), si bien que `update_ui_from_project`
# s'arrête après la remise à `False` de `webtoon_mode` (branche de retour anticipé, aucune image à
# charger) — suffisant pour prouver que la ligne `# fork:` s'exécute avant tout le reste, sans
# construire un projet complet.


def test_update_ui_from_project_resets_webtoon_mode(main):
    main.webtoon_mode = True
    assert not main.image_files  # précondition : fixture fraîche, aucun projet chargé

    main.project_ctrl.update_ui_from_project()

    assert main.webtoon_mode is False


# --- Garde de couverture : aucun widget interactif oublié dans l'ancien contenu --------------


def _collect_interactive_offenders(main) -> list[str]:
    """Même scan que la garde de couverture réelle (`test_legacy_content_has_no_remaining_interactive_widget`),
    factorisé pour être réutilisé par `test_legacy_content_guard_catches_an_unlisted_injected_button`
    (preuve que la garde mord). Depuis la sous-étape 2b, `manifest.PARKED`
    (`manual_radio`/`automatic_radio`/`webtoon_toggle`) reste dans l'ancien contenu par
    construction (jamais déplacé) : seule exception acceptée en plus de `QScrollBar`, identifiée
    par identité (pas par type, trop large) pour que la garde continue de mordre sur tout
    widget interactif non listé."""
    legacy = main._shell_legacy
    parked_ids = {
        id(widget)
        for widget in (getattr(main, name, None) for name in manifest.PARKED)
        if isinstance(widget, QtWidgets.QWidget)
    }
    offenders = []
    for widget in legacy.findChildren(QtWidgets.QWidget):
        if not isinstance(widget, _INTERACTIVE_TYPES):
            continue
        if isinstance(widget, QtWidgets.QScrollBar):
            # Exception documentée : barre interne d'un `QAbstractScrollArea` resté dans
            # l'ancien contenu (`tools_scroll`, `workspace.py:369` — ses widgets internes ont
            # été extraits un par un, le conteneur défilant lui-même n'est pas déplacé).
            continue
        if id(widget) in parked_ids:
            # Exception documentée : `manifest.PARKED` (spec 04, jalon 2, 2b) — masqué
            # explicitement (`setVisible(False)`), jamais déplacé, jamais détruit.
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
    offenders = _collect_interactive_offenders(main)
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
    offenders = _collect_interactive_offenders(widget)
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


@pytest.mark.parametrize("fail_at", [1, 10, 25, _count_expected_moves()])
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
    main.central_stack.setCurrentWidget(main.image_viewer)
    main.resize(width, height)
    main.show()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    # Mesure en contexte Bulle (sous-étape 2c) : hors de ce contexte, les champs sont sur la page
    # inactive de la pile et leur géométrie ne reflète pas forcément la taille de fenêtre réelle.
    _select_fake_bubble(main)
    QtWidgets.QApplication.processEvents()

    s_height = main.s_text_edit.height()
    t_height = main.t_text_edit.height()
    print(
        f"[mesure shell 2c] fenêtre {width}x{height} : s_text_edit={s_height}px t_text_edit={t_height}px"
    )

    # Pas d'assertion de seuil ici (rapportée telle quelle à Philippe, voir consigne de vérif) :
    # seule la mesure compte. On vérifie seulement que les deux champs restent visibles et non
    # réduits à rien.
    assert s_height > 0
    assert t_height > 0


# Fenêtre par défaut (Air 13"), seuil du jalon : les champs regagnent la hauteur perdue en 2a
# (rangées de langue déplacées vers la page Page, sous-étape 2c) — au moins 150 px, contre 120 px
# avant (2a) et 84/83 px à « Texte plus grand » (2a, sous les 120 px d'avant).
_DEFAULT_WINDOW_SIZE = (1225, 797)
_MIN_TEXT_EDIT_HEIGHT_AT_DEFAULT_SIZE = 150


def test_text_edit_height_at_default_window_size_meets_pre_shell_height(main):
    width, height = _DEFAULT_WINDOW_SIZE
    main.show_main_page()
    main.central_stack.setCurrentWidget(main.image_viewer)
    main.resize(width, height)
    main.show()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    _select_fake_bubble(main)
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


# --- Chemins qui réactivent les étapes ou Cancel (revérif tester, sous-étape 2b, point 1) -------
#
# `default_error_handler` réactive `hbutton_group` mais ne touche ni `translate_button` ni
# `cancel_button` : lors d'un lot, c'est `on_batch_process_finished` (câblé comme
# `finished_callback` de `run_threaded`, toujours invoqué après `error_callback` — voir
# `app/controllers/task_runner.py::_process_next_operation`, les deux signaux sont émis dans le
# `try`/`finally` de `GenericWorker.run`) qui referme l'état sur les trois boutons. Ce test le
# prouve en appelant les deux callbacks dans cet ordre, sans thread réel, exactement comme le
# ferait `run_threaded` en cas d'échec.


def test_default_error_handler_then_batch_finished_reaches_resting_state(main, monkeypatch):
    _neutralize_batch_side_effects(main, monkeypatch)
    # `default_error_handler`, branche générique, ouvrirait sinon une vraie boîte de dialogue
    # modale (`Messages.show_error_with_copy` → `QMessageBox.exec()`) : bloquerait indéfiniment
    # sous le pilote `offscreen` (aucun utilisateur pour cliquer OK).
    monkeypatch.setattr(Messages, "show_error_with_copy", staticmethod(lambda *a, **k: None))
    main._run_batch_for_paths([_FAKE_BATCH_PAGE])

    # État "pendant le lot", juste avant l'échec : Cancel actif, étapes/Translate grisés.
    assert main.cancel_button.isEnabled() is True

    main.default_error_handler((RuntimeError, RuntimeError("échec simulé"), ""))
    # `default_error_handler` seul ne referme pas tout : Cancel reste actif, Translate grisé.
    # C'est `on_batch_process_finished`, appelé juste après par le vrai worker, qui referme.
    assert main.cancel_button.isEnabled() is True
    assert main.translate_button.isEnabled() is False

    main.on_batch_process_finished()
    _assert_resting_state(main)


def test_cancel_current_task_disables_cancel_only_while_batch_active(main, monkeypatch):
    """`task_runner.cancel_current_task` (`app/controllers/task_runner.py:144-156`) grise Cancel
    seulement si `_batch_active` est vrai ; hors lot, il ne doit toucher à rien (pas de bouton à
    regriser puisqu'aucun n'est actif)."""
    main.cancel_current_task()
    assert main.cancel_button.isEnabled() is False  # déjà grisé au repos, inchangé

    _neutralize_batch_side_effects(main, monkeypatch)
    main._run_batch_for_paths([_FAKE_BATCH_PAGE])
    assert main.cancel_button.isEnabled() is True

    main.cancel_current_task()
    assert main.cancel_button.isEnabled() is False
    assert main._batch_cancel_requested is True


def test_retry_skipped_batch_images_reaches_same_states_as_a_normal_batch(main, monkeypatch):
    """`retry_skipped_batch_images` retombe sur `_run_batch_for_paths` : mêmes états de boutons
    qu'un lot normal, pas de chemin de réactivation différent."""
    _neutralize_batch_side_effects(main, monkeypatch)
    main.batch_report_ctrl._latest_batch_report = {
        "skipped_entries": [{"image_path": _FAKE_BATCH_PAGE}],
    }

    main.retry_skipped_batch_images()

    for button in main.hbutton_group.get_button_group().buttons():
        assert button.isEnabled() is False
    assert main.translate_button.isEnabled() is False
    assert main.cancel_button.isEnabled() is True

    main.on_batch_process_finished()
    _assert_resting_state(main)


# --- Pendant une opération manuelle, Cancel reste grisé (revérif tester, point 2) ---------------


def test_manual_workflow_never_touches_cancel_button(main):
    """`app/controllers/manual_workflow.py` grise `hbutton_group` à plusieurs endroits mais ne
    référence jamais `cancel_button` (grep, revérifié ici par introspection du module plutôt que
    par une liste figée de noms de fonctions, pour ne pas se démoder si le fichier est réorganisé) :
    Cancel reste sous le seul contrôle du chemin lot (`_run_batch_for_paths`/
    `on_batch_process_finished`/`cancel_current_task`)."""
    import app.controllers.manual_workflow as manual_workflow_module

    source = inspect.getsource(manual_workflow_module)
    assert "cancel_button" not in source


def test_block_detect_disables_hbutton_group_without_enabling_cancel(main, monkeypatch):
    """Exercice concret d'une opération manuelle (`block_detect`, point d'entrée le plus simple de
    `manual_workflow.py`) : `disable_hbutton_group()` grise les étapes, Cancel reste tel quel
    (grisé au repos)."""
    monkeypatch.setattr(main.pipeline, "detect_blocks", lambda *a, **k: None)
    monkeypatch.setattr(main, "run_threaded", lambda *a, **k: None)
    main.image_files = [_FAKE_BATCH_PAGE]
    main.curr_img_idx = 0
    main.image_states = {_FAKE_BATCH_PAGE: {}}

    assert main.cancel_button.isEnabled() is False
    main.block_detect()
    for button in main.hbutton_group.get_button_group().buttons():
        assert button.isEnabled() is False
    assert main.cancel_button.isEnabled() is False


# --- Webtoon inaccessible depuis l'interface (revérif tester, point 4) --------------------------


def test_webtoon_toggle_has_no_keyboard_shortcut():
    """Aucun raccourci ne peut plus déclencher le mode webtoon : `app/shortcuts.py` ne référence
    aucun identifiant de raccourci lié au webtoon."""
    import app.shortcuts as shortcuts_module

    for definition in shortcuts_module.SHORTCUT_DEFINITIONS:
        assert "webtoon" not in definition.id.lower()


def test_webtoon_toggle_hidden_and_has_no_default_shortcut_bound(main):
    assert main.webtoon_toggle.isVisibleTo(main) is False
    assert main.webtoon_toggle.shortcut().isEmpty()


def test_update_ui_from_project_resets_webtoon_mode_before_display_and_set_mode(main, monkeypatch):
    """Reprend `test_update_ui_from_project_resets_webtoon_mode` avec un projet non vide : prouve
    que la remise à `False` a bien lieu avant `_display_image_and_set_mode` (qui lirait sinon un
    `webtoon_mode` resté à `True`, hérité d'un `.ctpr` sauvegardé avant la sous-étape 2b)."""
    main.image_files = [_FAKE_BATCH_PAGE]
    main.image_states = {_FAKE_BATCH_PAGE: {"source_lang": "Auto", "target_lang": "English"}}
    main.curr_img_idx = 0
    main.webtoon_mode = True  # simule un `.ctpr` webtoon rechargé (`project_state.py:182`)

    captured = {}

    def _fake_run_threaded(callback, result_callback=None, error_callback=None, *a, **k):
        # Capture l'état de `webtoon_mode` tel que vu par le résultat, sans threading réel.
        captured["webtoon_mode_at_display"] = main.webtoon_mode
        return None

    monkeypatch.setattr(main, "run_threaded", _fake_run_threaded)

    main.project_ctrl.update_ui_from_project()

    assert main.webtoon_mode is False
    assert captured["webtoon_mode_at_display"] is False


# --- Démarrage QSettings `main_page/mode` : automatique et manuel, même état final (point 3) ----


class _FakeQSettings:
    """Remplace `QSettings` sans toucher au vrai magasin de réglages (consigne d'hygiène) :
    `beginGroup`/`endGroup` no-op, `value` lit un dict fixe, `setValue` ignoré."""

    def __init__(self, values: dict | None = None) -> None:
        self._values = values or {}

    def beginGroup(self, _name: str) -> None:
        pass

    def endGroup(self) -> None:
        pass

    def value(self, key: str, default=None, type=None):  # noqa: A002 (nom imposé par QSettings)
        found = self._values.get(key, default)
        if type is not None and found is not None:
            return type(found)
        return found

    def setValue(self, _key: str, _value) -> None:
        pass


def _resting_button_snapshot(main) -> tuple:
    return (
        tuple(b.isEnabled() for b in main.hbutton_group.get_button_group().buttons()),
        main.translate_button.isEnabled(),
        main.cancel_button.isEnabled(),
    )


@pytest.mark.parametrize("mode", ["automatic", "manual"])
def test_load_main_page_settings_mode_reaches_identical_resting_state(main, monkeypatch, mode):
    values = {
        "source_language": "Auto",
        "target_language": "English",
        "mode": mode,
        "brush_size": 10,
        "eraser_size": 20,
    }
    monkeypatch.setattr(projects_module, "QSettings", lambda *a, **k: _FakeQSettings(values))

    main.project_ctrl.load_main_page_settings()

    assert _resting_button_snapshot(main) == (
        tuple(True for _ in main.hbutton_group.get_button_group().buttons()),
        True,
        False,
    )


def test_save_main_page_settings_does_not_raise_reading_parked_radio(main, monkeypatch):
    """`save_main_page_settings` (`projects.py:~1410`) lit toujours `main_radio.isChecked()` — le
    widget reste vivant (parqué, jamais détruit), la lecture ne doit pas lever."""
    fake = _FakeQSettings()
    monkeypatch.setattr(projects_module, "QSettings", lambda *a, **k: fake)

    main.project_ctrl.save_main_page_settings()  # ne doit pas lever


# --- COMIC_SHELL=0 : radios/interrupteur webtoon visibles en mode diagnostic (point 5) -----------


def test_comic_shell_disabled_hides_only_the_webtoon_toggle(qtbot, monkeypatch):
    """`COMIC_SHELL=0` renvoie l'ancienne disposition telle quelle (mode diagnostic) : les radios
    Manuel/Automatique, devenues inoffensives (fonctions de mode neutres), restent visibles ;
    l'interrupteur webtoon est masqué, le webtoon n'étant plus pris en charge (spec 04 §7)."""
    monkeypatch.setenv("COMIC_SHELL", "0")

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)

    assert widget._shell_active is False
    assert widget._shell_failure == "désactivé par COMIC_SHELL=0"
    assert widget.webtoon_toggle.isHidden() is True
    for name in ("manual_radio", "automatic_radio"):
        assert getattr(widget, name).isHidden() is False


# ================================================================================================
# Sous-étape 2c : panneau droit contextuel (pile Page/Bulle)
# ================================================================================================

# --- Structure : chaque widget dans la bonne page de la pile -----------------------------------


def test_page_widget_holds_language_widgets_bubble_widget_holds_text_fields(main):
    panel = main._shell_panel
    page_widget = panel.stack.widget(panel.page_index)
    bubble_widget = panel.stack.widget(panel.bubble_index)

    for name in ("s_combo", "t_combo", "set_all_button"):
        widget = getattr(main, name)
        assert page_widget.isAncestorOf(widget), f"{name} hors de la page Page"
        assert not bubble_widget.isAncestorOf(widget), f"{name} dans la page Bulle"

    for name in ("s_text_edit", "t_text_edit", "block_history_button"):
        widget = getattr(main, name)
        assert bubble_widget.isAncestorOf(widget), f"{name} hors de la page Bulle"
        assert not page_widget.isAncestorOf(widget), f"{name} dans la page Page"


def test_page_is_shown_by_default_with_nothing_selected(main):
    assert main._shell_panel.stack.currentIndex() == main._shell_panel.page_index


# --- Table de vérité de la bascule, `setCurrentIndex` seulement au changement ------------------


def test_stack_switches_on_curr_tblock_and_setCurrentIndex_only_on_change(main):
    panel = main._shell_panel
    changes = []
    panel.stack.currentChanged.connect(changes.append)

    assert panel.stack.currentIndex() == panel.page_index

    _select_fake_bubble(main)
    assert panel.stack.currentIndex() == panel.bubble_index
    assert changes == [panel.bubble_index]

    # Réévaluer sans rien changer : aucune nouvelle bascule (`setCurrentIndex` non appelé).
    main._shell_context_watcher.evaluate_now()
    assert changes == [panel.bubble_index]

    _deselect_to_page(main)
    assert panel.stack.currentIndex() == panel.page_index
    assert changes == [panel.bubble_index, panel.page_index]


def test_stack_switches_to_bubble_via_curr_tblock_item(main):
    panel = main._shell_panel
    main.curr_tblock_item = SimpleNamespace()
    main._shell_context_watcher.evaluate_now()
    assert panel.stack.currentIndex() == panel.bubble_index


def test_stack_switches_to_bubble_while_search_panel_visible(main):
    panel = main._shell_panel
    _show_main_with_viewer(main)

    main.show_search_sidebar()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    assert main.search_panel.isVisible() is True
    assert panel.stack.currentIndex() == panel.bubble_index

    main._set_search_sidebar_visible(False)
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    assert panel.stack.currentIndex() == panel.page_index


# --- Déclencheurs réels (pas seulement `evaluate_now` appelé à la main) ------------------------


def test_real_rectangle_selected_signal_switches_to_bubble(main):
    """Bout en bout par le vrai signal, pas seulement `evaluate_now` appelé à la main : un vrai
    `TextBlock` dans `blk_list`, à la même géométrie que le rectangle émis, pour que le vrai
    gestionnaire (`RectItemController.handle_rectangle_selection`, connecté au même signal depuis
    `controller.py`) affecte lui-même `curr_tblock` — sinon, câbler notre propre `curr_tblock`
    factice serait écrasé par ce même gestionnaire réel (aucune correspondance trouvée -> `None`),
    avant même que notre watcher (mis en attente par `QTimer.singleShot(0)`) ait pu le relire."""
    panel = main._shell_panel
    assert panel.stack.currentIndex() == panel.page_index

    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
    main.blk_list.append(blk)

    main.image_viewer.rectangle_selected.emit(QRectF(0, 0, 10, 10))
    QtWidgets.QApplication.processEvents()

    assert main.curr_tblock is blk
    assert panel.stack.currentIndex() == panel.bubble_index


def test_real_clear_text_edits_signal_switches_to_page(main):
    panel = main._shell_panel
    _select_fake_bubble(main)
    assert panel.stack.currentIndex() == panel.bubble_index

    main.curr_tblock = None
    main.image_viewer.clear_text_edits.emit()
    QtWidgets.QApplication.processEvents()

    assert panel.stack.currentIndex() == panel.page_index


def test_real_page_list_current_item_changed_signal_triggers_reevaluation(main):
    panel = main._shell_panel
    _select_fake_bubble(main)
    assert panel.stack.currentIndex() == panel.bubble_index

    main.curr_tblock = None
    main.page_list.currentItemChanged.emit(None, None)
    QtWidgets.QApplication.processEvents()

    assert panel.stack.currentIndex() == panel.page_index


def test_viewport_mouse_release_event_triggers_reevaluation(main):
    """Appelle `eventFilter` directement plutôt que `QApplication.sendEvent` (précédent :
    `test_alt_key_still_toggles_veil_through_shell` dans ce même fichier) : un `QEvent` générique
    (type seul, pas un vrai `QMouseEvent`) suffit à notre filtre (qui ne lit que `event.type()`),
    mais ferait planter la gestion d'événements réelle de `QGraphicsView` si elle le recevait via
    la boucle Qt (downcast implicite vers `QMouseEvent`)."""
    panel = main._shell_panel
    _select_fake_bubble(main)
    assert panel.stack.currentIndex() == panel.bubble_index

    main.curr_tblock = None
    watcher = main._shell_context_watcher
    event = QEvent(QEvent.Type.MouseButtonRelease)
    consumed = watcher.eventFilter(main.image_viewer.viewport(), event)
    assert consumed is False
    QtWidgets.QApplication.processEvents()

    assert panel.stack.currentIndex() == panel.page_index


def test_schedule_coalesces_multiple_triggers_into_one_evaluation(main, monkeypatch):
    watcher = main._shell_context_watcher
    calls = {"n": 0}
    original_evaluate = watcher.evaluate_now

    def _counting_evaluate():
        calls["n"] += 1
        original_evaluate()

    monkeypatch.setattr(watcher, "evaluate_now", _counting_evaluate)

    watcher.schedule()
    watcher.schedule()
    watcher.schedule()
    QtWidgets.QApplication.processEvents()

    assert calls["n"] == 1


# --- Libellés dynamiques de la page Bulle : relus à chaque évaluation --------------------------


def test_bubble_captions_reflect_combo_text_at_each_evaluation(main):
    panel = main._shell_panel

    main.s_combo.blockSignals(True)
    main.t_combo.blockSignals(True)
    main.s_combo.setCurrentText("English")
    main.t_combo.setCurrentText("French")
    main.s_combo.blockSignals(False)
    main.t_combo.blockSignals(False)

    _select_fake_bubble(main)

    assert "English" in panel.bubble_source_caption.text()
    assert "French" in panel.bubble_target_caption.text()

    # Changement sous `blockSignals` (motif réel de `app/controllers/image.py:~1077-1086`) :
    # aucun signal ne prévient le watcher, seule la prochaine évaluation le voit.
    main.s_combo.blockSignals(True)
    main.s_combo.setCurrentText("Spanish")
    main.s_combo.blockSignals(False)

    main._shell_context_watcher.evaluate_now()
    assert "Spanish" in panel.bubble_source_caption.text()


# --- Règle de focus (condition bloquante du critic, sous-étape 2c) -----------------------------


def test_focus_moves_to_image_viewer_when_switching_bubble_to_page(main):
    _show_main_with_viewer(main)
    _select_fake_bubble(main)
    assert main._shell_panel.stack.currentIndex() == main._shell_panel.bubble_index

    main.t_text_edit.setFocus()
    QtWidgets.QApplication.processEvents()
    assert main.window().focusWidget() is main.t_text_edit

    _deselect_to_page(main)

    fw = main.window().focusWidget()
    assert fw is main.image_viewer
    assert fw not in (main.s_combo, main.t_combo, main.set_all_button)


def test_focus_rule_holds_when_application_reports_no_focus_widget(main, monkeypatch):
    """Fenêtre inactive simulée : `QApplication.focusWidget()` tomberait à `None`, mais
    `window().focusWidget()` (ce que lit la règle de focus, jamais `QApplication.focusWidget()`)
    continue de désigner le widget qui regagnerait le focus à la réactivation — c'est précisément
    pourquoi la règle ne doit jamais lire `QApplication.focusWidget()`."""
    _show_main_with_viewer(main)
    _select_fake_bubble(main)

    main.t_text_edit.setFocus()
    QtWidgets.QApplication.processEvents()
    assert main.window().focusWidget() is main.t_text_edit

    monkeypatch.setattr(QtWidgets.QApplication, "focusWidget", staticmethod(lambda: None))
    assert QtWidgets.QApplication.focusWidget() is None
    assert main.window().focusWidget() is main.t_text_edit  # inchangé malgré le monkeypatch

    _deselect_to_page(main)

    assert main.window().focusWidget() is main.image_viewer


def test_focus_does_not_land_in_bubble_fields_when_switching_page_to_bubble(main):
    _show_main_with_viewer(main)
    assert main._shell_panel.stack.currentIndex() == main._shell_panel.page_index

    main.t_combo.setFocus()
    QtWidgets.QApplication.processEvents()
    assert main.window().focusWidget() is main.t_combo

    _select_fake_bubble(main)

    fw = main.window().focusWidget()
    assert fw is not main.s_text_edit
    assert fw is not main.t_text_edit


# --- Non-écriture : ni les champs, ni la scène, ne sont touchés par la bascule -----------------


def test_context_switches_do_not_write_field_contents_or_scene_state(main):
    _show_main_with_viewer(main)

    main.s_text_edit.setPlainText("texte source de test")
    main.t_text_edit.setPlainText("texte traduction de test")

    state_before = main.image_viewer.save_state()
    s_before = main.s_text_edit.toPlainText()
    t_before = main.t_text_edit.toPlainText()

    for i in range(10):
        if i % 2 == 0:
            _select_fake_bubble(main)
        else:
            _deselect_to_page(main)

    assert main.s_text_edit.toPlainText() == s_before
    assert main.t_text_edit.toPlainText() == t_before
    assert main.image_viewer.save_state() == state_before


# --- Chien de garde : ne lève jamais, y compris sans `curr_tblock` (ComicTranslateUI seul) -----


def test_watchdog_and_evaluate_now_do_not_raise_without_curr_tblock(qtbot):
    widget = ComicTranslateUI()
    qtbot.addWidget(widget)

    assert not hasattr(widget, "curr_tblock")
    assert not hasattr(widget, "curr_tblock_item")

    widget._shell_context_watcher.evaluate_now()  # ne doit pas lever
    widget._shell_context_watchdog.timeout.emit()  # ne doit pas lever


# --- Revérif tester (rapport 2c) : chemins sans signal fiable, rattrapés par le vrai chien de
# garde (pas `evaluate_now()` appelé à la main) --------------------------------------------------
#
# `DeleteBoxesCommand.redo`/`undo` (`app/ui/commands/box.py:203,208`) et
# `TextController.clear_text_edits` (`app/controllers/text.py:96-97`, utilisé par
# `ImageController.on_render_state_ready` en fin de lot sur la page affichée) affectent
# `curr_tblock`/`curr_tblock_item` directement, sans émettre `rectangle_selected` ni
# `clear_text_edits` : seul le chien de garde à 200 ms rattrape ces cas. Les tests suivants
# laissent tourner le vrai `QTimer` (`qtbot.waitUntil`), jamais `evaluate_now()` à la main.


def test_watchdog_catches_direct_curr_tblock_assignment_without_any_signal(main, qtbot):
    """Reproduit exactement le motif de `DeleteBoxesCommand.redo` (`box.py:203`) et de
    `TextController.clear_text_edits` (`text.py:96-97`, chemin `on_render_state_ready`,
    `image.py:~1225-1227`) : affectation directe de `curr_tblock`, aucun signal émis. `main` doit
    être affichée : le chien de garde sort immédiatement si `panel.stack.isVisible()` est faux
    (`watcher.py:210`), comme dans l'application réelle où la fenêtre est toujours visible."""
    _show_main_with_viewer(main)
    panel = main._shell_panel
    _select_fake_bubble(main)
    assert panel.stack.currentIndex() == panel.bubble_index

    main.curr_tblock = None  # affectation directe, comme box.py:203 / text.py:96 — pas de signal

    qtbot.waitUntil(lambda: panel.stack.currentIndex() == panel.page_index, timeout=400)


def test_watchdog_catches_direct_bubble_selection_without_any_signal(main, qtbot):
    """Sens inverse : un contrôleur affecte `curr_tblock` sans passer par
    `handle_rectangle_selection` (motif générique visé par le chien de garde)."""
    _show_main_with_viewer(main)
    panel = main._shell_panel
    assert panel.stack.currentIndex() == panel.page_index

    main.curr_tblock = _fake_text_block()  # affectation directe, aucun signal émis

    qtbot.waitUntil(lambda: panel.stack.currentIndex() == panel.bubble_index, timeout=400)


def test_watchdog_interval_is_at_most_200ms_as_documented(main):
    assert main._shell_context_watchdog.interval() <= 200


# --- Recherche Ctrl+F : ordre réel `select_rectangle` (signal synchrone) puis `setFocus`
# synchrone sur le champ de la page encore masquée (`search_replace.py::_apply_match_selection`,
# ~ligne 786-791) --------------------------------------------------------------------------------
#
# `InteractionManager.select_rectangle` (`app/ui/canvas/interaction_manager.py:180-186`) émet
# `rectangle_selected` de façon synchrone (connexion directe, même thread) ; notre watcher se
# contente de `schedule()` (bascule différée par `QTimer.singleShot(0)`). Le code amont appelle
# `t_text_edit.setFocus()` juste après, dans le même appel, donc avant que la pile ait basculé.
# Preuve, avec les vrais widgets de l'app (pas une reproduction synthétique) : Qt accepte
# `setFocus()` sur un widget caché (page inactive de la pile) et le restitue fidèlement une fois
# la page rendue courante — aucun `RuntimeWarning`, aucune perte de focus.


def test_search_style_focus_before_stack_switch_still_lands_correctly(main, qtbot):
    _show_main_with_viewer(main)
    panel = main._shell_panel
    assert panel.stack.currentIndex() == panel.page_index

    # Même geste que `RectItemController.handle_rectangle_selection` (connecté au signal réel) :
    # affecte `curr_tblock` de façon synchrone, avant tout traitement Qt de l'événement.
    main.curr_tblock = _fake_text_block()
    # Reproduit `search_replace.py::_apply_match_selection` : `setFocus()` synchrone sur
    # `t_text_edit`, alors que la pile est encore sur la page Page (bascule différée).
    main.t_text_edit.setFocus()

    assert panel.stack.currentIndex() == panel.page_index  # pas encore basculé (différé)
    assert main.window().focusWidget() is main.t_text_edit  # Qt l'accepte déjà, widget caché

    # Notre watcher n'a pas encore tourné : c'est `evaluate_now()` (appelé directement par les
    # tests précédents) ou le passage réel par la boucle d'événements qui déclenche la bascule.
    # Ici, personne n'a émis de signal (affectation directe) : seul le chien de garde rattrape.
    qtbot.waitUntil(lambda: panel.stack.currentIndex() == panel.bubble_index, timeout=400)

    assert main.t_text_edit.hasFocus() is True
    assert main.window().focusWidget() is main.t_text_edit


# --- Règle de focus : `image_viewer` invisible (écran vide `drag_browser`) ----------------------
#
# Point à attaquer 1 : quand `image_viewer` n'est pas visible, `_move_focus_out_of_outgoing`
# appelle `clearFocus()` sur le widget sortant plutôt que de lui donner le focus — vérifie qu'il
# n'atterrit jamais sur `s_combo`/`t_combo`/`set_all_button` (les widgets de la page entrante).


def test_focus_cleared_not_redirected_to_page_widgets_when_viewer_hidden(main, qtbot):
    main.show_main_page()
    main.show()
    QtWidgets.QApplication.processEvents()

    main.central_stack.setCurrentWidget(main.drag_browser)
    QtWidgets.QApplication.processEvents()
    assert main.image_viewer.isVisible() is False

    _select_fake_bubble(main)
    main.t_text_edit.setFocus()
    QtWidgets.QApplication.processEvents()
    assert main.window().focusWidget() is main.t_text_edit

    _deselect_to_page(main)
    QtWidgets.QApplication.processEvents()

    fw = main.window().focusWidget()
    assert fw is not main.s_combo
    assert fw is not main.t_combo
    assert fw is not main.set_all_button
    assert fw is not main.t_text_edit  # sorti de la page Bulle (masquée)


# --- Robustesse : repli du shell => aucun observateur installé, aucune erreur -------------------


def test_no_context_watcher_installed_when_shell_falls_back(qtbot, monkeypatch):
    monkeypatch.setattr(
        manifest,
        "ALL_ZONES",
        manifest.ALL_ZONES + (("BOGUS", ("nonexistent_widget_xyz",)),),
    )

    widget = ComicTranslateUI()
    qtbot.addWidget(widget)

    assert widget._shell_active is False
    assert not hasattr(widget, "_shell_context_watcher")
    assert not hasattr(widget, "_shell_context_watchdog")
    assert not hasattr(widget, "_shell_panel") or widget._shell_panel is None


# --- Coût du chien de garde : un tick ne doit rien faire de coûteux (pas de disque, pas de rendu) --


def test_watchdog_tick_cost_is_cheap(main):
    import statistics
    import time

    _show_main_with_viewer(main)
    watcher = main._shell_context_watcher

    durations = []
    for _ in range(50):
        start = time.perf_counter()
        watcher.evaluate_now()
        durations.append(time.perf_counter() - start)

    median_ms = statistics.median(durations) * 1000
    print(f"[mesure shell 2c] chien de garde : médiane {median_ms:.4f} ms sur 50 ticks")
    assert median_ms < 5.0  # large marge : un tick ne fait que lire deux combos + comparer un index


# --- Non-écriture : aucune trace, dans le code du paquet, d'une écriture interdite ---------------


def test_shell_watcher_and_panel_never_write_forbidden_targets():
    """Analyse AST (pas un grep textuel, qui mordrait sur les docstrings qui *décrivent* la
    règle) en complément de `test_context_switches_do_not_write_field_contents_or_scene_state`
    (comportemental) : aucun appel `*.setPlainText(...)`/`*.insertPlainText(...)`/`*.clear()`, et
    aucune affectation `*.curr_tblock = ...`/`*.curr_tblock_item = ...`, dans le code réel de
    `modules/shell/watcher.py`/`modules/shell/panel.py` — seuls les deux libellés dynamiques de la
    page Bulle (`bubble_source_caption`/`bubble_target_caption`) peuvent recevoir `.setText(...)`."""
    import ast

    forbidden_calls = {"setPlainText", "insertPlainText", "clear"}
    forbidden_assign_attrs = {"curr_tblock", "curr_tblock_item"}

    for module in (watcher_module, panel_module):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls, (
                    f"{module.__name__}: appel interdit .{node.func.attr}(...) à la ligne "
                    f"{node.lineno}"
                )
                if node.func.attr == "setText":
                    target = node.func.value
                    target_name = getattr(target, "attr", None) or getattr(target, "id", None)
                    assert target_name in ("bubble_source_caption", "bubble_target_caption"), (
                        f"{module.__name__}: .setText(...) inattendu sur {target_name!r} à la "
                        f"ligne {node.lineno}"
                    )
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute):
                        assert target.attr not in forbidden_assign_attrs, (
                            f"{module.__name__}: affectation interdite .{target.attr} = ... à la "
                            f"ligne {node.lineno}"
                        )
