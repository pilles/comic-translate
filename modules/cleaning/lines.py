"""N2 — détection et protection des longs traits fins sombres (bords de case).

Pur numpy/imkit/mahotas. Aucun import Qt ni pipeline (contrainte de conception,
`clean_page` est appelé depuis le worker comme depuis l'UI).
"""

from __future__ import annotations

import logging

import numpy as np
import imkit as imk

from .config import CleaningConfig

logger = logging.getLogger("modules.cleaning")


def run_ge(dark: np.ndarray, length: int, axis: int) -> np.ndarray:
    """Marque tout pixel appartenant à une plage `dark` contiguë de longueur >= `length`.

    Équivalent en O(N) numpy de `imk.morphology_ex(dark, imk.MORPH_OPEN, ones((1, L)))`
    (axis=1, plages horizontales) ou son symétrique vertical (axis=0). L'équivalence
    exacte avec l'ouverture morphologique n'est garantie QUE pour `length` impair
    (assert ci-dessous) : un noyau pair n'a pas de centre unique, l'alignement de
    mahotas et celui de cette implémentation diffèrent alors potentiellement de 1 px
    (critic pass2 consigne #8).

    Convention (consigne #8) : le tableau est aplati après un padding d'une colonne
    nulle de chaque côté de chaque ligne (empêche une plage de "déborder" d'une ligne
    à l'autre une fois aplati, et garantit une transition franche aux deux bords de
    l'image). `diff(flat.astype(int8))` : `d[i] = flat[i+1] - flat[i]`, donc une plage
    commence à l'indice `i+1` où `d[i] == 1`. L'accumulateur `+1`/`-1` est en `int8` :
    les plages retenues sont disjointes par construction (elles sont séparées par au
    moins un pixel faux), le cumsum ne peut donc valoir que 0 ou 1.
    """
    if length % 2 != 1:
        raise ValueError(f"run_ge: length doit être impair (reçu {length})")
    if axis == 0:
        return run_ge(dark.T, length, axis=1).T
    if axis != 1:
        raise ValueError(f"axis doit valoir 0 ou 1, reçu {axis}")

    h, w = dark.shape
    padded = np.zeros((h, w + 2), dtype=np.int8)
    padded[:, 1:-1] = dark.astype(np.int8)
    flat = padded.reshape(-1)

    diff = np.diff(flat)
    starts = np.flatnonzero(diff == 1) + 1
    ends = np.flatnonzero(diff == -1) + 1

    run_lengths = ends - starts
    keep = run_lengths >= length

    acc = np.zeros(flat.shape[0], dtype=np.int8)
    acc[starts[keep]] += 1
    acc[ends[keep]] -= 1
    # fork (sécurité mineure #6) : np.cumsum promeut silencieusement un int8 en
    # int64 par défaut (8x la RSS). Les plages sont disjointes (docstring
    # ci-dessus) : le cumsum ne visite jamais que {0, 1}, un int8 explicite
    # suffit et ne déborde pas.
    mask_flat = np.cumsum(acc, dtype=np.int8) > 0

    out_padded = mask_flat.reshape(h, w + 2)
    return out_padded[:, 1:-1]


def detect_thin_lines(dark: np.ndarray, cfg: CleaningConfig) -> np.ndarray:
    """Top-hat directionnel (critic pass2 consigne M2) : longs traits FINS uniquement.

    Un aplat sombre (silhouette, ombre) contient souvent une plage horizontale
    sombre >= line_length, mais il est aussi épais verticalement (>= line_max_thickness
    de haut en bas à cet endroit) : on l'exclut en exigeant l'absence d'une plage
    perpendiculaire longue de longueur >= line_max_thickness au même pixel.

    Limite connue et documentée (jalon 2, consigne 7) : ce détecteur ne voit que des
    traits AXIAUX (horizontaux/verticaux) ; un trait incliné ou ondulé (cadre courbe)
    lui échappe presque toujours — c'est la raison d'être de `detect_line_components`
    (`line_detector="components"`, défaut désormais). Conservé tel quel (algorithme
    inchangé) pour `line_detector="runs"`, comparaison de mesure (`--n2-impl`).
    """
    long_h = run_ge(dark, cfg.line_length, axis=1)
    thick_v = run_ge(dark, cfg.line_max_thickness, axis=0)
    trait_h = long_h & ~thick_v

    long_v = run_ge(dark, cfg.line_length, axis=0)
    thick_h = run_ge(dark, cfg.line_max_thickness, axis=1)
    trait_v = long_v & ~thick_h

    return trait_h | trait_v


