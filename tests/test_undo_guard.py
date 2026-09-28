"""Hors GUI (spec 04, jalon 3, sous-étape 3a-bis) : `modules.undo_guard.macro`, module pur (aucun
import PySide6 — voir ADR-012/ADR-014/ADR-020 pour le précédent de découplage).
`modules.undo_guard.ui` importe PySide6 — testé en `--gui` (`tests/test_undo_guard_ui.py`), jamais
ici.

Garde statique sur le code amont (`app/controllers/manual_workflow.py`,
`pipeline/inpainting.py`) : plus aucun `activeStack().beginMacro(`/`activeStack().endMacro(`
hors la macro par pile déjà sûre du nettoyage multi-pages (`stack.beginMacro`/`stack.endMacro`,
try/finally existant, hors périmètre de cette sous-étape), et le nombre attendu d'appels à
`guard_cleaning(`/`guard_segmentation(` (fabriques de `modules/undo_guard/ui.py` qui enveloppent
`macro.page_bound`/`macro.in_macro` — la conception initiale nommait directement `page_bound`/
`in_macro` aux sites d'appel ; l'implémentation les indirecte via ces deux fabriques pour éviter
de répéter `lock_name`/`macro_name`/le message d'abandon à chaque site, voir le rapport
d'implémentation). Lu par `tokenize`, commentaires exclus, pour ne pas se reconnaître dans les
commentaires `# fork:` qui nomment ces mêmes fonctions."""

from __future__ import annotations

import io
import os
import subprocess
import sys
import tokenize
from pathlib import Path
from typing import Any

import pytest

from modules.undo_guard import macro

REPO_ROOT = Path(__file__).resolve().parent.parent
MANUAL_WORKFLOW_PATH = REPO_ROOT / "app" / "controllers" / "manual_workflow.py"
INPAINTING_PATH = REPO_ROOT / "pipeline" / "inpainting.py"


def _code_text(path: Path) -> str:
    """Concatène tous les tokens sauf les commentaires, pour rechercher un motif dans le *code*
    seul — un commentaire `# fork: ... beginMacro ...` ne doit jamais compter comme un appel réel.
    Lu via `Path.read_text` (fins de ligne universelles : `manual_workflow.py` a des fins de ligne
    mixtes CRLF/CR/LF, voir `CLAUDE.md`) puis `tokenize.generate_tokens` sur le texte déjà normalisé
    — jamais `tokenize.tokenize` sur les octets bruts, dont le `readline` binaire ne coupe que sur
    `\\n` et laisserait des `\\r` isolés au milieu du flux de jetons."""
    text = path.read_text(encoding="utf-8")
    tokens = tokenize.generate_tokens(io.StringIO(text).readline)
    pieces = [tok.string for tok in tokens if tok.type != tokenize.COMMENT]
    return "".join(pieces)


# --- Garde statique amont ------------------------------------------------------------------------


def test_no_active_stack_begin_or_end_macro_left_in_manual_workflow():
    code = _code_text(MANUAL_WORKFLOW_PATH)
    assert "activeStack().beginMacro(" not in code
    assert "activeStack().endMacro(" not in code


def test_manual_workflow_calls_guard_cleaning_once_and_guard_segmentation_three_times():
    code = _code_text(MANUAL_WORKFLOW_PATH)
    assert code.count("guard_cleaning(") == 1
    assert code.count("guard_segmentation(") == 3


def test_no_end_macro_left_in_inpainting():
    code = _code_text(INPAINTING_PATH)
    assert "endMacro(" not in code


def test_multi_page_cleaning_still_closes_its_own_macro_per_file_unwrapped():
    """Hors périmètre 3a-bis (déjà sûr : `stack.beginMacro`/`stack.endMacro` par fichier, dans un
    `try/finally`) — ce test fige qu'il n'a pas été touché par erreur."""
    code = _code_text(MANUAL_WORKFLOW_PATH)
    assert code.count("stack.beginMacro(") == 1
    assert code.count("stack.endMacro(") == 1


# --- Fakes duck-typées (précédent : tests/test_reset.py::_FakeMain) -------------------------------


class _FakeStack:
    def __init__(self, log: list, label: str):
        self._log = log
        self._label = label

    def beginMacro(self, name: str) -> None:
        self._log.append(("begin", self._label, name))

    def endMacro(self) -> None:
        self._log.append(("end", self._label))


