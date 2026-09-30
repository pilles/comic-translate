"""Hors GUI (spec 04, jalon 3, sous-étape 3a-ter, ADR-022) : sélection pure du candidat visé par une
annulation de texte (`modules/text_undo/match.py`), résolution de cible sur un faux `main`
(`modules/text_undo/resolve.py`, `shiboken6` injecté), pureté du module, garde statique des lignes
`# fork:` prouvée par mutation. Les scénarios avec de vrais items Qt sont dans
`tests/test_text_undo_ui.py` (`--gui`)."""

from __future__ import annotations

import ast
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from modules.history import versions
from modules.text_undo import match, resolve
from modules.text_undo.match import Anchor

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- Faux objets ---------------------------------------------------------------------------------


class _Pos:
    def __init__(self, x: float, y: float) -> None:
        self._x, self._y = x, y

    def x(self) -> float:
        return self._x

    def y(self) -> float:
        return self._y


class FakeItem:
    """Faux `TextBlockItem` : `pos()`, `rotation()`, `toPlainText()`, `scene()`."""

    def __init__(self, x=10.0, y=10.0, rotation=0.0, text="Bonjour", scene=None, name="item"):
        self.x, self.y, self.rot, self.text, self._scene, self.name = (
            x,
            y,
            rotation,
            text,
            scene,
            name,
        )
        self.raises = False

    def pos(self) -> _Pos:
        if self.raises:
            raise RuntimeError("Internal C++ object (FakeItem) already deleted.")
        return _Pos(self.x, self.y)

    def rotation(self) -> float:
        return self.rot

    def toPlainText(self) -> str:  # noqa: N802
        return self.text

    def scene(self) -> Any:
        return self._scene

    def __repr__(self) -> str:
        return f"FakeItem({self.name})"


class FakeBlock:
    def __init__(self, x=10, y=10, angle=0.0, translation="Bonjour", text="Hello"):
        self.xyxy = [x, y, x + 50, y + 30]
        self.angle = angle
        self.translation = translation
        self.text = text


def _valid(obj: Any) -> bool:
    return not getattr(obj, "dead", False)


REF: match.Reference = (10.0, 10.0, 0.0)


def _pick(candidates, **overrides):
    kwargs: dict[str, Any] = {
        "reference": REF,
        "expected_text": "Bonjour",
        "is_valid": _valid,
    }
    kwargs.update(overrides)
    return match.pick_item(candidates, **kwargs)


# --- pick_item : tolérances ----------------------------------------------------------------------


def test_exact_position_is_selected():
    item = FakeItem()
    pick = _pick([item])
    assert pick.item is item
    assert pick.reason == match.REASON_OK


@pytest.mark.parametrize("dx,dy", [(5.0, 0.0), (0.0, -5.0), (5.0, 5.0)])
def test_position_within_tolerance_is_selected(dx, dy):
    item = FakeItem(10 + dx, 10 + dy)
    assert _pick([item]).item is item


@pytest.mark.parametrize("dx,dy", [(5.01, 0.0), (0.0, 5.01), (-6.0, 0.0)])
def test_position_out_of_tolerance_is_rejected(dx, dy):
    pick = _pick([FakeItem(10 + dx, 10 + dy)])
    assert pick.item is None
    assert pick.reason == match.REASON_NO_CANDIDATE


def test_rotation_within_and_out_of_tolerance():
    within = FakeItem(rotation=1.0)
    assert _pick([within]).item is within
    assert _pick([FakeItem(rotation=1.5)]).item is None
    assert _pick([FakeItem(rotation=-2.0)]).item is None


def test_no_reference_means_no_item():
    pick = _pick([FakeItem()], reference=None)
    assert pick.item is None
    assert pick.reason == match.REASON_NO_REFERENCE


# --- pick_item : texte attendu (M2) --------------------------------------------------------------


def test_expected_text_is_verified_even_with_a_single_candidate():
    pick = _pick([FakeItem(text="Autre contenu")])
    assert pick.item is None
    assert pick.reason == match.REASON_NO_CANDIDATE


def test_expected_text_none_disables_the_text_check():
    item = FakeItem(text="peu importe")
    assert _pick([item], expected_text=None).item is item


def test_text_match_is_exact_not_normalised():
    assert _pick([FakeItem(text="bonjour")]).item is None
    assert _pick([FakeItem(text="Bonjour ")]).item is None


