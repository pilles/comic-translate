"""GUI (spec 03, jalon B) : bouton « Voir l'original » et touche Alt
maintenue (`modules/view/original.py`), voile peint par la vue
(`OriginalViewImageViewer.drawForeground`), et filtre d'événements applicatif
(`_OriginalViewEventFilter`). Reproduit les 10 scénarios de la conception
(v2 §Tests) et les consignes C6-C8 du critic (passage 2).

`--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`) : construit une
vraie `ComicTranslate` (fenêtre complète), pas seulement `ComicTranslateUI`
(précédent : `tests/test_history_restore.py`).

Note d'environnement (sans rapport avec ce jalon) : sous le pilote Qt
`offscreen`, le viewport de `ComicTranslate.image_viewer` (imbriqué dans la
fenêtre frameless du fork) ne reçoit jamais de géométrie réelle
(`QSize(100, 30)` quel que soit `resize()`/`show()`/`show_main_page()`) —
limite de plateforme pour ce widget nested + fenêtre frameless. Les tests qui
ont besoin d'une comparaison de pixels réelle (`viewport().grab()`) utilisent
donc une `OriginalViewImageViewer` autonome (fixture `standalone_viewer`), qui
obtient une vraie géométrie de viewport en tant que fenêtre de premier niveau.
Les autres tests (état, bouton, filtre, undo/redo, export) utilisent la
fixture `main` (vraie `ComicTranslate`), où seule la géométrie de peinture est
dégradée — la logique elle-même (peinture, `get_image_array`,
`save_current_image`, `save_state`) est indépendante de la taille réelle du
viewport."""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QEvent, Qt

import modules.view.original as original_module
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.commands.box import AddTextItemCommand
from app.ui.commands.inpaint import PatchInsertCommand
from app.ui.dayu_widgets.push_button import MPushButton
from modules.view.original import OriginalViewImageViewer

_PHOTO_WIDTH = 160
_PHOTO_HEIGHT = 120


def _synthetic_image(
    width: int = _PHOTO_WIDTH, height: int = _PHOTO_HEIGHT, fill: int = 120
) -> np.ndarray:
    return np.full((height, width, 3), fill, dtype=np.uint8)


@pytest.fixture
def main(qtbot):
    from controller import ComicTranslate

    instance = ComicTranslate()
    qtbot.addWidget(instance)
    instance._skip_close_prompt = True
    yield instance
    # `qtbot` ferme (et détruit) le widget automatiquement en fin de test.


@pytest.fixture
def standalone_viewer(qtbot):
    """Vue seule (hors `ComicTranslate`) — voir la note d'environnement en
    tête de fichier : obtient une vraie géométrie de viewport, nécessaire aux
    comparaisons `viewport().grab()`. Le bouton est un jumeau minimal de celui
    posé par `attach_original_button` (mêmes attributs lus par
    `_veil_active`/`drawForeground`), sans le reste du câblage applicatif
    (filtre Alt, `webtoon_toggle`) qui exige une vraie fenêtre principale et
    n'est pas nécessaire pour ces tests de peinture."""
    viewer = OriginalViewImageViewer(None)
    qtbot.addWidget(viewer)
    viewer.resize(_PHOTO_WIDTH, _PHOTO_HEIGHT)
    viewer.show()
    qtbot.waitExposed(viewer)
    button = MPushButton("Original")
    button.setCheckable(True)
    viewer._original_view_button = button
    return viewer, button


def _add_open_page(main, file_path: str) -> QtGui.QUndoStack:
    """Reproduit le minimum de `ImageStateController.thread_load_images`
    (précédent : `tests/test_history_restore.py::_add_open_page`)."""
    main.image_files = [file_path]
    main.curr_img_idx = 0
    stack = QtGui.QUndoStack(main)
    main.undo_stacks[file_path] = stack
    main.undo_group.addStack(stack)
    main.undo_group.setActiveStack(stack)
    return stack


def _post_key(main, etype: QEvent.Type, key: int, autorep: bool = False) -> bool:
    event = QtGui.QKeyEvent(etype, key, Qt.KeyboardModifier.NoModifier, autorep=autorep)
    return main._original_view_filter.eventFilter(main, event)