def detect_line_components(
    dark: np.ndarray,
    cfg: CleaningConfig,
    mask_crop: np.ndarray,
) -> np.ndarray:
    """N2 v2 (jalon 2, critic pass2 étape 1) : traits fins par composantes connexes.

    Généralise `detect_thin_lines` aux traits NON axiaux (cadre ondulé, incliné) :
    une ouverture morphologique par élément carré `(2T+1)x(2T+1)` (T = line_max_thickness)
    élimine toute structure trop fine pour ce carré, quelle que soit son orientation ;
    `dark & ~OPEN(dark, carré)` (top-hat) isole donc ce résidu fin, y compris pour un
    trait courbe ou incliné (contrairement à `run_ge`, limité aux plages axiales).

    Deux garde-fous par composante connexe du résidu fin :
    - étendue (plus grande dimension de la bbox de la composante) >= `line_length` —
      un jambage de lettre est fin mais court, un bord de case est fin et long ;
    - part HORS de `mask_crop` (masque résiduel courant, avant N2) >= `line_outside_min`
      x aire de la composante — un jambage de lettre est entièrement contenu dans le
      masque de son propre bloc (part hors-masque ~= 0), un bord de case déborde
      largement de la zone de texte (part hors-masque élevée). Sans ce filtre, un
      trait épais de glyphe serait protégé lui aussi.
    """
    thickness = max(1, int(cfg.line_max_thickness))
    ksize = 2 * thickness + 1
    square = np.ones((ksize, ksize), np.uint8)
    opened = imk.morphology_ex(dark.astype(np.uint8) * 255, imk.MORPH_OPEN, square) > 0
    thin = dark & ~opened
    out = np.zeros_like(dark)
    if not np.any(thin):
        return out

    num_labels, labels = imk.connected_components(thin, connectivity=8)
    if num_labels <= 1:
        return out

    mask_bool = mask_crop > 0
    for label in range(1, num_labels):
        comp = labels == label
        ys, xs = np.nonzero(comp)
        if ys.size == 0:
            continue
        # Le "+1" ici est correct et INDEPENDANT du bug imkit documenté dans
        # `modules/cleaning/uniform.py::_label_bbox_xyxy` (CC_STAT_WIDTH/HEIGHT
        # de `connected_components_with_stats`, surestimés de 1 px) : cette
        # fonction utilise `imk.connected_components` (pas `_with_stats`) et
        # calcule l'étendue directement à partir des indices de pixels
        # (min/max INCLUSIFS via np.nonzero), pas depuis une bbox mahotas
        # exclusive — le +1 convertit ici un écart d'indices en un nombre de
        # pixels, ce qui est le comportement voulu.
        extent = max(int(ys.max() - ys.min()) + 1, int(xs.max() - xs.min()) + 1)
        if extent < cfg.line_length:
            continue
        area = int(ys.size)
        outside = int(np.count_nonzero(~mask_bool[ys, xs]))
        if outside < cfg.line_outside_min * area:
            continue
        out |= comp
    return out


def _line_band_bounds(
    xyxy,
    image_shape: tuple[int, int],
    margin: int,
) -> tuple[int, int, int, int]:
    h, w = image_shape[:2]
    x1, y1, x2, y2 = [int(round(float(v))) for v in xyxy[:4]]
    bx1 = max(0, x1 - margin)
    by1 = max(0, y1 - margin)
    bx2 = min(w, x2 + margin)
    by2 = min(h, y2 + margin)
    return bx1, by1, bx2, by2


def bubble_exclusion_zone(
    shape: tuple[int, int],
    blk_list: list,
    margin: int,
) -> np.ndarray:
    """Union des bbox `text_bubble` dilatées de `margin` px (zone d'exclusion N1/N2).

    Partagé entre `apply_line_protection` (M3, jalon 2 : le retrait N2 ne doit
    jamais amputer le résidu de masque d'une bulle) et `modules.cleaning.uniform`
    (anneau N1, purge et test de proximité "bulle_proche").
    """
    h, w = shape[:2]
    zone = np.zeros((h, w), dtype=bool)
    for blk in blk_list:
        if getattr(blk, "text_class", None) != "text_bubble":
            continue
        bubble_xyxy = getattr(blk, "bubble_xyxy", None)
        if bubble_xyxy is None or len(bubble_xyxy) < 4:
            continue
        bx1, by1, bx2, by2 = [int(round(float(v))) for v in bubble_xyxy[:4]]
        x1 = max(0, bx1 - margin)
        y1 = max(0, by1 - margin)
        x2 = min(w, bx2 + margin)
        y2 = min(h, by2 + margin)
        if x2 > x1 and y2 > y1:
            zone[y1:y2, x1:x2] = True
    return zone


