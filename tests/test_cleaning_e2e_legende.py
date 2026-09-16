"""Test bout en bout synthétique (specs/02 jalon 2, critic pass1 test (i) /
pass2 §g) : `clean_page` complet (N2 -> bubble_cleanup -> N1) sur une planche
synthétique combinant les trois pièges du défaut d'origine (specs/02 §1) :
cadre de case ONDULÉ (donc hors de portée d'un détecteur axial), une légende
posée 13 px au-dessus de ce cadre, sur un lavis clair (fond légèrement bruité,
pas blanc pur), et une bulle collée au cadre par en dessous.

Aucune image de bench/pages, aucun réseau, aucun modèle ONNX : `bubble_cleanup`
est une fausse fonction (fast-fill minimal), pas `pipeline.inpainting`.
"""

from __future__ import annotations

import numpy as np

from modules.cleaning.apply import clean_page
from modules.cleaning.config import CleaningConfig
from modules.utils.textblock import TextBlock

# Géométrie de la scène (cf. docstring de module).
H, W = 500, 900
BACKGROUND = 215  # lavis clair, pas blanc pur (bruit gaussien ajouté ci-dessous)
BORDER_Y0, BORDER_AMPLITUDE, BORDER_PERIOD, BORDER_THICKNESS = 300, 3, 50, 3
BUBBLE_XYXY = (350, 303, 550, 400)  # collée au cadre par le haut (by1 == bas du cadre)
CAPTION_GAP_ABOVE_BORDER = 13
CAPTION_X1, CAPTION_X2 = 400, 500
CAPTION_HEIGHT = 24


def _blk(xyxy, text_class="text_free", bubble_xyxy=None):
    return TextBlock(
        text_bbox=np.array(xyxy),
        bubble_bbox=np.array(bubble_xyxy) if bubble_xyxy is not None else None,
        text_class=text_class,
        text="x",
        translation="x",
    )


def _border_row_at(x: int) -> int:
    return int(BORDER_Y0 + BORDER_AMPLITUDE * np.sin(2 * np.pi * x / BORDER_PERIOD))


def _build_scene():
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 3, (H, W, 1))
    image = np.clip(BACKGROUND + noise, 0, 255).astype(np.uint8)
    image = np.repeat(image, 3, axis=2)

    # Cadre ondulé (sinusoïde ± amplitude), épaisseur fixe, plein largeur.
    half = BORDER_THICKNESS // 2
    for x in range(W):
        y = _border_row_at(x)
        image[max(0, y - half) : y + half + 1, x] = 20

    bx1, by1, bx2, by2 = BUBBLE_XYXY
    image[by1:by2, bx1:bx2] = 245  # intérieur de bulle, avant fast-fill

    cap_bottom = BORDER_Y0 - BORDER_AMPLITUDE - BORDER_THICKNESS // 2 - CAPTION_GAP_ABOVE_BORDER
    cap_top = cap_bottom - CAPTION_HEIGHT
    for i in range(6):
        gx = CAPTION_X1 + i * 15
        image[cap_top + 5 : cap_top + 15, gx : gx + 8] = 15  # glyphes de la légende

    mask = np.zeros((H, W), np.uint8)
    mask[cap_top:cap_bottom, CAPTION_X1 - 5 : CAPTION_X2 + 5] = 255
    mask[by1:by2, bx1:bx2] = 255  # résidu de texte de bulle, avant fast-fill

    blk_free = _blk([CAPTION_X1, cap_top, CAPTION_X2, cap_bottom], text_class="text_free")
    blk_bubble = _blk(
        [bx1, by1, bx2, by2], text_class="text_bubble", bubble_xyxy=[bx1, by1, bx2, by2]
    )
    return image, mask, [blk_free, blk_bubble], (cap_top, cap_bottom)


def _stub_bubble_cleanup(bx1, by1, bx2, by2, fill_color=245):
    """Fast-fill minimal : remplit l'intérieur de bulle et vide son masque,
    comme `pipeline.inpainting._apply_fast_bubble_cleanup` (non importé ici,
    conception B3 : `bubble_cleanup` est toujours injecté)."""

    def _cleanup(img, msk, blk_list):
        out_img = img.copy()
        out_mask = msk.copy()
        out_img[by1:by2, bx1:bx2] = fill_color
        out_mask[by1:by2, bx1:bx2] = 0
        return out_img, out_mask, 1

    return _cleanup


def test_e2e_caption_flattened_border_continuous_bubble_mask_intact():
    image, mask, blks, (cap_top, cap_bottom) = _build_scene()
    bx1, by1, bx2, by2 = BUBBLE_XYXY
    bubble_cleanup = _stub_bubble_cleanup(bx1, by1, bx2, by2)
    cfg = CleaningConfig(uniform_fill=True, protect_lines=True)

    out_image, out_mask, cleaned_blocks, report = clean_page(
        image, mask, blks, cfg, bubble_cleanup=bubble_cleanup
    )

    # Légende aplatie : le rapport la decide "uni" et son residu de masque est vide.
    caption_reports = [r for r in report if r.bloc == 0]
    assert len(caption_reports) == 1
    assert caption_reports[0].decision == "uni"
    assert not np.any(out_mask[cap_top:cap_bottom, CAPTION_X1 - 5 : CAPTION_X2 + 5])

    # Cadre continu : chaque colonne du cadre ondulé reste sombre (jamais
    # repeinte par le fondu de la légende voisine).
    for x in range(0, W, 5):
        y = _border_row_at(x)
        assert out_image[y, x, 0] <= 40, f"cadre efface en x={x}"

    # Masque et image de la bulle intacts (fast-fill non perturbe par N1).
    assert not np.any(out_mask[by1:by2, bx1:bx2])
    assert np.array_equal(
        out_image[by1:by2, bx1:bx2], np.full((by2 - by1, bx2 - bx1, 3), 245, np.uint8)
    )
    assert cleaned_blocks == 1