# --- pick_item : contrôle croisé item/bloc (M2) --------------------------------------------------


def test_cross_check_keeps_only_the_item_paired_with_the_block():
    blk, other = FakeBlock(), FakeBlock(x=200)
    good = FakeItem(name="good")
    wrong = FakeItem(x=12.0, name="wrong")  # plus loin, mais on lui fait pointer un autre bloc
    pairing = {id(good): blk, id(wrong): other}
    pick = _pick([wrong, good], blk=blk, block_of=lambda item: pairing[id(item)])
    assert pick.item is good


def test_cross_check_rejects_the_only_candidate_paired_with_another_block():
    blk, other = FakeBlock(), FakeBlock()
    pick = _pick([FakeItem()], blk=blk, block_of=lambda item: other)
    assert pick.item is None


def test_cross_check_inactive_without_block():
    item = FakeItem()
    assert _pick([item], blk=None, block_of=lambda i: FakeBlock()).item is item


def test_cross_check_that_raises_rejects_the_candidate():
    def boom(_item):
        raise RuntimeError("appariement impossible")

    assert _pick([FakeItem()], blk=FakeBlock(), block_of=boom).item is None


# --- pick_item : départage et refus --------------------------------------------------------------


def test_closest_candidate_wins():
    near, far = FakeItem(11.0, 10.0, name="near"), FakeItem(14.0, 10.0, name="far")
    assert _pick([far, near]).item is near
    assert _pick([near, far]).item is near  # indépendant de l'ordre


def test_tie_is_refused_whatever_the_order():
    left, right = FakeItem(8.0, 10.0, name="left"), FakeItem(12.0, 10.0, name="right")
    for order in ([left, right], [right, left]):
        pick = _pick(order)
        assert pick.item is None
        assert pick.reason == match.REASON_AMBIGUOUS


def test_two_items_with_different_text_are_not_a_tie():
    right = FakeItem(12.0, 10.0, text="Bonjour", name="right")
    left = FakeItem(8.0, 10.0, text="Salut", name="left")
    assert _pick([left, right]).item is right


def test_filters_eliminating_everything_give_no_item():
    pick = _pick([FakeItem(x=100.0), FakeItem(text="x")])
    assert pick.item is None
    assert pick.reason == match.REASON_NO_CANDIDATE
    assert _pick([]).item is None


# --- pick_item : candidats invalides -------------------------------------------------------------


def test_none_and_invalid_candidates_are_filtered():
    dead = FakeItem(name="dead")
    dead.dead = True  # type: ignore[attr-defined]
    live = FakeItem(x=13.0, name="live")
    assert _pick([None, dead, live]).item is live


def test_none_alone_is_not_selected():
    assert _pick([None]).item is None


def test_is_valid_that_raises_is_ignored():
    def bad_valid(obj):
        raise RuntimeError("boom")

    assert _pick([FakeItem()], is_valid=bad_valid).item is None


def test_probe_that_raises_is_ignored():
    broken = FakeItem(name="broken")
    broken.raises = True
    ok = FakeItem(x=13.0, name="ok")
    assert _pick([broken, ok]).item is ok


def test_default_is_valid_excludes_none():
    # `shiboken6.isValid(None)` est vrai (critic m2) : l'exclusion doit être explicite.
    assert resolve.default_is_valid(None) is False
    assert resolve.default_is_valid(object()) is True  # objet non Shiboken : accepté


# --- pick_block ----------------------------------------------------------------------------------


def test_pick_block_by_position_and_field_value():
    a, b = FakeBlock(translation="Bonjour"), FakeBlock(x=200, translation="Bonjour")
    pick = match.pick_block([b, a], reference=REF, field="translation", expected="Bonjour")
    assert pick.item is a


def test_pick_block_refuses_changed_content():
    pick = match.pick_block(
        [FakeBlock(translation="Remplacé")], reference=REF, field="translation", expected="Bonjour"
    )
    assert pick.item is None


def test_pick_block_refuses_ties():
    left, right = FakeBlock(x=8), FakeBlock(x=12)
    pick = match.pick_block([left, right], reference=REF, field="translation", expected="Bonjour")
    assert pick.item is None
    assert pick.reason == match.REASON_AMBIGUOUS


