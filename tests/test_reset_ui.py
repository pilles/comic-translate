"""GUI (spec 04, jalon 3, sous-étape 3a) : bouton « Réinitialiser » la page
(`modules/reset/{state,commands,ui}.py`). `--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`).

Précédents : `tests/test_shell_ui.py` (fixture `main` sans effet de bord, `main.show()` requis pour
les chiens de garde qui sortent tôt si le widget est caché), `tests/test_history_restore.py`
(`_add_open_page`), `tests/test_original_view.py` (image synthétique)."""

from __future__ import annotations


import imkit as imk
import numpy as np
import pytest
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QUndoCommand, QUndoStack

import modules.ocr.processor as ocr_processor_module
import modules.reset.ui as reset_ui_module
import modules.translation.processor as translation_processor_module
from app.projects.project_state_v2 import load_state_from_proj_file_v2, save_state_to_proj_file_v2
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.commands.inpaint import PatchInsertCommand
from modules.history import versions
from modules.pagestate.collect import page_progress
from modules.reset import commands as reset_commands
from modules.reset import state as reset_state
from modules.utils.textblock import TextBlock

_PHOTO_WIDTH = 160
_PHOTO_HEIGHT = 120


def _synthetic_image(width: int = _PHOTO_WIDTH, height: int = _PHOTO_HEIGHT, fill: int = 120):
    return np.full((height, width, 3), fill, dtype=np.uint8)


def _neutralize_side_effects(main) -> None:
    """Précédent : `tests/test_shell_ui.py::_neutralize_side_effects`."""
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
    """Ouvre `file_path` comme page unique affichée, avec une pile d'annulation active — minimum
    reproduit de `ImageStateController.thread_load_images` (précédent : `_add_open_page` de
    `tests/test_history_restore.py`/`tests/test_original_view.py`)."""
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


def _add_rendered_text_item(main, blk: TextBlock):
    return main.image_viewer.add_text_item(
        TextItemProperties(
            text=blk.translation,
            position=(blk.xyxy[0], blk.xyxy[1]),
            rotation=blk.angle,
            text_color=QtGui.QColor("black"),
        )
    )


def _add_patch(main, file_path: str, stack: QtGui.QUndoStack, bbox=(0, 0, 10, 10)):
    patch_img = np.zeros((10, 10, 3), dtype=np.uint8)
    command = PatchInsertCommand(main, [{"bbox": bbox, "image": patch_img}], file_path)
    stack.push(command)
    return command


def _add_brush_stroke(main):
    path = QtGui.QPainterPath()
    path.addRect(QRectF(5, 5, 20, 20))
    main.image_viewer.load_brush_strokes(
        [{"path": path, "pen": "#ff000000", "brush": "#00000000", "width": 3}]
    )


def _build_synthetic_page(main, file_path: str, stack: QtGui.QUndoStack) -> TextBlock:
    """Page « de synthèse » : un bloc avec historique (`versions`), un rectangle, un texte rendu,
    un tracé de pinceau, un patch de nettoyage posé via `PatchInsertCommand` (précédent :
    `tests/test_original_view.py`)."""
    blk = _add_block(main)
    versions.set_text(blk, "text", "Hello", versions.ORIGIN_OCR, {"ocr": "Default"})
    versions.set_text(blk, "translation", "Bonjour", versions.ORIGIN_TRANSLATION, {"model": "X"})
    main.image_viewer.add_rectangle(QRectF(0, 0, 50, 30), QPointF(10, 10), 0)
    _add_rendered_text_item(main, blk)
    _add_brush_stroke(main)
    _add_patch(main, file_path, stack)
    main.image_ctrl.save_image_state(file_path)
    return blk


def _reset_now(main, p: str, stack: QtGui.QUndoStack) -> reset_commands.ResetPageCommand:
    command = reset_commands.ResetPageCommand(main, p, stack)
    stack.push(command)
    return command


# =================================================================================================
# Attache
# =================================================================================================


def test_button_attached_after_loading_with_spacing(main):
    header = main._shell_header_layout
    loading_index = header.indexOf(main.loading)
    button_index = header.indexOf(main.page_reset_button)
    assert button_index > loading_index
    # Un item d'espacement (`insertSpacing`) sépare le bouton de `loading`.
    assert header.itemAt(loading_index + 1).spacerItem() is not None


def test_button_no_focus_and_labelled(main):
    button = main.page_reset_button
    assert button.focusPolicy() == QtGui.Qt.FocusPolicy.NoFocus
    assert button.text() == "Réinitialiser"
    assert "Annulable" in button.toolTip()


def test_button_absent_under_comic_shell_0(qtbot, monkeypatch):
    monkeypatch.setenv("COMIC_SHELL", "0")
    from controller import ComicTranslate

    instance = ComicTranslate()
    qtbot.addWidget(instance)
    _neutralize_side_effects(instance)
    assert getattr(instance, "page_reset_button", None) is None
    monkeypatch.delenv("COMIC_SHELL", raising=False)


