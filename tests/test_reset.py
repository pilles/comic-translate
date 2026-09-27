"""Hors GUI (spec 04, jalon 3, sous-étape 3a) : `modules.reset.state`, module pur (aucun import
PySide6, voir ADR-012/ADR-014). `modules.reset.commands`/`modules.reset.ui` importent PySide6 —
testés en `--gui` (`tests/test_reset_ui.py`), jamais ici ; `commands.py` est vérifié par analyse
AST du fichier source (sans l'importer, précédent : aucun test hors GUI n'importe
`modules.shell.layout`, voir `tests/test_shell.py`)."""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from modules.reset import state

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMANDS_PATH = REPO_ROOT / "modules" / "reset" / "commands.py"

_FORBIDDEN_CALLS = {"push", "beginMacro", "endMacro", "mark_project_dirty"}


# --- Fakes duck-typées (précédent : tests/test_pagestate.py::_FakeMain) -------------------------


class _FakeButton:
    def __init__(self, enabled: bool = True):
        self._enabled = enabled

    def isEnabled(self) -> bool:
        return self._enabled


class _FakeButtonGroup:
    def __init__(self, buttons: list[_FakeButton]):
        self._buttons = buttons

    def buttons(self) -> list[_FakeButton]:
        return self._buttons


class _FakeHButtonGroup:
    def __init__(self, buttons: list[_FakeButton]):
        self._group = _FakeButtonGroup(buttons)

    def get_button_group(self) -> _FakeButtonGroup:
        return self._group


class _FakeTaskRunner:
    def __init__(self, is_processing_queue: bool = False):
        self.is_processing_queue = is_processing_queue


class _FakeImageViewer:
    def __init__(self, has_photo: bool = True):
        self._has_photo = has_photo

    def hasPhoto(self) -> bool:
        return self._has_photo


class _FakeUndoGroup:
    def __init__(self, active: Any = None):
        self._active = active

    def activeStack(self) -> Any:
        return self._active


_STACK = object()
_OTHER_STACK = object()


class _FakeMain:
    """Contrôleur minimal, duck-typé comme `modules.reset.state` le lit."""

    def __init__(self, **kwargs: Any):
        self.hbutton_group = _FakeHButtonGroup([_FakeButton(True) for _ in range(6)])
        self.task_runner_ctrl = _FakeTaskRunner(False)
        self._batch_active = False
        self.webtoon_mode = False

        content_widget = object()
        self.main_content_widget = content_widget
        self._center_stack = SimpleNamespace(currentWidget=lambda: content_widget)

        self.image_viewer = _FakeImageViewer(True)
        self.central_stack = SimpleNamespace(currentWidget=lambda: self.image_viewer)

        self.curr_img_idx = 0
        self.image_files = ["a.png"]
        self.image_data = {"a.png": object()}

        self.undo_stacks = {"a.png": _STACK}
        self.undo_group = _FakeUndoGroup(_STACK)

        for key, value in kwargs.items():
            setattr(self, key, value)


# --- blank_page_state ---------------------------------------------------------------------------


def _full_before_state() -> dict:
    return {
        "blk_list": [1, 2],
        "brush_strokes": [{"path": "x"}],
        "viewer_state": {
            "rectangles": [{"rect": (0, 0, 1, 1)}],
            "text_items_state": [{"text": "hi"}],
            "push_to_stack": True,
            "transform": (1, 0, 0, 0, 1, 0, 0, 0, 1),
            "center": (5, 5),
            "scene_rect": (0, 0, 100, 100),
        },
        "source_lang": "English",
        "target_lang": "French",
        "skip": False,
        "export_group_name": "album",
        "unknown_future_key": "kept",
    }


def test_blank_page_state_empties_processed_keys_only():
    before = _full_before_state()
    blank = state.blank_page_state(before)

    assert blank["blk_list"] == []
    assert blank["brush_strokes"] == []
    assert blank["viewer_state"]["rectangles"] == []
    assert blank["viewer_state"]["text_items_state"] == []
    assert "push_to_stack" not in blank["viewer_state"]

    # Le reste survit à l'identique.
    assert blank["source_lang"] == "English"
    assert blank["target_lang"] == "French"
    assert blank["skip"] is False
    assert blank["export_group_name"] == "album"
    assert blank["unknown_future_key"] == "kept"
    assert blank["viewer_state"]["transform"] == before["viewer_state"]["transform"]
    assert blank["viewer_state"]["center"] == before["viewer_state"]["center"]
    assert blank["viewer_state"]["scene_rect"] == before["viewer_state"]["scene_rect"]