def test_pick_block_ignores_none_and_incomplete_blocks():
    incomplete = SimpleNamespace(xyxy=None, angle=0)
    good = FakeBlock()
    pick = match.pick_block(
        [None, incomplete, good], reference=REF, field="translation", expected="Bonjour"
    )
    assert pick.item is good


# --- Ancre / page --------------------------------------------------------------------------------


def test_same_page_rules():
    assert match.same_page("a.png", "a.png")
    assert not match.same_page("a.png", "b.png")
    assert match.same_page(None, "b.png")  # page d'ancre inconnue (TextFormatCommand)
    assert match.same_page("a.png", None)


def test_anchor_reference_tuple():
    assert Anchor("p", 1.0, 2.0, 3.0).reference == (1.0, 2.0, 3.0)


def test_contains_by_identity():
    a, b = FakeBlock(), FakeBlock()
    assert match.contains_by_identity([a], a)
    assert not match.contains_by_identity([a], b)  # même contenu, autre objet
    assert not match.contains_by_identity([a], None)


# --- Liste blanche de format ---------------------------------------------------------------------


def test_reduce_to_format_keeps_only_whitelisted_keys():
    state = {
        "font_family": "Arial",
        "font_size": 20,
        "text_color": "red",
        "alignment": 4,
        "line_spacing": 1.2,
        "outline": True,
        "outline_color": None,
        "outline_width": 1,
        "bold": False,
        "italic": True,
        "underline": False,
        "direction": 0,
        "selection_outlines": [1, 2],
        # à exclure :
        "layout": object(),
        "_ct_text_changed_slot": lambda: None,
        "_ct_signals_connected": True,
        "selected": True,
        "editing_mode": True,
        "vertical": True,
        "resizing": False,
    }
    reduced = match.reduce_to_format(state)
    assert set(reduced) == set(match.FORMAT_KEYS)
    for forbidden in ("layout", "_ct_text_changed_slot", "selected", "editing_mode", "vertical"):
        assert forbidden not in reduced
    assert reduced["selection_outlines"] == [1, 2]
    assert reduced["selection_outlines"] is not state["selection_outlines"]  # copie


def test_reduce_to_format_is_idempotent_and_tolerates_missing_keys():
    once = match.reduce_to_format({"bold": True, "layout": 1})
    assert once == {"bold": True}
    assert match.reduce_to_format(once) == once


def test_format_keys_exact_list():
    assert match.FORMAT_KEYS == (
        "font_family",
        "font_size",
        "text_color",
        "alignment",
        "line_spacing",
        "outline",
        "outline_color",
        "outline_width",
        "bold",
        "italic",
        "underline",
        "direction",
        "selection_outlines",
    )


# --- resolve : faux main -------------------------------------------------------------------------


class FakeTextCtrl:
    def __init__(self, blocks_by_item: dict[int, Any] | None = None) -> None:
        self.blocks_by_item = blocks_by_item or {}

    def _find_text_block_for_item(self, item: Any) -> Any:  # noqa: SLF001
        return self.blocks_by_item.get(id(item))


def _fake_main(blk_list, items, ctrl=None, page="a.png"):
    scene = object()
    for item in items:
        item._scene = scene
    return SimpleNamespace(
        image_viewer=SimpleNamespace(_scene=scene, text_items=list(items)),
        text_ctrl=ctrl or FakeTextCtrl(),
        blk_list=list(blk_list),
        curr_img_idx=0,
        image_files=[page],
    )


def _target(main, **kwargs):
    defaults: dict[str, Any] = {
        "item": None,
        "blk": None,
        "anchor": None,
        "expected": "Bonjour",
        "is_valid": _valid,
    }
    defaults.update(kwargs)
    return resolve.resolve_text_target(main, **defaults)


def test_field_constants_follow_the_history_module():
    assert resolve.FIELD_TRANSLATION == versions.FIELD_TRANSLATION
    assert resolve.FIELD_TEXT == versions.FIELD_TEXT


def test_nominal_returns_the_original_objects():
    blk, item = FakeBlock(), FakeItem()
    main = _fake_main([blk], [item])
    target = _target(main, item=item, blk=blk)
    assert (target.item, target.blk, target.reason) == (item, blk, resolve.REASON_NOMINAL)


