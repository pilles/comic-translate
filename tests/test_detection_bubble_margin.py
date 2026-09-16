"""MIN_BUBBLE_MARGIN_PX - rejet des fausses bulles RT-DETR calées sur une
legende narrative (marge bulle/texte < 3 px), specs/00 (bug diagnostique en
session). Toutes les boites sont synthetiques, aucun modele ONNX charge,
aucune page reelle.
"""

from __future__ import annotations

import numpy as np

from modules.detection.base import DetectionEngine
from modules.utils.textblock import TextBlock


class _FakeEngine(DetectionEngine):
    """Sous-classe concrete minimale : ne charge aucun modele."""

    def initialize(self, **kwargs) -> None:  # pragma: no cover - non utilise
        pass

    def detect(self, image: np.ndarray) -> list[TextBlock]:  # pragma: no cover
        pass


def _engine() -> _FakeEngine:
    return _FakeEngine(settings=None)


def _image(size: int = 300) -> np.ndarray:
    # Image plate suffisante pour extract_foreground_color (h,w >= 6).
    return np.full((size, size, 3), 200, dtype=np.uint8)


def _single_block(text_box, bubble_box) -> TextBlock:
    engine = _engine()
    image = _image()
    text_boxes = np.array([text_box])
    bubble_boxes = np.array([bubble_box])
    blocks = engine.create_text_blocks(image, text_boxes, bubble_boxes)
    assert len(blocks) == 1
    return blocks[0]


def test_bubble_margin_10px_is_text_bubble() -> None:
    # (a) bulle large, marge confortable (10 px de chaque cote) -> text_bubble
    text_box = [50, 50, 150, 100]
    bubble_box = [40, 40, 160, 110]
    blk = _single_block(text_box, bubble_box)

    assert blk.text_class == "text_bubble"
    assert blk.bubble_xyxy is not None
    assert list(blk.bubble_xyxy) == bubble_box


def test_bubble_margin_1px_is_text_free() -> None:
    # (b) bulle calee a 1 px du texte (signature de la fausse bulle mesuree
    # sur l'album de test) -> text_free, pas de bubble_xyxy
    text_box = [50, 50, 150, 100]
    bubble_box = [49, 49, 151, 101]
    blk = _single_block(text_box, bubble_box)

    assert blk.text_class == "text_free"
    assert blk.bubble_xyxy is None


def test_bubble_overlap_with_negative_margin_on_one_side_is_text_free() -> None:
    # (c) texte chevauchant une bulle avec IoU >= 0.2 (branche
    # do_rectangles_overlap) mais qui deborde de la bulle de 5 px sur un
    # seul cote -> marge minimale negative (-5) < 3 px.
    #
    # Comportement choisi : on rejette aussi ce cas. Le seuil de marge ne
    # distingue pas "vraie bulle mal cadree par le detecteur" de "fausse
    # bulle sur legende" - la mesure (specs/00) ne couvre que les cas de
    # confinement quasi total. On accepte donc de perdre occasionnellement
    # une vraie bulle a bord tres proche du texte (rare, cf. mesure : aucune
    # vraie bulle sous 4 px dans l'album de test) plutot que de garder les
    # fausses bulles. Le bloc redevient text_free (nettoyage par mode texte
    # libre, pas d'ellipse inscrite fautive).
    text_box = [50, 50, 150, 100]
    bubble_box = [40, 40, 145, 110]
    blk = _single_block(text_box, bubble_box)

    assert blk.text_class == "text_free"
    assert blk.bubble_xyxy is None


def test_bubble_margin_exactly_3px_is_text_bubble() -> None:
    # (d) borne : marge minimale exactement egale au seuil -> acceptee
    # (< 3 px rejette, donc 3 px pile est encore une bulle valide)
    text_box = [50, 50, 150, 100]
    bubble_box = [47, 47, 153, 103]
    blk = _single_block(text_box, bubble_box)

    assert blk.text_class == "text_bubble"
    assert blk.bubble_xyxy is not None
    assert list(blk.bubble_xyxy) == bubble_box


def test_no_bubble_boxes_all_text_free() -> None:
    # Garde-fou : sans bulle candidate, comportement inchange.
    engine = _engine()
    image = _image()
    text_boxes = np.array([[50, 50, 150, 100]])
    blocks = engine.create_text_blocks(image, text_boxes, np.array([]))

    assert len(blocks) == 1
    assert blocks[0].text_class == "text_free"
    assert blocks[0].bubble_xyxy is None
