"""GUI (spec 04, jalon 1) : piste d'avancement par page (`modules/pagestate/ui.py`),
délégué composé par-dessus `PageListItemDelegate` (`app/ui/list_view.py`).

`--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`). Précédents :
`tests/test_original_view.py` (vraie `ComicTranslate`, note d'environnement
sur `transform`/`center` sous le pilote `offscreen`) et
`tests/test_history_restore.py` (widgets légers hors `ComicTranslate` quand
c'est suffisant)."""

from __future__ import annotations

import copy
import hashlib
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from app.ui.list_view import PageListView
from modules.pagestate.progress import PageProgress
from modules.pagestate.ui import PageStateDelegate, _Refresher, attach_page_state

_ROW_WIDTH = 220
_ROW_HEIGHT = 60
_PHOTO_WIDTH = 40
_PHOTO_HEIGHT = 30


class _FakeBlock:
    """Bloc minimal, duck-typé comme `modules.history.flush_pending` et
    `modules.pagestate.progress.compute_progress` le lisent."""

    def __init__(self, text: str = "", translation: str = ""):
        self.text = text
        self.translation = translation

    def __eq__(self, other: object) -> bool:
        # Comparaison par valeur : permet de comparer deux `blk_list`
        # d'instances `ComicTranslate` distinctes dans
        # `test_project_page_state_identical_with_and_without_attach`.
        if not isinstance(other, _FakeBlock):
            return NotImplemented
        return self.text == other.text and self.translation == other.translation


def _synthetic_image(width: int = _PHOTO_WIDTH, height: int = _PHOTO_HEIGHT) -> np.ndarray:
    return np.full((height, width, 3), 120, dtype=np.uint8)


def _make_page_list(qtbot, height: int = 240) -> PageListView:
    page_list = PageListView()
    qtbot.addWidget(page_list)
    page_list.resize(_ROW_WIDTH, height)
    page_list.show()
    qtbot.waitExposed(page_list)
    return page_list


def _add_item(page_list: PageListView, path: str, skip: bool = False) -> QtWidgets.QListWidgetItem:
    item = QtWidgets.QListWidgetItem(path)
    item.setData(Qt.ItemDataRole.UserRole, path)
    if skip:
        font = item.font()
        font.setStrikeOut(True)
        item.setFont(font)
    page_list.addItem(item)
    return item


# --- Pixels de la piste : présents pour une page FAITE, atténués pour ABSENTE --


def test_track_pixels_present_for_done_page_and_attenuated_for_empty_page(qtbot):
    page_list = _make_page_list(qtbot)
    _add_item(page_list, "done.png")
    _add_item(page_list, "empty.png")

    done_progress = PageProgress(10, 9, 9, 6, 9)
    empty_progress = PageProgress(0, 0, 0, 0, 0)

    def provider(path: str) -> PageProgress:
        return done_progress if path == "done.png" else empty_progress

    inner = page_list.itemDelegate()
    delegate = PageStateDelegate(inner, provider, parent=page_list)
    page_list.setItemDelegate(delegate)
    page_list.viewport().update()
    qtbot.wait(20)

    image = page_list.viewport().grab().toImage()

    index_done = page_list.model().index(0, 0)
    index_empty = page_list.model().index(1, 0)
    rect_done = page_list.visualRect(index_done)
    rect_empty = page_list.visualRect(index_empty)

    background = image.pixelColor(rect_empty.left() + 1, rect_empty.top() + 1)

    def _max_diff(rect: QtCore.QRect) -> int:
        y = rect.bottom() - 8
        diffs = []
        for x in range(rect.left() + 60, rect.right() - 4, 4):
            color = image.pixelColor(x, y)
            diffs.append(
                abs(color.red() - background.red())
                + abs(color.green() - background.green())
                + abs(color.blue() - background.blue())
            )
        return max(diffs) if diffs else 0

    diff_done = _max_diff(rect_done)
    diff_empty = _max_diff(rect_empty)

    assert diff_done > 20, f"piste FAITE non visible (diff max = {diff_done})"
    assert diff_done > diff_empty * 2, (
        f"piste ABSENTE pas assez atténuée par rapport à FAITE "
        f"(diff_done={diff_done}, diff_empty={diff_empty})"
    )


# --- sizeHint identique avec et sans attache ------------------------------------


