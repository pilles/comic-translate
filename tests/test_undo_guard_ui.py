"""GUI (spec 04, jalon 3, sous-étape 3a-bis) : verrou d'annulation + macros sûres pour le
nettoyage et la segmentation (`modules/undo_guard/{macro,ui}.py`, sites gardés dans
`app/controllers/manual_workflow.py`). `--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`).

Précédents : `tests/test_reset_ui.py` (fixture `main` sans effet de bord, `main.show()` requis
pour les chiens de garde qui sortent tôt si le widget est caché, `_add_open_page`/
`_add_second_page`/`_add_block`/`_add_brush_stroke`), `qtbot.capture_exceptions()` (précédent :
`tests/test_reset_ui.py::test_maj1_undo_past_an_undone_reset_restores_text_on_recreated_item`) pour les
scénarios où une exception traverse un rappel Qt (`QTimer.singleShot`) sans faire échouer le test
par la remontée globale de pytest-qt.

Vrai worker (`main.run_threaded`, vrai `QThreadPool`) partout, jamais `run_threaded` remplacé par
un no-op : on veut prouver le comportement bout en bout, `qtbot.waitUntil` plutôt que
`processEvents()` à la main."""

from __future__ import annotations

import threading

import numpy as np
import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QRectF

import modules.reset.ui as reset_ui_module
from app.ui.commands.inpaint import PatchInsertCommand
from app.ui.dayu_widgets.message import MMessage
from app.ui.messages import Messages
from modules.reset import state as reset_state
from modules.undo_guard.ui import _TOOLTIP_LOCKED, acquire_lock, release_lock
from modules.utils.textblock import TextBlock

_PHOTO_WIDTH = 160
_PHOTO_HEIGHT = 120
_WAIT_MS = 5000