def test_attach_failure_does_not_prevent_app_startup(qtbot, monkeypatch):
    """Casse un point réel de l'attache (construction du bouton) : `attach_page_reset` est
    importée par nom dans `controller.py`, donc patcher `MPushButton` dans le module (plutôt que
    remplacer la fonction elle-même) atteint le vrai code exécuté au démarrage."""
    monkeypatch.setattr(
        reset_ui_module,
        "MPushButton",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    from controller import ComicTranslate

    instance = ComicTranslate()
    qtbot.addWidget(instance)
    _neutralize_side_effects(instance)
    assert isinstance(instance, ComicTranslate)
    assert getattr(instance, "page_reset_button", None) is None


def test_attach_page_reset_degrades_when_header_missing(main):
    fake_main = QtWidgets.QWidget()
    try:
        assert reset_ui_module.attach_page_reset(fake_main) is None
    finally:
        fake_main.deleteLater()


# =================================================================================================
# Contrat Qt figé : macro ouverte
# =================================================================================================


def test_macro_open_contract_on_real_undo_stack():
    stack = QUndoStack()
    stack.beginMacro("op")
    assert stack.count() == stack.index() + 1
    assert stack.canRedo() is False
    assert reset_state.macro_open(stack.count(), stack.index(), stack.canRedo()) is True
    stack.endMacro()
    assert reset_state.macro_open(stack.count(), stack.index(), stack.canRedo()) is False


def test_undone_command_is_not_mistaken_for_open_macro():
    stack = QUndoStack()
    stack.push(QUndoCommand("cmd"))
    stack.undo()
    assert reset_state.macro_open(stack.count(), stack.index(), stack.canRedo()) is False


# =================================================================================================
# Disponibilité
# =================================================================================================


def test_availability_false_before_any_page_loaded(main):
    available, _reason = reset_state.availability(main)
    assert available is False
    assert main.page_reset_button.isEnabled() is False


def test_availability_true_once_page_displayed(main):
    _add_open_page(main, "/tmp/reset_page_a.png")
    main._page_reset_watcher.refresh()
    available, reason = reset_state.availability(main)
    assert (available, reason) == (True, "")
    assert main.page_reset_button.isEnabled() is True


def test_button_disabled_while_steps_disabled(main):
    _add_open_page(main, "/tmp/reset_page_b.png")
    main.disable_hbutton_group()
    main._page_reset_watcher.refresh()
    assert main.page_reset_button.isEnabled() is False
    main.enable_hbutton_group()
    main._page_reset_watcher.refresh()
    assert main.page_reset_button.isEnabled() is True


def test_button_disabled_during_batch(main):
    _add_open_page(main, "/tmp/reset_page_c.png")
    main._batch_active = True
    main._page_reset_watcher.refresh()
    assert main.page_reset_button.isEnabled() is False
    main._batch_active = False


def test_button_refreshes_on_active_stack_changed(main):
    _add_open_page(main, "/tmp/reset_page_d.png")
    other_stack = QtGui.QUndoStack(main)
    main.undo_group.addStack(other_stack)
    main.undo_group.setActiveStack(other_stack)
    QtWidgets.QApplication.processEvents()
    assert main.page_reset_button.isEnabled() is False


def test_watchdog_catches_direct_state_change_without_signal(main):
    _add_open_page(main, "/tmp/reset_page_e.png")
    for button in main.hbutton_group.get_button_group().buttons():
        button.blockSignals(True)
        button.setEnabled(False)
        button.blockSignals(False)
    # Pas de signal `EnabledChange` volontairement contourné : seul le chien de garde (250 ms)
    # doit rattraper — on l'appelle directement plutôt que d'attendre pour ne pas ralentir la
    # suite (précédent : `tests/test_shell_ui.py`, chien de garde du panneau contextuel).
    main._page_reset_watcher.refresh()
    assert main.page_reset_button.isEnabled() is False


# =================================================================================================
# Réinitialisation : état vierge, annulation, identité
# =================================================================================================


def test_reset_produces_pristine_live_state(main):
    file_path = "/tmp/reset_synth_1.png"
    stack = _add_open_page(main, file_path)
    _build_synthetic_page(main, file_path, stack)

    _reset_now(main, file_path, stack)

    assert main.blk_list == []
    viewer_state = main.image_viewer.save_state()
    assert viewer_state["rectangles"] == []
    assert viewer_state["text_items_state"] == []
    assert main.image_viewer.save_brush_strokes() == []
    assert main.image_patches.get(file_path) == []


def test_reset_keeps_languages_and_skip_and_view_transform(main):
    file_path = "/tmp/reset_synth_2.png"
    stack = _add_open_page(main, file_path)
    main.image_states[file_path]["skip"] = True
    main.image_states[file_path]["export_group_name"] = "mon_album"
    _build_synthetic_page(main, file_path, stack)
    before_transform = main.image_viewer.save_state()["transform"]

    _reset_now(main, file_path, stack)

    state = main.image_states[file_path]
    assert state["skip"] is True
    assert state["export_group_name"] == "mon_album"
    assert main.image_viewer.save_state()["transform"] == before_transform


def test_undo_restores_serialization_and_block_identity(main):
    file_path = "/tmp/reset_synth_3.png"
    stack = _add_open_page(main, file_path)
    blk = _build_synthetic_page(main, file_path, stack)
    live_list = main.blk_list
    before_state = main.image_ctrl._build_image_state(
        file_path,
        main.image_viewer.save_state(),
        main.image_viewer.save_brush_strokes(),
        main.blk_list.copy(),
        False,
    )

    _reset_now(main, file_path, stack)
    stack.undo()

    assert main.blk_list is live_list
    assert len(main.blk_list) == 1
    assert main.blk_list[0] is blk
    assert versions.versions_of(blk) == before_state["blk_list"][0].__dict__.get("versions")
    # Comparaison tolérante (précédent : `ImageViewer.save_state`/`load_state` arrondit déjà les
    # dimensions au pixel près à chaque aller-retour, indépendamment de la réinitialisation) :
    # seuls le nombre et la position (coin haut-gauche, rotation) doivent survivre à l'identique.
    rects_before = before_state["viewer_state"]["rectangles"]
    rects_after = main.image_viewer.save_state()["rectangles"]
    assert len(rects_after) == len(rects_before)
    for before_rect, after_rect in zip(rects_before, rects_after):
        assert after_rect["rect"][:2] == pytest.approx(before_rect["rect"][:2], abs=1)
        assert after_rect["rotation"] == pytest.approx(before_rect["rotation"])
    assert len(main.image_viewer.save_brush_strokes()) == len(before_state["brush_strokes"])
    assert len(main.image_patches.get(file_path, [])) == 1


def test_undo_preserves_two_overlapping_patches_order(main):
    file_path = "/tmp/reset_synth_4.png"
    stack = _add_open_page(main, file_path)
    _add_block(main)
    _add_patch(main, file_path, stack, bbox=(0, 0, 10, 10))
    _add_patch(main, file_path, stack, bbox=(5, 5, 15, 15))
    main.image_ctrl.save_image_state(file_path)
    order_before = [p["hash"] for p in main.image_patches[file_path]]

    _reset_now(main, file_path, stack)
    stack.undo()

    order_after = [p["hash"] for p in main.image_patches[file_path]]
    assert order_after == order_before


def test_no_push_beginmacro_endmacro_during_redo_or_undo(main):
    file_path = "/tmp/reset_synth_5.png"
    stack = _add_open_page(main, file_path)
    _build_synthetic_page(main, file_path, stack)
    count_before_push = stack.count()

    _reset_now(main, file_path, stack)
    assert stack.count() == count_before_push + 1

    stack.undo()
    assert stack.count() == count_before_push + 1
    stack.redo()
    assert stack.count() == count_before_push + 1


# =================================================================================================
# M1 : dessiner une boîte après reset, annuler/refaire par-dessus
# =================================================================================================


def test_m1_box_drawn_after_reset_survives_undo_redo_cycle(main):
    file_path = "/tmp/reset_m1.png"
    stack = _add_open_page(main, file_path)
    _build_synthetic_page(main, file_path, stack)

    _reset_now(main, file_path, stack)
    assert main.blk_list == []

    rect_item = main.image_viewer.add_rectangle(QRectF(0, 0, 20, 20), QPointF(30, 30), 0)
    main.rect_item_ctrl.handle_rectangle_creation(rect_item)
    assert len(main.blk_list) == 1

    stack.undo()  # annule AddRectangleCommand
    stack.undo()  # annule ResetPageCommand
    assert len(main.blk_list) == 1  # page restaurée (bloc de synthèse)

    stack.redo()  # refait ResetPageCommand
    assert main.blk_list == []
    stack.redo()  # refait AddRectangleCommand
    assert len(main.blk_list) == 1
    assert main.blk_list[0].xyxy is not None


# =================================================================================================
# M3 : page rendue -> aucun rectangle fantôme après reset
# =================================================================================================


def test_m3_no_ghost_rectangles_after_reset_of_rendered_page(main):
    file_path = "/tmp/reset_m3.png"
    stack = _add_open_page(main, file_path)
    _build_synthetic_page(main, file_path, stack)

    _reset_now(main, file_path, stack)

    assert main.image_viewer.rectangles == []
    assert [item for item in main.image_viewer._scene.items() if hasattr(item, "rect")] == []


# =================================================================================================
# Page déjà vierge : rien poussé
# =================================================================================================


def test_pristine_page_pushes_nothing(main):
    file_path = "/tmp/reset_pristine.png"
    stack = _add_open_page(main, file_path)
    count_before = stack.count()

    reset_ui_module.request_reset(main)

    assert stack.count() == count_before


def test_pristine_check_reads_live_state_not_image_states(main):
    """Critic MIN4 : la vérification « déjà vierge » lit l'état vivant, jamais `image_states`
    (qui ne serait à jour qu'après une navigation)."""
    file_path = "/tmp/reset_pristine_live.png"
    stack = _add_open_page(main, file_path)
    _add_block(main)  # vivant non vide, `image_states` pas encore resynchronisé
    count_before = stack.count()

    reset_ui_module.request_reset(main)

    assert stack.count() == count_before + 1


# =================================================================================================
# Édition en attente abandonnée
# =================================================================================================


def test_pending_text_edit_is_discarded_not_committed(main):
    file_path = "/tmp/reset_pending_edit.png"
    stack = _add_open_page(main, file_path)
    blk = _add_block(main)
    item = _add_rendered_text_item(main, blk)
    main.image_ctrl.save_image_state(file_path)

    main.text_ctrl.on_text_item_selected(item)
    main.text_ctrl._schedule_text_change_command(item, "Nouveau texte", blk)
    assert main.text_ctrl._pending_text_command is not None
    count_before = stack.count()

    _reset_now(main, file_path, stack)

    assert main.text_ctrl._pending_text_command is None
    assert not main.text_ctrl._text_change_timer.isActive()
    # Aucun `TextEditCommand` inutile poussé pour l'édition abandonnée : seule la commande de
    # réinitialisation elle-même a été ajoutée.
    assert stack.count() == count_before + 1


# =================================================================================================
# Macro orpheline : confirmation
# =================================================================================================


def test_orphan_macro_cancel_pushes_nothing(main, monkeypatch):
    file_path = "/tmp/reset_orphan_cancel.png"
    stack = _add_open_page(main, file_path)
    _add_block(main)
    stack.beginMacro("interrupted")
    monkeypatch.setattr(reset_ui_module, "_confirm_orphan_macro", lambda main: False)

    count_before = stack.count()
    reset_ui_module.request_reset(main)

    assert stack.count() == count_before
    assert main.blk_list != []


def test_orphan_macro_accept_resets_and_marks_dirty(main, monkeypatch):
    file_path = "/tmp/reset_orphan_accept.png"
    stack = _add_open_page(main, file_path)
    _add_block(main)
    stack.beginMacro("interrupted")
    monkeypatch.setattr(reset_ui_module, "_confirm_orphan_macro", lambda main: True)
    main._manual_dirty = False

    reset_ui_module.request_reset(main)

    assert main.blk_list == []
    assert main.has_unsaved_changes()
    assert stack.canUndo() is False  # annoncé par la confirmation : non annulable


def test_revalidation_after_modal_aborts_if_page_changed(main, monkeypatch):
    file_path = "/tmp/reset_orphan_revalidate.png"
    other_path = "/tmp/reset_orphan_other.png"
    stack = _add_open_page(main, file_path)
    _add_second_page(main, other_path)
    _add_block(main)
    stack.beginMacro("interrupted")

    def _simulate_navigation_during_modal(main):
        main.curr_img_idx = main.image_files.index(other_path)
        return True

    monkeypatch.setattr(reset_ui_module, "_confirm_orphan_macro", _simulate_navigation_during_modal)
    count_before = stack.count()

    reset_ui_module.request_reset(main)

    assert stack.count() == count_before
    main.curr_img_idx = main.image_files.index(file_path)  # restaure pour la suite du test


# =================================================================================================
# Pile orpheline
# =================================================================================================


def test_orphaned_stack_undo_does_not_mutate_after_page_removed(main):
    file_path = "/tmp/reset_orphan_stack.png"
    stack = _add_open_page(main, file_path)
    _build_synthetic_page(main, file_path, stack)
    _reset_now(main, file_path, stack)

    # La page est retirée du projet : sa pile devient orpheline (plus dans `undo_stacks`).
    main.undo_stacks.pop(file_path)
    main.image_files = []
    main.curr_img_idx = -1

    blk_list_before = list(main.blk_list)
    stack.undo()  # ne doit rien muter (garde de pile KO)
    assert main.blk_list == blk_list_before


# =================================================================================================
# Injection de faute
# =================================================================================================


def test_redo_failure_rolls_back_to_before_state(main, monkeypatch):
    file_path = "/tmp/reset_fault_redo.png"
    stack = _add_open_page(main, file_path)
    _build_synthetic_page(main, file_path, stack)
    blk_list_before = list(main.blk_list)
    patches_before = list(main.image_patches.get(file_path, []))

    original_load_image_state = main.image_ctrl.load_image_state
    calls = {"n": 0}

    def _boom(path):
        calls["n"] += 1
        raise RuntimeError("échec simulé de load_image_state")

    monkeypatch.setattr(main.image_ctrl, "load_image_state", _boom)
    count_before = stack.count()
    # Ne jamais relire `command` après `push` (critic MIN7) : une commande dont le premier `redo`
    # échoue s'auto-déclare obsolète, et `QUndoStack` détruit alors son objet C++ aussitôt.
    stack.push(reset_commands.ResetPageCommand(main, file_path, stack))

    assert calls["n"] >= 1
    assert stack.count() == count_before  # jamais ajoutée à la pile (obsolète au premier redo)
    assert main.blk_list == blk_list_before
    assert main.image_patches.get(file_path, []) == patches_before

    monkeypatch.setattr(main.image_ctrl, "load_image_state", original_load_image_state)


def test_undo_failure_keeps_page_reset(main, monkeypatch):
    file_path = "/tmp/reset_fault_undo.png"
    stack = _add_open_page(main, file_path)
    _build_synthetic_page(main, file_path, stack)
    _reset_now(main, file_path, stack)
    assert main.blk_list == []

    def _boom(path):
        raise RuntimeError("échec simulé de load_image_state pendant undo")

    monkeypatch.setattr(main.image_ctrl, "load_image_state", _boom)
    stack.undo()

    # L'échec est journalisé, la page reste dans son état réinitialisé (pas de retour arrière
    # partiel dangereux) — comportement documenté (commands.py::undo, branche `except`).
    assert main.blk_list == []


# =================================================================================================
# Caches
# =================================================================================================


def test_caches_cleared_for_this_page_only(main):
    file_path = "/tmp/reset_cache_a.png"
    other_path = "/tmp/reset_cache_b.png"
    stack = _add_open_page(main, file_path)
    _add_second_page(main, other_path, image=_synthetic_image(fill=200))
    _add_block(main)

    cache_manager = main.pipeline.cache_manager
    hash_a = cache_manager._generate_image_hash(main.image_data[file_path])
    hash_b = cache_manager._generate_image_hash(main.image_data[other_path])
    cache_manager.ocr_cache[(hash_a, "model", "en", "cpu")] = {"0_0_1_1_0": "x"}
    cache_manager.ocr_cache[(hash_b, "model", "en", "cpu")] = {"0_0_1_1_0": "y"}
    cache_manager.translation_cache[(hash_a, "tr", "en", "fr", "no_context")] = {
        "0_0_1_1_0": {"source_text": "a", "translation": "b"}
    }

    _reset_now(main, file_path, stack)

    remaining_ocr_hashes = {key[0] for key in cache_manager.ocr_cache}
    assert hash_a not in remaining_ocr_hashes
    assert hash_b in remaining_ocr_hashes
    assert not cache_manager.translation_cache


def test_cache_key_hash_matches_image_without_patches(main):
    """Égalité exigée par la conception : `_generate_image_hash(image_data[p])` doit être le même
    hash que celui utilisé par le pipeline pour peupler le cache (image sans patchs — ADR-016)."""
    file_path = "/tmp/reset_cache_hash.png"
    _add_open_page(main, file_path)
    cache_manager = main.pipeline.cache_manager
    hash_from_data = cache_manager._generate_image_hash(main.image_data[file_path])
    hash_from_viewer = cache_manager._generate_image_hash(
        main.image_viewer.get_image_array(include_patches=False)
    )
    assert hash_from_data == hash_from_viewer


# =================================================================================================
# Recherche rafraîchie
# =================================================================================================


def test_search_refreshed_on_redo_and_undo(main, monkeypatch):
    file_path = "/tmp/reset_search.png"
    stack = _add_open_page(main, file_path)
    _add_block(main)
    main.search_panel.find_input.setText("Hello")

    calls = []
    monkeypatch.setattr(main.search_ctrl, "on_undo_redo", lambda *a: calls.append("call"))

    _reset_now(main, file_path, stack)
    QtWidgets.QApplication.processEvents()
    assert calls == ["call"]

    stack.undo()
    QtWidgets.QApplication.processEvents()
    assert calls == ["call", "call"]


# =================================================================================================
# Focus
# =================================================================================================


def test_focus_returned_to_viewer_from_t_text_edit(main):
    file_path = "/tmp/reset_focus_t.png"
    _add_open_page(main, file_path)
    _add_block(main)
    main.t_text_edit.setFocus()
    QtWidgets.QApplication.processEvents()

    reset_ui_module.request_reset(main)

    assert main.image_viewer.hasFocus() or not main.t_text_edit.hasFocus()


def test_focus_rule_moves_focus_away_from_editable_combo():
    combo = QtWidgets.QComboBox()
    combo.setEditable(True)
    assert reset_ui_module._steals_focus(combo) is True


def test_focus_rule_ignores_non_editable_combo():
    combo = QtWidgets.QComboBox()
    combo.setEditable(False)
    assert reset_ui_module._steals_focus(combo) is False


def test_focus_rule_catches_descendant_of_stealing_type():
    spin = QtWidgets.QDoubleSpinBox()
    child = QtWidgets.QWidget(spin)
    assert reset_ui_module._steals_focus(child) is True


# =================================================================================================
# Autres pages intactes
# =================================================================================================


def test_other_pages_untouched_by_reset(main):
    file_path = "/tmp/reset_other_a.png"
    other_path = "/tmp/reset_other_b.png"
    stack = _add_open_page(main, file_path)
    _add_second_page(main, other_path)
    other_blk_list_before = list(main.image_states[other_path]["blk_list"])
    _add_block(main)

    _reset_now(main, file_path, stack)

    assert main.image_states[other_path]["blk_list"] == other_blk_list_before


# =================================================================================================
# Limite MAJ1 (connue, figée ici — corrigée dans une sous-étape séparée)
# =================================================================================================


def test_maj1_undo_past_an_undone_reset_targets_recreated_item(main, qtbot):
    """Fige le comportement actuel (non corrigé, `CLAUDE.md` §MAJ1) : `TextEditCommand.undo`
    (antérieur au reset) vise l'item de texte que le reset a détruit. Après
    Reset -> Annuler (reset, item RECRÉÉ par `load_state`) -> Annuler (au-delà), l'observé sur
    cette machine n'est pas seulement « le bloc change mais pas le texte affiché » : c'est un
    plantage de l'objet Qt détruit (`self.text_item` de `TextEditCommand`), capturé ici plutôt que
    prescrit — corrigé dans une sous-étape séparée (non demandée ici)."""
    file_path = "/tmp/reset_maj1.png"
    stack = _add_open_page(main, file_path)
    blk = _add_block(main, text="Hello", translation="Bonjour")
    item = _add_rendered_text_item(main, blk)
    main.image_ctrl.save_image_state(file_path)

    main.text_ctrl.on_text_item_selected(item)
    main.text_ctrl._schedule_text_change_command(item, "Salut", blk)
    main.text_ctrl._commit_pending_text_command()
    assert blk.translation == "Salut"

    _reset_now(main, file_path, stack)
    assert main.blk_list == []

    stack.undo()  # annule le reset : bloc restauré, item RECRÉÉ (nouvel objet Qt)
    assert len(main.blk_list) == 1
    assert main.blk_list[0] is blk

    # Aller au-delà : annule le `TextEditCommand` antérieur au reset, dont `self.text_item` vise
    # l'ancien objet Qt détruit par le reset (`app/ui/commands/text_edit.py:23`,
    # `app/controllers/text.py:477-479`). Capturé ici (précédent : `qtbot.capture_exceptions`,
    # documentation pytest-qt) plutôt que laissé faire échouer le test par la remontée globale de
    # pytest-qt — la limite MAJ1 est un défaut connu, pas une régression de ce lot.
    with qtbot.capture_exceptions() as exceptions:
        stack.undo()

    assert len(exceptions) == 1
    exc_type, exc_value, _tb = exceptions[0]
    assert exc_type is RuntimeError
    assert "already deleted" in str(exc_value)


# =================================================================================================
# Navigation pendant reset/undo
# =================================================================================================


def test_navigation_away_before_redo_prevents_mutation_on_first_attempt(main):
    file_path = "/tmp/reset_nav_first.png"
    other_path = "/tmp/reset_nav_other.png"
    stack = _add_open_page(main, file_path)
    _add_second_page(main, other_path)
    _add_block(main)

    count_before = stack.count()
    main.curr_img_idx = main.image_files.index(other_path)  # navigue avant le premier redo

    # Ne jamais relire la commande après `push` (critic MIN7, voir aussi test de la garde de
    # redo en échec) : la garde de page échoue au premier `redo`, la commande s'obsolète.
    stack.push(reset_commands.ResetPageCommand(main, file_path, stack))

    assert stack.count() == count_before
    main.curr_img_idx = main.image_files.index(file_path)
    assert len(main.blk_list) == 1


# =================================================================================================
# Aller-retour `.ctpr` réel (indépendant du lot livré) : `save_state_to_proj_file_v2` /
# `load_state_from_proj_file_v2`, mêmes fonctions que le vrai menu Fichier > Enregistrer/Ouvrir
# (précédent : `tests/test_history_restore.py::test_scenario_h_offscreen`, qui exige une page de
# banc non versionnée — ici une image synthétique écrite sur disque, puisque
# `save_state_to_proj_file_v2` hache les octets du fichier `image_files`, pas `image_data`).
# =================================================================================================


def _add_open_page_on_disk(main, file_path: str, image=None) -> QtGui.QUndoStack:
    """Comme `_add_open_page`, mais écrit aussi `image` sur disque à `file_path` : requis par
    `save_state_to_proj_file_v2` (`add_blob_if_needed` lit les octets du fichier, jamais
    `image_data`)."""
    image = image if image is not None else _synthetic_image()
    imk.write_image(file_path, image)
    return _add_open_page(main, file_path, image=image)


def _add_second_page_on_disk(main, file_path: str, image=None) -> QtGui.QUndoStack:
    image = image if image is not None else _synthetic_image(fill=60)
    imk.write_image(file_path, image)
    return _add_second_page(main, file_path, image=image)


def test_ctpr_roundtrip_reset_page_blank_other_page_intact(main, qtbot, tmp_path):
    from controller import ComicTranslate

    file_a = str(tmp_path / "page_a.png")
    file_b = str(tmp_path / "page_b.png")
    stack = _add_open_page_on_disk(main, file_a)
    _add_second_page_on_disk(main, file_b)

    _build_synthetic_page(main, file_a, stack)
    main.image_states[file_a]["skip"] = True
    main.image_states[file_a]["export_group_name"] = "mon_album"

    # Page B « traitée » (un bloc avec traduction), jamais affichée -> vit uniquement dans
    # `image_states`, comme une page déjà quittée par navigation.
    blk_b = TextBlock(text_bbox=np.array([5, 5, 40, 20]), text="Hi", translation="Salut")
    versions.set_text(blk_b, "translation", "Salut", versions.ORIGIN_TRANSLATION, {"model": "X"})
    main.image_states[file_b]["blk_list"] = [blk_b]
    main.image_states[file_b]["source_lang"] = "English"
    main.image_states[file_b]["target_lang"] = "French"

    _reset_now(main, file_a, stack)
    assert main.blk_list == []

    ctpr_path = str(tmp_path / "roundtrip_reset.ctpr")
    save_state_to_proj_file_v2(main, ctpr_path)  # aucune exception

    reloaded = ComicTranslate()
    qtbot.addWidget(reloaded)
    _neutralize_side_effects(reloaded)

    load_state_from_proj_file_v2(reloaded, ctpr_path)  # aucune exception

    # `load_state_from_proj_file_v2` matérialise chaque image dans un nouveau chemin temporaire
    # (précédent : `tests/test_history_restore.py::test_scenario_h_offscreen`) — l'ordre de
    # `image_files` est préservé, c'est la clé de correspondance stable, jamais le chemin d'origine.
    assert len(reloaded.image_files) == 2
    reloaded_a = reloaded.image_files[0]
    reloaded_b = reloaded.image_files[1]

    state_a = reloaded.image_states[reloaded_a]
    assert state_a["blk_list"] == []
    assert state_a["viewer_state"]["rectangles"] == []
    assert state_a["viewer_state"]["text_items_state"] == []
    assert state_a["skip"] is True
    assert state_a["export_group_name"] == "mon_album"

    state_b = reloaded.image_states[reloaded_b]
    assert len(state_b["blk_list"]) == 1
    assert state_b["blk_list"][0].translation == "Salut"
    assert state_b["source_lang"] == "English"
    assert state_b["target_lang"] == "French"


def test_ctpr_roundtrip_after_reset_then_undo_restores_content(main, qtbot, tmp_path):
    """Réinitialiser puis annuler avant de sauvegarder : le `.ctpr` doit porter le contenu
    restauré, pas l'état vierge intermédiaire."""
    from controller import ComicTranslate

    file_a = str(tmp_path / "page_undo.png")
    stack = _add_open_page_on_disk(main, file_a)
    _build_synthetic_page(main, file_a, stack)
    blk_count_before = len(main.blk_list)
    assert blk_count_before == 1

    _reset_now(main, file_a, stack)
    assert main.blk_list == []
    stack.undo()
    assert len(main.blk_list) == 1
    main.image_ctrl.save_image_state(file_a)

    ctpr_path = str(tmp_path / "roundtrip_undo.ctpr")
    save_state_to_proj_file_v2(main, ctpr_path)

    reloaded = ComicTranslate()
    qtbot.addWidget(reloaded)
    _neutralize_side_effects(reloaded)
    load_state_from_proj_file_v2(reloaded, ctpr_path)

    assert len(reloaded.image_files) == 1
    reloaded_state = reloaded.image_states[reloaded.image_files[0]]
    assert len(reloaded_state["blk_list"]) == 1
    assert reloaded_state["viewer_state"]["rectangles"] != []


# =================================================================================================
# Chaîne réaliste : Détecter -> Reconnaître/Traduire (factices) -> Rendre -> réinitialiser ->
# annuler au-delà (pas de plantage natif, pile cohérente) — sans toucher au texte via une commande
# Qt avant le reset (la limite MAJ1 figée plus haut concerne spécifiquement `TextEditCommand`,
# pas `AddRectangleCommand`).
# =================================================================================================


class _FakeOCREngine:
    def __init__(self, texts):
        self._texts = texts

    def process_image(self, img, blk_list):
        for blk, text in zip(blk_list, self._texts):
            blk.text = text
        return blk_list


class _FakeTranslationEngine:
    def __init__(self, translations):
        self._translations = translations

    def translate(self, blk_list):
        for blk, translation in zip(blk_list, self._translations):
            blk.translation = translation
        return blk_list


def test_realistic_chain_undo_past_reset_no_crash_stack_stays_coherent(main, monkeypatch):
    file_path = "/tmp/reset_chain.png"
    stack = _add_open_page(main, file_path)

    # Détecter : une boîte posée à la main (précédent : `tests/test_history_restore.py`).
    rect_item = main.image_viewer.add_rectangle(QRectF(0, 0, 60, 40), QPointF(20, 20), 0)
    main.rect_item_ctrl.handle_rectangle_creation(rect_item)
    assert len(main.blk_list) == 1
    count_after_detect = stack.count()

    # Reconnaître / Traduire (factices, précédent : `tests/test_history_restore.py`).
    monkeypatch.setattr(
        ocr_processor_module.OCRFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeOCREngine(["Hello"])),
    )
    main.pipeline.ocr_handler.OCR_image(single_block=False)
    assert main.blk_list[0].text == "Hello"

    monkeypatch.setattr(
        translation_processor_module.TranslationFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeTranslationEngine(["Bonjour"])),
    )
    main.pipeline.translation_handler.translate_image(single_block=False)
    # Casse appliquée par `modules.utils.translator_utils` (réglage global « MAJUSCULES »,
    # sans rapport avec le reset) : comparaison insensible à la casse.
    assert main.blk_list[0].translation.casefold() == "bonjour"
    translated_value = main.blk_list[0].translation

    # Rendre (item de texte posé directement, pas de commande Qt engagée dessus).
    _add_rendered_text_item(main, main.blk_list[0])
    main.image_ctrl.save_image_state(file_path)

    _reset_now(main, file_path, stack)
    assert main.blk_list == []
    index_after_reset = stack.index()
    assert stack.canRedo() is False
    assert stack.canUndo() is True

    # Annuler le reset : page restaurée.
    stack.undo()
    assert len(main.blk_list) == 1
    assert main.blk_list[0].translation == translated_value
    assert stack.index() == index_after_reset - 1
    assert stack.canRedo() is True

    # Annuler au-delà : annule `AddRectangleCommand` (posé avant le reset), jamais de
    # `TextEditCommand` ici (contrairement à la limite MAJ1) -> pas de plantage natif attendu.
    stack.undo()
    assert stack.index() == count_after_detect - 1
    assert main.blk_list == []
    assert stack.canUndo() is False

    # Refaire jusqu'au bout : cohérence miroir (redo AddRectangleCommand, puis redo le reset).
    stack.redo()
    assert len(main.blk_list) == 1
    stack.redo()
    assert main.blk_list == []  # reset refait
    assert stack.canRedo() is False


