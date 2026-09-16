"""Contrat de `clean_page` (specs/02 B4, critic pass2 consigne #2)."""

from __future__ import annotations

import numpy as np

from modules.cleaning.apply import clean_page
from modules.cleaning.config import INERT, CleaningConfig
from modules.utils.textblock import TextBlock


def _blk(xyxy, text_class="text_free"):
    return TextBlock(text_bbox=np.array(xyxy), text_class=text_class, text="x", translation="x")


def test_inert_without_bubble_cleanup_is_object_identity():
    image = np.full((50, 50, 3), 200, np.uint8)
    mask = np.zeros((50, 50), np.uint8)
    mask[10:20, 10:20] = 255

    out_image, out_mask, cleaned_blocks, report = clean_page(image, mask, [], INERT)

    assert out_image is image
    assert out_mask is mask
    assert cleaned_blocks == 0
    assert report == []


def test_inert_with_injected_bubble_cleanup_returns_verbatim_triplet():
    image = np.full((50, 50, 3), 200, np.uint8)
    mask = np.zeros((50, 50), np.uint8)
    mask[10:20, 10:20] = 255

    def fake_bubble_cleanup(img, msk, blk_list):
        # Renvoie un 3-uplet fraichement construit (copie), jamais les entrees.
        return img.copy(), msk.copy(), 7

    out_image, out_mask, cleaned_blocks, report = clean_page(
        image, mask, [], INERT, bubble_cleanup=fake_bubble_cleanup
    )

    # `clean_page` ne doit ajouter aucune copie/transformation par-dessus le
    # 3-uplet produit par bubble_cleanup : verifie via une deuxieme execution
    # independante de la meme fonction factice, comparee octet pour octet.
    expected_image, expected_mask, expected_cleaned = fake_bubble_cleanup(image, mask, None)
    assert out_image.tobytes() == expected_image.tobytes()
    assert out_mask.tobytes() == expected_mask.tobytes()
    assert cleaned_blocks == expected_cleaned == 7
    assert report == []


def test_inert_with_passthrough_bubble_cleanup_preserves_identity():
    """Si `bubble_cleanup` ne copie pas lui-meme, `clean_page` ne doit pas non
    plus copier : identite d'objet bout en bout (aucun court-circuit, aucune
    copie ajoutee)."""
    image = np.full((50, 50, 3), 200, np.uint8)
    mask = np.zeros((50, 50), np.uint8)
    mask[10:20, 10:20] = 255

    def passthrough(img, msk, blk_list):
        return img, msk, 3

    out_image, out_mask, cleaned_blocks, report = clean_page(
        image, mask, [], INERT, bubble_cleanup=passthrough
    )

    assert out_image is image
    assert out_mask is mask
    assert cleaned_blocks == 3
    assert report == []


def test_active_config_never_mutates_received_image_or_mask():
    image = np.full((100, 100, 3), 240, np.uint8)
    image[40:60, 40:60] = 10
    mask = np.zeros((100, 100), np.uint8)
    mask[40:60, 40:60] = 255
    blk = _blk([40, 40, 60, 60])
    cfg = CleaningConfig(uniform_fill=True, protect_lines=True)

    image_before = image.tobytes()
    mask_before = mask.tobytes()

    out_image, out_mask, cleaned_blocks, report = clean_page(image, mask, [blk], cfg)

    assert image.tobytes() == image_before
    assert mask.tobytes() == mask_before
    assert out_image is not image
    assert out_mask is not mask


def test_active_config_copies_even_when_all_components_decide_lama():
    """Documente le comportement reel : la conception B4.3 vise une copie
    paresseuse ("a la premiere ecriture reelle"), mais `clean_page`
    (modules/cleaning/apply.py) copie inconditionnellement `image`/`mask` des
    qu'un `bubble_cleanup` absent et une config active sont combines (copies
    faites avant meme de savoir si N1 va ecrire quoi que ce soit). Meme quand
    toutes les composantes decident "lama" (aucune ecriture N1), `out_image`
    n'est donc PAS le meme objet que `image`. Ce n'est pas teste comme un bug
    (le contrat n'exige l'identite que pour le cas inerte), seulement documente
    pour ne pas laisser une regression future se re-presenter comme "attendue"."""
    grad_row = np.linspace(0, 255, 100).astype(np.uint8)
    image = np.stack([np.tile(grad_row, (100, 1))] * 3, axis=-1)
    mask = np.zeros((100, 100), np.uint8)
    mask[40:60, 40:60] = 255
    blk = _blk([40, 40, 60, 60])
    cfg = CleaningConfig(uniform_fill=True)

    out_image, out_mask, cleaned_blocks, report = clean_page(image, mask, [blk], cfg)

    assert all(r.decision == "lama" for r in report)
    assert out_image is not image


def test_active_config_mask_never_grows_pixelwise():
    """Mission tester #2 : non-regression du contrat `clean_page` en mode actif.
    `out_mask` ne peut jamais AJOUTER de pixel masque par rapport a `mask`
    (N1/N2 ne font que retirer du masque, jamais en ajouter) — verifie pixel a
    pixel, sur une planche qui exerce a la fois N2 (trait fin protege puis
    retire du masque, hors de la bbox texte) et N1 (legende uniforme -> uni)."""
    h, w = 300, 400
    image = np.full((h, w, 3), 235, np.uint8)
    image[100:103, :] = 20  # trait long fin, plein largeur, hors bbox texte -> protege puis retire
    image[150:170, 50:350] = 12  # legende sombre, uniforme
    mask = np.zeros((h, w), np.uint8)
    mask[95:200, 40:360] = 255  # masque residuel dilate, deborde sur le trait
    blk = _blk([50, 150, 350, 170])
    cfg = CleaningConfig(uniform_fill=True, protect_lines=True)
    mask_before = mask.copy()

    out_image, out_mask, cleaned_blocks, report = clean_page(image, mask, [blk], cfg)

    assert not np.any((out_mask > 0) & (mask_before == 0))  # jamais de pixel masque ajoute
    # Sanity : le scenario n'est pas degenere, le masque a bien diminue quelque part.
    assert int(np.count_nonzero(out_mask)) < int(np.count_nonzero(mask_before))