def _post_mouse_press(main) -> bool:
    event = QtGui.QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QtCore.QPointF(0, 0),
        QtCore.QPointF(0, 0),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    return main._original_view_filter.eventFilter(main, event)


def _activate(main) -> None:
    """`qtbot.addWidget` seul ne montre ni n'active la fenêtre, et le centre
    reste sur l'écran de démarrage (`startup_home`) tant qu'aucune page n'est
    chargée : `main.isActiveWindow()` et `_workspace_is_active` (tous deux
    gardés par `_can_arm`) resteraient sinon `False`."""
    main.show_main_page()
    main.show()
    main.activateWindow()
    QtWidgets.QApplication.processEvents()


# --- Test 1 : non-régression export/état (voile invisible pour l'export) ---


def test_veil_does_not_change_get_image_array_or_save_state(main):
    img = _synthetic_image()
    main.image_viewer.display_image_array(img, fit=False)
    main.image_viewer.add_text_item(
        TextItemProperties(
            text="BULLE", position=(10, 10), rotation=0, text_color=QtGui.QColor("black")
        )
    )
    # Laisse `viewport().rect()` (utilisé par `save_state()['center']`) se
    # stabiliser avant de figer l'état de référence (fait mesuré : deux
    # `save_state()` consécutifs sans aucune interaction diffèrent sinon).
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()

    arr_before = main.image_viewer.get_image_array(paint_all=True)
    state_before = main.image_viewer.save_state()

    main.original_view_button.setChecked(True)

    arr_after = main.image_viewer.get_image_array(paint_all=True)
    state_after = main.image_viewer.save_state()

    assert np.array_equal(arr_before, arr_after)
    assert state_before == state_after


# --- Test 2 : le voile se voit ---------------------------------------------


def test_veil_visible_in_viewport_grab(standalone_viewer, qtbot):
    viewer, button = standalone_viewer
    img = _synthetic_image()
    viewer.display_image_array(img, fit=True)
    viewer.add_text_item(
        TextItemProperties(
            text="VISIBLE", position=(10, 10), rotation=0, text_color=QtGui.QColor("red")
        )
    )
    qtbot.wait(10)

    grab_plain = viewer.viewport().grab()
    button.setChecked(True)
    viewer.viewport().update()
    qtbot.wait(10)
    grab_veiled = viewer.viewport().grab()

    assert grab_plain.toImage() != grab_veiled.toImage()


# --- Test 3 : bouton/touche -------------------------------------------------


def test_alt_keypress_arms_and_keyrelease_disarms(main, monkeypatch):
    _activate(main)
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )
    assert not main.image_viewer._original_view_alt_held

    consumed = _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)
    assert consumed is False
    assert main.image_viewer._original_view_alt_held
    assert main.original_view_button.isDown()
    assert main.image_viewer._veil_active()

    _post_key(main, QEvent.Type.KeyRelease, Qt.Key.Key_Alt)
    assert not main.image_viewer._original_view_alt_held
    assert not main.original_view_button.isDown()
    assert not main.image_viewer._veil_active()


def test_alt_autorepeat_does_not_arm(main, monkeypatch):
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )
    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=True)
    assert not main.image_viewer._original_view_alt_held
    assert not main.original_view_button.isDown()


def test_button_checked_keeps_veil_active_without_alt(main):
    main.original_view_button.setChecked(True)
    assert main.image_viewer._veil_active()
    assert not main.image_viewer._original_view_alt_held


# --- Test 4 : changement de page --------------------------------------------


def test_page_change_keeps_veil_active_and_paints_new_photo(main):
    img1 = _synthetic_image(fill=50)
    main.image_viewer.display_image_array(img1, fit=False)
    main.original_view_button.setChecked(True)
    assert main.image_viewer._veil_active()

    img2 = _synthetic_image(fill=180)
    main.image_viewer.clear_scene()  # recrée self.photo (jamais cachée)
    main.image_viewer.display_image_array(img2, fit=False)

    assert main.image_viewer._veil_active()
    arr = main.image_viewer.get_image_array(paint_all=False)
    assert np.array_equal(arr, img2)


# --- Test 5 : undo/redo pendant le voile ------------------------------------


