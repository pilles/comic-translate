"""Invariants specs/02 : masque generate_mask, equivalence clean_page inerte,
et observation critic pass2 consigne #5 (legende proche d'une bulle)."""

from __future__ import annotations

import numpy as np

from modules.cleaning.config import INERT
from modules.cleaning.apply import clean_page
from modules.utils.image_utils import generate_mask
from modules.utils.textblock import TextBlock
from pipeline.inpainting import InpaintingHandler


def _letters_image(h, w, y0=65, y1=82, x0=35, n=8, step=9, glyph_w=5):
    """Motif de blocs sombres espaces ('lettres') : le detecteur de contenu
    (modules/detection/utils/content.py) rejette un aplat solide (pas assez
    'texte'), il faut des composantes separees pour obtenir un masque non vide."""
    image = np.full((h, w, 3), 240, np.uint8)
    for i in range(n):
        x = x0 + i * step
        image[y0:y1, x : x + glyph_w] = 10
    return image


def _blk(xyxy, text_class="text_free", bubble_xyxy=None):
    return TextBlock(
        text_bbox=np.array(xyxy),
        bubble_bbox=np.array(bubble_xyxy) if bubble_xyxy is not None else None,
        text_class=text_class,
        text="x",
        translation="x",
    )


def test_generate_mask_default_matches_explicit_free_dilate_iterations_3():
    h, w = 200, 200
    image = _letters_image(h, w)
    blk_free = _blk([30, 60, 110, 90], text_class="text_free")
    blk_bubble = _blk(
        [60, 120, 160, 150],
        text_class="text_bubble",
        bubble_xyxy=[50, 100, 170, 160],
    )
    image[120:150, 60:160] = 10
    blks = [blk_free, blk_bubble]

    m_default = generate_mask(image, blks)
    m_explicit_3 = generate_mask(image, blks, free_dilate_iterations=3)

    assert m_default.tobytes() == m_explicit_3.tobytes()


def test_clean_page_inert_matches_direct_apply_fast_bubble_cleanup_byte_for_byte():
    h, w = 200, 200
    image = _letters_image(h, w)
    blk_free = _blk([30, 60, 110, 90], text_class="text_free")
    blk_bubble = _blk(
        [60, 120, 160, 150],
        text_class="text_bubble",
        bubble_xyxy=[50, 100, 170, 160],
    )
    image[120:150, 60:160] = 10
    blks = [blk_free, blk_bubble]
    mask = generate_mask(image, blks)
    assert np.any(mask)

    handler = InpaintingHandler(None)
    direct_image, direct_mask, direct_cleaned = handler._apply_fast_bubble_cleanup(
        image, mask, blks
    )
    via_image, via_mask, via_cleaned, via_report = clean_page(
        image, mask, blks, INERT, bubble_cleanup=handler._apply_fast_bubble_cleanup
    )

    assert direct_image.tobytes() == via_image.tobytes()
    assert direct_mask.tobytes() == via_mask.tobytes()
    assert direct_cleaned == via_cleaned
    assert via_report == []


def test_caption_8px_from_200px_bubble_bubble_path_inputs_observed_unchanged():
    """Critic pass2 consigne #5 : une composante situee entre bubble_ring_exclusion
    (7 px) et ~5% de la taille de la bulle peut en theorie etre absorbee par
    `_get_associated_residual_components` (rayon 17 px) lors du fast-fill de la
    bulle. Ce test ne force PAS un resultat : il execute le scenario documente
    (legende text_free a 8 px d'une bulle de 200 px) et enregistre l'observation.

    Observation (calibree lors de l'ecriture de ce test) : avec cette geometrie,
    le residu de masque de la legende ressort byte-identique juste apres l'appel
    a `_apply_fast_bubble_cleanup` (avant meme N1) : le chemin bulle ne l'a pas
    touche. Ceci ne garantit rien pour d'autres geometries (cf. consigne #5) --
    seul un ecart mesure justifierait une alerte, pas cette seule execution."""
    h, w = 400, 400
    image = np.full((h, w, 3), 235, np.uint8)
    bx1, by1, bx2, by2 = 100, 100, 300, 300  # bulle 200x200
    image[by1:by2, bx1:bx2] = 250
    image[180:190, 150:250] = 20  # texte de bulle (stroke, pour le fast-fill)

    cap_x2 = bx1 - 8  # 8 px de la bulle
    cap_x1 = cap_x2 - 60
    image[150:170, cap_x1:cap_x2] = 15

    mask = np.zeros((h, w), np.uint8)
    mask[180:190, 150:250] = 255
    mask[150:170, cap_x1:cap_x2] = 255
    caption_area_before = int(np.count_nonzero(mask[150:170, cap_x1:cap_x2]))

    blk_bubble = _blk(
        [150, 180, 250, 190], text_class="text_bubble", bubble_xyxy=[bx1, by1, bx2, by2]
    )
    blk_caption = _blk([cap_x1, 150, cap_x2, 170], text_class="text_free")
    blks = [blk_caption, blk_bubble]

    handler = InpaintingHandler(None)
    _cleaned_image, residual_mask, cleaned_blocks = handler._apply_fast_bubble_cleanup(
        image, mask, blks
    )

    caption_area_after_bubble_path = int(np.count_nonzero(residual_mask[150:170, cap_x1:cap_x2]))
    # Observation figee pour ce scenario precis : le chemin bulle seul (avant N1)
    # laisse la legende entierement intacte.
    assert caption_area_after_bubble_path == caption_area_before
    assert cleaned_blocks == 1  # la bulle, elle, a bien ete traitee
