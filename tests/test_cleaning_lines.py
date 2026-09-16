"""N2 - detection/protection des traits fins (specs/02 M2/M3, critic pass2 #8)."""

from __future__ import annotations

import imkit as imk
import numpy as np
import pytest

from modules.cleaning.config import CleaningConfig
from modules.cleaning.lines import apply_line_protection, detect_thin_lines, run_ge
from modules.utils.textblock import TextBlock


def _blk(xyxy, text_class="text_free", bubble_xyxy=None):
    return TextBlock(
        text_bbox=np.array(xyxy),
        bubble_bbox=np.array(bubble_xyxy) if bubble_xyxy is not None else None,
        text_class=text_class,
        text="x",
        translation="x",
    )


@pytest.mark.parametrize("length", [61, 31])
def test_run_ge_equals_morphology_open_for_odd_length(length):
    rng = np.random.default_rng(0)
    dark = rng.random((30, 200)) < 0.3

    got = run_ge(dark, length, axis=1)
    expected = imk.morphology_ex(dark, imk.MORPH_OPEN, np.ones((1, length), np.uint8)) > 0

    assert np.array_equal(got, expected)


def test_run_ge_rejects_even_length():
    with pytest.raises(ValueError):
        run_ge(np.zeros((10, 10), dtype=bool), 10, axis=1)


def test_run_ge_accepts_2d_grayscale_input_without_exception():
    dark = np.zeros((50, 50), dtype=bool)
    dark[10, 5:20] = True
    out = detect_thin_lines(dark, CleaningConfig())
    assert out.shape == (50, 50)


def test_thin_horizontal_line_is_removed_with_halo_glyphs_kept():
    """Trait dans la marge de dilatation du masque, hors bbox texte brute (garde-fou
    M2, jalon 2) : retire du masque. Glyphe (blob compact, hors longueur minimale,
    donc jamais protege quelle que soit sa position) intact."""
    h, w = 300, 300
    image = np.full((h, w, 3), 240, np.uint8)
    image[101:104, :] = 20  # trait fin 3 px sur toute la largeur, hors bbox texte
    image[170:180, 120:130] = 10  # glyphe (blob compact, pas un trait long)
    mask = np.zeros((h, w), np.uint8)
    mask[100:200, 50:250] = 255  # masque (dilate), deborde 8 px au-dessus de la bbox texte
    blk = _blk([50, 108, 250, 192])  # bbox texte brute, plus etroite que le masque
    cfg = CleaningConfig(protect_lines=True)

    protected_halo, removed = apply_line_protection(mask, image, [blk], cfg)

    assert removed > 0
    assert np.any(protected_halo)
    assert not np.any(mask[101:104, 60:240])  # trait retire du masque
    assert np.all(mask[172:178, 122:128] > 0)  # glyphe intact


def test_thick_flat_40x200_is_not_protected():
    h, w = 300, 300
    image = np.full((h, w, 3), 240, np.uint8)
    image[100:140, 20:220] = 20  # aplat 40 (epais) x 200 (long)
    mask = np.zeros((h, w), np.uint8)
    mask[80:160, 0:260] = 255
    blk = _blk([0, 80, 260, 160])
    cfg = CleaningConfig(protect_lines=True)

    protected_halo, removed = apply_line_protection(mask, image, [blk], cfg)

    assert removed == 0
    assert not np.any(protected_halo)


def test_segment_shorter_than_length_is_not_protected():
    h, w = 300, 300
    image = np.full((h, w, 3), 240, np.uint8)
    image[150:152, 100:140] = 20  # longueur 40 < line_length=61
    mask = np.zeros((h, w), np.uint8)
    mask[100:200, 50:250] = 255
    blk = _blk([50, 100, 250, 200])
    cfg = CleaningConfig(protect_lines=True)

    protected_halo, removed = apply_line_protection(mask, image, [blk], cfg)

    assert removed == 0
    assert not np.any(protected_halo)


def _make_tilted_line(h, w, angle_deg, thickness=1.0, length=250):
    """Trait ideal (sans anti-aliasing) incline de `angle_deg`, epaisseur perpendiculaire
    `thickness`. Choisi pour placer la bascule de detection entre 0.5 deg et 2 deg avec
    line_length=61 (sin(theta) = thickness / line_length -> theta_bascule ~ 2.8 deg)."""
    theta = np.deg2rad(angle_deg)
    ys, xs = np.mgrid[0:h, 0:w]
    cx, cy = w / 2, h / 2
    dx = xs - cx
    dy = ys - cy
    along = dx * np.cos(theta) + dy * np.sin(theta)
    perp = -dx * np.sin(theta) + dy * np.cos(theta)
    dark = (np.abs(perp) <= thickness / 2) & (np.abs(along) <= length / 2)
    image = np.full((h, w, 3), 240, np.uint8)
    image[dark] = 20
    return image