def build_protected_halo(
    image: np.ndarray,
    blk_list: list,
    cfg: CleaningConfig,
    protect_mask: np.ndarray | None = None,
    *,
    mask: np.ndarray | None = None,
) -> np.ndarray:
    """Construit le masque de protection des traits, une fois par page.

    Restreint à la bande "étroite" (bbox text_free ± `line_band_margin`) : les
    bulles et les blocs autres que `text_free` ne sont jamais amputés par N2.
    Retourne un booléen plein format (H, W) : True là où un trait fin sombre
    (+ halo) a été détecté et retenu.

    Jalon 2 (critic pass2, étape 1) :
    - `line_detector` bascule l'algorithme de détection : "components" (défaut,
      `detect_line_components`, généralise aux traits non axiaux) ou "runs"
      (`detect_thin_lines`, algorithme d'origine inchangé, ignore `mask`).
    - En mode "components", la détection tourne sur une bande "large" (bbox ±
      (`line_band_margin` + `line_length`)) pour ne pas tronquer l'étendue d'une
      composante à un bord de crop ; le seuil Otsu reste calculé sur la bande
      étroite (M1, cohérent avec le mode "runs") ; `mask` (résidu avant N2) sert
      au critère hors-masque de `detect_line_components`.
    - Garde-fou M2 (bbox texte brutes) et restriction à la bande étroite
      appliqués APRÈS le halo (dilatation `line_halo`).
    - Plafond `line_max_protected_share` (consigne 5) : au-delà, protection
      ABANDONNÉE sur la bande concernée (jamais de repli vers "runs" — "runs"
      protège davantage, pas moins, un repli irait à l'encontre du plafond).

    `protect_mask` (traits de pinceau humains, sécurité mineure #4) : un pixel
    marqué par l'utilisateur ne peut jamais être considéré comme un trait à
    protéger, même s'il chevauche un bord de case détecté — l'intention
    explicite du pinceau prime sur la détection automatique.
    """
    h, w = image.shape[:2]
    protected = np.zeros((h, w), dtype=bool)
    if not cfg.protect_lines:
        return protected

    halo_kernel = np.ones((3, 3), np.uint8)

    text_free_blocks = [
        blk
        for blk in blk_list
        if getattr(blk, "text_class", None) == "text_free"
        and getattr(blk, "xyxy", None) is not None
        and len(blk.xyxy) >= 4
    ]

    # Garde-fou M2 : bbox de texte brutes (sans marge), jamais protégées, même
    # si une composante fine les traverse (coût documenté specs/02 §11).
    raw_text_union = np.zeros((h, w), dtype=bool)
    for blk in text_free_blocks:
        x1, y1, x2, y2 = [int(round(float(v))) for v in blk.xyxy[:4]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 > x1 and y2 > y1:
            raw_text_union[y1:y2, x1:x2] = True

    for blk in text_free_blocks:
        xyxy = blk.xyxy
        nx1, ny1, nx2, ny2 = _line_band_bounds(xyxy, (h, w), cfg.line_band_margin)
        if nx2 <= nx1 or ny2 <= ny1:
            continue

        narrow_crop = image[ny1:ny2, nx1:nx2]
        if narrow_crop.size == 0:
            continue
        gray_narrow = imk.to_gray(narrow_crop)
        otsu_val, _ = imk.otsu_threshold(gray_narrow)
        # otsu peut dégénérer à 0 sur une bande très majoritairement blanche
        # (le cas même où un trait fin doit être protégé) : n'utiliser otsu
        # que s'il retombe dans une plage plausible, sinon se rabattre sur le
        # plafond `line_dark_max` plutôt que de perdre toute détection.
        if 0 < otsu_val < cfg.line_dark_max:
            dark_thresh = float(otsu_val)
        else:
            dark_thresh = float(cfg.line_dark_max)

        if cfg.line_detector == "components":
            wide_margin = cfg.line_band_margin + cfg.line_length
            wx1, wy1, wx2, wy2 = _line_band_bounds(xyxy, (h, w), wide_margin)
            if wx2 <= wx1 or wy2 <= wy1:
                continue
            wide_crop = image[wy1:wy2, wx1:wx2]
            if wide_crop.size == 0:
                continue
            gray_wide = imk.to_gray(wide_crop)
            dark_wide = gray_wide <= dark_thresh
            if mask is not None:
                mask_wide = mask[wy1:wy2, wx1:wx2]
            else:
                mask_wide = np.zeros(dark_wide.shape, dtype=np.uint8)
            lines_local = detect_line_components(dark_wide, cfg, mask_wide)
            band_x1, band_y1, band_x2, band_y2 = wx1, wy1, wx2, wy2
        else:
            dark_narrow = gray_narrow <= dark_thresh
            lines_local = detect_thin_lines(dark_narrow, cfg)
            band_x1, band_y1, band_x2, band_y2 = nx1, ny1, nx2, ny2

        if not np.any(lines_local):
            continue
        prot_local = (
            imk.dilate(
                lines_local.astype(np.uint8) * 255,
                halo_kernel,
                iterations=cfg.line_halo,
            )
            > 0
        )

        band_final = np.zeros((h, w), dtype=bool)
        band_final[band_y1:band_y2, band_x1:band_x2] = prot_local
        # Restriction à la bande étroite + garde-fou M2, APRES le halo.
        band_result = np.zeros((h, w), dtype=bool)
        band_result[ny1:ny2, nx1:nx2] = (
            band_final[ny1:ny2, nx1:nx2] & ~raw_text_union[ny1:ny2, nx1:nx2]
        )

        band_area = (ny2 - ny1) * (nx2 - nx1)
        protected_area = int(np.count_nonzero(band_result))
        if band_area > 0 and protected_area > cfg.line_max_protected_share * band_area:
            logger.warning(
                "cleaning: protection N2 abandonnee sur la bande [%d:%d,%d:%d] "
                "(%.1f%% de pixels proteges > plafond %.0f%%, line_detector=%s)",
                ny1,
                ny2,
                nx1,
                nx2,
                100.0 * protected_area / band_area,
                100.0 * cfg.line_max_protected_share,
                cfg.line_detector,
            )
            continue  # bande abandonnee (consigne 5) : jamais de repli vers "runs"

        protected |= band_result

    if protect_mask is not None:
        protected &= ~protect_mask

    return protected


def apply_line_protection(
    mask: np.ndarray,
    image: np.ndarray,
    blk_list: list,
    cfg: CleaningConfig,
    protect_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, int]:
    """Retire du masque les pixels protégés, restreints à bande(text_free) ∩ ¬bulle.

    Mute `mask` EN PLACE (l'appelant garantit qu'il s'agit d'une copie possédée).
    M3 (jalon 2) : le retrait est restreint à l'intersection de la bande de
    détection (bbox text_free ± `line_band_margin`) et du complémentaire de la
    zone bulle dilatée (`bubble_exclusion_zone`, marge `bubble_ring_exclusion`) —
    le contour d'une bulle proche d'une légende ne doit jamais être amputé du
    masque bulle (déjà borné par `clip_to_bubble` côté nettoyage des bulles) par
    ce module. `protect_mask` (traits de pinceau humains) est exclu du halo N2 :
    jamais retiré du masque (sécurité mineure #4).

    Retourne (protected_halo, pixels_retires_total).
    """
    protected_halo = build_protected_halo(
        image, blk_list, cfg, protect_mask=protect_mask, mask=mask
    )
    if not np.any(protected_halo):
        return protected_halo, 0

    h, w = mask.shape[:2]
    bubble_zone = bubble_exclusion_zone((h, w), blk_list, cfg.bubble_ring_exclusion)
    removed_total = 0
    for blk in blk_list:
        if getattr(blk, "text_class", None) != "text_free":
            continue
        xyxy = getattr(blk, "xyxy", None)
        if xyxy is None or len(xyxy) < 4:
            continue
        bx1, by1, bx2, by2 = _line_band_bounds(xyxy, (h, w), cfg.line_band_margin)
        if bx2 <= bx1 or by2 <= by1:
            continue

        mask_band = mask[by1:by2, bx1:bx2]
        prot_band = protected_halo[by1:by2, bx1:bx2] & ~bubble_zone[by1:by2, bx1:bx2]
        before = int(np.count_nonzero(mask_band))
        mask_band[prot_band] = 0
        after = int(np.count_nonzero(mask_band))
        removed_total += before - after

    return protected_halo, removed_total
