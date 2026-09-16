"""N1 - attribution bloc -> composantes connexes (specs/02 B2, critic pass2 #4).

Toutes les images sont synthetiques (numpy), aucune page de bench/pages, aucun
reseau, aucun modele ONNX.
"""

from __future__ import annotations

import numpy as np

from modules.cleaning.config import CleaningConfig
from modules.cleaning.uniform import (
    REASON_BRUSH,
    REASON_BUBBLE_NEAR,
    REASON_NO_OWNER,
    REASON_RING_TOO_SMALL,
    REASON_SHARED,
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


def _run(image, mask, blk_list, cfg=None, protect_mask=None, protected_halo=None):
    cfg = cfg or CleaningConfig(uniform_fill=True)
    h, w = mask.shape[:2]
    return clean_uniform_components(
        image.copy(),
        mask.copy(),
        blk_list,
        cfg,
        protected_halo=protected_halo
        if protected_halo is not None
        else np.zeros((h, w), dtype=bool),
        protect_mask=protect_mask,
        seed_bounds_fn=_resolve_block_crop_bounds,
        px_retires_n2_by_pixel=np.zeros((h, w), dtype=bool),
    )


def test_component_attributed_to_single_owner_by_seed_and_becomes_uni():
    image = np.full((200, 200, 3), 240, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    blk = _blk([60, 80, 140, 120])

    reports = _run(image, mask, [blk])

    assert len(reports) == 1
    assert reports[0].bloc == 0
    assert reports[0].decision == "uni"
    assert reports[0].skip_reason is None


def test_uni_leaves_no_residual_mask_pixel_in_core():
    image = np.full((200, 200, 3), 240, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    blk = _blk([60, 80, 140, 120])
    mask_copy = mask.copy()

    h, w = mask.shape[:2]
    mutable_mask = mask.copy()
    clean_uniform_components(
        image.copy(),
        mutable_mask,
        [blk],
        CleaningConfig(uniform_fill=True),
        protected_halo=np.zeros((h, w), dtype=bool),
        protect_mask=None,
        seed_bounds_fn=_resolve_block_crop_bounds,
        px_retires_n2_by_pixel=np.zeros((h, w), dtype=bool),
    )

    assert np.any(mask_copy)  # le masque d'origine avait bien du contenu
    assert not np.any(mutable_mask)  # plus rien apres remplissage uni (core entier)


def test_component_shared_by_two_blocks_is_skipped_partagee():
    image = np.full((200, 200, 3), 240, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    # Un seul blob continu, mais deux blocs dont la graine (seed_box) le touche tous les deux.
    mask[80:120, 40:160] = 255
    blk_left = _blk([40, 80, 100, 120])
    blk_right = _blk([100, 80, 160, 120])

    reports = _run(image, mask, [blk_left, blk_right])

    assert len(reports) == 1
    assert reports[0].decision == "skip"
    assert reports[0].skip_reason == REASON_SHARED


def test_component_touching_dilated_bubble_zone_is_skipped_bulle_proche():
    """Jalon 2 (consigne 1/M9) : le test "touche" a ete remplace par une fraction
    (`bubble_overlap_max=0.20`) : recouvrement core/zone-bulle-dilatee = 2/7 = 28.6%,
    nettement au-dessus du plafond -> bulle_proche (voir tests dedies pour le cas
    limite <= 20%, resolu en "uni")."""
    image = np.full((300, 300, 3), 230, np.uint8)
    mask = np.zeros((300, 300), np.uint8)
    # Caption au-dessus de la bulle, 5 px de marge (bubble_ring_exclusion = 7) :
    # place au-dessus (pas a gauche/droite) pour ne pas etre aussi touchee par le
    # seed_box propre de la bulle, qui s'etend horizontalement de bubble_margin
    # (8 px, cf. _resolve_block_crop_bounds) mais reste borne verticalement a
    # l'interieur de la bulle (bubble_inset_y) : les deux seeds ne se recouvrent
    # donc pas, la composante n'a qu'un seul proprietaire (le bloc text_free).
    mask[138:145, 120:180] = 255
    blk_free = _blk([120, 138, 180, 145], text_class="text_free")
    blk_bubble = _blk(
        [130, 150, 170, 250], text_class="text_bubble", bubble_xyxy=[100, 150, 200, 250]
    )

    reports = _run(image, mask, [blk_free, blk_bubble])

    caption_reports = [r for r in reports if r.bloc == 0]
    assert len(caption_reports) == 1
    assert caption_reports[0].decision == "skip"
    assert caption_reports[0].skip_reason == REASON_BUBBLE_NEAR


def test_component_touching_protect_mask_is_skipped_pinceau():
    image = np.full((200, 200, 3), 240, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    blk = _blk([60, 80, 140, 120])
    protect_mask = np.zeros((200, 200), dtype=bool)
    protect_mask[90:100, 90:100] = True  # coup de pinceau humain traversant le core

    reports = _run(image, mask, [blk], protect_mask=protect_mask)

    assert len(reports) == 1
    assert reports[0].decision == "skip"
    assert reports[0].skip_reason == REASON_BRUSH


def test_ring_excludes_bubble_zone_per_critic_consigne_4():
    image = np.full((300, 300, 3), 230, np.uint8)
    # Bande contaminee, UNIQUEMENT dans la zone bulle dilatee de 7 px (x in [93,100),
    # bulle a x=100 - 7 = 93), donc censee etre hors anneau si la consigne #4
    # etait respectee. (Corrige : la plage precedente [83,93) etait hors zone.)
    image[:, 93:100] = 30
    mask = np.zeros((300, 300), np.uint8)
    # Core a 10 px du bord de la bulle (bord bulle x=100) : hors zone d'exclusion
    # (7 px), donc pas skip "bulle_proche" ; mais l'anneau (ring_outer=8) empiete
    # sur la bande contaminee [93,98).
    mask[100:140, 60:90] = 255
    blk_free = _blk([60, 100, 90, 140], text_class="text_free")
    blk_bubble = _blk(
        [100, 50, 200, 150], text_class="text_bubble", bubble_xyxy=[100, 50, 200, 150]
    )

    reports = _run(image, mask, [blk_free, blk_bubble])
    caption_reports = [r for r in reports if r.bloc == 0]
    assert len(caption_reports) == 1
    assert caption_reports[0].skip_reason is None  # pas skip : distance > 7 px
    assert caption_reports[0].decision == "uni"


def test_shared_free_and_bubble_owner_low_overlap_resolves_to_free_owner_uni():
    """(iv) Consigne 1 (jalon 2) : une composante co-revendiquee par UN bloc
    text_free et UN bloc text_bubble (B1' : la graine d'une bulle couvre ~tout
    son bbox, image_utils.py:299-306) n'est plus systematiquement "partagee" —
    resolue par fraction (core ∩ graine bulle / core). Ici ~2 % de recouvrement
    (bien en-dessous de bubble_overlap_max=0.20) : le bloc text_free devient
    proprietaire unique, la composante peut aller jusqu'a "uni"."""
    h, w = 300, 700
    image = np.full((h, w, 3), 230, np.uint8)
    mask = np.zeros((h, w), np.uint8)
    mask[100:110, 50:450] = 255
    blk_free = _blk([50, 100, 450, 110], text_class="text_free")
    bubble_xyxy = [450, 100, 500, 190]  # graine bulle ~2% de recouvrement avec le core
    blk_bubble = _blk(bubble_xyxy, text_class="text_bubble", bubble_xyxy=bubble_xyxy)

    reports = _run(image, mask, [blk_free, blk_bubble])

    caption_reports = [r for r in reports if r.bloc == 0]
    assert len(caption_reports) == 1
    assert caption_reports[0].skip_reason is None
    assert caption_reports[0].decision == "uni"


def test_shared_free_and_bubble_owner_high_overlap_is_bulle_proche():
    """(iv) Meme scenario, ~30 % de recouvrement (graine bulle) : au-dessus du
    plafond (bubble_overlap_max=0.20), skip "bulle_proche" plutot que "uni" ou
    "partagee" (la co-propriete est bien resolue, mais la bulle est trop proche)."""
    h, w = 300, 700
    image = np.full((h, w, 3), 230, np.uint8)
    mask = np.zeros((h, w), np.uint8)
    mask[100:110, 50:450] = 255
    blk_free = _blk([50, 100, 450, 110], text_class="text_free")
    bubble_xyxy = [338, 100, 500, 190]  # graine bulle ~30% de recouvrement avec le core
    blk_bubble = _blk(bubble_xyxy, text_class="text_bubble", bubble_xyxy=bubble_xyxy)

    reports = _run(image, mask, [blk_free, blk_bubble])

    caption_reports = [r for r in reports if r.bloc == 0]
    assert len(caption_reports) == 1
    assert caption_reports[0].decision == "skip"
    assert caption_reports[0].skip_reason == REASON_BUBBLE_NEAR


def test_component_report_records_aire_core_and_zero_distance_for_owned_component():
    """Consigne 10 (jalon 2) : `aire_core`/`distance_bloc_le_plus_proche` doivent
    être renseignés pour une composante possédée (ici superposée au bloc
    propriétaire -> distance 0). `bbox_core` fait l'objet d'un test dédié
    (voir plus bas, valeur exacte compensée cf. `_label_bbox_xyxy`)."""
    image = np.full((200, 200, 3), 240, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    blk = _blk([60, 80, 140, 120])

    reports = _run(image, mask, [blk])

    r = reports[0]
    assert r.aire_core == (120 - 80) * (140 - 60)
    assert r.bbox_core is not None
    assert r.distance_bloc_le_plus_proche == 0.0


def test_component_report_records_distance_even_without_owner_sans_bloc():
    """Consigne 10 (jalon 2) : une composante SANS propriétaire (aucune graine ne
    la touche) doit tout de même exposer `aire_core`/`bbox_core` et une distance
    au bloc le plus proche non nulle (diagnostic, y compris pour les lignes
    "sans_bloc")."""
    image = np.full((200, 200, 3), 240, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255  # composante isolee
    blk_far = _blk([160, 160, 190, 190])  # bloc loin, sa graine ne touche pas la composante

    reports = _run(image, mask, [blk_far])

    assert len(reports) == 1
    r = reports[0]
    assert r.decision == "skip"
    assert r.skip_reason == REASON_NO_OWNER
    assert r.aire_core == (120 - 80) * (140 - 60)
    assert r.bbox_core is not None
    assert r.distance_bloc_le_plus_proche is not None
    assert r.distance_bloc_le_plus_proche > 0.0


def test_bbox_core_matches_exact_core_bounds_not_off_by_one():
    """Bug trouvé par le tester, compensé (hors périmètre de correction pour
    `imkit`, fichier amont non modifié) : `imkit/transforms.py:425-426` calcule
    `width=xmax-xmin+1` / `height=ymax-ymin+1` en supposant que
    `mh.labeled.bbox()` renvoie des bornes INCLUSIVES, alors qu'elles sont
    EXCLUSIVES -> `CC_STAT_WIDTH`/`CC_STAT_HEIGHT` surestimés de 1 px chacun.
    `modules/cleaning/uniform.py::_label_bbox_xyxy` compense (retranche 1,
    borné à >= 1) pour que `bbox_core` (CSV, consigne 10) soit exact."""
    image = np.full((200, 200, 3), 240, np.uint8)
    mask = np.zeros((200, 200), np.uint8)
    mask[80:120, 60:140] = 255
    blk = _blk([60, 80, 140, 120])

    reports = _run(image, mask, [blk])

    assert reports[0].bbox_core == (60, 80, 140, 120)


def test_component_split_by_protected_band_big_chunk_uni_crumb_stays_masked_for_lama():
    """Mission tester #3 (« miettes ») : une légende coupée en deux par une bande
    protégée (N2) devient deux composantes connexes disjointes — le gros morceau
    doit rester éligible et devenir "uni", la miette (isolée, entièrement
    entourée d'une bande protégée à > `ring_outer` px dans toutes les
    directions -> anneau purgé à 0 < `ring_min_pixels`) doit rester "lama"
    (masquée à 255, jamais démasquée sans peinture)."""
    h, w = 300, 400
    image = np.full((h, w, 3), 240, np.uint8)
    mask = np.zeros((h, w), np.uint8)
    # Gros morceau (large, uniforme) : deviendra "uni".
    mask[100:140, 40:200] = 255
    # Miette : petit residu isole (8x8), loin du gros morceau.
    mask[110:118, 214:222] = 255
    # Bande protegee entourant largement la miette (marge > ring_outer=8 px
    # dans toutes les directions) : purge la totalite de son anneau geometrique,
    # sans toucher au gros morceau (qui s'arrete a x=200, loin de x=195).
    protected_halo = np.zeros((h, w), dtype=bool)
    protected_halo[95:145, 205:235] = True
    blk = _blk([40, 100, 222, 140])

    h_, w_ = mask.shape[:2]
    out_image = image.copy()
    out_mask = mask.copy()
    reports = clean_uniform_components(
        out_image,
        out_mask,
        [blk],
        CleaningConfig(uniform_fill=True),
        protected_halo=protected_halo,
        protect_mask=None,
        seed_bounds_fn=_resolve_block_crop_bounds,
        px_retires_n2_by_pixel=np.zeros((h_, w_), dtype=bool),
    )

    assert len(reports) == 2
    big = max(reports, key=lambda r: r.aire_core)
    crumb = min(reports, key=lambda r: r.aire_core)

    assert big.decision == "uni"
    assert not np.any(out_mask[100:140, 40:200])  # gros morceau demasque et peint

    assert crumb.decision == "lama"
    assert crumb.skip_reason == REASON_RING_TOO_SMALL
    assert crumb.n_ring < CleaningConfig().ring_min_pixels
    # La miette reste integralement masquee (255) : jamais demasquee sans peinture.
    assert np.all(out_mask[110:118, 214:222] == 255)
    assert np.array_equal(out_image[110:118, 214:222], image[110:118, 214:222])