def test_size_hint_identical_with_and_without_attach(qtbot):
    page_list = _make_page_list(qtbot)
    _add_item(page_list, "a.png")
    index = page_list.model().index(0, 0)
    option = QtWidgets.QStyleOptionViewItem()
    option.rect = QtCore.QRect(0, 0, _ROW_WIDTH, _ROW_HEIGHT)

    inner = page_list.itemDelegate()
    hint_before = inner.sizeHint(option, index)

    delegate = PageStateDelegate(inner, lambda _path: PageProgress(0, 0, 0, 0, 0), parent=page_list)
    page_list.setItemDelegate(delegate)

    hint_after = delegate.sizeHint(option, index)

    assert hint_after == hint_before


# --- attach_page_state ne lève jamais, même sans page_list exploitable ---------


def test_attach_page_state_without_page_list_does_not_raise():
    class _Bare:
        pass

    assert attach_page_state(_Bare()) is None


def test_attach_page_state_with_unusable_page_list_does_not_raise():
    class _Bare:
        page_list = object()  # pas de itemDelegate()/setItemDelegate() Qt

    assert attach_page_state(_Bare()) is None


def test_attach_page_state_without_existing_delegate_does_not_raise(qtbot):
    page_list = _make_page_list(qtbot)
    page_list.setItemDelegate(None)  # type: ignore[arg-type]

    class _Bare:
        pass

    main = _Bare()
    main.page_list = page_list
    assert attach_page_state(main) is None


# --- setItemDelegate ne détruit pas `inner` -------------------------------------


def test_set_item_delegate_does_not_destroy_inner(qtbot):
    page_list = _make_page_list(qtbot)
    inner = page_list.itemDelegate()
    delegate = PageStateDelegate(inner, lambda _path: PageProgress(0, 0, 0, 0, 0), parent=page_list)
    page_list.setItemDelegate(delegate)

    _add_item(page_list, "a.png")
    index = page_list.model().index(0, 0)
    option = QtWidgets.QStyleOptionViewItem()
    option.rect = QtCore.QRect(0, 0, _ROW_WIDTH, _ROW_HEIGHT)

    # `inner` reste un objet Qt vivant et utilisable après avoir été remplacé
    # comme délégué courant.
    hint = inner.sizeHint(option, index)
    assert hint.isValid()


# --- attach_page_state réel : délégué composé installé, inner conservé --------


def test_attach_page_state_installs_composed_delegate_and_keeps_inner(qtbot):
    from controller import ComicTranslate

    main = ComicTranslate()
    qtbot.addWidget(main)
    main._skip_close_prompt = True

    delegate = main._page_state_delegate
    assert isinstance(delegate, PageStateDelegate)
    assert main.page_list.itemDelegate() is delegate
    assert main._page_state_inner_delegate is not None
    assert main._page_state_inner_delegate.__class__.__name__ == "PageListItemDelegate"


# --- QUndoGroup.indexChanged : endMacro et setActiveStack ----------------------


def test_undo_group_index_changed_emitted_on_endmacro_and_set_active_stack(qtbot):
    group = QtGui.QUndoGroup()
    stack1 = QtGui.QUndoStack()
    stack2 = QtGui.QUndoStack()
    group.addStack(stack1)
    group.addStack(stack2)
    group.setActiveStack(stack1)

    with qtbot.waitSignal(group.indexChanged, timeout=1000):
        stack1.beginMacro("test")
        stack1.push(QtGui.QUndoCommand("noop"))
        stack1.endMacro()

    with qtbot.waitSignal(group.indexChanged, timeout=1000):
        group.setActiveStack(stack2)


# --- Coût du tick du chien de garde : médiane < 1 ms ----------------------------


