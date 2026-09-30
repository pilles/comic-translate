"""GUI (spec 04, jalon 3, sous-étape 3a-ter, ADR-022) : annulations de texte robustes aux items
recréés (`modules/text_undo/`, `TextEditCommand`, `TextFormatCommand`, `RestoreVersionCommand`),
validation de l'édition en attente au changement de page (D1) et avant Annuler/Rétablir (M1 bis).
`--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`).

Précédents : `tests/test_reset_ui.py` (fixture `main` sans effet de bord, `main.show()` requis,
`_add_open_page`/`_add_second_page`/`_add_block`), `tests/test_undo_guard_ui.py` (neutralisation des
boîtes de dialogue et toasts, vrai clic sur le bouton Annuler, verrou d'annulation). Aucun vrai
modèle, aucune écriture réelle (QSettings, dossier de données), aucune vraie modale."""

from __future__ import annotations

import numpy as np
import pytest
import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets

import modules.reset.commands as reset_commands
from app.ui.canvas.text.text_item_properties import TextItemProperties
from app.ui.canvas.text_item import TextBlockItem
from app.ui.commands.box import AddTextItemCommand
from app.ui.commands.textformat import TextFormatCommand
from app.ui.dayu_widgets.message import MMessage
from app.ui.messages import Messages
from modules.history import commands as history_commands
from modules.history import versions
from modules.text_undo import match
from modules.undo_guard.ui import acquire_lock, release_lock
from modules.utils.textblock import TextBlock

_PHOTO_WIDTH = 160
_PHOTO_HEIGHT = 120
_PAGE_A = "/tmp/text_undo_a.png"
_PAGE_B = "/tmp/text_undo_b.png"
_ALIGN_LEFT = QtCore.Qt.AlignmentFlag.AlignLeft
_ALIGN_CENTER = QtCore.Qt.AlignmentFlag.AlignCenter