def test_blank_page_state_never_mutates_input():
    before = _full_before_state()
    original_viewer_state = dict(before["viewer_state"])

    state.blank_page_state(before)

    assert before["blk_list"] == [1, 2]
    assert before["brush_strokes"] == [{"path": "x"}]
    assert before["viewer_state"] == original_viewer_state
    assert before["viewer_state"]["push_to_stack"] is True


def test_blank_page_state_handles_missing_viewer_state():
    before = {"blk_list": [1], "brush_strokes": [], "skip": False}
    blank = state.blank_page_state(before)
    assert blank["viewer_state"] == {"rectangles": [], "text_items_state": []}


def test_blank_page_state_result_is_valid_for_load_state():
    """`ImageViewer.load_state` fait `state['rectangles']` sans `.get` (défaut amont n°4,
    ADR-014) : la sortie de `blank_page_state` doit toujours porter cette clé."""
    blank = state.blank_page_state({})
    assert "rectangles" in blank["viewer_state"]
    assert blank["viewer_state"]["rectangles"] == []


# --- merge_processed -----------------------------------------------------------------------------


def test_merge_processed_restores_processed_keys_from_before():
    before = _full_before_state()
    current = state.blank_page_state(before)
    # Pendant que la page était vierge : langue changée, vue déplacée.
    current["source_lang"] = "Japanese"
    current["viewer_state"]["transform"] = (2, 0, 0, 0, 2, 0, 0, 0, 1)
    current["viewer_state"]["center"] = (9, 9)

    restored = state.merge_processed(current, before)

    assert restored["blk_list"] == before["blk_list"]
    assert restored["brush_strokes"] == before["brush_strokes"]
    assert restored["viewer_state"]["rectangles"] == before["viewer_state"]["rectangles"]
    assert (
        restored["viewer_state"]["text_items_state"] == before["viewer_state"]["text_items_state"]
    )
    assert restored["viewer_state"]["push_to_stack"] is True

    # Ce qui a changé pendant que la page était vierge est conservé, pas écrasé.
    assert restored["source_lang"] == "Japanese"
    assert restored["viewer_state"]["transform"] == (2, 0, 0, 0, 2, 0, 0, 0, 1)
    assert restored["viewer_state"]["center"] == (9, 9)

    # Inchangé si non concerné.
    assert restored["target_lang"] == "French"
    assert restored["export_group_name"] == "album"


def test_merge_processed_never_mutates_inputs():
    before = _full_before_state()
    current = state.blank_page_state(before)
    current_copy_marker = dict(current)

    state.merge_processed(current, before)

    assert current == current_copy_marker
    assert before["viewer_state"]["push_to_stack"] is True


def test_merge_processed_removes_push_to_stack_absent_from_before():
    before = {
        "blk_list": [],
        "brush_strokes": [],
        "viewer_state": {"rectangles": [], "text_items_state": []},
    }
    current = {
        "blk_list": [1],
        "brush_strokes": [],
        "viewer_state": {"rectangles": [], "text_items_state": [], "push_to_stack": True},
    }
    restored = state.merge_processed(current, before)
    assert "push_to_stack" not in restored["viewer_state"]


def test_merge_processed_tolerates_corrupted_before_viewer_state():
    before = {"blk_list": [1], "brush_strokes": [], "viewer_state": "not-a-dict"}
    current = {"blk_list": [], "brush_strokes": [], "viewer_state": {"rectangles": [1]}}
    restored = state.merge_processed(current, before)
    assert restored["blk_list"] == [1]
    assert "rectangles" not in restored["viewer_state"]


def test_merge_processed_pops_processed_key_absent_from_before():
    before: dict = {}
    current = {"blk_list": [1, 2], "brush_strokes": [3]}
    restored = state.merge_processed(current, before)
    assert "blk_list" not in restored
    assert "brush_strokes" not in restored


# --- is_pristine -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("blk_list", "viewer_state", "brush_strokes", "patches", "expected"),
    [
        ([], {"rectangles": [], "text_items_state": []}, [], [], True),
        ([], {}, [], None, True),
        ([1], {"rectangles": [], "text_items_state": []}, [], [], False),
        ([], {"rectangles": [1]}, [], [], False),
        ([], {"text_items_state": [1]}, [], [], False),
        ([], {}, [{"path": "x"}], [], False),
        ([], {}, [], [{"bbox": (0, 0, 1, 1)}], False),
        (None, None, None, None, True),
    ],
)
def test_is_pristine(blk_list, viewer_state, brush_strokes, patches, expected):
    assert state.is_pristine(blk_list, viewer_state, brush_strokes, patches) is expected