def test_watchdog_tick_median_cost_under_one_millisecond(qtbot):
    n_pages = 242
    n_blocks_per_page = 30

    class _Bare:
        pass

    main = _Bare()
    main.webtoon_mode = False
    main._batch_active = False
    main.blk_list = []
    main.image_data = {}
    main.image_files = [f"page_{i}.png" for i in range(n_pages)]
    main.curr_img_idx = -1
    main.image_patches = {path: [] for path in main.image_files}
    main.image_states = {
        path: {
            "blk_list": [_FakeBlock(f"t{i}-{j}", f"tr{i}-{j}") for j in range(n_blocks_per_page)],
            "viewer_state": {"text_items_state": [{"x": j} for j in range(n_blocks_per_page)]},
        }
        for i, path in enumerate(main.image_files)
    }

    # Fenêtre haute pour maximiser le nombre de lignes visibles (pire cas
    # réaliste : grand panneau de pages, vignettes réduites) plutôt que les
    # 242 pages en entier.
    page_list = _make_page_list(qtbot, height=3600)
    for path in main.image_files:
        _add_item(page_list, path)

    main.page_list = page_list
    main.image_viewer = None  # jamais consulté : curr_img_idx = -1, aucune page vivante

    delegate = attach_page_state(main)
    assert delegate is not None
    watchdog = main._page_state_watchdog

    watchdog.timeout.emit()  # chauffe

    samples_ns = []
    for _ in range(30):
        start = time.perf_counter_ns()
        watchdog.timeout.emit()
        samples_ns.append(time.perf_counter_ns() - start)

    median_ms = statistics.median(samples_ns) / 1_000_000
    print(
        f"[pagestate] tick chien de garde, médiane sur 30 essais "
        f"({n_pages} pages x {n_blocks_per_page} blocs) : {median_ms:.4f} ms"
    )
    assert median_ms < 1.0


# --- Lignes de page d'un projet sérialisé : identiques avec/sans attache -------


def test_project_page_state_identical_with_and_without_attach(qtbot):
    """Neutralise `transform`/`center` (note d'environnement documentée dans
    `tests/test_original_view.py` : sous le pilote `offscreen`, le viewport
    imbriqué de `ComicTranslate.image_viewer` n'obtient jamais de géométrie
    réelle, ces deux champs ne sont donc pas stables d'une instance à
    l'autre). Le reste de l'état de page sauvegardé (`viewer_state` sans
    `transform`/`center`, `blk_list`, `skip`, langues) doit être strictement
    identique, attache posée ou non — ce jalon est lecture seule partout."""
    from controller import ComicTranslate

    def _build_state(with_attach: bool) -> dict[str, Any]:
        main = ComicTranslate()
        qtbot.addWidget(main)
        main._skip_close_prompt = True
        if not with_attach:
            # `attach_page_state` a déjà été appelé par `__init__` (`# fork:`
            # dans `controller.py`) : on neutralise l'attache réelle en
            # remettant le délégué d'origine, pour comparer un état "sans
            # attache" sans reconstruire `ComicTranslate` sans son câblage.
            inner = main._page_state_inner_delegate
            if inner is not None:
                main.page_list.setItemDelegate(inner)

        main.image_files = ["fake_page.png"]
        main.curr_img_idx = 0
        stack = QtGui.QUndoStack(main)
        main.undo_stacks["fake_page.png"] = stack
        main.undo_group.addStack(stack)
        main.undo_group.setActiveStack(stack)

        main.image_viewer.display_image_array(_synthetic_image(), fit=False)
        main.blk_list = [_FakeBlock("Bonjour", "Hello")]

        main.image_ctrl.save_image_state("fake_page.png")
        state = dict(main.image_states["fake_page.png"])
        viewer_state = dict(state["viewer_state"])
        viewer_state.pop("transform", None)
        viewer_state.pop("center", None)
        state["viewer_state"] = viewer_state
        return state

    state_without_paint = _build_state(False)
    state_with_paint = _build_state(True)

    assert state_without_paint == state_with_paint


# --- Lecture seule renforcée : octets `.ctpr` identiques avant/après activité --