@pytest.fixture(autouse=True)
def _no_blocking_dialogs(monkeypatch):
    """Précédent : `tests/test_undo_guard_ui.py` — jamais de vraie modale ni de vrai toast."""
    monkeypatch.setattr(Messages, "show_error_with_copy", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(Messages, "show_network_error", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(Messages, "show_server_error", staticmethod(lambda *a, **k: None))
    for name in ("info", "success", "warning", "error"):
        monkeypatch.setattr(MMessage, name, staticmethod(lambda *a, **k: None))


def _synthetic_image(fill: int = 120):
    return np.full((_PHOTO_HEIGHT, _PHOTO_WIDTH, 3), fill, dtype=np.uint8)


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


def _open_page(main, file_path: str = _PAGE_A) -> QtGui.QUndoStack:
    """Page unique affichée avec sa pile d'annulation active (précédent : `_add_open_page`)."""
    main.image_files = [file_path]
    main.curr_img_idx = 0
    main.image_data[file_path] = _synthetic_image()

    stack = QtGui.QUndoStack(main)
    main.undo_stacks[file_path] = stack
    main.undo_group.addStack(stack)
    main.undo_group.setActiveStack(stack)

    main.show_main_page()
    main.central_stack.setCurrentWidget(main.image_viewer)
    main.show()
    QtWidgets.QApplication.processEvents()
    QtWidgets.QApplication.processEvents()
    main.image_viewer.display_image_array(main.image_data[file_path], fit=False)
    main.image_ctrl.save_image_state(file_path)
    return stack


def _add_page_b(main, file_path: str = _PAGE_B) -> QtGui.QUndoStack:
    main.image_files.append(file_path)
    main.image_data[file_path] = _synthetic_image(fill=60)
    stack = QtGui.QUndoStack(main)
    main.undo_stacks[file_path] = stack
    main.undo_group.addStack(stack)
    main.image_states[file_path] = main.image_ctrl._build_image_state(file_path, {}, [], [], False)
    return stack


def _add_block(main, xyxy=(10, 10, 60, 40), translation="Bonjour") -> TextBlock:
    blk = TextBlock(text_bbox=np.array(xyxy), text="Hello", translation=translation)
    main.blk_list.append(blk)
    return blk


def _add_item(main, x: float = 10, y: float = 10, text: str = "Bonjour"):
    return main.image_viewer.add_text_item(
        TextItemProperties(text=text, position=(x, y), rotation=0, text_color=QtGui.QColor("black"))
    )


def _page_with_text(main, translation: str = "Bonjour", file_path: str = _PAGE_A):
    stack = _open_page(main, file_path)
    blk = _add_block(main, translation=translation)
    item = _add_item(main, text=translation)
    item.set_plain_text(translation)  # comme `on_blk_rendered` (applique tous les attributs)
    main.image_ctrl.save_image_state(file_path)
    return stack, blk, item


def _edit(main, item, text: str) -> None:
    """Modifie réellement l'item (`text_changed` -> bloc), puis valide comme la minuterie de
    400 ms."""
    item.set_plain_text(text)
    main.text_ctrl._commit_pending_text_command()


def _type(item, text: str) -> None:
    """Idem `_edit` sans valider : reste « en attente » (minuterie de 400 ms)."""
    item.set_plain_text(text)


def _goto(main, index: int) -> None:
    main.image_ctrl.display_image(index)
    QtWidgets.QApplication.processEvents()


def _round_trip(main) -> None:
    """A -> B -> A : la scène est reconstruite, les items d'origine sont détruits."""
    _goto(main, 1)
    _goto(main, 0)


def _texts(main) -> list[str]:
    return [item.toPlainText() for item in main.image_viewer.text_items]


def _scene_text_items(main) -> list[TextBlockItem]:
    return [i for i in main.image_viewer._scene.items() if isinstance(i, TextBlockItem)]


def _undo(qtbot, stack) -> None:
    with qtbot.capture_exceptions() as exceptions:
        stack.undo()
    assert exceptions == []


def _redo(qtbot, stack) -> None:
    with qtbot.capture_exceptions() as exceptions:
        stack.redo()
    assert exceptions == []


# =================================================================================================
# (1) TextEditCommand : navigation A -> B -> A
# =================================================================================================


def test_text_edit_undo_redo_after_navigation_round_trip(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _edit(main, item, "Salut")
    assert blk.translation == "Salut"
    assert stack.count() == 1

    _round_trip(main)
    assert shiboken6.isValid(item) is False
    assert _texts(main) == ["Salut"]

    _undo(qtbot, stack)
    assert _texts(main) == ["Bonjour"]
    assert blk.translation == "Bonjour"
    assert len(_scene_text_items(main)) == 1

    _redo(qtbot, stack)
    assert _texts(main) == ["Salut"]
    assert blk.translation == "Salut"
    assert len(_scene_text_items(main)) == 1


def test_text_edit_after_round_trip_can_be_undone_twice_in_a_row(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _edit(main, item, "Salut")
    _edit(main, item, "Coucou")
    assert stack.count() == 2

    _round_trip(main)
    _undo(qtbot, stack)
    assert (_texts(main), blk.translation) == (["Salut"], "Salut")
    _undo(qtbot, stack)
    assert (_texts(main), blk.translation) == (["Bonjour"], "Bonjour")
    _redo(qtbot, stack)
    _redo(qtbot, stack)
    assert (_texts(main), blk.translation) == (["Coucou"], "Coucou")


# =================================================================================================
# (2) RestoreVersionCommand : navigation A -> B -> A
# =================================================================================================


def _versioned_block(main) -> TextBlock:
    """Journal `... Bonjour, Salut` (le `flush_pending` de l'enregistrement de page a déjà posé un
    pré-état) ; le bloc vaut « Salut »."""
    blk = main.blk_list[0]
    versions.set_text(blk, "translation", "Bonjour", versions.ORIGIN_TRANSLATION, {"model": "X"})
    versions.set_text(blk, "translation", "Salut", versions.ORIGIN_TRANSLATION, {"model": "X"})
    return blk


def _entry(blk: TextBlock, value: str):
    return next(e for e in versions.versions_of(blk, "translation") if e["value"] == value)


def test_restore_version_undo_redo_after_navigation_round_trip(main, qtbot):
    stack, blk, item = _page_with_text(main, translation="Salut")
    blk = _versioned_block(main)
    _add_page_b(main)
    older = _entry(blk, "Bonjour")
    stack.push(history_commands.RestoreVersionCommand(main, blk, older))
    assert blk.translation == "Bonjour"
    assert item.toPlainText() == "Bonjour"
    entries_after_restore = len(versions.versions_of(blk, "translation"))

    _round_trip(main)
    assert shiboken6.isValid(item) is False

    _undo(qtbot, stack)
    assert _texts(main) == ["Salut"]
    assert blk.translation == "Salut"
    # L'entrée `restore` est retirée : historique cohérent.
    assert len(versions.versions_of(blk, "translation")) == entries_after_restore - 1

    _redo(qtbot, stack)
    assert _texts(main) == ["Bonjour"]
    assert blk.translation == "Bonjour"
    # Pas de doublon `restore` au rétablissement.
    entries = versions.versions_of(blk, "translation")
    assert len(entries) == entries_after_restore
    assert [e["origin"] for e in entries].count(versions.ORIGIN_RESTORE) == 1
    assert len(_scene_text_items(main)) == 1


def test_restore_version_without_any_item_writes_the_live_block_only(main, qtbot):
    """Bloc jamais rendu à la construction : comportement d'origine (bloc vivant écrit sans
    contrôle de son texte, panneau mis à jour sous `blockSignals`)."""
    stack = _open_page(main)
    blk = _add_block(main, translation="Salut")
    blk = _versioned_block(main)
    _add_page_b(main)
    main.curr_tblock = blk
    main.t_text_edit.blockSignals(True)
    main.t_text_edit.setPlainText("Salut")
    main.t_text_edit.blockSignals(False)

    stack.push(history_commands.RestoreVersionCommand(main, blk, _entry(blk, "Bonjour")))
    assert blk.translation == "Bonjour"
    assert main.t_text_edit.toPlainText() == "Bonjour"

    # Le champ a été modifié à la main entre-temps (sans commande) : l'ancien comportement
    # l'écrase (pas de contrôle sans item mémorisé) — inchangé.
    blk.translation = "Retouché"
    _undo(qtbot, stack)
    assert blk.translation == "Salut"


# =================================================================================================
# (3) TextFormatCommand : navigation A -> B -> A, liste blanche de format
# =================================================================================================

_SENTINEL_LAYOUT = object()


def _format_scenario(main, qtbot):
    """Item marqué de trois attributs hors liste blanche (`layout`, `editing_mode`, `selected`),
    commande de format poussée, aller-retour A -> B -> A, puis annulation. Renvoie l'item vivant
    après annulation et la pile."""
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    item.layout = _SENTINEL_LAYOUT
    item.editing_mode = True
    item.selected = True

    command = TextFormatCommand(main.image_viewer, item)
    item.set_alignment(_ALIGN_LEFT)
    command.finalize_new_state()
    stack.push(command)
    assert item.alignment == _ALIGN_LEFT

    _round_trip(main)
    assert shiboken6.isValid(item) is False
    live = main.image_viewer.text_items[0]
    assert live.alignment == _ALIGN_LEFT  # rechargé depuis l'état de la page
    item_layout_before = live.layout

    _undo(qtbot, stack)
    return stack, blk, live, item_layout_before


def test_format_undo_redo_after_navigation_round_trip(main, qtbot):
    stack, blk, live, layout_before = _format_scenario(main, qtbot)

    assert live.alignment == _ALIGN_CENTER  # format revenu
    assert len(_scene_text_items(main)) == 1
    # Liste blanche : ni `layout`, ni `editing_mode`, ni `selected` de l'item mort.
    assert live.layout is not _SENTINEL_LAYOUT
    assert live.layout is layout_before
    assert live.editing_mode is not True
    assert live.selected is not True

    # Taper dans l'item vivant met encore le bloc à jour (câblage des signaux intact).
    live.set_plain_text("Tapé")
    assert blk.translation == "Tapé"

    live.set_plain_text("Bonjour")
    main.text_ctrl._pending_text_command = None
    _redo(qtbot, stack)
    assert live.alignment == _ALIGN_LEFT
    assert len(_scene_text_items(main)) == 1


def test_format_scenario_fails_with_a_complete_dict_mutation(main, qtbot, monkeypatch):
    """Preuve par mutation : si la réduction à la liste blanche est neutralisée (`__dict__`
    complet), l'invariant `layout` du test précédent est violé."""
    monkeypatch.setattr(match, "reduce_to_format", lambda state: dict(state))
    _stack, _blk, live, _layout_before = _format_scenario(main, qtbot)
    assert live.layout is _SENTINEL_LAYOUT  # l'objet mort a écrasé l'attribut de l'item vivant


def test_format_undo_is_a_noop_when_no_item_exists(main, qtbot):
    stack, blk, item = _page_with_text(main)
    command = TextFormatCommand(main.image_viewer, item)
    item.set_alignment(_ALIGN_LEFT)
    command.finalize_new_state()
    stack.push(command)

    main.image_viewer.clear_text_items()  # retrait non tracé : l'item est détaché
    _undo(qtbot, stack)
    assert _scene_text_items(main) == []
    assert main.image_viewer.text_items == []
    _redo(qtbot, stack)
    assert _scene_text_items(main) == []


# =================================================================================================
# (4) Reset -> annuler le reset -> annuler la RV puis la TF
# =================================================================================================


def test_reset_undo_then_restore_version_and_format_undo(main, qtbot):
    stack, blk, item = _page_with_text(main, translation="Salut")
    blk = _versioned_block(main)
    older = _entry(blk, "Bonjour")
    stack.push(history_commands.RestoreVersionCommand(main, blk, older))  # -> "Bonjour"

    command = TextFormatCommand(main.image_viewer, item)
    item.set_alignment(_ALIGN_LEFT)
    command.finalize_new_state()
    stack.push(command)
    main.image_ctrl.save_image_state(_PAGE_A)

    stack.push(reset_commands.ResetPageCommand(main, _PAGE_A, stack))
    assert main.blk_list == []

    _undo(qtbot, stack)  # annule le reset : items recréés
    assert shiboken6.isValid(item) is False
    assert [b is blk for b in main.blk_list] == [True]

    _undo(qtbot, stack)  # TextFormatCommand
    live = main.image_viewer.text_items[0]
    assert live.alignment == _ALIGN_CENTER

    _undo(qtbot, stack)  # RestoreVersionCommand
    assert _texts(main) == ["Salut"]
    assert blk.translation == "Salut"

    _redo(qtbot, stack)
    _redo(qtbot, stack)
    assert _texts(main) == ["Bonjour"]
    assert main.image_viewer.text_items[0].alignment == _ALIGN_LEFT
    assert len(_scene_text_items(main)) == 1


# =================================================================================================
# (5) Même page, sans navigation : annuler la TE, annuler le rendu, rétablir le rendu, rétablir la TE
# =================================================================================================


def test_render_undo_redo_then_text_edit_redo_targets_the_new_item(main, qtbot):
    stack, blk, item = _page_with_text(main)
    stack_before_render = stack.count()
    stack.push(AddTextItemCommand(main, item))  # le « rendu »
    _edit(main, item, "Salut")
    assert stack.count() == stack_before_render + 2

    _undo(qtbot, stack)  # TE (item d'origine, nominal)
    assert item.toPlainText() == "Bonjour"
    _undo(qtbot, stack)  # rendu annulé : l'item d'origine est détaché
    assert _scene_text_items(main) == []

    _redo(qtbot, stack)  # rendu rétabli : NOUVEL item
    new_items = main.image_viewer.text_items
    assert len(new_items) == 1
    assert new_items[0] is not item
    assert new_items[0].toPlainText() == "Bonjour"

    _redo(qtbot, stack)  # TE : doit viser l'item recréé
    assert _texts(main) == ["Salut"]
    assert blk.translation == "Salut"
    assert len(_scene_text_items(main)) == 1

    _undo(qtbot, stack)
    assert _texts(main) == ["Bonjour"]


# =================================================================================================
# (6) Retrait non tracé : clear_text_items -> annuler la TE
# =================================================================================================


def test_untracked_item_removal_then_text_edit_undo_restores_the_block_only(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _edit(main, item, "Salut")
    main.curr_tblock = blk
    main.t_text_edit.blockSignals(True)
    main.t_text_edit.setPlainText("Salut")
    main.t_text_edit.blockSignals(False)

    main.image_viewer.clear_text_items()  # retrait non tracé
    assert shiboken6.isValid(item)  # détaché mais encore vivant côté C++

    _undo(qtbot, stack)
    assert blk.translation == "Bonjour"  # bloc restauré
    assert main.t_text_edit.toPlainText() == "Bonjour"  # panneau, sous blockSignals
    assert main.image_viewer.text_items == []  # aucun item créé
    assert _scene_text_items(main) == []

    _redo(qtbot, stack)
    assert blk.translation == "Salut"
    assert _scene_text_items(main) == []


# =================================================================================================
# (7) « Tout remplacer » depuis une autre page, puis retour : aucune mutation (critic M2)
# =================================================================================================


def test_replace_all_from_another_page_leaves_the_replaced_text_untouched(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _edit(main, item, "Salut")
    _goto(main, 1)

    # Ce que fait « Tout remplacer » pour une page non affichée (`_apply_block_text_with_html`).
    main.search_ctrl._apply_block_text_by_key(
        in_target=True,
        file_path=_PAGE_A,
        xyxy=tuple(int(v) for v in blk.xyxy),
        angle=float(blk.angle),
        new_text="Remplacé",
    )
    assert blk.translation == "Remplacé"

    _goto(main, 0)
    assert _texts(main) == ["Remplacé"]

    _undo(qtbot, stack)
    assert _texts(main) == ["Remplacé"]  # ni l'item ...
    assert blk.translation == "Remplacé"  # ... ni le bloc n'ont été écrasés
    assert len(_scene_text_items(main)) == 1

    _redo(qtbot, stack)
    assert _texts(main) == ["Remplacé"]
    assert blk.translation == "Remplacé"


# =================================================================================================
# (8) Deux items proches : le bon est choisi, égalité -> refus
# =================================================================================================


def test_two_close_items_with_different_text_the_right_one_is_chosen(main, qtbot):
    stack = _open_page(main)
    _add_page_b(main)
    blk = _add_block(main, translation="Bonjour")
    item = _add_item(main, x=10, text="Bonjour")
    other = _add_item(main, x=13, text="Merci")  # proche, autre texte
    main.image_ctrl.save_image_state(_PAGE_A)
    assert other.toPlainText() == "Merci"

    _edit(main, item, "Salut")
    _round_trip(main)
    assert sorted(_texts(main)) == ["Merci", "Salut"]

    _undo(qtbot, stack)
    assert sorted(_texts(main)) == ["Bonjour", "Merci"]
    assert blk.translation == "Bonjour"
    _redo(qtbot, stack)
    assert sorted(_texts(main)) == ["Merci", "Salut"]


def test_two_equidistant_items_with_the_same_text_are_refused(main, qtbot):
    stack = _open_page(main)
    _add_page_b(main)
    blk = _add_block(main, translation="Bonjour")
    item = _add_item(main, x=8, text="Bonjour")
    twin = _add_item(main, x=12, text="Salut")  # même texte que l'item après édition
    main.image_ctrl.save_image_state(_PAGE_A)
    assert twin.toPlainText() == "Salut"

    _edit(main, item, "Salut")
    _round_trip(main)
    assert sorted(_texts(main)) == ["Salut", "Salut"]

    _undo(qtbot, stack)
    # Égalité de distance (2 px de part et d'autre du bloc) : aucun item n'est touché ; le bloc
    # vivant, dont le texte est bien celui attendu, est restauré (chemin D2).
    assert sorted(_texts(main)) == ["Salut", "Salut"]
    assert blk.translation == "Bonjour"


# =================================================================================================
# (9) Nouveau Détecter : blocs remplacés par des copies (critic M3)
# =================================================================================================


def test_undo_on_a_live_item_never_writes_a_dead_block(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _edit(main, item, "Salut")
    assert blk.translation == "Salut"

    copy_blk = blk.deep_copy()  # ce que fait un nouveau Détecter : blocs neufs, anciens morts
    main.blk_list = [copy_blk]
    main.curr_tblock_item = item
    main.curr_tblock = blk  # le panneau pointe encore sur le bloc mort

    _undo(qtbot, stack)
    assert item.toPlainText() == "Bonjour"
    assert blk.translation == "Salut"  # aucune écriture dans le bloc mort
    assert copy_blk.translation == "Bonjour"  # le bloc vivant apparié est écrit
    assert main.curr_tblock is copy_blk  # jamais un bloc mort

    _redo(qtbot, stack)
    assert copy_blk.translation == "Salut"
    assert blk.translation == "Salut"
    assert main.curr_tblock is copy_blk


def test_undo_with_no_live_block_updates_the_item_and_clears_curr_tblock(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _edit(main, item, "Salut")
    main.blk_list = []
    main.curr_tblock_item = item
    main.curr_tblock = blk

    _undo(qtbot, stack)
    assert item.toPlainText() == "Bonjour"
    assert blk.translation == "Salut"
    assert main.curr_tblock is None


def test_restore_version_on_a_replaced_block_never_journals_the_dead_block(main, qtbot):
    stack, blk, item = _page_with_text(main, translation="Salut")
    blk = _versioned_block(main)
    older = _entry(blk, "Bonjour")
    stack.push(history_commands.RestoreVersionCommand(main, blk, older))
    journal_before = list(versions.versions_of(blk, "translation"))

    copy_blk = blk.deep_copy()
    main.blk_list = [copy_blk]

    _undo(qtbot, stack)
    assert item.toPlainText() == "Salut"
    assert copy_blk.translation == "Salut"
    assert versions.versions_of(blk, "translation") == journal_before  # mort : intact


# =================================================================================================
# (10) D1 : édition en attente puis navigation avant 400 ms
# =================================================================================================


def test_pending_edit_is_committed_on_the_left_page_stack_at_navigation(main, qtbot):
    stack_a, blk, item = _page_with_text(main)
    stack_b = _add_page_b(main)
    _type(item, "Salut")
    assert main.text_ctrl._pending_text_command is not None
    assert stack_a.count() == 0

    _goto(main, 1)  # avant que la minuterie de 400 ms ne se déclenche
    assert main.text_ctrl._pending_text_command is None
    assert stack_a.count() == 1  # sur la pile de la page quittée
    assert stack_b.count() == 0  # pile de la page affichée inchangée

    _goto(main, 0)
    _undo(qtbot, stack_a)
    assert _texts(main) == ["Bonjour"]
    assert blk.translation == "Bonjour"


def test_pending_edit_survives_neither_a_lost_command_nor_a_late_push(main, qtbot):
    stack_a, blk, item = _page_with_text(main)
    stack_b = _add_page_b(main)
    _type(item, "Salut")
    _goto(main, 1)
    qtbot.wait(600)  # la minuterie de 400 ms ne doit plus rien pousser
    assert stack_b.count() == 0
    assert stack_a.count() == 1


# =================================================================================================
# (11) M1 bis : taper puis Annuler/Rétablir avant 400 ms
# =================================================================================================


def _prepare_pending_after_one_committed_edit(main):
    stack, blk, item = _page_with_text(main)
    _edit(main, item, "Salut")  # commande 1, validée
    _type(item, "Coucou")  # commande 2, en attente
    assert main.text_ctrl._pending_text_command is not None
    assert stack.count() == 1
    return stack, blk, item


def test_undo_shortcut_commits_the_pending_edit_first(main, qtbot):
    stack, blk, item = _prepare_pending_after_one_committed_edit(main)

    with qtbot.capture_exceptions() as exceptions:
        main.shortcut_ctrl._activate_shortcut("undo")
    assert exceptions == []

    assert main.text_ctrl._pending_text_command is None
    assert stack.count() == 2
    assert stack.index() == 1  # la commande 2 (validée à l'instant) est annulée, pas la 1
    assert item.toPlainText() == "Salut"
    assert blk.translation == "Salut"
    assert stack.canRedo() is True

    main.shortcut_ctrl._activate_shortcut("redo")
    assert item.toPlainText() == "Coucou"


def test_undo_button_click_commits_the_pending_edit_first(main, qtbot):
    stack, blk, item = _prepare_pending_after_one_committed_edit(main)
    undo_button, redo_button = main.undo_tool_group.get_button_group().buttons()

    with qtbot.capture_exceptions() as exceptions:
        qtbot.mouseClick(undo_button, QtCore.Qt.MouseButton.LeftButton)
    assert exceptions == []

    assert main.text_ctrl._pending_text_command is None
    assert stack.count() == 2
    assert stack.index() == 1
    assert item.toPlainText() == "Salut"
    assert blk.translation == "Salut"

    with qtbot.capture_exceptions() as exceptions:
        qtbot.mouseClick(redo_button, QtCore.Qt.MouseButton.LeftButton)
    assert exceptions == []
    assert item.toPlainText() == "Coucou"
    qtbot.wait(600)
    assert stack.count() == 2  # rien de plus poussé par la minuterie


def test_signal_order_pressed_is_emitted_before_clicked(main, qtbot):
    """Ordre réel des signaux du bouton (mécanisme retenu pour M1 bis : `pressed` -> validation)."""
    _open_page(main)
    undo_button = main.undo_tool_group.get_button_group().buttons()[0]
    order: list[str] = []
    undo_button.pressed.connect(lambda: order.append("pressed"))
    undo_button.released.connect(lambda: order.append("released"))
    undo_button.clicked.connect(lambda: order.append("clicked"))

    qtbot.mouseClick(undo_button, QtCore.Qt.MouseButton.LeftButton)
    assert order == ["pressed", "released", "clicked"]


def test_undo_lock_keeps_priority_over_the_pending_edit_commit(main, qtbot):
    stack, blk, item = _prepare_pending_after_one_committed_edit(main)
    undo_button = main.undo_tool_group.get_button_group().buttons()[0]

    acquire_lock(main, "clean")
    try:
        main.shortcut_ctrl._activate_shortcut("undo")
        qtbot.mouseClick(undo_button, QtCore.Qt.MouseButton.LeftButton)
        assert main.text_ctrl._pending_text_command is not None  # rien n'a été validé
        assert stack.count() == 1
        assert stack.index() == 1
        assert item.toPlainText() == "Coucou"
    finally:
        release_lock(main, "clean")

    qtbot.mouseClick(undo_button, QtCore.Qt.MouseButton.LeftButton)  # verrou levé : accepté
    assert stack.count() == 2
    assert stack.index() == 1
    assert item.toPlainText() == "Salut"


# =================================================================================================
# (12) Chemin nominal inchangé
# =================================================================================================


def test_nominal_path_passes_the_original_item_to_apply_text_from_command(main, qtbot, monkeypatch):
    stack, blk, item = _page_with_text(main)
    _edit(main, item, "Salut")

    received: list[tuple] = []
    real = main.text_ctrl.apply_text_from_command

    def spy(text_item, text, html=None, blk=None):
        received.append((text_item, text, blk))
        return real(text_item, text, html=html, blk=blk)

    monkeypatch.setattr(main.text_ctrl, "apply_text_from_command", spy)
    _undo(qtbot, stack)
    _redo(qtbot, stack)

    assert [entry[0] is item for entry in received] == [True, True]
    assert [entry[1] for entry in received] == ["Bonjour", "Salut"]
    assert all(entry[2] is blk for entry in received)
    assert blk.translation == "Salut"


# =================================================================================================
# (13) Item sans bloc (façon import PSD)
# =================================================================================================


def test_item_without_block_survives_navigation_and_undo(main, qtbot):
    stack = _open_page(main)
    _add_page_b(main)
    item = _add_item(main, x=30, y=30, text="Texte PSD")
    main.image_ctrl.save_image_state(_PAGE_A)
    assert main.blk_list == []

    _edit(main, item, "Texte modifié")
    assert stack.count() == 1
    _round_trip(main)
    assert shiboken6.isValid(item) is False
    assert _texts(main) == ["Texte modifié"]

    _undo(qtbot, stack)
    assert _texts(main) == ["Texte PSD"]
    assert main.blk_list == []
    _redo(qtbot, stack)
    assert _texts(main) == ["Texte modifié"]
    assert len(_scene_text_items(main)) == 1


# =================================================================================================
# (14) Vérification indépendante (testeur) : cas de Philippe bout en bout, saisie en cours,
#      clavier sur le bouton, non-régression du chemin nominal, repli supprimé, historique
# =================================================================================================


def _shortcut(main, name: str) -> None:
    """Vrai chemin ⌘Z/⌘Y (`ShortcutController._activate_shortcut`) ; le focus est retiré des
    champs de texte (sinon l'application laisse Qt annuler dans le champ, comportement amont)."""
    main.image_viewer.setFocus()
    QtWidgets.QApplication.focusWidget()
    main.shortcut_ctrl._activate_shortcut(name)
    QtWidgets.QApplication.processEvents()


def _select_for_panel(main, item) -> None:
    """Sélectionne l'item comme un clic : `curr_tblock_item`/`curr_tblock` + panneau remplis."""
    main.text_ctrl.on_text_item_selected(item)


def _type_in_panel(main, text: str) -> None:
    """Frappe dans le vrai champ `t_text_edit` (signal `textChanged` réel)."""
    main.t_text_edit.setPlainText(text)


def _panel(main) -> str:
    return main.t_text_edit.toPlainText()


def test_e2e_panel_edit_wait_navigate_return_shortcut_undo_redo(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _select_for_panel(main, item)
    _type_in_panel(main, "Salut")
    qtbot.wait(600)  # vraie minuterie de 400 ms
    assert stack.count() == 1
    assert blk.translation == "Salut"

    _goto(main, 1)
    _goto(main, 0)
    assert shiboken6.isValid(item) is False
    # Le panneau est vidé par la navigation : on re-sélectionne le nouvel item comme un clic.
    new_item = _scene_text_items(main)[0]
    _select_for_panel(main, new_item)
    assert _panel(main) == "Salut"

    with qtbot.capture_exceptions() as exceptions:
        _shortcut(main, "undo")
    assert exceptions == []
    assert _texts(main) == ["Bonjour"]
    assert blk.translation == "Bonjour"
    assert _panel(main) == "Bonjour"
    assert main.blk_list[0] is blk

    _shortcut(main, "redo")
    assert _texts(main) == ["Salut"]
    assert blk.translation == "Salut"
    assert _panel(main) == "Salut"


def test_e2e_panel_still_selected_across_navigation_shows_old_text_after_undo(main, qtbot):
    """Variante sans re-sélection : le panneau doit refléter l'annulation dès qu'il est relu."""
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _select_for_panel(main, item)
    _type_in_panel(main, "Salut")
    qtbot.wait(600)
    _round_trip(main)
    _shortcut(main, "undo")
    new_item = _scene_text_items(main)[0]
    _select_for_panel(main, new_item)
    assert (_texts(main), blk.translation, _panel(main)) == (["Bonjour"], "Bonjour", "Bonjour")


def test_e2e_canvas_edit_wait_navigate_return_shortcut_undo_redo(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _select_for_panel(main, item)
    item.set_plain_text("Salut")  # édition sur le canevas
    qtbot.wait(600)
    assert stack.count() == 1
    _round_trip(main)

    _shortcut(main, "undo")
    assert (_texts(main), blk.translation) == (["Bonjour"], "Bonjour")
    _shortcut(main, "redo")
    assert (_texts(main), blk.translation) == (["Salut"], "Salut")


def test_e2e_restore_version_then_navigate_shortcut_undo_redo(main, qtbot):
    stack, blk, item = _page_with_text(main, translation="Salut")
    blk = _versioned_block(main)
    _add_page_b(main)
    stack.push(history_commands.RestoreVersionCommand(main, blk, _entry(blk, "Bonjour")))
    _round_trip(main)
    _shortcut(main, "undo")
    assert (_texts(main), blk.translation) == (["Salut"], "Salut")
    _shortcut(main, "redo")
    assert (_texts(main), blk.translation) == (["Bonjour"], "Bonjour")


def test_e2e_bold_and_size_then_navigate_shortcut_undo_redo(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _select_for_panel(main, item)
    item.setSelected(True)
    size_before = item.font_size
    main.text_ctrl.on_font_size_change(str(size_before + 10))
    main.bold_button.setChecked(True)
    main.text_ctrl.bold()
    assert stack.count() == 2
    assert item.bold is True

    _round_trip(main)
    new_item = _scene_text_items(main)[0]
    assert (new_item.bold, new_item.font_size) == (True, size_before + 10)

    _shortcut(main, "undo")
    assert new_item.bold is False
    assert new_item.font_size == size_before + 10
    _shortcut(main, "undo")
    assert new_item.font_size == size_before
    _shortcut(main, "redo")
    _shortcut(main, "redo")
    assert (new_item.bold, new_item.font_size) == (True, size_before + 10)


def test_pending_panel_typing_then_navigation_under_400ms_is_undoable_on_right_page(main, qtbot):
    stack_a, blk, item = _page_with_text(main)
    stack_b = _add_page_b(main)
    _select_for_panel(main, item)
    _type_in_panel(main, "Salut")
    assert main.text_ctrl._pending_text_command is not None
    _goto(main, 1)
    assert (stack_a.count(), stack_b.count()) == (1, 0)
    _goto(main, 0)
    _shortcut(main, "undo")
    assert (_texts(main), blk.translation) == (["Bonjour"], "Bonjour")
    _shortcut(main, "redo")
    assert (_texts(main), blk.translation) == (["Salut"], "Salut")


def test_typing_then_undo_shortcut_under_400ms_undoes_the_typing_and_loses_nothing(main, qtbot):
    """Comportement observé : la frappe en cours est d'abord validée puis annulée -> le texte
    revient à l'ancien, mais la frappe reste rétablissable (rien n'est perdu)."""
    stack, blk, item = _page_with_text(main)
    _select_for_panel(main, item)
    _type_in_panel(main, "Salut")
    _shortcut(main, "undo")
    assert (stack.count(), stack.index()) == (1, 0)
    assert (_texts(main), blk.translation) == (["Bonjour"], "Bonjour")
    _shortcut(main, "redo")
    assert (_texts(main), blk.translation) == (["Salut"], "Salut")


@pytest.mark.parametrize("key", [QtCore.Qt.Key.Key_Space, QtCore.Qt.Key.Key_Return])
def test_keyboard_activation_of_undo_button_commits_pending_edit(main, qtbot, key):
    stack, blk, item = _page_with_text(main)
    undo_button = main.undo_tool_group.get_button_group().buttons()[0]
    pressed: list[bool] = []
    undo_button.pressed.connect(lambda: pressed.append(True))
    _type(item, "Salut")
    undo_button.setFocus()
    qtbot.keyClick(undo_button, key)
    # Espace active le bouton (pressed émis) ; Entrée n'active un QAbstractButton que s'il est
    # `autoDefault`/défaut : on constate sans supposer.
    if pressed:
        assert stack.count() == 1
        assert item.toPlainText() == "Bonjour"
    else:
        pytest.skip("Entrée n'active pas ce bouton (pas de `pressed`) : aucun risque de perte")


def test_space_on_undo_button_is_swallowed_by_the_lock(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _edit(main, item, "Salut")
    _type(item, "Coucou")
    undo_button = main.undo_tool_group.get_button_group().buttons()[0]
    undo_button.setFocus()
    acquire_lock(main, "clean")
    try:
        qtbot.keyClick(undo_button, QtCore.Qt.Key.Key_Space)
        assert main.text_ctrl._pending_text_command is not None
        assert (stack.count(), stack.index()) == (1, 1)
        assert item.toPlainText() == "Coucou"
    finally:
        release_lock(main, "clean")


def test_nominal_no_navigation_type_undo_redo_format_undo_matches_upstream(main, qtbot):
    stack, blk, item = _page_with_text(main)
    _select_for_panel(main, item)
    item.setSelected(True)
    size = item.font_size
    _type_in_panel(main, "Salut")
    qtbot.wait(600)
    _shortcut(main, "undo")
    assert (_texts(main), blk.translation, _panel(main)) == (["Bonjour"], "Bonjour", "Bonjour")
    _shortcut(main, "redo")
    assert (_texts(main), blk.translation, _panel(main)) == (["Salut"], "Salut", "Salut")
    main.text_ctrl.on_font_size_change(str(size + 6))
    assert item.font_size == size + 6
    _shortcut(main, "undo")
    assert item.font_size == size
    assert (_texts(main), blk.translation) == (["Salut"], "Salut")


@pytest.mark.parametrize(
    "new_text",
    ["a  b", "ligne1\nligne2", " espace avant et après ", "ÉCOLE éàü 漢字", "a\n\nb", "x" * 300],
)
def test_awkward_texts_are_never_refused_after_navigation(main, qtbot, new_text):
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _edit(main, item, new_text)
    stored = item.toPlainText()
    _round_trip(main)
    assert _texts(main) == [stored]
    _undo(qtbot, stack)
    assert (_texts(main), blk.translation) == (["Bonjour"], "Bonjour")
    _redo(qtbot, stack)
    assert _texts(main) == [stored]
    assert len(_scene_text_items(main)) == 1


def test_undo_after_edit_when_translation_was_reformatted_in_block_keeps_working(main, qtbot):
    """`format_translations` peut réécrire `blk.translation` sans toucher l'item : l'annulation
    d'après navigation se fonde sur le texte de l'ITEM, pas celui du bloc."""
    stack, blk, item = _page_with_text(main)
    _add_page_b(main)
    _edit(main, item, "Salut")
    blk.translation = "SALUT !!"  # réécriture externe du bloc
    _round_trip(main)
    _undo(qtbot, stack)
    assert _texts(main) == ["Bonjour"]


def test_format_undo_after_render_undone_then_redone_no_navigation(main, qtbot):
    """Ancien repli `find_matching_txt_item` : item recréé (rendu annulé puis rétabli) sans
    navigation -> la TF vise le nouvel item."""
    stack = _open_page(main)
    _add_block(main)
    item = _add_item(main, text="Bonjour")
    item.set_plain_text("Bonjour")
    stack.push(AddTextItemCommand(main, item))
    _select_for_panel(main, item)
    item.setSelected(True)
    size = item.font_size
    main.text_ctrl.on_font_size_change(str(size + 8))
    assert stack.count() == 2

    _undo(qtbot, stack)  # TF
    _undo(qtbot, stack)  # rendu annulé
    assert _scene_text_items(main) == []
    _redo(qtbot, stack)  # rendu rétabli : item recréé
    new_items = _scene_text_items(main)
    assert len(new_items) == 1
    _redo(qtbot, stack)  # TF rétablie sur l'item recréé
    assert new_items[0].font_size == size + 8
    _undo(qtbot, stack)
    assert new_items[0].font_size == size


def test_history_does_not_fill_with_parasitic_entries_over_many_undo_redo_and_flushes(main, qtbot):
    stack, blk, item = _page_with_text(main, translation="Salut")
    blk = _versioned_block(main)
    _add_page_b(main)
    llm_before = [e["value"] for e in versions.versions_of(blk, "translation")]
    _edit(main, item, "Coucou")
    for _ in range(15):
        _undo(qtbot, stack)
        _redo(qtbot, stack)
        _round_trip(main)  # flush_pending à chaque enregistrement de page
    entries = versions.versions_of(blk, "translation")
    print("history sizes:", len(llm_before), "->", len(entries), [e["origin"] for e in entries])
    values = [e["value"] for e in entries]
    assert "Bonjour" in values and "Salut" in values  # les versions LLM ne sont pas chassées
    assert len(entries) <= len(llm_before) + 2