def test_nominal_with_dead_block_replaces_it_by_the_paired_block_or_none():
    dead_blk, live_blk, item = FakeBlock(), FakeBlock(), FakeItem()
    main = _fake_main([live_blk], [item], FakeTextCtrl({}))
    unpaired = _target(main, item=item, blk=dead_blk)
    assert unpaired.item is item and unpaired.blk is None  # M3 : jamais le bloc mort

    main.text_ctrl.blocks_by_item[id(item)] = live_blk
    paired = _target(main, item=item, blk=dead_blk)
    assert paired.blk is live_blk


def test_nominal_without_block_stays_without_block():
    item = FakeItem()
    main = _fake_main([], [item])
    target = _target(main, item=item, blk=None)
    assert target.item is item and target.blk is None


def test_detached_item_is_replaced_by_the_recreated_one():
    blk, old, new = FakeBlock(), FakeItem(name="old"), FakeItem(name="new")
    main = _fake_main([blk], [new], FakeTextCtrl({id(new): blk}))
    old._scene = None  # détaché
    target = _target(main, item=old, blk=blk)
    assert target.item is new and target.blk is blk
    assert target.reason == resolve.REASON_SUBSTITUTED


def test_recreated_item_with_other_text_is_refused_and_block_text_is_verified():
    blk, new = FakeBlock(translation="Remplacé"), FakeItem(text="Remplacé")
    main = _fake_main([blk], [new], FakeTextCtrl({id(new): blk}))
    target = _target(main, item=FakeItem(), blk=blk)
    assert not target.resolved  # aucune mutation : rien ne correspond au texte attendu


def test_block_only_path_when_no_item_exists():
    blk = FakeBlock(translation="Bonjour")
    main = _fake_main([blk], [])
    target = _target(main, item=FakeItem(), blk=blk)
    assert target.item is None and target.blk is blk
    assert target.reason == resolve.REASON_BLOCK_ONLY


def test_dead_block_is_found_again_through_the_anchor():
    dead, live = FakeBlock(), FakeBlock()
    main = _fake_main([live], [])
    target = _target(main, item=FakeItem(), blk=dead, anchor=Anchor("a.png", 10.0, 10.0, 0.0))
    assert target.blk is live and target.item is None


def test_anchor_of_another_page_resolves_nothing():
    live = FakeBlock()
    main = _fake_main([live], [])
    target = _target(main, item=FakeItem(), blk=FakeBlock(), anchor=Anchor("b.png", 10, 10, 0))
    assert not target.resolved
    assert target.reason == match.REASON_OTHER_PAGE


def test_ambiguous_items_fall_back_to_block_only():
    blk = FakeBlock()
    left, right = FakeItem(8.0, 10.0, name="l"), FakeItem(12.0, 10.0, name="r")
    ctrl = FakeTextCtrl({id(left): blk, id(right): blk})
    main = _fake_main([blk], [left, right], ctrl)
    target = _target(main, item=FakeItem(), blk=blk)
    assert target.item is None and target.blk is blk  # D2 : jamais un choix instable


def test_want_item_false_skips_the_item_search_and_the_text_check():
    blk = FakeBlock(translation="modifié entre-temps")
    main = _fake_main([blk], [FakeItem()])
    target = _target(main, item=None, blk=blk, want_item=False, verify_live_block=False)
    assert target.item is None and target.blk is blk


# --- Pureté --------------------------------------------------------------------------------------