def test_readonly_project_bytes_identical_before_and_after_heavy_paint_and_tick_activity(
    qtbot, tmp_path
):
    """Renforce la garantie « lecture seule » autrement que par comparaison de
    deux instances (faiblesse signalée par l'implementer sur
    `test_project_page_state_identical_with_and_without_attach`) : une seule
    instance, un état de projet construit une fois, sérialisé par le vrai
    code de sauvegarde `.ctpr` (`save_state_to_proj_file_v2`) avant puis après
    une rafale de peinture + ticks de chien de garde + demandes de
    rafraîchissement — les octets du fichier doivent être strictement
    identiques (aucun appel réseau, `image_files` vide : pas de blob image à
    matérialiser, seul l'état de page compte ici)."""
    from app.projects.project_state_v2 import save_state_to_proj_file_v2
    from controller import ComicTranslate
    from modules.utils.textblock import TextBlock

    main = ComicTranslate()
    qtbot.addWidget(main)
    main._skip_close_prompt = True

    blk_done = TextBlock(text="Bonjour", translation="Hello")
    blk_partial = TextBlock(text="Salut", translation="")
    main.image_files = []
    main.curr_img_idx = -1
    main.image_states = {
        "p1.png": {
            "blk_list": [blk_done, blk_partial],
            "viewer_state": {"text_items_state": [{"x": 1}]},
        },
        "p2.png": {"blk_list": [], "viewer_state": {"text_items_state": []}},
    }
    main.image_patches = {}

    page_list = main.page_list
    page_list.clear()
    _add_item(page_list, "p1.png")
    _add_item(page_list, "p2.png", skip=True)
    page_list.resize(_ROW_WIDTH, 240)
    page_list.show()
    qtbot.waitExposed(page_list)

    def _snapshot_states(image_states: dict) -> dict:
        # `TextBlock` n'a pas de `__eq__` par valeur : comparer les
        # attributs (`vars`) plutôt que les instances elles-mêmes, pour ne
        # pas confondre « objets différents » et « données différentes ».
        return {
            path: {
                "blk_list": [dict(vars(blk)) for blk in state.get("blk_list", [])],
                "viewer_state": copy.deepcopy(state.get("viewer_state")),
            }
            for path, state in image_states.items()
        }

    before_states = _snapshot_states(main.image_states)
    before_patches = copy.deepcopy(main.image_patches)

    ctpr_before = str(tmp_path / "before.ctpr")
    save_state_to_proj_file_v2(main, ctpr_before)
    hash_before = hashlib.sha256(Path(ctpr_before).read_bytes()).hexdigest()

    # Rafale : peinture de toutes les lignes, plusieurs ticks du chien de
    # garde, et une rafale de demandes de rafraîchissement.
    delegate = main._page_state_delegate
    option = QtWidgets.QStyleOptionViewItem()
    option.rect = QtCore.QRect(0, 0, _ROW_WIDTH, _ROW_HEIGHT)
    pixmap = QtGui.QPixmap(_ROW_WIDTH, _ROW_HEIGHT)
    painter = QtGui.QPainter(pixmap)
    try:
        for row in range(page_list.count()):
            index = page_list.model().index(row, 0)
            for _ in range(5):
                delegate.paint(painter, option, index)
    finally:
        painter.end()

    watchdog = main._page_state_watchdog
    for _ in range(10):
        watchdog.timeout.emit()

    refresher = main._page_state_refresher
    for _ in range(50):
        refresher.request()
    qtbot.wait(80)

    ctpr_after = str(tmp_path / "after.ctpr")
    save_state_to_proj_file_v2(main, ctpr_after)
    hash_after = hashlib.sha256(Path(ctpr_after).read_bytes()).hexdigest()

    assert hash_after == hash_before, "octets .ctpr modifiés par la peinture/les ticks pagestate"
    assert _snapshot_states(main.image_states) == before_states
    assert main.image_patches == before_patches


# --- Étranglement du rafraîchissement : une rafale => une repeinte par cycle ---


def test_refresher_throttles_burst_of_requests_and_is_not_starved(qtbot):
    class _CountingViewport:
        def __init__(self):
            self.updates = 0

        def update(self):
            self.updates += 1

    class _CountingPageList:
        def __init__(self):
            self._viewport = _CountingViewport()

        def viewport(self):
            return self._viewport

    page_list = _CountingPageList()
    refresher = _Refresher(page_list)

    for _ in range(50):
        refresher.request()
    qtbot.wait(60)
    assert page_list.viewport().updates == 1, "rafale non étranglée à une seule repeinte"

    # Une nouvelle rafale après l'écoulement du minuteur doit reprogrammer
    # une repeinte (pas d'affamement, `request()` relance bien après coup).
    for _ in range(50):
        refresher.request()
    qtbot.wait(60)
    assert page_list.viewport().updates == 2


# --- Chien de garde : ne repeint que si la signature des lignes change ---------