def test_line_tilted_half_degree_is_protected():
    h, w = 300, 300
    image = _make_tilted_line(h, w, angle_deg=0.5, thickness=1.0)
    mask = np.zeros((h, w), np.uint8)
    # Fenetre de masque ne couvrant qu'une moitie de la longueur du trait (le
    # trait deborde largement hors du masque -> critere hors-masque satisfait,
    # jalon 2) ET hors de la bbox texte brute (garde-fou M2, jalon 2) : la bbox
    # se termine (y=135) avant que le masque ne commence (y=140).
    mask[140:160, 26:150] = 255
    blk = _blk([26, 50, 150, 135])
    cfg = CleaningConfig(protect_lines=True)

    protected_halo, removed = apply_line_protection(mask, image, [blk], cfg)

    assert removed > 0
    assert np.any(protected_halo)


@pytest.mark.parametrize(
    "line_detector,expected_protected",
    [("runs", False), ("components", True)],
)
def test_line_tilted_two_degrees_protection_depends_on_detector(line_detector, expected_protected):
    """Limite documentee (critic pass2 #8) pour "runs" : avec line_length=61 et une
    epaisseur perpendiculaire de 1 px, la bascule detection/non-detection de
    `run_ge` se situe vers 2.8 deg (sin(theta) = epaisseur / line_length). A 2 deg,
    le trait n'est PLUS detecte comme "long et fin" par `run_ge` (le run horizontal
    a une rangee donnee tombe sous 61 px) : comportement fige, pas pretendu ideal.

    "components" (jalon 2, defaut) leve cette limite : le critere d'etendue (bbox
    de la composante fine) ne depend pas de l'axe, un trait incliné de 2 deg reste
    detecte tant que sa plus grande dimension de bbox >= line_length — ce qui est
    le cas ici (longueur totale 250 px, quasi horizontale)."""
    h, w = 300, 300
    image = _make_tilted_line(h, w, angle_deg=2.0, thickness=1.0)
    mask = np.zeros((h, w), np.uint8)
    mask[140:160, 26:150] = 255
    blk = _blk([26, 50, 150, 135])
    cfg = CleaningConfig(protect_lines=True, line_detector=line_detector)

    protected_halo, removed = apply_line_protection(mask, image, [blk], cfg)

    if expected_protected:
        assert removed > 0
        assert np.any(protected_halo)
    else:
        assert removed == 0
        assert not np.any(protected_halo)


def test_n2_does_not_touch_non_eligible_bubble_component():
    """N2 restreint la bande de detection aux blocs text_free (specs/02 §4) : un
    trait sous un bloc text_bubble ne doit jamais etre retire du masque."""
    h, w = 300, 300
    image = np.full((h, w, 3), 240, np.uint8)
    image[150:153, :] = 20
    mask = np.zeros((h, w), np.uint8)
    mask[100:200, 50:250] = 255
    blk_bubble = _blk([50, 100, 250, 200], text_class="text_bubble")
    cfg = CleaningConfig(protect_lines=True)

    protected_halo, removed = apply_line_protection(mask, image, [blk_bubble], cfg)

    assert removed == 0
    assert not np.any(protected_halo)


def test_m3_line_band_overlapping_bubble_zone_leaves_bubble_mask_untouched():
    """M3 (jalon 2, reecrit ce test qui ne verifiait que l'absence de bande pour
    un bloc bulle, pas le vrai chevauchement M3) : la bande de detection d'une
    legende (text_free) peut deborder jusque dans la zone bulle (bbox ±
    `bubble_ring_exclusion`) d'un bloc voisin ; meme si un trait fin y est
    detecte et protege, le RETRAIT du masque reste restreint a
    bande ∩ ¬bubble_zone (`apply_line_protection`) — le masque de la bulle
    (residu, pas encore nettoye par `bubble_cleanup`) n'est jamais ampute."""
    h, w = 300, 400
    image = np.full((h, w, 3), 240, np.uint8)
    image[200:203, :] = 20  # trait fin, plein largeur, traverse la zone bulle
    mask = np.zeros((h, w), np.uint8)
    mask[190:230, 150:250] = 255  # masque de la bulle (residu, pas encore nettoye)
    # legende dont la bande (bbox ± line_band_margin=69) atteint la zone bulle,
    # sans que sa PROPRE bbox brute (garde-fou M2) ne la recouvre.
    blk_free = _blk([10, 130, 60, 150], text_class="text_free")
    blk_bubble = _blk(
        [150, 190, 250, 230], text_class="text_bubble", bubble_xyxy=[150, 190, 250, 230]
    )
    cfg = CleaningConfig(protect_lines=True)

    protected_halo, removed = apply_line_protection(mask, image, [blk_free, blk_bubble], cfg)

    assert np.any(protected_halo[200:203, :])  # le trait est bien detecte/protege
    assert np.all(mask[190:230, 150:250] > 0)  # masque bulle intact, jamais ampute
    assert removed == 0