def test_undo_redo_during_veil_add_text_and_patch(main):
    _add_open_page(main, "fake_page.png")
    img = _synthetic_image()
    main.image_viewer.display_image_array(img, fit=False)

    main.original_view_button.setChecked(True)

    text_item = main.image_viewer.add_text_item(
        TextItemProperties(
            text="Bulle", position=(10, 10), rotation=0, text_color=QtGui.QColor("black")
        )
    )
    add_cmd = AddTextItemCommand(main, text_item)
    main.push_command(add_cmd)
    assert text_item in main.image_viewer.text_items

    patch_img = np.zeros((10, 10, 3), dtype=np.uint8)
    patches = [{"bbox": (5, 5, 10, 10), "image": patch_img}]
    patch_cmd = PatchInsertCommand(main, patches, "fake_page.png")
    main.push_command(patch_cmd)
    assert len(main.image_patches["fake_page.png"]) == 1

    stack = main.undo_group.activeStack()

    stack.undo()  # annule le patch
    assert len(main.image_patches.get("fake_page.png", [])) == 0
    assert main.original_view_button.isChecked()  # le voile n'est pas touché par l'undo

    stack.undo()  # annule l'ajout de texte
    assert text_item not in main.image_viewer.text_items

    stack.redo()  # rejoue l'ajout de texte
    assert len(main.image_viewer.text_items) == 1

    stack.redo()  # rejoue le patch
    assert len(main.image_patches.get("fake_page.png", [])) == 1
    assert main.original_view_button.isChecked()


# --- Test 6 : aucune clé nouvelle -------------------------------------------


def test_no_new_persisted_keys(main):
    _add_open_page(main, "fake_page.png")
    img = _synthetic_image()
    main.image_viewer.display_image_array(img, fit=False)
    main.blk_list = []

    main.original_view_button.setChecked(False)
    main.image_ctrl.save_image_state("fake_page.png")
    state_off = dict(main.image_states["fake_page.png"])

    main.original_view_button.setChecked(True)
    main.image_ctrl.save_image_state("fake_page.png")
    state_on = dict(main.image_states["fake_page.png"])

    assert set(state_off.keys()) == set(state_on.keys())
    assert set(state_off["viewer_state"].keys()) == set(state_on["viewer_state"].keys())
    assert not any("original" in k.lower() or "veil" in k.lower() for k in state_on)
    assert not any("original" in k.lower() or "veil" in k.lower() for k in state_on["viewer_state"])


def test_original_view_module_never_touches_qsettings():
    assert "QSettings" not in inspect.getsource(original_module)


# --- Test 7 / C6 : webtoon ---------------------------------------------------


def test_webtoon_blocks_arming_even_when_conditions_otherwise_valid(main, monkeypatch):
    _activate(main)
    monkeypatch.setattr(main.image_viewer.webtoon_manager, "is_active", lambda: True)
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )

    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)

    assert not main.image_viewer._original_view_alt_held
    assert not main.original_view_button.isDown()


def test_webtoon_button_checked_paints_nothing(standalone_viewer, qtbot, monkeypatch):
    viewer, button = standalone_viewer
    img = _synthetic_image()
    viewer.display_image_array(img, fit=True)
    viewer.add_text_item(
        TextItemProperties(
            text="VISIBLE", position=(10, 10), rotation=0, text_color=QtGui.QColor("red")
        )
    )
    monkeypatch.setattr(viewer.webtoon_manager, "is_active", lambda: True)
    qtbot.wait(10)

    grab_unchecked = viewer.viewport().grab()
    button.setChecked(True)
    viewer.viewport().update()
    qtbot.wait(10)
    grab_checked = viewer.viewport().grab()

    assert grab_unchecked.toImage() == grab_checked.toImage()


def test_no_photo_loaded_paints_nothing_even_when_button_checked(standalone_viewer, qtbot):
    viewer, button = standalone_viewer  # jamais de display_image_array : photo.pixmap() reste nulle

    grab_unchecked = viewer.viewport().grab()
    button.setChecked(True)
    viewer.viewport().update()
    qtbot.wait(10)
    grab_checked = viewer.viewport().grab()

    assert grab_unchecked.toImage() == grab_checked.toImage()


# --- Test 8 : réinitialisation ------------------------------------------------


def test_window_deactivate_disarms_veil(main, monkeypatch):
    _activate(main)
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )
    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)
    assert main.image_viewer._original_view_alt_held

    main._original_view_filter.eventFilter(main, QEvent(QEvent.Type.WindowDeactivate))

    assert not main.image_viewer._original_view_alt_held
    assert not main.original_view_button.isDown()