def test_watchdog_repaints_only_when_visible_signature_changes(qtbot, monkeypatch):
    page_list = _make_page_list(qtbot)
    _add_item(page_list, "p.png")

    class _Bare:
        pass

    main = _Bare()
    main.webtoon_mode = False
    main._batch_active = False
    main.blk_list = []
    main.image_data = {}
    main.image_files = ["p.png"]
    main.curr_img_idx = -1
    main.image_patches = {"p.png": []}
    main.image_states = {"p.png": {"blk_list": [], "viewer_state": {"text_items_state": []}}}
    main.page_list = page_list
    main.image_viewer = None

    delegate = attach_page_state(main)
    assert delegate is not None
    watchdog = main._page_state_watchdog
    watchdog.stop()  # ticks manuels seulement, pas de course avec le minuteur réel

    calls = []
    monkeypatch.setattr(page_list.viewport(), "update", lambda: calls.append(1))

    watchdog.timeout.emit()  # première signature (depuis `None`) : repeinte
    assert len(calls) == 1

    watchdog.timeout.emit()  # donnée identique : pas de repeinte
    assert len(calls) == 1

    main.image_states["p.png"]["blk_list"] = [_FakeBlock("Bonjour", "Hello")]
    watchdog.timeout.emit()  # donnée changée : repeinte
    assert len(calls) == 2

    watchdog.timeout.emit()  # de nouveau stable : pas de repeinte
    assert len(calls) == 2


# --- Colonne trop étroite : rien dessiné, aucune exception ---------------------


def test_paint_no_draw_no_exception_when_column_too_narrow(qtbot):
    page_list = _make_page_list(qtbot)
    _add_item(page_list, "p.png")

    inner = page_list.itemDelegate()
    delegate = PageStateDelegate(inner, lambda _path: PageProgress(5, 5, 5, 5, 5), parent=page_list)

    # Largeur de ligne bien inférieure à marge + vignette + espace + 20 px de
    # piste minimale (`_TRACK_MIN_WIDTH`) : `_track_geometry` doit renvoyer
    # `None`, `_paint_track` ne rien peindre, sans lever.
    narrow_width = 30
    pixmap = QtGui.QPixmap(narrow_width, _ROW_HEIGHT)
    painter = QtGui.QPainter(pixmap)
    option = QtWidgets.QStyleOptionViewItem()
    option.rect = QtCore.QRect(0, 0, narrow_width, _ROW_HEIGHT)
    index = page_list.model().index(0, 0)
    try:
        delegate.paint(painter, option, index)
    finally:
        painter.end()  # aucune exception ne doit remonter jusqu'ici


# --- Piste atténuée (pas absente) sur une ligne « à sauter » -------------------


def test_track_present_but_attenuated_for_skipped_done_row(qtbot):
    page_list = _make_page_list(qtbot)
    _add_item(page_list, "done.png")
    _add_item(page_list, "skipped_done.png", skip=True)
    _add_item(page_list, "empty.png")

    done_progress = PageProgress(10, 9, 9, 6, 9)
    empty_progress = PageProgress(0, 0, 0, 0, 0)

    def provider(path: str) -> PageProgress:
        return empty_progress if path == "empty.png" else done_progress

    inner = page_list.itemDelegate()
    delegate = PageStateDelegate(inner, provider, parent=page_list)
    page_list.setItemDelegate(delegate)
    page_list.viewport().update()
    qtbot.wait(20)

    image = page_list.viewport().grab().toImage()

    index_done = page_list.model().index(0, 0)
    index_skipped = page_list.model().index(1, 0)
    index_empty = page_list.model().index(2, 0)
    rect_done = page_list.visualRect(index_done)
    rect_skipped = page_list.visualRect(index_skipped)
    rect_empty = page_list.visualRect(index_empty)

    background = image.pixelColor(rect_empty.left() + 1, rect_empty.top() + 1)

    def _max_diff(rect: QtCore.QRect) -> int:
        y = rect.bottom() - 8
        diffs = []
        for x in range(rect.left() + 60, rect.right() - 4, 4):
            color = image.pixelColor(x, y)
            diffs.append(
                abs(color.red() - background.red())
                + abs(color.green() - background.green())
                + abs(color.blue() - background.blue())
            )
        return max(diffs) if diffs else 0

    diff_done = _max_diff(rect_done)
    diff_skipped = _max_diff(rect_skipped)
    diff_empty = _max_diff(rect_empty)

    # Atténuée (opacité réduite) mais toujours visible : ni aussi marquée que
    # la ligne FAITE non sautée, ni confondue avec une ligne ABSENTE.
    assert diff_skipped > diff_empty, "piste absente sur une ligne sautée FAITE"
    assert diff_skipped < diff_done, "piste sautée pas atténuée par rapport à la ligne non sautée"