class _FakeUndoGroup:
    def __init__(self, active: Any = None):
        self.active = active

    def activeStack(self) -> Any:
        return self.active


class _FakeMain:
    def __init__(self, **kwargs: Any):
        self.log: list = []
        self.stack_a = _FakeStack(self.log, "a")
        self.stack_b = _FakeStack(self.log, "b")
        self.image_files = ["a.png", "b.png"]
        self.curr_img_idx = 0
        self.undo_stacks = {"a.png": self.stack_a, "b.png": self.stack_b}
        self.undo_group = _FakeUndoGroup(self.stack_a)
        for key, value in kwargs.items():
            setattr(self, key, value)


# --- in_macro -------------------------------------------------------------------------------------


def test_in_macro_opens_and_closes_on_the_active_stack():
    main = _FakeMain()
    calls: list[str] = []

    def fn(x: int) -> int:
        calls.append("fn")
        return x * 2

    wrapped = macro.in_macro(main, "inpaint", fn)
    result = wrapped(21)

    assert result == 42
    assert calls == ["fn"]
    assert main.log == [("begin", "a", "inpaint"), ("end", "a")]


def test_in_macro_closes_even_if_fn_raises_then_reraises():
    main = _FakeMain()

    def fn() -> None:
        raise ValueError("boom")

    wrapped = macro.in_macro(main, "inpaint", fn)
    with pytest.raises(ValueError, match="boom"):
        wrapped()

    assert main.log == [("begin", "a", "inpaint"), ("end", "a")]


def test_in_macro_calls_fn_without_macro_when_no_active_stack():
    main = _FakeMain(undo_group=_FakeUndoGroup(None))
    calls: list[str] = []

    def fn() -> str:
        calls.append("fn")
        return "ok"

    wrapped = macro.in_macro(main, "inpaint", fn)
    assert wrapped() == "ok"
    assert calls == ["fn"]
    assert main.log == []


def test_in_macro_uses_the_stack_active_at_call_time_not_at_construction():
    """Contrairement à `page_bound`, `in_macro` capture la pile *à l'appel* du rappel, pas à la
    construction du wrapper — utilisé pour la segmentation multi-pages, où le rappel peut
    s'exécuter après un changement de page."""
    main = _FakeMain()
    wrapped = macro.in_macro(main, "draw_segmentation_boxes", lambda: None)
    main.undo_group.active = main.stack_b  # changement de page avant l'appel du rappel

    wrapped()

    assert main.log == [("begin", "b", "draw_segmentation_boxes"), ("end", "b")]


# --- page_bound : cas nominal --------------------------------------------------------------------


def test_page_bound_opens_and_closes_on_the_origin_stack_when_page_unchanged():
    main = _FakeMain()
    calls: list[str] = []

    def fn(x: int) -> int:
        calls.append("fn")
        return x + 1

    wrapped = macro.page_bound(main, "inpaint", fn)
    result = wrapped(41)

    assert result == 42
    assert calls == ["fn"]
    assert main.log == [("begin", "a", "inpaint"), ("end", "a")]


def test_page_bound_return_value_and_args_pass_through():
    main = _FakeMain()
    wrapped = macro.page_bound(main, "draw_segmentation_boxes", lambda *a, **k: (a, k))
    assert wrapped(1, 2, kw="x") == ((1, 2), {"kw": "x"})


# --- page_bound : capture au clic, pas au rappel -------------------------------------------------


def test_page_bound_captures_origin_page_and_stack_at_construction():
    main = _FakeMain()
    wrapped = macro.page_bound(main, "inpaint", lambda: "fn")

    # Changement de page (et de pile active) *après* la construction du wrapper, avant l'appel.
    main.curr_img_idx = 1
    main.undo_group.active = main.stack_b

    result = wrapped()

    assert result is None  # abandonné : fn jamais appelée
    assert main.log == []  # aucune macro ouverte ni sur "a" ni sur "b"


def test_page_bound_abandons_when_active_stack_changed_since_click():
    main = _FakeMain()
    calls: list[str] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: calls.append("fn"))

    main.undo_group.active = main.stack_b  # pile active changée, page affichée inchangée

    assert wrapped() is None
    assert calls == []
    assert main.log == []


