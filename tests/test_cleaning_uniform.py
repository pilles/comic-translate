"""N1 - remplissage uni : anneau, decision uni/lama, residu_bord (specs/02 B2)."""

from __future__ import annotations

import imkit as imk
import numpy as np

import modules.cleaning.apply as apply_module
from modules.cleaning.apply import clean_page
from modules.cleaning.config import CleaningConfig
from modules.cleaning.uniform import (
    CLIP_ABSENT,
    REASON_CORE_RATIO,
    REASON_QUADRANTS,
    clean_uniform_components,
)
from modules.utils.image_utils import _resolve_block_crop_bounds
from modules.utils.textblock import TextBlock


def _blk(xyxy, text_class="text_free", bubble_xyxy=None):
    return TextBlock(
        text_bbox=np.array(xyxy),
        bubble_bbox=np.array(bubble_xyxy) if bubble_xyxy is not None else None,
        text_class=text_class,
        text="x",
        translation="x",
    )


def _run(image, mask, blk_list, cfg=None, protect_mask=None):
    cfg = cfg or CleaningConfig(uniform_fill=True)
    h, w = mask.shape[:2]
    return clean_uniform_components(
        image.copy(),
        mask.copy(),
        blk_list,
        cfg,
        protected_halo=np.zeros((h, w), dtype=bool),
        protect_mask=protect_mask,
        seed_bounds_fn=_resolve_block_crop_bounds,
        px_retires_n2_by_pixel=np.zeros((h, w), dtype=bool),
    )


def test_ring_excludes_already_masked_pixels_of_another_component():
    """Un pixel deja masque (autre composante, non encore traitee) ne doit pas
    entrer dans le calcul de la mediane/part de l'anneau (ring &= ~(mask>0))."""
    image = np.full((250, 250, 3), 240, np.uint8)
    mask = np.zeros((250, 250), np.uint8)
    mask[80:120, 60:140] = 255  # composante 1 (caption)
    # composante 2 : couleur tres differente, dans le rayon d'anneau de la 1ere
    # (ring_outer=8 par defaut) mais separee par au moins un pixel de fond.
    mask[80:120, 142:150] = 255
    image[80:120, 142:150] = 5

    blk = _blk([60, 80, 140, 120])
    reports = _run(image, mask, [blk])

    # Les deux composantes touchent le meme seed_box (un seul bloc) : chacune est
    # evaluee independamment. Celle qui nous interesse est la plus grande (caption).
    caption_report = max(reports, key=lambda r: r.n_ring)
    assert caption_report.decision == "uni"
    assert caption_report.part == 1.0