@pytest.fixture(autouse=True)
def _no_blocking_error_dialogs(monkeypatch):
    """`default_error_handler`, branche générique, ouvrirait sinon une vraie boîte de dialogue
    modale (`Messages.show_error_with_copy` → `QMessageBox.exec()`) : bloquerait indéfiniment sous
    le pilote `offscreen`, aucun utilisateur pour cliquer OK (précédent :
    `tests/test_shell_ui.py::test_default_error_handler_then_batch_finished_reaches_resting_state`).
    Plusieurs scénarios de ce fichier font lever une `RuntimeError` dans un worker réel, qui
    remonte jusqu'à `default_error_handler` — neutralisé pour tout le fichier, pas seulement les
    tests qui en ont l'air d'avoir besoin (un rappel gardé peut y mener indirectement)."""
    monkeypatch.setattr(Messages, "show_error_with_copy", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(Messages, "show_network_error", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(Messages, "show_server_error", staticmethod(lambda *a, **k: None))


@pytest.fixture(autouse=True)
def _no_real_dayu_toasts(monkeypatch):
    """`MMessage.{warning,success,info,error}` construisent une vraie fenêtre `dayu_widgets`
    (icônes SVG, style, `QTimer` d'auto-fermeture) : sous le pilote `offscreen`, en enchaînant de
    nombreuses instances `ComicTranslate` (une par test), on observe une corruption intermittente
    et non locale du style Qt (`self.style()` renvoie un `QWidgetItem` au lieu d'un `QStyle` —
    `AttributeError: ... object has no attribute 'polish'/'pixelMetric'`, PySide6/Shiboken, pas
    reproductible en isolant un seul test). `modules.undo_guard.ui._notify_warning` et
    `modules.reset.ui._notify` (exercé par `test_reset_no_orphan_confirmation_after_failed_cleaning`
    de ce fichier) passent tous les deux par `MMessage` : neutralisé pour tout le fichier, comme
    `Messages` ci-dessus — aucun de ces tests ne vérifie le rendu du toast, seulement qu'il est
    déclenché (ou non) et que les rappels/l'état du verrou restent corrects."""
    monkeypatch.setattr(MMessage, "info", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(MMessage, "success", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(MMessage, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(MMessage, "error", staticmethod(lambda *a, **k: None))


def _synthetic_image(width: int = _PHOTO_WIDTH, height: int = _PHOTO_HEIGHT, fill: int = 120):
    return np.full((height, width, 3), fill, dtype=np.uint8)


def _neutralize_side_effects(main) -> None:
    """Précédent : `tests/test_reset_ui.py::_neutralize_side_effects`."""
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


def _show_main_with_viewer(main) -> None:
    main.show_main_page()
    main.central_stack.setCurrentWidget(main.image_viewer)
    main.show()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()


def _add_open_page(main, file_path: str, image=None) -> QtGui.QUndoStack:
    image = image if image is not None else _synthetic_image()
    main.image_files = [file_path]
    main.curr_img_idx = 0
    main.image_data[file_path] = image

    stack = QtGui.QUndoStack(main)
    main.undo_stacks[file_path] = stack
    main.undo_group.addStack(stack)
    main.undo_group.setActiveStack(stack)

    _show_main_with_viewer(main)
    main.image_viewer.display_image_array(image, fit=False)
    main.image_ctrl.save_image_state(file_path)
    return stack


def _add_second_page(main, file_path: str, image=None) -> QtGui.QUndoStack:
    image = image if image is not None else _synthetic_image(fill=60)
    main.image_files.append(file_path)
    main.image_data[file_path] = image
    stack = QtGui.QUndoStack(main)
    main.undo_stacks[file_path] = stack
    main.undo_group.addStack(stack)
    main.image_states[file_path] = main.image_ctrl._build_image_state(file_path, {}, [], [], False)
    return stack


def _add_block(main, xyxy=(10, 10, 60, 40), text="Hello", translation="Bonjour") -> TextBlock:
    blk = TextBlock(text_bbox=np.array(xyxy), text=text, translation=translation)
    main.blk_list.append(blk)
    return blk


def _add_brush_stroke(main) -> None:
    path = QtGui.QPainterPath()
    path.addRect(QRectF(5, 5, 20, 20))
    main.image_viewer.load_brush_strokes(
        [{"path": path, "pen": "#ff000000", "brush": "#00000000", "width": 3}]
    )


def _add_patch(main, file_path: str, stack: QtGui.QUndoStack, bbox=(0, 0, 10, 10)):
    """Précédent : `tests/test_reset_ui.py::_add_patch` — une commande annulable réelle, sans
    dépendre du worker de nettoyage."""
    patch_img = np.zeros((10, 10, 3), dtype=np.uint8)
    command = PatchInsertCommand(main, [{"bbox": bbox, "image": patch_img}], file_path)
    stack.push(command)
    return command


def _select_pages(main, paths: list[str]) -> None:
    """Sélection multiple minimale dans `page_list` (précédent : aucun test existant ne peuple
    `page_list` pour un lot restreint — construit ici la donnée minimale lue par
    `get_selected_page_paths`, `controller.py:316-328`)."""
    main.page_list.clear()
    for path in paths:
        item = QtWidgets.QListWidgetItem(path)
        item.setData(QtCore.Qt.ItemDataRole.UserRole, path)
        main.page_list.addItem(item)
    for row in range(main.page_list.count()):
        main.page_list.item(row).setSelected(True)


def _fake_patch_list(bbox=(0, 0, 10, 10)) -> list[dict]:
    return [{"bbox": list(bbox), "image": np.zeros((bbox[3], bbox[2], 3), dtype=np.uint8)}]


def _is_unrelated_dayu_menu_resize_noise(exc: tuple) -> bool:
    """Sous le pilote `offscreen`, `app/ui/dayu_widgets/menu.py::QMenu.resizeEvent` lève parfois un
    `AttributeError` intermittent, sans rapport avec `modules.undo_guard` (Shiboken/PySide6 :
    `'QWidgetItem' object has no attribute 'pixelMetric'`/`'polish'`, non reproductible en isolant
    un seul test — bruit d'infra GUI préexistant, cf. la même fragilité sur
    `tests/test_reset_ui.py:770`). Ne masque que ce motif précis, jamais une `AttributeError`
    générique."""
    exc_type, exc_value = exc[0], exc[1]
    return exc_type is AttributeError and (
        "pixelMetric" in str(exc_value) or "polish" in str(exc_value)
    )


def _idle(main, qtbot, timeout: int = _WAIT_MS, *, own_exception_capture: bool = False) -> None:
    """`own_exception_capture=True` : le test a déjà ouvert son propre `qtbot.capture_exceptions()`
    autour de cet appel (les deux tests `..._exception_inside_result_callback...`) — ne pas lui
    voler les exceptions qu'il veut inspecter en ouvrant une seconde capture imbriquée. Sinon,
    capture et ignore uniquement `_is_unrelated_dayu_menu_resize_noise`, relève toute autre
    exception pour ne pas masquer un vrai défaut."""
    if own_exception_capture:
        qtbot.waitUntil(lambda: not main.task_runner_ctrl.is_processing_queue, timeout=timeout)
        return

    with qtbot.capture_exceptions() as exceptions:
        qtbot.waitUntil(lambda: not main.task_runner_ctrl.is_processing_queue, timeout=timeout)

    unexpected = [exc for exc in exceptions if not _is_unrelated_dayu_menu_resize_noise(exc)]
    if unexpected:
        exc_type, exc_value, exc_tb = unexpected[0]
        raise exc_value.with_traceback(exc_tb)


# =================================================================================================
# Nettoyage page seule
# =================================================================================================


def test_cleaning_success_opens_closes_macro_undo_redo(main, qtbot):
    file_path = "/tmp/undo_guard_clean_ok.png"
    stack = _add_open_page(main, file_path)
    _add_brush_stroke(main)
    count_before = stack.count()

    main.pipeline.inpaint = lambda: _fake_patch_list()

    main.inpaint_and_set()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    assert stack.count() == count_before + 1  # une seule macro pour patch + effacement des traits
    assert stack.canUndo() is True
    assert len(main.image_patches.get(file_path, [])) == 1
    for button in main.undo_tool_group.get_button_group().buttons():
        assert button.isEnabled() is True

    stack.undo()
    assert main.image_patches.get(file_path, []) == []

    stack.redo()
    assert len(main.image_patches.get(file_path, [])) == 1


def test_cleaning_worker_error_no_macro_lock_released(main, qtbot):
    file_path = "/tmp/undo_guard_clean_err.png"
    stack = _add_open_page(main, file_path)
    _add_brush_stroke(main)
    count_before = stack.count()

    def _boom():
        raise RuntimeError("échec simulé du nettoyage")

    main.pipeline.inpaint = _boom

    main.inpaint_and_set()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    assert stack.count() == count_before  # aucune macro poussée
    assert stack.canUndo() is False
    for button in main.undo_tool_group.get_button_group().buttons():
        assert button.isEnabled() is True


def test_cleaning_current_worker_cancel_no_macro_lock_released(main, qtbot):
    file_path = "/tmp/undo_guard_clean_cancel.png"
    stack = _add_open_page(main, file_path)
    _add_brush_stroke(main)
    count_before = stack.count()

    event = threading.Event()

    def _blocking_inpaint():
        event.wait(timeout=5)
        return _fake_patch_list()

    main.pipeline.inpaint = _blocking_inpaint

    main.inpaint_and_set()
    qtbot.waitUntil(lambda: main.current_worker is not None, timeout=_WAIT_MS)
    assert main._undo_locked_by == "clean"
    main.current_worker.cancel()
    event.set()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    assert stack.count() == count_before  # résultat annulé (is_cancelled) : jamais de macro
    for button in main.undo_tool_group.get_button_group().buttons():
        assert button.isEnabled() is True


def test_cleaning_page_switch_while_worker_runs_abandons_on_both_pages(main, qtbot):
    file_path_a = "/tmp/undo_guard_clean_a.png"
    file_path_b = "/tmp/undo_guard_clean_b.png"
    stack_a = _add_open_page(main, file_path_a)
    _add_brush_stroke(main)
    stack_b = _add_second_page(main, file_path_b)
    count_a_before = stack_a.count()
    count_b_before = stack_b.count()

    event = threading.Event()

    def _blocking_inpaint():
        event.wait(timeout=5)
        return _fake_patch_list()

    main.pipeline.inpaint = _blocking_inpaint

    main.inpaint_and_set()
    qtbot.waitUntil(lambda: main.current_worker is not None, timeout=_WAIT_MS)

    # Navigation vers B pendant le calcul (précédent : tests/test_reset_ui.py, changement de
    # `curr_img_idx` seul suffit à faire échouer la garde de page de `page_bound`).
    main.curr_img_idx = main.image_files.index(file_path_b)
    main.undo_group.setActiveStack(stack_b)

    event.set()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    assert stack_a.count() == count_a_before
    assert stack_b.count() == count_b_before
    assert main.image_patches.get(file_path_b, []) in ([], None)

    main.curr_img_idx = main.image_files.index(file_path_a)
    main.undo_group.setActiveStack(stack_a)


def test_cleaning_dropped_from_queue_without_any_callback_lock_released_by_watchdog(main, qtbot):
    """File vidée par `cancel_current_task` avant que l'opération n'ait jamais démarré (défaut
    amont n°3, ADR-019) : aucun rappel n'est jamais appelé pour l'opération de nettoyage restée en
    file derrière une opération factice bloquante — le filet du chien de garde doit lever le verrou
    sans qu'aucun `finished_callback` n'ait tourné."""
    file_path = "/tmp/undo_guard_clean_dropped.png"
    _add_open_page(main, file_path)
    _add_brush_stroke(main)

    blocker_event = threading.Event()
    main.run_threaded(lambda: blocker_event.wait(timeout=5), None, None, None)
    qtbot.waitUntil(lambda: main.task_runner_ctrl.is_processing_queue, timeout=_WAIT_MS)

    finished_called = {"n": 0}
    main.pipeline.inpaint = lambda: _fake_patch_list()

    original_on_manual_finished = main.on_manual_finished

    def _tracking_finished():
        finished_called["n"] += 1
        original_on_manual_finished()

    main.on_manual_finished = _tracking_finished
    main.inpaint_and_set()  # mis en file derrière le bloqueur, verrou posé tout de suite

    assert main._undo_locked_by == "clean"

    main.cancel_current_task()  # vide la file : notre opération ne démarrera jamais

    qtbot.waitUntil(lambda: main._undo_locked_by is None, timeout=_WAIT_MS)
    assert finished_called["n"] == 0  # bien le filet, pas le chemin normal

    blocker_event.set()  # débloque le worker déjà lancé, laisse la file se vider proprement
    _idle(main, qtbot)


# =================================================================================================
# Verrou : annulation refusée pendant le calcul, acceptée après
# =================================================================================================


def test_undo_redo_refused_by_click_and_shortcut_during_cleaning_then_accepted_after(main, qtbot):
    """Correctif (constat du tester, 2026-09-28) : plus de `setEnabled` sur les boutons Annuler/
    Rétablir (ADR-018 — `MToolButton.changeEvent` construit un `QGraphicsOpacityEffect` sur
    `EnabledChange`, pendant la dépêche d'un `clicked`, plantage natif PySide6/Shiboken6 mesuré à
    10-20 % des lancements de ce fichier). Les boutons restent actifs (`isEnabled() is True`) tout
    du long ; la preuve porte sur un vrai clic Qt (`qtbot.mouseClick`) qui n'annule rien pendant le
    verrou, et qui annule normalement une fois levé."""
    file_path = "/tmp/undo_guard_lock_refuses.png"
    stack = _add_open_page(main, file_path)
    _add_brush_stroke(main)
    _add_patch(main, file_path, stack)  # une commande annulable déjà sur la pile, avant le clic
    assert stack.canUndo() is True
    count_after_setup = stack.count()

    event = threading.Event()
    main.pipeline.inpaint = lambda: (event.wait(timeout=5), _fake_patch_list())[1]

    main.inpaint_and_set()
    qtbot.waitUntil(lambda: main._undo_locked_by == "clean", timeout=_WAIT_MS)

    undo_button, redo_button = main.undo_tool_group.get_button_group().buttons()
    original_undo_tooltip = getattr(undo_button, "_undo_guard_original_tooltip", "")
    # Jamais désactivés (ADR-018) : seul le filtre d'événements avale le clic, et l'infobulle
    # signale l'indisponibilité.
    assert undo_button.isEnabled() is True
    assert redo_button.isEnabled() is True
    assert undo_button.toolTip() == _TOOLTIP_LOCKED
    assert redo_button.toolTip() == _TOOLTIP_LOCKED

    # Raccourci : refusé pendant le verrou (ne mute pas la pile).
    main.shortcut_ctrl._activate_shortcut("undo")
    assert stack.count() == count_after_setup
    assert stack.canUndo() is True

    # Clic Qt réel : avalé par `_UndoRedoClickBlocker` (filtre d'événements), n'annule rien.
    qtbot.mouseClick(undo_button, QtCore.Qt.MouseButton.LeftButton)
    assert stack.count() == count_after_setup
    assert stack.canUndo() is True

    event.set()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    assert undo_button.isEnabled() is True
    assert redo_button.isEnabled() is True
    assert undo_button.toolTip() == original_undo_tooltip  # infobulle d'origine restaurée
    assert redo_button.toolTip() != _TOOLTIP_LOCKED
    assert stack.count() == count_after_setup + 1  # la macro du nettoyage réussi
    assert len(main.image_patches.get(file_path, [])) == 2  # patch initial + patch du nettoyage

    # Accepté une fois le verrou levé : un vrai clic Qt annule la macro du nettoyage, pas le
    # patch initial.
    qtbot.mouseClick(undo_button, QtCore.Qt.MouseButton.LeftButton)
    assert len(main.image_patches.get(file_path, [])) == 1


# =================================================================================================
# Segmentation page seule (blocs déjà présents)
# =================================================================================================


def test_segmentation_single_page_with_blocks_success(main, qtbot):
    file_path = "/tmp/undo_guard_segment_ok.png"
    stack = _add_open_page(main, file_path)
    _add_block(main)
    count_before = stack.count()

    main.load_segmentation_points()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    # +1 `ClearRectsCommand` (comportement amont préexistant, poussé sans condition au tout début
    # de `load_segmentation_points`, avant même la branche prise) + 1 macro de segmentation.
    assert stack.count() == count_before + 2
    assert stack.canUndo() is True


def test_segmentation_single_page_with_blocks_worker_error(main, qtbot):
    file_path = "/tmp/undo_guard_segment_worker_err.png"
    stack = _add_open_page(main, file_path)
    _add_block(main)
    count_before = stack.count()

    def _boom(*_a, **_k):
        raise RuntimeError("échec simulé du calcul des tracés")

    main.image_viewer.drawing_manager.make_segmentation_stroke_data = _boom

    main.load_segmentation_points()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    # jamais de macro (le rappel de succès n'a pas tourné) ; +1 `ClearRectsCommand` amont.
    assert stack.count() == count_before + 1


def test_segmentation_single_page_exception_inside_result_callback_macro_still_closes(main, qtbot):
    """Exception dans le rappel gardé lui-même (pas dans le worker) : capturée via
    `qtbot.capture_exceptions()` (précédent `tests/test_reset_ui.py`), la macro doit malgré tout
    se refermer (`finally` de `page_bound`) et l'étape déjà posée reste annulable."""
    file_path = "/tmp/undo_guard_segment_partial.png"
    stack = _add_open_page(main, file_path)
    _add_block(main, xyxy=(10, 10, 60, 40))
    _add_block(main, xyxy=(70, 10, 120, 40))
    count_before = stack.count()

    calls = {"n": 0}
    original_draw = main.image_viewer.draw_segmentation_lines

    def _draw_then_boom(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("échec simulé au 2e tracé")
        return original_draw(*args, **kwargs)

    main.image_viewer.draw_segmentation_lines = _draw_then_boom

    with qtbot.capture_exceptions() as exceptions:
        main.load_segmentation_points()
        _idle(main, qtbot, own_exception_capture=True)

    # `capture_exceptions` capture aussi le bruit intermittent, sans rapport, d'un
    # `QMenu.resizeEvent` de `app/ui/dayu_widgets/menu.py` sous le pilote `offscreen` (précédent :
    # `tests/test_reset_ui.py:770`, même fragilité) — on ne retient que notre `RuntimeError`.
    runtime_errors = [exc for exc in exceptions if exc[0] is RuntimeError]
    assert len(runtime_errors) == 1
    assert "2e tracé" in str(runtime_errors[0][1])

    assert main._undo_locked_by is None
    # macro refermée malgré l'exception (finally) + 1 `ClearRectsCommand` amont.
    assert stack.count() == count_before + 2
    assert stack.canUndo() is True

    stack.undo()  # l'étape partielle (premier tracé) reste annulable normalement


# =================================================================================================
# Segmentation page seule, sans blocs (détection puis segmentation) : blk_detect_segment
# =================================================================================================


def test_blk_detect_segment_success(main, qtbot):
    file_path = "/tmp/undo_guard_blkdetect_ok.png"
    stack = _add_open_page(main, file_path)
    assert main.blk_list == []
    count_before = stack.count()

    fake_block = TextBlock(text_bbox=np.array((5, 5, 40, 30)))
    main.pipeline.detect_blocks = lambda load_rects=True: ([fake_block], load_rects)

    main.load_segmentation_points()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    assert main.blk_list == [fake_block]
    assert stack.count() == count_before + 2  # `ClearRectsCommand` amont + macro de segmentation
    assert stack.canUndo() is True


def test_blk_detect_segment_exception_inside_result_callback(main, qtbot):
    file_path = "/tmp/undo_guard_blkdetect_err.png"
    stack = _add_open_page(main, file_path)
    count_before = stack.count()

    fake_block = TextBlock(text_bbox=np.array((5, 5, 40, 30)))
    main.pipeline.detect_blocks = lambda load_rects=True: ([fake_block], load_rects)

    def _boom(*_a, **_k):
        raise RuntimeError("échec simulé du tracé de segmentation")

    main.image_viewer.draw_segmentation_lines = _boom

    with qtbot.capture_exceptions() as exceptions:
        main.load_segmentation_points()
        _idle(main, qtbot, own_exception_capture=True)

    # Cf. `test_segmentation_single_page_exception_inside_result_callback_macro_still_closes` :
    # ignore le bruit intermittent d'un `QMenu.resizeEvent` sans rapport (`dayu_widgets`,
    # `offscreen`).
    runtime_errors = [exc for exc in exceptions if exc[0] is RuntimeError]
    assert len(runtime_errors) == 1
    assert "tracé de segmentation" in str(runtime_errors[0][1])
    assert main._undo_locked_by is None
    # `blk_detect_segment` a affecté `main.blk_list` avant de lever : la macro s'est bien refermée
    # (même vide, une macro fermée reste comptée comme une entrée — parité amont, voir ADR-020).
    assert main.blk_list == [fake_block]
    assert stack.count() == count_before + 2  # `ClearRectsCommand` amont + macro (vide) fermée


# =================================================================================================
# Segmentation multi-pages
# =================================================================================================


def test_segmentation_multi_page_success(main, qtbot):
    file_path_a = "/tmp/undo_guard_multiseg_a.png"
    file_path_b = "/tmp/undo_guard_multiseg_b.png"
    stack_a = _add_open_page(main, file_path_a)
    _add_block(main)
    stack_b = _add_second_page(main, file_path_b)
    stack_b_count_before = stack_b.count()
    main.image_states[file_path_b]["blk_list"] = [TextBlock(text_bbox=np.array((5, 5, 40, 30)))]
    _select_pages(main, [file_path_a, file_path_b])
    count_before = stack_a.count()

    main.load_segmentation_points()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    # `ClearRectsCommand` amont (pile active au clic = A) + macro (`in_macro`, refermée sur la pile
    # active *au rappel*, toujours A ici puisque rien ne navigue pendant le calcul).
    assert stack_a.count() == count_before + 2
    assert stack_a.canUndo() is True
    assert stack_b.count() == stack_b_count_before


def test_segmentation_multi_page_error_no_macro_lock_released(main, qtbot):
    file_path_a = "/tmp/undo_guard_multiseg_err_a.png"
    file_path_b = "/tmp/undo_guard_multiseg_err_b.png"
    stack_a = _add_open_page(main, file_path_a)
    _add_block(main)
    _add_second_page(main, file_path_b)
    main.image_states[file_path_b]["blk_list"] = [TextBlock(text_bbox=np.array((5, 5, 40, 30)))]
    _select_pages(main, [file_path_a, file_path_b])
    count_before = stack_a.count()

    original_serialize = main.manual_workflow_ctrl._serialize_segmentation_strokes

    def _boom(*_a, **_k):
        raise RuntimeError("échec simulé du calcul multi-pages")

    main.manual_workflow_ctrl._serialize_segmentation_strokes = _boom

    main.load_segmentation_points()
    _idle(main, qtbot)

    assert main._undo_locked_by is None
    # aucune macro (le clic n'en ouvre plus, l'échec est dans le worker) ; +1 `ClearRectsCommand`.
    assert stack_a.count() == count_before + 1

    main.manual_workflow_ctrl._serialize_segmentation_strokes = original_serialize


# =================================================================================================
# Après un nettoyage en échec : Réinitialiser ne propose plus la confirmation « historique bloqué »
# =================================================================================================


def test_reset_no_orphan_confirmation_after_failed_cleaning(main, qtbot, monkeypatch):
    file_path = "/tmp/undo_guard_reset_after_failure.png"
    stack = _add_open_page(main, file_path)
    _add_brush_stroke(main)
    _add_block(main)

    def _boom():
        raise RuntimeError("échec simulé du nettoyage")

    main.pipeline.inpaint = _boom
    main.inpaint_and_set()
    _idle(main, qtbot)

    assert reset_state.macro_open(stack.count(), stack.index(), stack.canRedo()) is False

    def _fail_if_called(main):
        raise AssertionError("la confirmation « historique bloqué » n'aurait pas dû être proposée")

    monkeypatch.setattr(reset_ui_module, "_confirm_orphan_macro", _fail_if_called)

    reset_ui_module.request_reset(main)  # ne doit pas lever, ni appeler _confirm_orphan_macro
    assert main.blk_list == []


# =================================================================================================
# Journal Qt : aucun message natif d'annulation incohérente (critic m6, fixture `qtlog`)
# =================================================================================================


def test_no_qt_undo_stack_warnings_across_success_and_error_paths(main, qtbot, qtlog):
    file_path = "/tmp/undo_guard_qtlog.png"
    _add_open_page(main, file_path)
    _add_brush_stroke(main)
    _add_block(main)

    main.pipeline.inpaint = lambda: _fake_patch_list()
    main.inpaint_and_set()
    _idle(main, qtbot)

    def _boom():
        raise RuntimeError("échec simulé")

    main.pipeline.inpaint = _boom
    main.inpaint_and_set()
    _idle(main, qtbot)

    forbidden = ("no matching beginMacro", "cannot undo in the middle of a macro")
    messages = [record.message for record in qtlog.records]
    for text in messages:
        for needle in forbidden:
            assert needle not in text


# =================================================================================================
# Verrou : deux opérations gardées successives (Segmenter puis Nettoyer en file) — release_lock
# par nom ne laisse jamais un verrou orphelin, ni ne lève le verrou de l'autre (critic m1).
# =================================================================================================


def test_release_lock_by_name_does_not_lift_a_lock_acquired_under_a_different_name(main, qtbot):
    """Unitaire, directement sur `acquire_lock`/`release_lock` (pas de worker) : un appel de
    relâchement avec un nom périmé (l'ancien verrou a déjà été remplacé par un nouveau, cas
    "deux opérations gardées successives") ne doit ni lever le verrou actif, ni restaurer les
    infobulles à tort — seul un `release_lock` portant le nom actuellement posé les restaure.
    Boutons jamais désactivés (ADR-018, plus de `setEnabled`) : la preuve porte sur l'infobulle."""
    _show_main_with_viewer(main)
    undo_button, redo_button = main.undo_tool_group.get_button_group().buttons()
    original_undo_tooltip = getattr(undo_button, "_undo_guard_original_tooltip", "")
    original_redo_tooltip = getattr(redo_button, "_undo_guard_original_tooltip", "")

    acquire_lock(main, "segment")
    assert main._undo_locked_by == "segment"
    assert undo_button.isEnabled() is True
    assert redo_button.isEnabled() is True
    assert undo_button.toolTip() == _TOOLTIP_LOCKED
    assert redo_button.toolTip() == _TOOLTIP_LOCKED

    # "Nettoyer" se pose par-dessus avant que "Segmenter" n'ait relâché (verrou remplacé, jamais
    # cumulé — un seul nom actif à la fois, cf. `modules/undo_guard/ui.py::acquire_lock`).
    acquire_lock(main, "clean")
    assert main._undo_locked_by == "clean"

    # Le `finished_callback` tardif de "Segmenter" relâche par son propre nom, périmé : no-op.
    release_lock(main, "segment")
    assert main._undo_locked_by == "clean"  # pas d'orpheline levée à tort
    assert undo_button.toolTip() == _TOOLTIP_LOCKED  # ni d'infobulle restaurée à tort
    assert redo_button.toolTip() == _TOOLTIP_LOCKED

    # Le relâchement du verrou réellement actif fonctionne normalement, aucune trace orpheline.
    release_lock(main, "clean")
    assert main._undo_locked_by is None
    assert undo_button.isEnabled() is True
    assert redo_button.isEnabled() is True
    assert undo_button.toolTip() == original_undo_tooltip
    assert redo_button.toolTip() == original_redo_tooltip


def test_segmentation_then_cleaning_queued_back_to_back_both_locks_released_no_orphan(main, qtbot):
    """Intégration, vrais rappels gardés : la garde de "Segmenter" pose son verrou de façon
    synchrone au clic, avant même que son opération ait fini de tourner ; si "Nettoyer" est
    déclenché tout de suite après (sans laisser l'événement `finished` de la segmentation
    traverser la boucle Qt), sa garde pose son propre verrou par-dessus. Prouve que la fin
    (tardive) de la segmentation ne relâche pas à tort le verrou du nettoyage encore en cours, et
    que les deux opérations aboutissent normalement, sans verrou ni bouton bloqué à la fin."""
    file_path = "/tmp/undo_guard_seg_then_clean.png"
    stack = _add_open_page(main, file_path)
    _add_block(main)
    _add_brush_stroke(main)
    count_before = stack.count()

    main.pipeline.inpaint = lambda: _fake_patch_list()

    main.load_segmentation_points()  # verrou "segment" posé, opération démarrée tout de suite
    assert main._undo_locked_by == "segment"
    assert main.task_runner_ctrl.is_processing_queue is True

    # Avant que la boucle d'événements Qt n'ait pu délivrer le résultat/la fin de la segmentation
    # (aucun `qtbot.wait`/`processEvents` entre les deux appels) : simule un second déclenchement
    # rapproché, mis en file derrière la segmentation encore en cours.
    main.inpaint_and_set()
    assert main._undo_locked_by == "clean"  # remplacé, jamais cumulé

    _idle(main, qtbot)

    assert main._undo_locked_by is None
    for button in main.undo_tool_group.get_button_group().buttons():
        assert button.isEnabled() is True
        assert button.toolTip() != _TOOLTIP_LOCKED  # infobulle d'origine restaurée
    # `ClearRectsCommand` amont + macro de segmentation + macro de nettoyage.
    assert stack.count() == count_before + 3
    assert stack.canUndo() is True
    assert len(main.image_patches.get(file_path, [])) == 1