@pytest.mark.parametrize("module", ["modules.text_undo", "modules.text_undo.match"])
def test_pure_modules_import_neither_pyside6_nor_shiboken6(module):
    code = textwrap.dedent(
        f"""
        import sys
        import {module}
        bad = sorted(m for m in sys.modules if m.split(".")[0] in ("PySide6", "shiboken6"))
        assert not bad, bad
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60
    )
    assert result.returncode == 0, result.stderr


def test_match_source_has_no_qt_import_statement():
    tree = ast.parse((REPO_ROOT / "modules/text_undo/match.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & {"PySide6", "shiboken6"}


# --- Garde statique des lignes `# fork:` (prouvée par mutation) ----------------------------------


def _fork_call_problems(source: str, func: str, callee: str, import_name: str) -> list[str]:
    """Vérifie que `func` appelle `callee` sur une ligne portant `# fork:` et que `import_name`
    est importé depuis `modules.text_undo.resolve` sur une ligne `# fork:`."""
    problems: list[str] = []
    lines = source.splitlines()
    tree = ast.parse(source)

    imports = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "modules.text_undo.resolve"
        and any(alias.name == import_name for alias in node.names)
    ]
    if not imports:
        problems.append(f"import de {import_name} absent")
    elif "# fork:" not in lines[imports[0].lineno - 1]:
        problems.append("ligne d'import sans # fork:")

    fn = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == func), None
    )
    if fn is None:
        return problems + [f"fonction {func} absente"]
    calls = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == callee
    ]
    if not calls:
        problems.append(f"{func} n'appelle plus {callee}")
    elif "# fork:" not in lines[calls[0].lineno - 1]:
        problems.append("ligne d'appel sans # fork:")
    return problems


_TEXT_EDIT = REPO_ROOT / "app/ui/commands/text_edit.py"
_TEXT_FORMAT = REPO_ROOT / "app/ui/commands/textformat.py"


def test_text_edit_apply_delegates_to_the_resolver():
    source = _TEXT_EDIT.read_text(encoding="utf-8")
    assert _fork_call_problems(source, "_apply", "apply_text_edit", "apply_text_edit") == []


def test_text_format_get_item_delegates_to_the_resolver():
    source = _TEXT_FORMAT.read_text(encoding="utf-8")
    assert (
        _fork_call_problems(source, "_get_item", "resolve_format_target", "resolve_format_target")
        == []
    )


def test_guard_catches_the_upstream_call_by_mutation():
    """La garde échoue si l'appel amont d'origine est réintroduit (mutation en mémoire)."""
    source = _TEXT_EDIT.read_text(encoding="utf-8")
    mutated = "\n".join(
        "        self.main.text_ctrl.apply_text_from_command("
        "self.text_item, text, html=html, blk=self.blk)"
        if "apply_text_edit(self, text, html)" in line
        else line
        for line in source.splitlines()
    )
    assert mutated != source
    problems = _fork_call_problems(mutated, "_apply", "apply_text_edit", "apply_text_edit")
    assert "_apply n'appelle plus apply_text_edit" in problems

    source_tf = _TEXT_FORMAT.read_text(encoding="utf-8")
    mutated_tf = source_tf.replace(
        "return resolve_format_target(self, self.scene, properties)",
        "return self.find_matching_txt_item(self.scene, properties)",
    )
    assert mutated_tf != source_tf
    assert _fork_call_problems(
        mutated_tf, "_get_item", "resolve_format_target", "resolve_format_target"
    )


def test_guard_catches_a_missing_fork_marker_by_mutation():
    source = _TEXT_EDIT.read_text(encoding="utf-8")
    stripped = "\n".join(
        line.split("  # fork:")[0] if "apply_text_edit" in line else line
        for line in source.splitlines()
    )
    assert stripped != source
    problems = _fork_call_problems(stripped, "_apply", "apply_text_edit", "apply_text_edit")
    assert "ligne d'appel sans # fork:" in problems
    assert "ligne d'import sans # fork:" in problems


def _lines_with(path: Path, needle: str) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if needle in line]


def test_d1_and_m1_bis_upstream_lines_are_present_and_marked():
    image = REPO_ROOT / "app/controllers/image.py"
    source = image.read_text(encoding="utf-8")
    display = source[source.index("def display_image(") :]
    commit_at = display.index("_commit_pending_text_command()")
    save_at = display.index("self.save_current_image_state()")
    assert commit_at < save_at  # D1 : avant que l'état/la scène ne soit quitté
    assert all("# fork:" in line for line in _lines_with(image, "_commit_pending_text_command"))

    shortcuts = REPO_ROOT / "app/controllers/shortcuts.py"
    commit_lines = _lines_with(shortcuts, "_commit_pending_text_command")
    assert len(commit_lines) == 1 and "# fork:" in commit_lines[0]
    text = shortcuts.read_text(encoding="utf-8")
    assert text.index("_undo_locked_by") < text.index(
        "_commit_pending_text_command"
    )  # verrou d'abord


def test_text_controller_has_no_fork_line_for_this_step():
    """Décision : aucune ligne dans `app/controllers/text.py`."""
    assert not [
        line
        for line in _lines_with(REPO_ROOT / "app/controllers/text.py", "# fork:")
        if "3a-ter" in line or "text_undo" in line
    ]