# --- drop_cache_entries --------------------------------------------------------------------------


def test_drop_cache_entries_removes_matching_tuple_keys_only():
    cache = {
        ("hash1", "model_a", "en", "cpu"): {"a": "1"},
        ("hash1", "model_b", "en", "cpu"): {"a": "2"},
        ("hash2", "model_a", "en", "cpu"): {"a": "3"},
    }
    removed = state.drop_cache_entries(cache, "hash1")
    assert removed == 2
    assert list(cache.keys()) == [("hash2", "model_a", "en", "cpu")]


def test_drop_cache_entries_tolerates_non_tuple_keys():
    cache = {"not-a-tuple": {"a": 1}, ("hash1", "x"): {"a": 2}}
    removed = state.drop_cache_entries(cache, "hash1")
    assert removed == 1
    assert "not-a-tuple" in cache


def test_drop_cache_entries_tolerates_empty_tuple_key():
    cache = {(): {"a": 1}}
    removed = state.drop_cache_entries(cache, "hash1")
    assert removed == 0
    assert () in cache


def test_drop_cache_entries_no_match_returns_zero():
    cache = {("other", "x"): {}}
    assert state.drop_cache_entries(cache, "hash1") == 0
    assert len(cache) == 1


# --- macro_open : table de vérité ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "index", "can_redo", "expected"),
    [
        (1, 0, False, True),  # macro ouverte : occupe un emplacement, pas encore refermée
        (1, 0, True, False),  # commande simple déjà annulée : peut être refaite
        (1, 1, False, False),  # commande simple, état courant
        (0, 0, False, False),  # pile vide
        (2, 1, False, True),  # macro ouverte après une commande déjà validée
        (2, 2, False, False),
        (2, 2, True, False),
    ],
)
def test_macro_open_truth_table(count, index, can_redo, expected):
    assert state.macro_open(count, index, can_redo) is expected


# --- stack_matches / page_matches ------------------------------------------------------------


def test_stack_matches_true_when_registered_stack_is_the_same_object():
    main = _FakeMain()
    assert state.stack_matches(main, "a.png", _STACK) is True


def test_stack_matches_false_when_stack_replaced():
    main = _FakeMain()
    assert state.stack_matches(main, "a.png", _OTHER_STACK) is False


def test_stack_matches_false_when_page_unknown():
    main = _FakeMain()
    assert state.stack_matches(main, "missing.png", _STACK) is False


def test_page_matches_true_nominal():
    main = _FakeMain()
    assert state.page_matches(main, "a.png") is True


def test_page_matches_false_when_index_out_of_range():
    main = _FakeMain(curr_img_idx=-1)
    assert state.page_matches(main, "a.png") is False


def test_page_matches_false_when_displayed_page_differs():
    main = _FakeMain(image_files=["a.png", "b.png"], curr_img_idx=1)
    assert state.page_matches(main, "a.png") is False


def test_page_matches_false_when_image_data_missing():
    main = _FakeMain(image_data={})
    assert state.page_matches(main, "a.png") is False


def test_page_matches_false_when_image_data_entry_is_none():
    main = _FakeMain(image_data={"a.png": None})
    assert state.page_matches(main, "a.png") is False


def test_page_matches_false_in_webtoon_mode():
    main = _FakeMain(webtoon_mode=True)
    assert state.page_matches(main, "a.png") is False


# --- availability ---------------------------------------------------------------------------


def test_availability_true_nominal():
    main = _FakeMain()
    assert state.availability(main) == (True, "")


def test_availability_false_when_a_step_button_is_disabled():
    main = _FakeMain(
        hbutton_group=_FakeHButtonGroup(
            [_FakeButton(True), _FakeButton(False)] + [_FakeButton(True) for _ in range(4)]
        )
    )
    available, reason = state.availability(main)
    assert available is False
    assert reason == state.REASON_STEPS_DISABLED


def test_availability_false_while_processing_queue():
    main = _FakeMain(task_runner_ctrl=_FakeTaskRunner(True))
    assert state.availability(main) == (False, state.REASON_PROCESSING)


def test_availability_false_while_batch_active():
    main = _FakeMain(_batch_active=True)
    assert state.availability(main) == (False, state.REASON_BATCH)


