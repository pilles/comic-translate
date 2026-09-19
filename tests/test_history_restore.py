"""GUI (spec 03, jalon A) : bouton « Historique du bloc », menu, et
`RestoreVersionCommand` (undo/redo), plus la reproduction hors écran du
scénario manuel H de la conception (voir scratchpad
`conception-spec03-jalonA-v2.md` §H) et un contrôle du défaut connu Me
(aliasing de `versions` après `AddRectangleCommand.undo`/`redo`).

Simplifications assumées pour la reproduction du scénario H (documentées en
commentaire à chaque étape) : la « détection » pose une bbox à la main (la
détection ML elle-même n'est pas instrumentée par le jalon A) ; OCR et
traduction sont servis par de faux moteurs injectés à la fabrique, comme
dans `tests/test_block_versions_integration.py` — seul le câblage
historique est en jeu, pas la qualité des modèles.

`--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`) : construit une
vraie `ComicTranslate` (fenêtre complète), pas seulement `ComicTranslateUI`.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import QPointF, QRectF

import modules.ocr.processor as ocr_processor_module
import modules.translation.processor as translation_processor_module
from app.projects.project_state_v2 import load_state_from_proj_file_v2, save_state_to_proj_file_v2
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.commands.box import AddRectangleCommand
from modules.history import commands, ui, versions
from modules.utils.textblock import TextBlock

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE_PATH = REPO_ROOT / "bench" / "pages" / "funhome_012.jpg"


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


@pytest.fixture
def main(qtbot):
    from controller import ComicTranslate

    instance = ComicTranslate()
    qtbot.addWidget(instance)
    instance._skip_close_prompt = True
    yield instance
    # `qtbot` ferme (et détruit) le widget automatiquement en fin de test ;
    # un second appel à `.close()` ici lèverait (temp_dir déjà supprimé).


def _add_open_page(main, file_path: str) -> QtGui.QUndoStack:
    """Reproduit le minimum de `ImageStateController.thread_load_images` pour
    obtenir une pile d'annulation active (`push_command` sans pile active ne
    fait rien) sans passer par le chargeur de fichiers complet."""
    main.image_files = [file_path]
    main.curr_img_idx = 0
    stack = QtGui.QUndoStack(main)
    main.undo_stacks[file_path] = stack
    main.undo_group.addStack(stack)
    main.undo_group.setActiveStack(stack)
    return stack


# --- Bouton et menu -----------------------------------------------------


def test_block_history_button_present_and_always_enabled(main):
    button = main.block_history_button
    assert isinstance(button, QtWidgets.QToolButton)
    assert button.isEnabled()
    assert "Historique" in button.toolTip()


def test_menu_shows_disabled_placeholder_when_no_block_selected(main):
    main.curr_tblock = None

    menu = ui.build_history_menu(main, main.block_history_button)

    actions = menu.actions()
    assert len(actions) == 1
    assert actions[0].text() == "Aucun bloc sélectionné"
    assert not actions[0].isEnabled()


def test_menu_shows_disabled_placeholder_when_block_has_no_history(main):
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
    assert versions.versions_of(blk) == []
    main.curr_tblock = blk

    menu = ui.build_history_menu(main, main.block_history_button)

    actions = menu.actions()
    assert len(actions) == 1
    assert actions[0].text() == "Aucun historique pour ce bloc"
    assert not actions[0].isEnabled()


def test_menu_lists_entries_recent_first_with_separator_and_current_checked(main):
    blk = TextBlock(text_bbox=np.array([0, 0, 10, 10]))
    versions.set_text(blk, "translation", "Salut", versions.ORIGIN_TRANSLATION, {"model": "Custom"})
    versions.set_text(blk, "translation", "Coucou", versions.ORIGIN_MANUAL)
    versions.set_text(blk, "text", "Hi", versions.ORIGIN_OCR, {"ocr": "Default"})
    main.curr_tblock = blk

    menu = ui.build_history_menu(main, main.block_history_button)

    actions = menu.actions()
    non_separator = [a for a in actions if not a.isSeparator()]
    assert len(non_separator) == 3
    assert any(a.isSeparator() for a in actions)

    # Traduction : la plus récente ("Coucou") en tête, cochée/désactivée.
    assert "Coucou" in non_separator[0].text()
    assert non_separator[0].isChecked() and not non_separator[0].isEnabled()
    assert "Salut" in non_separator[1].text()
    assert not non_separator[1].isChecked() and non_separator[1].isEnabled()

    # Source : une seule entrée, courante, cochée/désactivée.
    assert "Hi" in non_separator[2].text()
    assert non_separator[2].isChecked() and not non_separator[2].isEnabled()


# --- RestoreVersionCommand -----------------------------------------------


def test_restore_translation_with_matched_item_redo_undo_redo(main):
    _add_open_page(main, "fake_page.png")
    blk = TextBlock(text_bbox=np.array([10, 20, 110, 60]), angle=0)
    versions.set_text(
        blk, "translation", "Bonjour", versions.ORIGIN_TRANSLATION, {"model": "Custom"}
    )
    versions.set_text(blk, "translation", "Salut", versions.ORIGIN_TRANSLATION, {"model": "Custom"})
    main.blk_list = [blk]

    item = main.image_viewer.add_text_item(
        TextItemProperties(
            text="Salut", position=(10, 20), rotation=0, text_color=QtGui.QColor("black")
        )
    )

    older_entry = versions.versions_of(blk, "translation")[0]  # "Bonjour"
    command = commands.RestoreVersionCommand(main, blk, older_entry)
    main.push_command(command)

    assert blk.translation == "Bonjour"
    assert item.toPlainText() == "Bonjour"
    entries = versions.versions_of(blk, "translation")
    assert entries[-1]["origin"] == versions.ORIGIN_RESTORE
    assert entries[-1]["value"] == "Bonjour"
    len_after_redo = len(entries)

    main.undo_group.activeStack().undo()
    assert blk.translation == "Salut"
    assert item.toPlainText() == "Salut"
    assert len(versions.versions_of(blk, "translation")) == len_after_redo - 1

    main.undo_group.activeStack().redo()
    assert blk.translation == "Bonjour"
    assert item.toPlainText() == "Bonjour"
    # Un deuxième redo ne doit pas ajouter une deuxième entrée "restore".
    assert len(versions.versions_of(blk, "translation")) == len_after_redo


def test_restore_translation_without_matched_item_updates_widget_under_block_signals(main):
    _add_open_page(main, "fake_page.png")
    blk = TextBlock(text_bbox=np.array([10, 20, 110, 60]), angle=0)
    versions.set_text(
        blk, "translation", "Bonjour", versions.ORIGIN_TRANSLATION, {"model": "Custom"}
    )
    versions.set_text(blk, "translation", "Salut", versions.ORIGIN_TRANSLATION, {"model": "Custom"})
    main.blk_list = [blk]
    main.curr_tblock = blk
    main.t_text_edit.setPlainText("Salut")

    older_entry = versions.versions_of(blk, "translation")[0]
    command = commands.RestoreVersionCommand(main, blk, older_entry)
    main.push_command(command)

    assert blk.translation == "Bonjour"
    assert main.t_text_edit.toPlainText() == "Bonjour"


def test_restore_text_field_does_not_touch_translation(main):
    _add_open_page(main, "fake_page.png")
    blk = TextBlock(text_bbox=np.array([10, 20, 110, 60]), angle=0)
    versions.set_text(blk, "text", "Hello", versions.ORIGIN_OCR, {"ocr": "Default"})
    versions.set_text(blk, "text", "Hi", versions.ORIGIN_OCR, {"ocr": "Default"})
    versions.set_text(blk, "translation", "Salut", versions.ORIGIN_TRANSLATION, {"model": "Custom"})
    main.blk_list = [blk]
    main.curr_tblock = blk
    main.s_text_edit.setPlainText("Hi")
    main.t_text_edit.setPlainText("Salut")

    older_entry = versions.versions_of(blk, "text")[0]  # "Hello"
    command = commands.RestoreVersionCommand(main, blk, older_entry)
    main.push_command(command)

    assert blk.text == "Hello"
    assert main.s_text_edit.toPlainText() == "Hello"
    # `translation` inchangée : ni la valeur, ni le journal, ni le widget.
    assert blk.translation == "Salut"
    assert main.t_text_edit.toPlainText() == "Salut"
    assert [e["value"] for e in versions.versions_of(blk, "translation")] == ["Salut"]


# --- Me : aliasing connu après AddRectangleCommand.undo/redo --------------


def test_add_rectangle_command_redo_after_undo_does_not_duplicate_block(main):
    _add_open_page(main, "fake_page.png")
    rect_item = main.image_viewer.add_rectangle(QRectF(0, 0, 50, 50), QPointF(10, 10))
    blk = TextBlock(text_bbox=np.array([10, 10, 60, 60]))
    versions.set_text(blk, "text", "abc", versions.ORIGIN_OCR, {"ocr": "Default"})
    blk_list: list[TextBlock] = []

    command = AddRectangleCommand(main, rect_item, blk, blk_list)
    main.push_command(command)
    assert len(blk_list) == 1

    main.undo_group.activeStack().undo()
    assert len(blk_list) == 0

    main.undo_group.activeStack().redo()
    assert len(blk_list) == 1  # pas de doublon (Me)


# --- Scénario H (hors écran) ----------------------------------------------


@pytest.mark.skipif(not PAGE_PATH.exists(), reason="page de banc absente (non versionnée)")
def test_scenario_h_offscreen(main, monkeypatch, tmp_path, qtbot):
    import imkit as imk
    from controller import ComicTranslate

    img = imk.read_image(str(PAGE_PATH))
    main.image_viewer.display_image_array(img, fit=False)
    assert main.image_viewer.hasPhoto()

    file_path = str(PAGE_PATH)
    _add_open_page(main, file_path)

    # « Détecter » simulé : une bulle posée à la main (la détection ML n'est
    # pas instrumentée par le jalon A, hors périmètre).
    blk = TextBlock(text_bbox=np.array([100, 100, 300, 160]))
    main.blk_list = [blk]
    main.image_viewer.add_rectangle(QRectF(0, 0, 200, 60), QPointF(100, 100))

    # « Reconnaître » (OCR, faux moteur).
    monkeypatch.setattr(
        ocr_processor_module.OCRFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeOCREngine(["MY FATHER COULD"])),
    )
    main.pipeline.ocr_handler.OCR_image(single_block=False)
    assert blk.text == "MY FATHER COULD"

    # « Traduire ».
    monkeypatch.setattr(
        translation_processor_module.TranslationFactory,
        "create_engine",
        classmethod(lambda cls, *a, **k: _FakeTranslationEngine(["MON PERE POUVAIT"])),
    )
    main.pipeline.translation_handler.translate_image(single_block=False)
    assert blk.translation == "MON PERE POUVAIT"

    # Correction manuelle (frappe directe, hors `set_text`).
    blk.translation = "MON PÈRE POUVAIT"

    # `save_current_image_state()` -> flush_pending -> pré-état manual.
    main.image_ctrl.save_current_image_state()

    translation_entries = versions.versions_of(blk, "translation")
    text_entries = versions.versions_of(blk, "text")
    assert [e["value"] for e in translation_entries] == ["MON PERE POUVAIT", "MON PÈRE POUVAIT"]
    assert [e["value"] for e in text_entries] == ["MY FATHER COULD"]
    assert len(translation_entries) + len(text_entries) == 3

    # « Vider » puis « Traduire » le bloc seul (chemin bloc unique, sert le
    # cache rempli par le passage page entière ci-dessus).
    blk.translation = ""
    monkeypatch.setattr(main.pipeline, "get_selected_block", lambda: blk)
    main.pipeline.translation_handler.translate_image(single_block=True)

    translation_entries = versions.versions_of(blk, "translation")
    assert len(translation_entries) + len(text_entries) == 4
    assert translation_entries[-1]["origin"] == versions.ORIGIN_CACHE

    # Restaurer la correction manuelle.
    manual_entry = next(e for e in translation_entries if e["origin"] == versions.ORIGIN_MANUAL)
    restore_command = commands.RestoreVersionCommand(main, blk, manual_entry)
    main.push_command(restore_command)
    assert blk.translation == "MON PÈRE POUVAIT"

    # Sauvegarde, dans le scratchpad, sous un nouveau projet.
    main.image_ctrl.save_current_image_state()
    ctpr_path = str(tmp_path / "scenario_h.ctpr")
    save_state_to_proj_file_v2(main, ctpr_path)

    reloaded = ComicTranslate()
    qtbot.addWidget(reloaded)
    reloaded._skip_close_prompt = True

    load_state_from_proj_file_v2(reloaded, ctpr_path)
    reloaded_state = reloaded.image_states.get(file_path) or next(
        iter(reloaded.image_states.values())
    )
    reloaded_blk = reloaded_state["blk_list"][0]
    reloaded_entries = versions.versions_of(reloaded_blk, "translation")
    print(
        "Scénario H — journal après rechargement (.ctpr) :",
        [(e["origin"], e["value"]) for e in reloaded_entries],
    )
    assert any(e["origin"] == versions.ORIGIN_RESTORE for e in reloaded_entries)
    assert reloaded_blk.translation == "MON PÈRE POUVAIT"