def test_application_state_change_disarms_veil_when_not_active(main, monkeypatch):
    _activate(main)
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )
    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)
    assert main.image_viewer._original_view_alt_held

    # Simule le passage en arrière-plan (Cmd+Tab), indépendamment de l'état
    # réel — non piloté par le harnais sous le pilote offscreen.
    monkeypatch.setattr(
        QtWidgets.QApplication.instance(),
        "applicationState",
        lambda: Qt.ApplicationState.ApplicationInactive,
    )
    main._original_view_filter.eventFilter(main, QEvent(QEvent.Type.ApplicationStateChange))

    assert not main.image_viewer._original_view_alt_held


def test_arming_refused_when_modal_widget_active(main, monkeypatch):
    _activate(main)
    dummy_modal = QtWidgets.QWidget()
    monkeypatch.setattr(
        original_module.QApplication, "activeModalWidget", staticmethod(lambda: dummy_modal)
    )
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )

    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)

    assert not main.image_viewer._original_view_alt_held


def test_arming_refused_when_workspace_not_active(main, monkeypatch):
    _activate(main)
    main._center_stack.setCurrentWidget(main.settings_page)
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )

    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)

    assert not main.image_viewer._original_view_alt_held


def test_arming_refused_when_window_not_active(main, monkeypatch):
    _activate(main)
    monkeypatch.setattr(main, "isActiveWindow", lambda: False)
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )

    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)

    assert not main.image_viewer._original_view_alt_held


# --- Test 9 / C8 : export bout en bout, octets identiques -------------------


def test_save_current_image_byte_identical_veil_active_vs_lifted(main, tmp_path):
    img = _synthetic_image()
    main.image_viewer.display_image_array(img, fit=False)
    main.image_viewer.add_text_item(
        TextItemProperties(text="X", position=(5, 5), rotation=0, text_color=QtGui.QColor("black"))
    )

    path_on = tmp_path / "veil_on.png"
    path_off = tmp_path / "veil_off.png"

    main.original_view_button.setChecked(True)
    main.image_ctrl.save_current_image(str(path_on))

    main.original_view_button.setChecked(False)
    main.image_ctrl.save_current_image(str(path_off))

    assert path_on.read_bytes() == path_off.read_bytes()


# --- Test 10 : saisie en cours -----------------------------------------------


def test_alt_blocked_while_text_input_focused(main, monkeypatch):
    _activate(main)
    line_edit = QtWidgets.QLineEdit()
    monkeypatch.setattr(
        original_module.QApplication, "focusWidget", staticmethod(lambda: line_edit)
    )
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )

    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)

    assert not main.image_viewer._original_view_alt_held


def test_alt_blocked_while_text_item_in_editing_mode(main, monkeypatch):
    _activate(main)
    item = main.image_viewer.add_text_item(
        TextItemProperties(
            text="En cours", position=(0, 0), rotation=0, text_color=QtGui.QColor("black")
        )
    )
    item.editing_mode = True
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )

    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)

    assert not main.image_viewer._original_view_alt_held


# --- C7 : relâchement d'Alt manqué (désynchronisation) -----------------------


def test_alt_disarmed_on_other_keypress_without_modifier(main, monkeypatch):
    _activate(main)
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )
    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)
    assert main.image_viewer._original_view_alt_held

    # Alt relâché hors de la fenêtre : aucun QEvent.KeyRelease reçu, mais
    # l'état global du clavier ne contient plus AltModifier.
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.NoModifier),
    )
    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_A, autorep=False)

    assert not main.image_viewer._original_view_alt_held
    assert not main.original_view_button.isDown()


def test_alt_disarmed_on_mouse_press_without_modifier(main, monkeypatch):
    _activate(main)
    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.AltModifier),
    )
    _post_key(main, QEvent.Type.KeyPress, Qt.Key.Key_Alt, autorep=False)
    assert main.image_viewer._original_view_alt_held

    monkeypatch.setattr(
        original_module.QGuiApplication,
        "queryKeyboardModifiers",
        staticmethod(lambda: Qt.KeyboardModifier.NoModifier),
    )
    _post_mouse_press(main)

    assert not main.image_viewer._original_view_alt_held
