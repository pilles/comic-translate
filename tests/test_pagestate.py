"""Hors GUI (spec 04, jalon 1) : `modules.pagestate.progress` et
`modules.pagestate.collect`, module pur (aucun import PySide6, voir
ADR-012). Précédent pour le sous-processus « pas de PySide6 dans
`sys.modules` » : `modules/history/`, cherché ici via
`tests/test_block_versions_*.py` (pas de test équivalent trouvé pour
`modules/history` lui-même — motif recopié de
`tests/test_locale_onnxruntime.py::_run_ort_probe`)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from modules.pagestate import STEPS, PageProgress, compute_progress, live_path, page_progress

REPO_ROOT = Path(__file__).resolve().parent.parent


class _Block:
    def __init__(self, text: Any = "", translation: Any = ""):
        self.text = text
        self.translation = translation


class _NoTextBlock:
    """Bloc sans attribut `text` du tout (`getattr` défensif)."""

    def __init__(self, translation: Any = ""):
        self.translation = translation


class _FakeScene:
    pass


class _FakeItem:
    def __init__(self, scene: Any):
        self._scene = scene

    def scene(self) -> Any:
        return self._scene


class _RaisingItem:
    def scene(self) -> Any:
        raise RuntimeError("objet Qt détruit")


class _FakeViewer:
    def __init__(self, scene: Any, items: list[Any]):
        self._scene = scene
        self.text_items = items


class _FakeMain:
    """Contrôleur minimal, duck-typé comme `modules.pagestate.collect` le
    lit (aucune dépendance à `controller.ComicTranslate`)."""

    def __init__(self, **kwargs: Any):
        self.webtoon_mode = False
        self._batch_active = False
        self.image_files: list[str] = []
        self.curr_img_idx = -1
        self.image_data: dict[str, Any] = {}
        self.blk_list: list[Any] = []
        self.image_states: dict[str, Any] = {}
        self.image_patches: dict[str, Any] = {}
        for key, value in kwargs.items():
            setattr(self, key, value)


# --- compute_progress --------------------------------------------------------


def test_compute_progress_nominal():
    blocks = [_Block("Bonjour", "Hello"), _Block("Salut", ""), _Block("", "")]
    progress = compute_progress(blocks, n_patches=2, n_rendered=1)

    assert progress.n_blocks == 3
    assert progress.n_text == 2
    assert progress.n_translated == 1
    assert progress.n_patches == 2
    assert progress.n_rendered == 1
    for step in STEPS:
        assert progress.done(step)


def test_compute_progress_empty_blocks_all_absent():
    progress = compute_progress([], n_patches=0, n_rendered=0)
    assert progress == PageProgress(0, 0, 0, 0, 0)
    for step in STEPS:
        assert not progress.done(step)


def test_compute_progress_whitespace_only_text_not_counted():
    blocks = [_Block("   ", "\n\t")]
    progress = compute_progress(blocks, n_patches=0, n_rendered=0)
    assert progress.n_blocks == 1
    assert progress.n_text == 0
    assert progress.n_translated == 0


def test_compute_progress_none_fields_degrade_gracefully():
    blocks = [_Block(None, None)]
    progress = compute_progress(blocks, n_patches=0, n_rendered=0)
    assert progress.n_blocks == 1
    assert progress.n_text == 0
    assert progress.n_translated == 0


def test_compute_progress_non_string_fields_degrade_gracefully():
    blocks = [_Block(123, ["a", "b"])]
    progress = compute_progress(blocks, n_patches=0, n_rendered=0)
    assert progress.n_blocks == 1
    assert progress.n_text == 0
    assert progress.n_translated == 0


def test_compute_progress_missing_text_attribute_degrades_that_block_only():
    blocks = [_NoTextBlock(translation="Salut"), _Block("Bonjour", "Hello")]
    progress = compute_progress(blocks, n_patches=0, n_rendered=0)
    assert progress.n_blocks == 2
    assert progress.n_text == 1  # seul le bloc pourvu de `text` compte
    assert progress.n_translated == 2


def test_compute_progress_negative_patches_and_rendered_clamped_to_zero():
    progress = compute_progress([], n_patches=-1, n_rendered=-5)
    assert progress.n_patches == 0
    assert progress.n_rendered == 0


def test_page_progress_done_unknown_step_raises():
    progress = compute_progress([], n_patches=0, n_rendered=0)
    with pytest.raises(ValueError):
        progress.done("unknown-step")


# --- live_path -----------------------------------------------------------------


def test_live_path_none_in_webtoon_mode():
    main = _FakeMain(
        webtoon_mode=True, image_files=["a.png"], curr_img_idx=0, image_data={"a.png": object()}
    )
    assert live_path(main) is None


def test_live_path_none_while_batch_active():
    main = _FakeMain(
        _batch_active=True, image_files=["a.png"], curr_img_idx=0, image_data={"a.png": object()}
    )
    assert live_path(main) is None


def test_live_path_none_when_index_is_minus_one():
    main = _FakeMain(image_files=["a.png"], curr_img_idx=-1, image_data={"a.png": object()})
    assert live_path(main) is None


def test_live_path_none_when_index_out_of_range():
    main = _FakeMain(image_files=["a.png"], curr_img_idx=5, image_data={"a.png": object()})
    assert live_path(main) is None


def test_live_path_none_when_image_data_missing_entry():
    main = _FakeMain(image_files=["a.png"], curr_img_idx=0, image_data={})
    assert live_path(main) is None


def test_live_path_none_when_image_data_entry_is_none():
    main = _FakeMain(image_files=["a.png"], curr_img_idx=0, image_data={"a.png": None})
    assert live_path(main) is None


def test_live_path_nominal():
    main = _FakeMain(image_files=["a.png", "b.png"], curr_img_idx=1, image_data={"b.png": object()})
    assert live_path(main) == "b.png"


# --- page_progress : source (page vivante vs image_states) ---------------------


def test_page_progress_live_page_reads_blk_list_and_scene_items():
    scene = _FakeScene()
    other_scene = _FakeScene()
    items = [_FakeItem(scene), _FakeItem(scene), _FakeItem(other_scene)]
    main = _FakeMain(
        image_files=["live.png"],
        curr_img_idx=0,
        image_data={"live.png": object()},
        blk_list=[_Block("A", "a"), _Block("B", "")],
        image_patches={"live.png": [{"bbox": (0, 0, 1, 1)}]},
    )
    main.image_viewer = _FakeViewer(scene, items)

    progress = page_progress(main, "live.png")

    assert progress.n_blocks == 2
    assert progress.n_text == 2
    assert progress.n_translated == 1
    assert progress.n_patches == 1
    assert progress.n_rendered == 2  # seuls les items rattachés à `scene`


def test_page_progress_other_page_reads_image_states():
    main = _FakeMain(
        image_files=["live.png"],
        curr_img_idx=0,
        image_data={"live.png": object()},
        image_states={
            "other.png": {
                "blk_list": [_Block("C", "c")],
                "viewer_state": {"text_items_state": [{"x": 1}, {"x": 2}]},
            }
        },
        image_patches={"other.png": []},
    )
    main.image_viewer = _FakeViewer(_FakeScene(), [])

    progress = page_progress(main, "other.png")

    assert progress.n_blocks == 1
    assert progress.n_text == 1
    assert progress.n_translated == 1
    assert progress.n_patches == 0
    assert progress.n_rendered == 2


def test_page_progress_live_page_ignores_item_whose_scene_call_raises():
    scene = _FakeScene()
    main = _FakeMain(
        image_files=["live.png"],
        curr_img_idx=0,
        image_data={"live.png": object()},
        blk_list=[_Block("A", "a")],
    )
    main.image_viewer = _FakeViewer(scene, [_FakeItem(scene), _RaisingItem()])

    progress = page_progress(main, "live.png")

    assert progress.n_rendered == 1  # l'item Qt détruit ne compte pas, ne lève pas


# --- Dégradation étape par étape sur données pourries ---------------------------


def test_page_progress_path_absent_from_image_states_all_zero():
    main = _FakeMain(image_files=[], curr_img_idx=-1, image_states={"other.png": {}})
    progress = page_progress(main, "missing.png")
    assert progress == PageProgress(0, 0, 0, 0, 0)


def test_page_progress_state_not_a_dict_all_zero():
    main = _FakeMain(image_files=[], curr_img_idx=-1, image_states={"p.png": "corrompu"})
    progress = page_progress(main, "p.png")
    assert progress == PageProgress(0, 0, 0, 0, 0)


def test_page_progress_corrupted_viewer_state_degrades_render_only():
    main = _FakeMain(
        image_files=[],
        curr_img_idx=-1,
        image_states={
            "p.png": {
                "blk_list": [_Block("A", "a"), _NoTextBlock(translation="b")],
                "viewer_state": "not-a-dict",
            }
        },
        image_patches={"p.png": [1, 2, 3]},
    )
    progress = page_progress(main, "p.png")

    assert progress.n_blocks == 2
    assert progress.n_text == 1  # le bloc sans `text` ne compte pas, l'autre si
    assert progress.n_translated == 2
    assert progress.n_patches == 3
    assert progress.n_rendered == 0  # dégradé seul, le reste de la ligne survit


def test_page_progress_missing_text_items_state_key_degrades_render_only():
    main = _FakeMain(
        image_files=[],
        curr_img_idx=-1,
        image_states={
            "p.png": {
                "blk_list": [_Block("A", "a")],
                "viewer_state": {},  # pas de `text_items_state`
            }
        },
        image_patches={"p.png": []},
    )
    progress = page_progress(main, "p.png")

    assert progress.n_blocks == 1
    assert progress.n_text == 1
    assert progress.n_rendered == 0


def test_page_progress_image_patches_not_a_dict_degrades_clean_only():
    main = _FakeMain(
        image_files=[],
        curr_img_idx=-1,
        image_states={
            "p.png": {
                "blk_list": [_Block("A", "a")],
                "viewer_state": {"text_items_state": [1, 2]},
            }
        },
        image_patches="corrompu",
    )
    progress = page_progress(main, "p.png")

    assert progress.n_blocks == 1
    assert progress.n_text == 1
    assert progress.n_rendered == 2
    assert progress.n_patches == 0  # dégradé seul


def test_page_progress_image_states_not_a_dict_all_zero_without_raising():
    main = _FakeMain(image_files=[], curr_img_idx=-1, image_states="corrompu")
    progress = page_progress(main, "p.png")
    assert progress == PageProgress(0, 0, 0, 0, 0)


# --- Page vivante vs page non vivante : même compteur sur la même donnée -------


def test_page_progress_live_and_non_live_agree_on_same_data():
    """Renforce la conception (exigence n°1 du jalon) : quand la scène et
    `text_items_state` décrivent la même chose, le compteur « rendue »
    (et tous les autres) ne dépend pas de la source (page vivante ou
    `image_states`)."""
    blocks = [_Block("A", "a"), _Block("B", "")]
    scene = _FakeScene()
    items = [_FakeItem(scene), _FakeItem(scene), _FakeItem(_FakeScene())]  # 2 dans la scène active

    live_main = _FakeMain(
        image_files=["p.png"],
        curr_img_idx=0,
        image_data={"p.png": object()},
        blk_list=blocks,
        image_patches={"p.png": [1, 2]},
    )
    live_main.image_viewer = _FakeViewer(scene, items)

    non_live_main = _FakeMain(
        image_files=[],
        curr_img_idx=-1,
        image_states={
            "p.png": {
                "blk_list": blocks,
                "viewer_state": {"text_items_state": [{"x": 1}, {"x": 2}]},
            }
        },
        image_patches={"p.png": [1, 2]},
    )

    live_progress = page_progress(live_main, "p.png")
    non_live_progress = page_progress(non_live_main, "p.png")

    assert live_progress == non_live_progress == PageProgress(2, 2, 1, 2, 2)


# --- Robustesse : `blk_list` réaffecté pendant la lecture ------------------------


class _SelfMutatingBlockSequence:
    """Séquence qui remplace `main.blk_list` par une autre liste dès que
    `list(...)` commence à l'itérer — simule un remplacement concurrent de
    `blk_list` pendant que `collect._blocks_for` en prend une référence."""

    def __init__(self, main: "_FakeMain", items: list[Any], replacement: list[Any]):
        self._main = main
        self._items = items
        self._replacement = replacement

    def __iter__(self):
        self._main.blk_list = self._replacement
        return iter(self._items)


def test_page_progress_blk_list_reassigned_during_iteration_does_not_raise():
    main = _FakeMain(image_files=["live.png"], curr_img_idx=0, image_data={"live.png": object()})
    original = _SelfMutatingBlockSequence(
        main, [_Block("A", "a")], [_Block("B", "b"), _Block("C", "c")]
    )
    main.blk_list = original
    main.image_viewer = _FakeViewer(_FakeScene(), [])

    progress = page_progress(main, "live.png")

    # `list(blk_list)` a déjà été évalué avant le remplacement : la lecture
    # reste cohérente avec l'instantané pris localement (1 bloc), jamais
    # d'exception, et `main.blk_list` porte bien la nouvelle liste ensuite.
    assert progress.n_blocks == 1
    assert isinstance(main.blk_list, list)
    assert len(main.blk_list) == 2


# --- Aucun import PySide6 (module pur) ------------------------------------------


def test_modules_pagestate_does_not_import_pyside6_transitively():
    """Sous-processus (précédent : `tests/test_locale_onnxruntime.py`) :
    `modules.pagestate` (le paquet exporté par `__init__.py`, donc
    `progress.py` + `collect.py`) ne doit jamais tirer PySide6, pour rester
    importable depuis un thread worker (même contrainte que
    `modules/history`, ADR-012)."""
    code = (
        "import sys\n"
        "import modules.pagestate\n"
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
