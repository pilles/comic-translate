"""Equivalence masque manuel Qt vs approximation numpy du banc (specs/02 M7).

Ecarte de la collecte par defaut (`tests/conftest.py`), inclus par `--gui`
(cf. CLAUDE.md : `QT_QPA_PLATFORM=offscreen uv run pytest --gui`).

Compare le vrai `DrawingManager.generate_mask_from_strokes()` (Qt,
QGraphicsPathItem + QPainter) a `tools.bench_cleaning._manual_like_mask`
(imk.find_contours -> fill_poly -> dilate). Cible : egalite exacte. Sinon
(cas observe ici), mesure la difference symetrique et l'imprime -- c'est ce
chiffre qui doit remonter dans l'en-tete du rapport du banc (critic pass2 #9).
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6 import QtGui, QtWidgets  # noqa: E402
from PySide6.QtGui import QBrush, QColor, QPen  # noqa: E402
from PySide6.QtWidgets import QGraphicsPathItem  # noqa: E402

import tools.bench_cleaning as bc  # noqa: E402
from app.ui.canvas.image_viewer import ImageViewer  # noqa: E402
from modules.utils.textblock import TextBlock  # noqa: E402


def _letters_image(h, w):
    image = np.full((h, w, 3), 240, np.uint8)
    for i in range(8):
        x = 35 + i * 9
        image[65:82, x : x + 5] = 10
    return image


def _make_viewer(image: np.ndarray) -> ImageViewer:
    h, w = image.shape[:2]
    viewer = ImageViewer(None)
    contiguous = np.ascontiguousarray(image)
    qimage = QtGui.QImage(contiguous.data, w, h, 3 * w, QtGui.QImage.Format_RGB888)
    viewer.setPhoto(QtGui.QPixmap.fromImage(qimage))
    viewer.empty = False
    # Garde une reference vivante (QImage ne copie pas le buffer numpy).
    viewer._test_qimage_backing = contiguous
    return viewer


def _add_segmentation_stroke(viewer: ImageViewer, blk: TextBlock, image: np.ndarray) -> None:
    """Reproduit `draw_segmentation_lines` sans passer par le systeme de
    commandes/undo (qui exige une pile connectee a une fenetre complete) :
    ajoute directement le QGraphicsPathItem issu de `make_segmentation_stroke_data`,
    avec le meme pinceau (couleur 0x80ff0000 = marqueur "trait genere", cf.
    `generate_mask_from_strokes`)."""
    stroke = viewer.drawing_manager.make_segmentation_stroke_data(
        blk, image=image, free_dilate_iterations=3
    )
    assert stroke is not None, (
        "make_segmentation_stroke_data n'a produit aucun trait (crop_mask vide)"
    )
    item = QGraphicsPathItem(stroke["path"])
    item.setPen(QPen(QColor(stroke["pen"]), stroke["width"]))
    item.setBrush(QBrush(QColor(stroke["brush"])))
    viewer._scene.addItem(item)


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_manual_mask_equivalence_measured_gap(qapp, qtbot):
    h, w = 150, 150
    image = _letters_image(h, w)
    blk = TextBlock(
        text_bbox=np.array([30, 60, 110, 90]),
        text_class="text_free",
        text=bc.BENCH_TEXT_MARKER,
        translation=bc.BENCH_TEXT_MARKER,
    )

    viewer = _make_viewer(image)
    qtbot.addWidget(viewer)
    _add_segmentation_stroke(viewer, blk, image)
    assert viewer.drawing_manager.has_drawn_elements()

    qt_mask = viewer.get_mask_for_inpainting(free_dilate_iterations=3)
    assert qt_mask is not None

    bench_mask = bc._manual_like_mask(image, [blk], free_dilate_iterations=3)

    diff_pixels = int(np.count_nonzero(qt_mask != bench_mask))
    union_pixels = int(np.count_nonzero((qt_mask > 0) | (bench_mask > 0)))
    symmetric_diff_ratio = diff_pixels / union_pixels if union_pixels else 0.0

    print(
        f"\n[test_manual_mask_equivalence] ecart mesure (M7) : "
        f"diff_pixels={diff_pixels} union_pixels={union_pixels} "
        f"ratio={symmetric_diff_ratio:.3%}"
    )

    # Constat (critic pass2 #9, a rapporter a l'implementer) : PAS d'egalite
    # exacte. L'ecart mesure sur ce scenario synthetique est tres superieur a
    # l'hypothese de depart de la conception (~0.5%) : de l'ordre de 30-40%.
    # Le seuil ci-dessous fige ce qui est observe (avec marge), il ne
    # constitue pas un objectif de qualite -- voir le rapport du testeur.
    assert symmetric_diff_ratio < 0.60, (
        f"Ecart symetrique {symmetric_diff_ratio:.1%} bien au-dela de la marge "
        "figee pour ce test (0.60) : régression a investiguer."
    )