# =================================================================================================
# Disponibilité : écran des Réglages (reproduction réelle, pas seulement les fakes de test_reset.py)
# =================================================================================================


def test_button_disabled_on_settings_screen(main):
    _add_open_page(main, "/tmp/reset_settings.png")
    main._page_reset_watcher.refresh()
    assert main.page_reset_button.isEnabled() is True

    main.show_settings_page()
    QtWidgets.QApplication.processEvents()
    main._page_reset_watcher.refresh()
    assert main.page_reset_button.isEnabled() is False

    main.show_main_page()
    main.central_stack.setCurrentWidget(main.image_viewer)
    QtWidgets.QApplication.processEvents()
    main._page_reset_watcher.refresh()
    assert main.page_reset_button.isEnabled() is True


def test_button_disabled_on_empty_screen_before_any_page(main):
    main.show()
    QtWidgets.QApplication.processEvents()
    main._page_reset_watcher.refresh()
    assert main.page_reset_button.isEnabled() is False


# =================================================================================================
# Non-régression : pastilles (ADR-014) retombent à zéro puis reviennent après annulation
# =================================================================================================


def test_pagestate_badges_drop_to_zero_after_reset_and_return_after_undo(main):
    file_path = "/tmp/reset_badges.png"
    stack = _add_open_page(main, file_path)
    _build_synthetic_page(main, file_path, stack)

    before = page_progress(main, file_path)
    assert before.n_blocks > 0
    assert before.n_text > 0
    assert before.n_translated > 0
    assert before.n_patches > 0
    assert before.n_rendered > 0

    _reset_now(main, file_path, stack)

    after_reset = page_progress(main, file_path)
    assert after_reset == (0, 0, 0, 0, 0) or (
        after_reset.n_blocks == 0
        and after_reset.n_text == 0
        and after_reset.n_translated == 0
        and after_reset.n_patches == 0
        and after_reset.n_rendered == 0
    )

    stack.undo()

    after_undo = page_progress(main, file_path)
    assert after_undo.n_blocks == before.n_blocks
    assert after_undo.n_text == before.n_text
    assert after_undo.n_translated == before.n_translated
    assert after_undo.n_patches == before.n_patches
    assert after_undo.n_rendered == before.n_rendered


# =================================================================================================
# Non-régression : « Détecter » après reset relit l'image d'origine (ADR-016), jamais l'image
# patchée par un ancien nettoyage déjà invalidé par le reset.
# =================================================================================================


def test_detect_image_source_after_reset_excludes_old_patches(main):
    file_path = "/tmp/reset_detect_source.png"
    stack = _add_open_page(main, file_path)
    _add_patch(main, file_path, stack, bbox=(0, 0, 20, 20))
    main.image_ctrl.save_image_state(file_path)
    assert len(main.image_patches.get(file_path, [])) == 1

    _reset_now(main, file_path, stack)

    assert main.image_patches.get(file_path) == []
    # La source que « Détecter » utiliserait (image composée sans patch) redevient l'image brute.
    composed = main.image_viewer.get_image_array(include_patches=True)
    raw = main.image_data[file_path]
    assert np.array_equal(composed, raw)