def test_availability_false_in_webtoon_mode():
    main = _FakeMain(webtoon_mode=True)
    assert state.availability(main) == (False, state.REASON_WEBTOON)


def test_availability_false_when_workspace_not_shown():
    main = _FakeMain()
    main._center_stack = SimpleNamespace(currentWidget=lambda: object())
    assert state.availability(main) == (False, state.REASON_NO_WORKSPACE)


def test_availability_false_when_central_stack_shows_something_else():
    main = _FakeMain()
    main.central_stack = SimpleNamespace(currentWidget=lambda: object())
    assert state.availability(main) == (False, state.REASON_NO_WORKSPACE)


def test_availability_false_without_photo():
    main = _FakeMain(image_viewer=_FakeImageViewer(False))
    main.central_stack = SimpleNamespace(currentWidget=lambda: main.image_viewer)
    assert state.availability(main) == (False, state.REASON_NO_PHOTO)


def test_availability_false_when_no_current_page():
    main = _FakeMain(curr_img_idx=-1)
    assert state.availability(main) == (False, state.REASON_NO_PAGE)


def test_availability_false_when_image_data_empty_for_current_page():
    main = _FakeMain(image_data={"a.png": None})
    assert state.availability(main) == (False, state.REASON_NO_PAGE)


def test_availability_false_when_active_stack_mismatched():
    main = _FakeMain(undo_group=_FakeUndoGroup(_OTHER_STACK))
    assert state.availability(main) == (False, state.REASON_STACK_MISMATCH)


def test_availability_degrades_without_raising_on_missing_attribute():
    main = SimpleNamespace()  # aucun attribut exploitable
    available, reason = state.availability(main)
    assert available is False
    assert isinstance(reason, str) and reason


# --- Messages --------------------------------------------------------------------------------


def test_already_pristine_message_names_page_number_and_name():
    text = state.already_pristine_message(12, "page_012.png")
    assert "12" in text
    assert "page_012.png" in text


def test_success_message_with_native_shortcut():
    text = state.success_message(3, "page_003.png", "⌘Z")
    assert "3" in text
    assert "page_003.png" in text
    assert "⌘Z" in text
    assert "Annuler" in text


def test_success_message_without_shortcut_falls_back_to_title_bar():
    text = state.success_message(3, "page_003.png", "")
    assert "barre de titre" in text
    assert "()" not in text  # pas de parenthèses vides


def test_orphan_macro_confirmation_text_mentions_non_reversibility():
    text = state.orphan_macro_confirmation_text()
    assert "annulée" in text or "annulable" in text.lower()


# --- Aucun import PySide6 (module pur) --------------------------------------------------------


def test_modules_reset_state_does_not_import_pyside6_transitively():
    code = (
        "import sys\n"
        "import modules.reset\n"
        "import modules.reset.state\n"
        "leaked = sorted(k for k in sys.modules if k == 'PySide6' or k.startswith('PySide6.'))\n"
        "assert not leaked, leaked\n"
        "print('OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert proc.stdout.strip().splitlines()[-1] == "OK"


# --- Analyse AST de modules/reset/commands.py (jamais importé ici, voir tests/test_shell.py) ----


def _method_calls(tree: ast.Module, class_name: str, method_name: str) -> list[str]:
    """Noms des appels (`foo.bar(...)` -> `"bar"`) faits dans le corps de `class_name.method_name`,
    sans distinguer les appels imbriqués (suffisant : on cherche seulement l'absence totale de
    `push`/`beginMacro`/`endMacro`/`mark_project_dirty`)."""
    calls: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == method_name:
                    for call_node in ast.walk(member):
                        if isinstance(call_node, ast.Call) and isinstance(
                            call_node.func, ast.Attribute
                        ):
                            calls.append(call_node.func.attr)
    return calls


def test_reset_page_command_redo_never_pushes_or_marks_macro_or_dirty():
    tree = ast.parse(COMMANDS_PATH.read_text(encoding="utf-8"))
    calls = _method_calls(tree, "ResetPageCommand", "redo")
    assert calls, "redo() introuvable par l'analyse AST"
    assert not (_FORBIDDEN_CALLS & set(calls)), calls


def test_reset_page_command_undo_never_pushes_or_marks_macro_or_dirty():
    tree = ast.parse(COMMANDS_PATH.read_text(encoding="utf-8"))
    calls = _method_calls(tree, "ResetPageCommand", "undo")
    assert calls, "undo() introuvable par l'analyse AST"
    assert not (_FORBIDDEN_CALLS & set(calls)), calls