def test_black_caption_on_uniform_gray_background_is_uni_with_exact_fill():
    background = 240
    image = np.full((200, 200, 3), background, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    image[80:120, 60:140] = 10  # legende noire
    blk = _blk([60, 80, 140, 120])

    out_image = image.copy()
    out_mask = mask.copy()
    reports = clean_uniform_components(
        out_image,
        out_mask,
        [blk],
        CleaningConfig(uniform_fill=True),
        protected_halo=np.zeros((200, 200), dtype=bool),
        protect_mask=None,
        seed_bounds_fn=_resolve_block_crop_bounds,
        px_retires_n2_by_pixel=np.zeros((200, 200), dtype=bool),
    )

    assert reports[0].decision == "uni"
    filled = out_image[95:105, 90:110]
    assert np.all(np.abs(filled.astype(int) - background) <= 1)
    assert not np.any(out_mask[80:120, 60:140])


def test_black_caption_on_noisy_background_sigma4_is_uni():
    rng = np.random.default_rng(1)
    background = np.full((200, 200, 3), 240.0)
    noise = rng.normal(0, 4, background.shape)
    image = np.clip(background + noise, 0, 255).astype(np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    blk = _blk([60, 80, 140, 120])

    reports = _run(image, mask, [blk])

    assert reports[0].decision == "uni"


def test_linear_gradient_background_is_lama():
    grad_row = np.linspace(0, 255, 200).astype(np.uint8)
    image = np.stack([np.tile(grad_row, (200, 1))] * 3, axis=-1)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    blk = _blk([60, 80, 140, 120])

    reports = _run(image, mask, [blk])

    assert reports[0].decision == "lama"


def test_bimodal_ring_top_paper_bottom_dark_flat_is_lama_by_quadrants():
    """Anneau papier (haut) / aplat sombre (bas) : coherence inter-quadrants
    (ecart_quadrants) au-dessus du seuil -> lama, meme si `part` reste haut
    (tolerance elargie pour isoler precisement le critere quadrants)."""
    image = np.full((300, 300, 3), 240, np.uint8)
    image[:150, :, :] = 245
    image[150:, :, :] = 225
    mask = np.zeros((300, 300), np.uint8)
    mask[130:170, 130:170] = 255
    blk = _blk([130, 130, 170, 170])
    cfg = CleaningConfig(uniform_fill=True, color_tolerance=20)

    reports = _run(image, mask, [blk], cfg=cfg)

    assert reports[0].decision == "lama"
    assert reports[0].skip_reason == REASON_QUADRANTS
    assert reports[0].part >= cfg.uniform_share  # le probleme est bien la coherence
    assert reports[0].ecart_quadrants > cfg.ring_quadrant_max


def test_core_ratio_max_exceeded_is_lama():
    image = np.full((500, 500, 3), 240, np.uint8)
    mask = np.zeros((500, 500), np.uint8)
    mask[100:400, 100:400] = 255  # coeur 300x300, anneau tres etroit relativement
    blk = _blk([100, 100, 400, 400])

    reports = _run(image, mask, [blk])

    assert reports[0].decision == "lama"
    assert reports[0].skip_reason == REASON_CORE_RATIO


def test_residu_bord_bounded_on_uniform_background():
    background = 240
    image = np.full((200, 200, 3), background, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    blk = _blk([60, 80, 140, 120])

    reports = _run(image, mask, [blk])

    assert reports[0].decision == "uni"
    assert reports[0].residu_bord is not None
    assert reports[0].residu_bord <= 3.0


def test_ring_excludes_bubble_zone_not_just_masked_pixels():
    image = np.full((300, 300, 3), 230, np.uint8)
    # dans bubble_zone (bulle a x=100, dilatee de 7 px -> [93, ...)) ; [83,93) était hors zone.
    image[:, 93:100] = 30
    mask = np.zeros((300, 300), np.uint8)
    mask[100:140, 60:90] = 255  # core a 10 px de la bulle (hors zone d'exclusion 7 px)
    blk_free = _blk([60, 100, 90, 140], text_class="text_free")
    blk_bubble = _blk(
        [100, 50, 200, 150], text_class="text_bubble", bubble_xyxy=[100, 50, 200, 150]
    )

    reports = _run(image, mask, [blk_free, blk_bubble])
    caption_reports = [r for r in reports if r.bloc == 0]
    assert caption_reports[0].skip_reason is None
    assert caption_reports[0].decision == "uni"


def _rounded_rect_interior(h, w, x1, y1, x2, y2, radius):
    """Intérieur (bool) d'un rectangle à coins arrondis (SDF simple), angles compris."""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    cx = np.clip(xx, x1 + radius, x2 - radius)
    cy = np.clip(yy, y1 + radius, y2 - radius)
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    return dist <= radius


def _bubble_scene(fill_color: int):
    """Bulle rectangle arrondi (trait 3 px), légende large qui ne mord que de
    quelques px dans son sommet. `bubble_clips` fourni directement (construit
    "à la main", comme le ferait `modules.cleaning.apply` via
    `build_bubble_clip_mask` — ce module reste pur, sans import Qt)."""
    h, w = 400, 700
    x1, y1, x2, y2, radius = 300, 150, 500, 350, 30
    stroke = 3
    outer = _rounded_rect_interior(h, w, x1, y1, x2, y2, radius)
    inner = _rounded_rect_interior(
        h, w, x1 + stroke, y1 + stroke, x2 - stroke, y2 - stroke, radius - stroke
    )
    contour = outer & ~inner

    image = np.full((h, w, 3), 230, np.uint8)
    image[outer] = fill_color
    image[contour] = 20
    mask = np.zeros((h, w), np.uint8)
    mask[130:154, 20:680] = 255  # legende large, mord de quelques px dans le sommet de la bulle

    blk_free = _blk([20, 130, 680, 154], text_class="text_free")
    blk_bubble = _blk([x1, y1, x2, y2], text_class="text_bubble", bubble_xyxy=[x1, y1, x2, y2])
    bubble_clips = {1: (inner.copy(), "segmentation")}
    return image, mask, [blk_free, blk_bubble], bubble_clips, contour, inner


def _run_with_clips(image, mask, blk_list, bubble_clips, cfg=None):
    cfg = cfg or CleaningConfig(uniform_fill=True)
    h, w = mask.shape[:2]
    return clean_uniform_components(
        image,
        mask,
        blk_list,
        cfg,
        protected_halo=np.zeros((h, w), dtype=bool),
        protect_mask=None,
        seed_bounds_fn=_resolve_block_crop_bounds,
        px_retires_n2_by_pixel=np.zeros((h, w), dtype=bool),
        bubble_clips=bubble_clips,
    )


def test_bubble_contour_and_interior_never_modified_strict_equality():
    """(v) Consignes 2/3 (jalon 2) : bulle rectangle arrondi (trait 3 px), légende
    sur son sommet (recouvrement mineur, sous le plafond bubble_overlap_max) ->
    apres N1, AUCUN pixel du contour d'encre ni de l'interieur n'est modifie
    (egalite stricte), meme si le masque de la legende deborde sur la bulle."""
    image, mask, blk_list, bubble_clips, contour, inner = _bubble_scene(fill_color=232)
    image_before = image.copy()

    reports = _run_with_clips(image, mask, blk_list, bubble_clips)

    assert reports[0].decision == "uni"
    assert np.array_equal(image[contour], image_before[contour])
    assert np.array_equal(image[inner], image_before[inner])


def test_core_minus_core_fill_stays_masked_at_255():
    """(vi) Consigne 3 (jalon 2) : `core_fill` (pas `core`) est seul démasqué —
    les pixels de `core` proches du contour de bulle (exclus de `core_fill`)
    restent à 255 dans le masque residuel, pour LaMa."""
    image, mask, blk_list, bubble_clips, _contour, _inner = _bubble_scene(fill_color=232)
    mask_before = mask.copy()

    reports = _run_with_clips(image, mask, blk_list, bubble_clips)

    assert reports[0].decision == "uni"
    core_region = mask_before[130:154, 20:680] > 0
    still_masked = mask[130:154, 20:680] > 0
    core_minus_fill = core_region & still_masked
    assert np.any(core_minus_fill)  # le contour a bien exclu une partie du core
    assert np.all(mask[130:154, 20:680][core_minus_fill] == 255)


def test_bubble_clip_extension_used_when_fastfill_color_matches_ring():
    """Extension du contour de bulle (consigne 2) : couleur du fast-fill de la
    bulle proche de la médiane de l'anneau (<= color_tolerance) -> le clip
    (segmentation) dilaté est utilisé comme zone de non-remplissage."""
    image, mask, blk_list, bubble_clips, _contour, _inner = _bubble_scene(fill_color=232)

    reports = _run_with_clips(image, mask, blk_list, bubble_clips)

    assert reports[0].clip_bulle == "segmentation"


def test_bubble_color_fallback_used_when_fastfill_color_differs_from_ring():
    """Repli bulle colorée (consigne 2/9) : couleur du fast-fill de la bulle trop
    éloignée de la médiane de l'anneau (> color_tolerance) -> repli explicite sur
    la zone bulle entière (bbox dilatée), pas le contour fin."""
    image, mask, blk_list, bubble_clips, contour, inner = _bubble_scene(fill_color=250)
    image_before = image.copy()

    reports = _run_with_clips(image, mask, blk_list, bubble_clips)

    assert reports[0].clip_bulle == "repli_couleur"
    # le repli reste plus large mais protège toujours le contour/l'interieur.
    assert np.array_equal(image[contour], image_before[contour])
    assert np.array_equal(image[inner], image_before[inner])


def _mirror_blk(blk, w):
    x1, y1, x2, y2 = [int(v) for v in blk.xyxy[:4]]
    return _blk([w - x2, y1, w - x1, y2], text_class=blk.text_class)


def test_label_order_does_not_change_per_component_decisions():
    """M5 (jalon 2) : l'anneau et `no_touch` sont calculés sur `mask_entry` (figé
    à l'entrée de N1), jamais sur le masque live — la décision de chaque
    composante ne doit pas dépendre de l'ORDRE dans lequel les labels sont
    visités. Vérifié en miroir (image/masque/blocs retournés horizontalement) :
    l'étiquette mahotas attribuée à chaque composante s'inverse (celle qui était
    balayée en premier passe en second), le rapport par bloc doit rester
    identique au pixel près."""
    h, w = 300, 500
    image = np.full((h, w, 3), 230, np.uint8)
    mask = np.zeros((h, w), np.uint8)
    mask[100:120, 50:150] = 255  # composante A
    mask[100:120, 155:255] = 255  # composante B (ecart 5 px < ring_outer=8)
    image[100:120, 155:175] = 50  # coloration distincte pres de l'ecart (cote B)
    blk_a = _blk([50, 100, 150, 120], text_class="text_free")
    blk_b = _blk([155, 100, 255, 120], text_class="text_free")

    reports = _run(image, mask, [blk_a, blk_b])
    report_a = next(r for r in reports if r.bloc == 0)
    report_b = next(r for r in reports if r.bloc == 1)

    image_m = image[:, ::-1, :].copy()
    mask_m = mask[:, ::-1].copy()
    blk_a_m = _mirror_blk(blk_a, w)
    blk_b_m = _mirror_blk(blk_b, w)
    reports_m = _run(image_m, mask_m, [blk_a_m, blk_b_m])
    report_a_m = next(r for r in reports_m if r.bloc == 0)
    report_b_m = next(r for r in reports_m if r.bloc == 1)

    assert (report_a.decision, report_a.n_ring, report_a.mediane, report_a.part) == (
        report_a_m.decision,
        report_a_m.n_ring,
        report_a_m.mediane,
        report_a_m.part,
    )
    assert (report_b.decision, report_b.n_ring, report_b.mediane, report_b.part) == (
        report_b_m.decision,
        report_b_m.n_ring,
        report_b_m.mediane,
        report_b_m.part,
    )


def test_bubble_clip_absent_falls_back_to_full_bubble_zone():
    """Consigne 9 (jalon 2) : `bubble_clips` sans entrée pour la bulle (repli
    explicite, intérieur absent) -> `clip_bulle == "absent"`, et le repli reste
    au moins aussi protecteur que le clip fin (contour ET intérieur intacts)."""
    image, mask, blk_list, _bubble_clips, contour, inner = _bubble_scene(fill_color=232)
    image_before = image.copy()

    reports = _run_with_clips(image, mask, blk_list, bubble_clips={})

    assert reports[0].decision == "uni"
    assert reports[0].clip_bulle == CLIP_ABSENT
    assert np.array_equal(image[contour], image_before[contour])
    assert np.array_equal(image[inner], image_before[inner])


def test_bubble_clip_computed_once_per_bubble_regardless_of_component_count(monkeypatch):
    """Consigne 8 (jalon 2) : le clip de bulle est calculé UNE fois par bulle
    (deux appels : clip réel + ellipse de repli pour classifier l'origine),
    jamais une fois par composante N1 attribuée à cette bulle. Deux légendes
    distinctes, toutes deux dans la zone d'une même bulle, ne doivent pas faire
    grimper le nombre d'appels à `build_bubble_clip_mask`."""
    calls = {"n": 0}
    original = apply_module.build_bubble_clip_mask

    def _counting(*args, **kwargs):
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(apply_module, "build_bubble_clip_mask", _counting)

    h, w = 400, 900
    image = np.full((h, w, 3), 230, np.uint8)
    mask = np.zeros((h, w), np.uint8)
    # Deux composantes de legende distinctes (separees, chacune eligible seule).
    mask[100:120, 40:140] = 255
    mask[100:120, 200:300] = 255
    bx1, by1, bx2, by2 = 400, 90, 600, 200
    blk1 = _blk([40, 100, 140, 120], text_class="text_free")
    blk2 = _blk([200, 100, 300, 120], text_class="text_free")
    blk_bubble = _blk(
        [bx1, by1, bx2, by2], text_class="text_bubble", bubble_xyxy=[bx1, by1, bx2, by2]
    )

    cfg = CleaningConfig(uniform_fill=True)
    _out_image, _out_mask, _cleaned, report = clean_page(image, mask, [blk1, blk2, blk_bubble], cfg)

    assert len(report) >= 2  # les deux legendes ont bien ete evaluees separement
    assert calls["n"] == 2  # 1 bulle x (clip reel + ellipse de repli), jamais par composante


def test_bubble_contour_never_repainted_with_heavy_manual_redilate():
    """Robustesse (mission tester #4) : un masque redilate a la main (noyau 5x5,
    iterations=6, comme `generate_mask_from_strokes` en flux manuel — critic
    pass2 consigne 12) empiete largement sur la zone bulle, bien au-dela de
    `bubble_ring_exclusion` (7 px). Le contour/l'interieur de la bulle restent
    protege PAR CONSTRUCTION (clip reel, pas `protected`/la marge), quelle que
    soit l'ampleur du debordement du masque."""
    image, mask, blk_list, bubble_clips, contour, inner = _bubble_scene(fill_color=232)
    image_before = image.copy()

    kernel = np.ones((5, 5), np.uint8)
    mask_redilated = imk.dilate(mask, kernel, iterations=6)

    reports = _run_with_clips(image, mask_redilated, blk_list, bubble_clips)

    assert any(r.decision == "uni" for r in reports)
    assert np.array_equal(image[contour], image_before[contour])
    assert np.array_equal(image[inner], image_before[inner])