def test_m2_guard_line_through_text_bbox_not_protected_10px_above_is():
    """M2 fige (critic pass1, jalon 2) : un trait qui traverse la bbox de texte
    brute perd sa protection a cet endroit (cout accepte, specs/02 §11) ; le
    meme trait, decale de quelques px au-dessus de la bbox (dans la marge de
    dilatation du masque, hors garde-fou), reste protege et retire du masque."""
    h, w = 300, 300
    cfg = CleaningConfig(protect_lines=True)

    image_through = np.full((h, w, 3), 240, np.uint8)
    image_through[150:153, :] = 20  # traverse la bbox texte (rows100:200)
    mask_through = np.zeros((h, w), np.uint8)
    mask_through[100:200, 50:250] = 255
    blk_through = _blk([50, 100, 250, 200])
    _protected_through, removed_through = apply_line_protection(
        mask_through, image_through, [blk_through], cfg
    )
    assert removed_through == 0

    image_above = np.full((h, w, 3), 240, np.uint8)
    image_above[101:104, :] = 20  # hors bbox (retrecie a rows108:192), dans le masque
    mask_above = np.zeros((h, w), np.uint8)
    mask_above[100:200, 50:250] = 255
    blk_above = _blk([50, 108, 250, 192])
    _protected_above, removed_above = apply_line_protection(
        mask_above, image_above, [blk_above], cfg
    )
    assert removed_above > 0


def _wavy_line(h: int, w: int, y0: int, amplitude: float, period: float, thickness: int = 3):
    """Cadre ondulé (sinusoïde) : un bord de case incliné/courbe, hors de portée
    d'un détecteur axial (`run_ge`), mais visible d'une ouverture morphologique
    carrée orientée-libre (`detect_line_components`)."""
    image = np.full((h, w, 3), 240, np.uint8)
    xs = np.arange(w)
    ys = (y0 + amplitude * np.sin(2 * np.pi * xs / period)).astype(int)
    half = thickness // 2
    for x in xs:
        y = int(ys[x])
        image[max(0, y - half) : y + half + 1, x] = 20
    return image


def test_wavy_line_is_protected_by_components_not_by_runs():
    """Trait ondulé (jalon 2) : `run_ge` (axial) ne peut jamais suivre une
    sinusoïde, `detect_line_components` (top-hat par composantes connexes,
    orientation libre) si."""
    h, w = 300, 300
    image = _wavy_line(h, w, y0=150, amplitude=3, period=40, thickness=3)
    mask = np.zeros((h, w), np.uint8)
    mask[140:160, 26:150] = 255
    blk = _blk([26, 50, 150, 135])

    cfg_runs = CleaningConfig(protect_lines=True, line_detector="runs")
    protected_runs, removed_runs = apply_line_protection(mask.copy(), image, [blk], cfg_runs)
    assert removed_runs == 0
    assert not np.any(protected_runs)

    cfg_components = CleaningConfig(protect_lines=True, line_detector="components")
    protected_components, removed_components = apply_line_protection(
        mask.copy(), image, [blk], cfg_components
    )
    assert removed_components > 0
    assert np.any(protected_components)


def test_saturation_cap_abandons_protection_on_band_without_falling_back_to_runs(caplog):
    """(vii) Consigne 5 (jalon 2) : bande hachurée au-dela du plafond
    `line_max_protected_share` (0.35) -> protection ABANDONNEE sur cette bande
    (protected=0), warning journalise, masque NON ampute. Jamais de repli vers
    "runs" (qui protegerait davantage, pas moins — remplace le test "saturation
    -> runs" d'un jalon precedent)."""
    h, w = 400, 400
    image = np.full((h, w, 3), 240, np.uint8)
    for y in range(0, h, 10):
        image[y : y + 3, :] = 20  # hachures paralleles, plein largeur
    mask = np.zeros((h, w), np.uint8)
    mask[140:160, 150:250] = 255
    mask_before = mask.copy()
    blk = _blk([100, 100, 300, 200])
    cfg = CleaningConfig(protect_lines=True)

    with caplog.at_level("WARNING", logger="modules.cleaning"):
        protected_halo, removed = apply_line_protection(mask, image, [blk], cfg)

    assert removed == 0
    assert not np.any(protected_halo)
    assert np.array_equal(mask, mask_before)
    assert any("abandonnee" in record.message for record in caplog.records)