def test_page_bound_abandons_when_stack_for_origin_path_replaced():
    main = _FakeMain()
    calls: list[str] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: calls.append("fn"))

    main.undo_stacks["a.png"] = main.stack_b  # pile remplacée pour la page d'origine

    assert wrapped() is None
    assert calls == []
    assert main.log == []


def test_page_bound_abandons_when_displayed_page_is_a_different_path():
    main = _FakeMain()
    calls: list[str] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: calls.append("fn"))

    main.image_files = ["c.png", "b.png"]  # "a.png" n'est plus affichable à cet index
    main.curr_img_idx = 0

    assert wrapped() is None
    assert calls == []
    assert main.log == []


def test_page_bound_abandons_when_curr_img_idx_is_minus_one_at_click():
    main = _FakeMain(curr_img_idx=-1)
    calls: list[str] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: calls.append("fn"))

    assert wrapped() is None
    assert calls == []
    assert main.log == []


def test_page_bound_abandons_when_curr_img_idx_out_of_bounds_at_click():
    main = _FakeMain(curr_img_idx=99)
    calls: list[str] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: calls.append("fn"))

    assert wrapped() is None
    assert calls == []
    assert main.log == []


def test_page_bound_abandons_when_no_active_stack_at_click():
    main = _FakeMain(undo_group=_FakeUndoGroup(None))
    calls: list[str] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: calls.append("fn"))

    assert wrapped() is None
    assert calls == []
    assert main.log == []


def test_page_bound_calls_notify_on_abandon():
    main = _FakeMain()
    notified: list[bool] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: None, notify=lambda: notified.append(True))

    main.undo_group.active = main.stack_b

    wrapped()

    assert notified == [True]


def test_page_bound_swallows_exception_raised_by_notify():
    main = _FakeMain()

    def boom() -> None:
        raise RuntimeError("notify cassé")

    wrapped = macro.page_bound(main, "inpaint", lambda: None, notify=boom)
    main.undo_group.active = main.stack_b

    wrapped()  # ne lève pas


def test_page_bound_does_not_call_notify_on_success():
    main = _FakeMain()
    notified: list[bool] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: None, notify=lambda: notified.append(True))

    wrapped()

    assert notified == []


# --- page_bound : A -> B -> A ---------------------------------------------------------------------


def test_page_bound_applies_when_navigated_away_and_back_to_the_same_page():
    main = _FakeMain()
    calls: list[str] = []
    wrapped = macro.page_bound(main, "inpaint", lambda: calls.append("fn"))

    main.curr_img_idx = 1
    main.undo_group.active = main.stack_b  # navigation vers B
    main.curr_img_idx = 0
    main.undo_group.active = main.stack_a  # retour sur A (même pile, même page)

    result = wrapped()

    assert calls == ["fn"]
    assert main.log == [("begin", "a", "inpaint"), ("end", "a")]
    assert result is None  # valeur de retour de fn (None ici), pas un marqueur d'échec


# --- page_bound : referme même si fn lève -----------------------------------------------------


def test_page_bound_closes_macro_even_if_fn_raises_then_reraises():
    main = _FakeMain()

    def fn() -> None:
        raise ValueError("boom")

    wrapped = macro.page_bound(main, "inpaint", fn)
    with pytest.raises(ValueError, match="boom"):
        wrapped()

    assert main.log == [("begin", "a", "inpaint"), ("end", "a")]


# --- Messages --------------------------------------------------------------------------------


def test_cleaning_abandoned_message_names_page_number_and_name():
    text = macro.cleaning_abandoned_message(11, "page_011.png")
    assert "11" in text
    assert "page_011.png" in text
    assert "Nettoyage" in text


def test_segmentation_abandoned_message_names_page_number_and_name():
    text = macro.segmentation_abandoned_message(11, "page_011.png")
    assert "11" in text
    assert "page_011.png" in text
    assert "Segmentation" in text
    assert "Annuler" in text


# --- Pureté : aucun import PySide6 transitif ----------------------------------------------------


def test_modules_undo_guard_macro_does_not_import_pyside6_transitively():
    code = (
        "import sys\n"
        "import modules.undo_guard\n"
        "import modules.undo_guard.macro\n"
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
