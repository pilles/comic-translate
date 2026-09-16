"""N1 — remplissage uni par composantes connexes.

Pur numpy/imkit/mahotas. Aucun import Qt ni pipeline (les clips de bulle sont
calculés par l'appelant, `modules.cleaning.apply`, qui a licence d'importer
`modules.utils.image_utils`, cf. specs/02 jalon 2 consigne 8).

Le "graine" d'attribution bloc -> composantes utilise `_resolve_block_crop_bounds`
(`modules/utils/image_utils.py`, la même fonction que `build_block_mask_data`),
pour rester cohérent avec le rectangle déjà utilisé par le nettoyage des bulles.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import numpy as np
import imkit as imk

from .config import CleaningConfig
from .lines import bubble_exclusion_zone

logger = logging.getLogger("modules.cleaning")

# --- Raisons (decision / skip_reason) ---------------------------------------
DECISION_UNI = "uni"
DECISION_LAMA = "lama"
DECISION_SKIP = "skip"

REASON_SHARED = "partagee"
REASON_BUBBLE_OWNER = "bulle"
REASON_BUBBLE_NEAR = "bulle_proche"
REASON_BRUSH = "pinceau"
REASON_NO_OWNER = "sans_bloc"

REASON_RING_TOO_SMALL = "ring_trop_petit"
REASON_CORE_RATIO = "core_ratio_max"
REASON_NOT_UNIFORM = "non_uniforme"
REASON_QUADRANTS = "quadrants_incoherents"
REASON_QUADRANTS_INSUFFICIENT = "quadrants_insuffisants"

# clip_bulle (CSV, consigne 9) : origine du clip de bulle utilisé (ou repli).
CLIP_ABSENT = "absent"
CLIP_SEGMENTATION = "segmentation"
CLIP_ELLIPSE = "ellipse"
CLIP_COLOR_FALLBACK = "repli_couleur"


@dataclass
class ComponentReport:
    """Une ligne de rapport par composante connexe du masque résiduel.

    La plupart des champs sont optionnels (valeur par défaut) : seules les
    lignes "uni"/"lama" pleinement évaluées les renseignent tous.
    """

    label: int
    bloc: Optional[int]  # index dans blk_list, None si sans propriétaire
    classe: Optional[str]  # text_class du bloc propriétaire
    decision: str  # "uni" | "lama" | "skip"
    skip_reason: Optional[str] = None
    n_ring: int = 0
    # Jalon 2 : anneau géométrique (avant toute purge), sert au core_ratio (M5).
    n_ring_geom: int = 0
    mediane: Optional[tuple] = None
    part: Optional[float] = None
    ecart_quadrants: Optional[float] = None
    residu_bord: Optional[float] = None
    px_retires_n2: int = 0
    debord_case: int = 0
    # Jalon 2 (consigne 10) : ventilation des pixels purgés de l'anneau géométrique.
    purge_masque: int = 0
    purge_protege: int = 0
    purge_bulle: int = 0
    # Jalon 2 (consigne 10) : diagnostic bulle / distance / géométrie du coeur.
    part_bulle: Optional[float] = None
    clip_bulle: str = CLIP_ABSENT
    aire_core: int = 0
    bbox_core: Optional[tuple] = None
    distance_bloc_le_plus_proche: Optional[float] = None
    temps: float = 0.0


def _num_channels(image: np.ndarray) -> int:
    return image.shape[2] if image.ndim == 3 else 1


def _as_channel_view(crop: np.ndarray) -> np.ndarray:
    """Vue (H, W, C) sans copie, C=1 pour une entrée 2-D (contrat : tolérant 2-D)."""
    if crop.ndim == 2:
        return crop[..., np.newaxis]
    return crop


def _component_bbox(stats_row, shape: tuple[int, int], margin: int) -> tuple[int, int, int, int]:
    # CC_STAT_WIDTH/HEIGHT sont surestimés de 1 px chacun (bug imkit, voir
    # `_label_bbox_xyxy` ci-dessous) : sans conséquence ici, cette fenêtre ne
    # sert qu'à définir un crop englobant (avec marge) pour `labels_crop ==
    # label`, qui identifie le composant exactement quelle que soit la taille
    # de la fenêtre — 1 px de trop ne fait qu'élargir la marge d'un pixel.
    x = int(stats_row[imk.CC_STAT_LEFT])
    y = int(stats_row[imk.CC_STAT_TOP])
    w = int(stats_row[imk.CC_STAT_WIDTH])
    h = int(stats_row[imk.CC_STAT_HEIGHT])
    h_img, w_img = shape[:2]
    x1 = max(0, x - margin)
    y1 = max(0, y - margin)
    x2 = min(w_img, x + w + margin)
    y2 = min(h_img, y + h + margin)
    return x1, y1, x2, y2


def _label_bbox_xyxy(stats_row) -> tuple[int, int, int, int]:
    """Bbox EXACTE (sans marge) de la composante, en coordonnées image.

    Compense un off-by-one d'`imkit` (fichier amont, NE PAS modifier) :
    `imkit/transforms.py:425-426` calcule `width = xmax - xmin + 1` (et son
    symétrique `height`) en supposant des bornes `mh.labeled.bbox` INCLUSIVES,
    alors qu'elles sont EXCLUSIVES (vérifié : un bloc de 3 lignes x 4 colonnes
    donne `ymax - ymin == 3` et `xmax - xmin == 4`, sans +1 nécessaire).
    `CC_STAT_WIDTH`/`CC_STAT_HEIGHT` sont donc surestimés de 1 px chacun ; on
    retranche 1 ici (borné à >= 1, purement défensif : une composante de
    `area > 0` a toujours une largeur/hauteur réelle >= 1, donc une valeur
    (buguée) >= 2) pour que `bbox_core` (CSV, `_distance_to_nearest_block`)
    soit exact.
    """
    x = int(stats_row[imk.CC_STAT_LEFT])
    y = int(stats_row[imk.CC_STAT_TOP])
    w = max(1, int(stats_row[imk.CC_STAT_WIDTH]) - 1)
    h = max(1, int(stats_row[imk.CC_STAT_HEIGHT]) - 1)
    return x, y, x + w, y + h


def _distance_to_nearest_block(
    bbox_core: tuple[int, int, int, int], blk_list: list
) -> Optional[float]:
    """Distance (bord à bord, 0 si chevauchement) de `bbox_core` au bloc le plus
    proche de `blk_list`. Toujours calculée, y compris pour les composantes
    "sans_bloc" (consigne 10, diagnostic) : None seulement si `blk_list` est vide."""
    cx1, cy1, cx2, cy2 = bbox_core
    best: Optional[float] = None
    for blk in blk_list:
        xyxy = getattr(blk, "xyxy", None)
        if xyxy is None or len(xyxy) < 4:
            continue
        bx1, by1, bx2, by2 = [float(v) for v in xyxy[:4]]
        dx = max(bx1 - cx2, cx1 - bx2, 0.0)
        dy = max(by1 - cy2, cy1 - by2, 0.0)
        d = float(np.hypot(dx, dy))
        if best is None or d < best:
            best = d
    return best


def _fraction_in_zone(
    core: np.ndarray,
    crop_bounds: tuple[int, int, int, int],
    zone_bounds: tuple[int, int, int, int],
) -> float:
    """Fraction des pixels de `core` (repère `crop_bounds`) située à l'intérieur
    du rectangle `zone_bounds` (repère image). Utilisé pour la résolution
    multi-propriétaires (consigne 1) : `zone_bounds` = graine d'une bulle."""
    x1, y1, x2, y2 = crop_bounds
    zx1, zy1, zx2, zy2 = zone_bounds
    n_core = int(np.count_nonzero(core))
    ix1, iy1 = max(x1, zx1), max(y1, zy1)
    ix2, iy2 = min(x2, zx2), min(y2, zy2)
    if n_core == 0 or ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    lx1, ly1 = ix1 - x1, iy1 - y1
    lx2, ly2 = ix2 - x1, iy2 - y1
    overlap = int(np.count_nonzero(core[ly1:ly2, lx1:lx2]))
    return overlap / n_core


def _quadrant_indices(ring_ys: np.ndarray, ring_xs: np.ndarray, cy: float, cx: float) -> np.ndarray:
    dx = ring_xs.astype(np.float64) - cx
    dy = ring_ys.astype(np.float64) - cy
    return (dx >= 0).astype(np.int8) + 2 * (dy >= 0).astype(np.int8)


def _max_channel_abs_diff(pixels: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """max_c |p_c - ref_c| pour chaque pixel de `pixels` (N, C)."""
    return np.max(np.abs(pixels.astype(np.float64) - reference.astype(np.float64)), axis=-1)


def build_owner_map(
    residual_mask: np.ndarray,
    labels: np.ndarray,
    blk_list: list,
    seed_bounds_fn,
    image: np.ndarray,
) -> tuple[dict[int, list[int]], dict[int, tuple[int, int, int, int]]]:
    """label -> liste des index de blocs dont la graine touche ce label.

    Retourne aussi les bornes de graine par bloc (`seed_bounds_by_block`),
    réutilisées par la résolution multi-propriétaires (consigne 1) sans
    recalculer `seed_bounds_fn` (et ses éventuelles exceptions) une seconde fois.
    """
    owners: dict[int, list[int]] = {}
    seed_bounds_by_block: dict[int, tuple[int, int, int, int]] = {}
    for idx, blk in enumerate(blk_list):
        try:
            sx1, sy1, sx2, sy2 = seed_bounds_fn(image, blk, 5)
        except Exception:
            # Bloc mal formé (bbox invalide, etc.) : sans graine exploitable, il
            # ne peut revendiquer aucune composante. Ne doit jamais interrompre
            # l'attribution des autres blocs de la page.
            continue
        if sx2 <= sx1 or sy2 <= sy1:
            continue
        seed_bounds_by_block[idx] = (sx1, sy1, sx2, sy2)
        seed_region = residual_mask[sy1:sy2, sx1:sx2] > 0
        if not np.any(seed_region):
            continue
        seed_labels = labels[sy1:sy2, sx1:sx2][seed_region]
        touched = np.unique(seed_labels)
        touched = touched[touched > 0]
        for label in touched.tolist():
            owners.setdefault(int(label), []).append(idx)
    return owners, seed_bounds_by_block


def _bubble_no_fill_zone(
    image: np.ndarray,
    core: np.ndarray,
    crop_bounds: tuple[int, int, int, int],
    ring_median: np.ndarray,
    blk_list: list,
    bubble_clips: dict[int, tuple[Optional[np.ndarray], str]],
    cfg: CleaningConfig,
) -> tuple[np.ndarray, str]:
    """Zone à ne jamais repeindre (consignes 2/3/8/9, jalon 2).

    Union, sur toutes les bulles dont la zone (bbox ± `bubble_ring_exclusion`)
    intersecte la fenêtre de la composante, de :
    - le contour de bulle réel (`bubble_clips[idx]`, calculé une fois par
      `modules.cleaning.apply` sur l'image déjà fast-remplie), dilaté de
      `bubble_interior_dilation` px pour couvrir l'encre du contour sur tout
      son périmètre (angles compris, consigne 2) — SEULEMENT si la couleur du
      fast-fill de cette bulle (médiane de son intérieur érodé) colle à la
      médiane de l'anneau de la composante (garde couleur, ≤ `color_tolerance`) ;
    - sinon, repli explicite (consigne 9) sur la zone bulle entière (bbox
      dilatée) : bulle absente du dictionnaire, clip vide dans cette fenêtre,
      ou couleur du fast-fill trop éloignée de l'anneau ("bulle colorée").

    Ne s'appuie jamais sur `protected` (N2, consigne 2) : la protection du
    contour de bulle est autonome, par construction géométrique/couleur.
    """
    x1, y1, x2, y2 = crop_bounds
    zone = np.zeros(core.shape, dtype=bool)
    clip_kinds: set[str] = set()
    if not core.shape[0] or not core.shape[1]:
        return zone, CLIP_ABSENT

    dil_kernel = np.ones((3, 3), np.uint8)
    erode_kernel = np.ones((3, 3), np.uint8)
    channel_view = _as_channel_view(image[y1:y2, x1:x2])
    n_channels = channel_view.shape[-1]

    for idx, blk in enumerate(blk_list):
        if getattr(blk, "text_class", None) != "text_bubble":
            continue
        bubble_xyxy = getattr(blk, "bubble_xyxy", None)
        if bubble_xyxy is None or len(bubble_xyxy) < 4:
            continue
        m = cfg.bubble_ring_exclusion
        bx1, by1, bx2, by2 = [int(round(float(v))) for v in bubble_xyxy[:4]]
        zx1, zy1, zx2, zy2 = bx1 - m, by1 - m, bx2 + m, by2 + m
        if zx2 <= x1 or zx1 >= x2 or zy2 <= y1 or zy1 >= y2:
            continue  # cette bulle n'intersecte pas la fenêtre de la composante

        fallback_local = np.zeros(core.shape, dtype=bool)
        fx1, fy1 = max(zx1, x1) - x1, max(zy1, y1) - y1
        fx2, fy2 = min(zx2, x2) - x1, min(zy2, y2) - y1
        if fx2 > fx1 and fy2 > fy1:
            fallback_local[fy1:fy2, fx1:fx2] = True

        clip, kind = bubble_clips.get(idx, (None, CLIP_ABSENT))
        if clip is None:
            zone |= fallback_local
            clip_kinds.add(CLIP_ABSENT)
            continue

        clip_crop = clip[y1:y2, x1:x2]
        if not np.any(clip_crop):
            # Repli explicite (consigne 9) : clip vide dans cette fenêtre.
            zone |= fallback_local
            clip_kinds.add(CLIP_ABSENT)
            continue

        eroded = imk.erode(clip_crop.astype(np.uint8) * 255, erode_kernel, iterations=3) > 0
        if np.any(eroded):
            eys, exs = np.nonzero(eroded)
            sample = channel_view[eys, exs].reshape(-1, n_channels)
            bubble_color = np.median(sample, axis=0)
            color_ok = float(np.max(np.abs(bubble_color - ring_median))) <= cfg.color_tolerance
        else:
            color_ok = False  # rien de mesurable : repli prudent

        if not color_ok:
            zone |= fallback_local
            clip_kinds.add(CLIP_COLOR_FALLBACK)
            continue

        interior = (
            imk.dilate(
                clip_crop.astype(np.uint8) * 255,
                dil_kernel,
                iterations=cfg.bubble_interior_dilation,
            )
            > 0
        )
        zone |= interior
        clip_kinds.add(kind)

    clip_bulle = ",".join(sorted(clip_kinds)) if clip_kinds else CLIP_ABSENT
    return zone, clip_bulle


def clean_uniform_components(
    image: np.ndarray,
    mask: np.ndarray,
    blk_list: list,
    cfg: CleaningConfig,
    *,
    protected_halo: np.ndarray,
    protect_mask: np.ndarray | None,
    seed_bounds_fn,
    px_retires_n2_by_pixel: np.ndarray,
    bubble_clips: dict[int, tuple[np.ndarray | None, str]] | None = None,
) -> list[ComponentReport]:
    """N1. Mute `image` et `mask` EN PLACE (copies déjà possédées par l'appelant).

    `protected_halo` : masque N2 (bool, H×W), pour exclure les traits de l'anneau.
    `protect_mask` : traits de pinceau humains (bool ou None) — composante
    chevauchant `protect_mask` => skip "pinceau" (garde-fou M5).
    `px_retires_n2_by_pixel` : bool H×W, pixels retirés du masque par N2 (pour
    l'attribution approximative de `px_retires_n2` par composante, cf. lines.py).
    `bubble_clips` : {index bloc bulle -> (clip ou None, "segmentation"|"ellipse")},
    calculé une fois par `modules.cleaning.apply` (consigne 8) ; `None`/absent
    traité comme aucun clip disponible (repli sur la zone bulle, consigne 9).
    """
    reports: list[ComponentReport] = []
    if mask is None or not np.any(mask):
        return reports

    bubble_clips = bubble_clips or {}
    h, w = mask.shape[:2]
    # M5 (jalon 2) : figé à l'entrée de N1, indépendant de l'ordre de traitement
    # des labels (purge de l'anneau ET `no_touch` s'appuient dessus, jamais sur
    # le masque live `mask`, qui se vide progressivement).
    mask_entry = (mask > 0).copy()

    # Documenté, non corrigé (critic pass1 M7 / pass2 nit #13) :
    # `imk.connected_components_with_stats` alloue `np.indices((h, w), dtype=np.int64)`
    # (imkit/transforms.py) pour des centroïdes ici inutilisés — ~154 Mo sur un
    # chunk webtoon 12000x800, deux fois pour ce seul appel. Mesure hors de
    # portée du corpus "Fun Home" (pages entières, pas de chunk webtoon aussi
    # haut) ; corriger l'implémentation imkit sortirait du périmètre de ce jalon.
    binary = mask_entry.astype(np.uint8)
    num_labels, labels, stats, _centroids = imk.connected_components_with_stats(
        binary, connectivity=8
    )
    if num_labels <= 1:
        return reports

    owners, seed_bounds_by_block = build_owner_map(mask, labels, blk_list, seed_bounds_fn, image)
    bubble_zone = bubble_exclusion_zone((h, w), blk_list, cfg.bubble_ring_exclusion)

    for label in range(1, num_labels):
        t0 = time.perf_counter()
        owner_indices = owners.get(label, [])
        area = int(stats[label, imk.CC_STAT_AREA])
        if area <= 0:
            continue

        bbox_core = _label_bbox_xyxy(stats[label])
        distance_bloc = _distance_to_nearest_block(bbox_core, blk_list)

        x1, y1, x2, y2 = _component_bbox(stats[label], (h, w), cfg.ring_outer + cfg.feather_px + 2)
        core = labels[y1:y2, x1:x2] == label
        n_core = int(np.count_nonzero(core))
        bubble_zone_crop = bubble_zone[y1:y2, x1:x2]
        overlap_zone = float(np.count_nonzero(core & bubble_zone_crop)) / n_core if n_core else 0.0

        skip_reason: str | None = None
        bloc_idx: int | None = None
        classe: str | None = None

        text_free_owners = [
            i for i in owner_indices if getattr(blk_list[i], "text_class", None) == "text_free"
        ]
        bubble_owners = [
            i for i in owner_indices if getattr(blk_list[i], "text_class", None) == "text_bubble"
        ]
        other_owners = [
            i for i in owner_indices if i not in text_free_owners and i not in bubble_owners
        ]

        if not owner_indices:
            skip_reason = REASON_NO_OWNER
        elif len(owner_indices) == 1:
            bloc_idx = owner_indices[0]
            classe = getattr(blk_list[bloc_idx], "text_class", None)
            if classe != "text_free":
                skip_reason = REASON_BUBBLE_OWNER
        elif len(text_free_owners) == 1 and not other_owners and bubble_owners:
            # Consigne 1 : co-propriété résolue par fraction (graine bulle), le
            # test bloquant B1' (skip "partagee" à tort quand une bulle
            # co-revendique via son seed ~= tout son bbox) ne s'applique plus.
            bloc_idx = text_free_owners[0]
            classe = "text_free"
            for bubble_idx in bubble_owners:
                seed_bounds = seed_bounds_by_block.get(bubble_idx)
                frac = (
                    _fraction_in_zone(core, (x1, y1, x2, y2), seed_bounds)
                    if seed_bounds is not None
                    else 1.0
                )
                if frac > cfg.bubble_overlap_max:
                    skip_reason = REASON_BUBBLE_NEAR
                    break
        else:
            skip_reason = REASON_SHARED
            bloc_idx = owner_indices[0]
            classe = getattr(blk_list[bloc_idx], "text_class", None)

        if skip_reason is None and overlap_zone > cfg.bubble_overlap_max:
            skip_reason = REASON_BUBBLE_NEAR
        if (
            skip_reason is None
            and protect_mask is not None
            and np.any(protect_mask[y1:y2, x1:x2] & core)
        ):
            skip_reason = REASON_BRUSH

        common = dict(
            label=label,
            bloc=bloc_idx,
            classe=classe,
            aire_core=n_core,
            bbox_core=bbox_core,
            distance_bloc_le_plus_proche=distance_bloc,
            part_bulle=overlap_zone,
        )

        if skip_reason is not None:
            reports.append(
                ComponentReport(
                    decision=DECISION_SKIP,
                    skip_reason=skip_reason,
                    temps=time.perf_counter() - t0,
                    **common,
                )
            )
            logger.debug(
                "cleaning: block[%s] class=%s decision=skip reason=%s label=%d",
                bloc_idx,
                classe,
                skip_reason,
                label,
            )
            continue

        report = _evaluate_component(
            image,
            mask,
            mask_entry,
            core,
            (x1, y1, x2, y2),
            cfg,
            protected_halo,
            bubble_zone,
            common,
            px_retires_n2_by_pixel,
            blk_list,
            bubble_clips,
            t0,
        )
        reports.append(report)
        logger.debug(
            "cleaning: block[%s] class=%s decision=%s n_ring=%d part=%s",
            bloc_idx,
            classe,
            report.decision,
            report.n_ring,
            f"{report.part:.3f}" if report.part is not None else "n/a",
        )

    return reports


def _evaluate_component(
    image: np.ndarray,
    mask: np.ndarray,
    mask_entry: np.ndarray,
    core: np.ndarray,
    crop_bounds: tuple[int, int, int, int],
    cfg: CleaningConfig,
    protected_halo: np.ndarray,
    bubble_zone: np.ndarray,
    common: dict,
    px_retires_n2_by_pixel: np.ndarray,
    blk_list: list,
    bubble_clips: dict[int, tuple[np.ndarray | None, str]],
    t0: float,
) -> ComponentReport:
    x1, y1, x2, y2 = crop_bounds
    mask_crop = mask[y1:y2, x1:x2]
    mask_entry_crop = mask_entry[y1:y2, x1:x2]
    protected_crop = protected_halo[y1:y2, x1:x2]
    bubble_zone_crop = bubble_zone[y1:y2, x1:x2]

    n_core = int(np.count_nonzero(core))
    dil_kernel = np.ones((3, 3), np.uint8)
    core_u8 = core.astype(np.uint8) * 255
    dilated_outer = imk.dilate(core_u8, dil_kernel, iterations=cfg.ring_outer) > 0
    dilated_inner = (
        imk.dilate(core_u8, dil_kernel, iterations=cfg.ring_inner) > 0
        if cfg.ring_inner > 0
        else core
    )

    # M5/(a) core_ratio (jalon 2) : mesuré sur l'anneau GÉOMÉTRIQUE, avant toute
    # purge — sinon la purge (masque/protégé/bulle) réduit artificiellement
    # l'anneau et fait grimper core_ratio à tort (légende 6, ~0.79-0.80 mesuré).
    ring_geom = dilated_outer & ~dilated_inner
    n_ring_geom = int(np.count_nonzero(ring_geom))
    core_ratio = n_core / float(n_core + n_ring_geom) if (n_core + n_ring_geom) > 0 else 1.0

    px_retires_n2 = int(
        np.count_nonzero(
            px_retires_n2_by_pixel[y1:y2, x1:x2]
            & (imk.dilate(core_u8, dil_kernel, iterations=1) > 0)
        )
    )
    debord_case = int(np.count_nonzero(core & protected_crop))

    if core_ratio > cfg.core_ratio_max:
        return ComponentReport(
            decision=DECISION_LAMA,
            skip_reason=REASON_CORE_RATIO,
            n_ring_geom=n_ring_geom,
            px_retires_n2=px_retires_n2,
            debord_case=debord_case,
            temps=time.perf_counter() - t0,
            **common,
        )

    # Purges séquentielles (consigne 10 : ventilation par cause) sur mask_entry
    # figé, PAS sur mask_crop live (M5 : indépendance à l'ordre des labels).
    ring = ring_geom & ~(mask_entry_crop > 0)
    purge_masque = n_ring_geom - int(np.count_nonzero(ring))
    ring &= ~protected_crop
    n_apres_protege = int(np.count_nonzero(ring))
    purge_protege = (n_ring_geom - purge_masque) - n_apres_protege
    ring &= ~bubble_zone_crop
    n_ring = int(np.count_nonzero(ring))
    purge_bulle = n_apres_protege - n_ring

    if n_ring < cfg.ring_min_pixels:
        return ComponentReport(
            decision=DECISION_LAMA,
            skip_reason=REASON_RING_TOO_SMALL,
            n_ring=n_ring,
            n_ring_geom=n_ring_geom,
            purge_masque=purge_masque,
            purge_protege=purge_protege,
            purge_bulle=purge_bulle,
            px_retires_n2=px_retires_n2,
            debord_case=debord_case,
            temps=time.perf_counter() - t0,
            **common,
        )

    channel_view = _as_channel_view(image[y1:y2, x1:x2])
    n_channels = channel_view.shape[-1]
    ring_ys, ring_xs = np.nonzero(ring)
    ring_pixels = channel_view[ring_ys, ring_xs].reshape(-1, n_channels)
    median = np.median(ring_pixels, axis=0)

    diffs = _max_channel_abs_diff(ring_pixels, median)
    part = float(np.mean(diffs <= cfg.color_tolerance))

    core_ys, core_xs = np.nonzero(core)
    cy = float(np.mean(core_ys)) if core_ys.size else 0.0
    cx = float(np.mean(core_xs)) if core_xs.size else 0.0
    quadrant_ids = _quadrant_indices(ring_ys, ring_xs, cy, cx)
    min_quadrant_pixels = max(1, cfg.ring_min_pixels // 8)
    quadrant_medians = []
    for q in range(4):
        q_mask = quadrant_ids == q
        if int(np.count_nonzero(q_mask)) < min_quadrant_pixels:
            continue
        quadrant_medians.append(np.median(ring_pixels[q_mask], axis=0))

    base_kwargs = dict(
        n_ring=n_ring,
        n_ring_geom=n_ring_geom,
        purge_masque=purge_masque,
        purge_protege=purge_protege,
        purge_bulle=purge_bulle,
        mediane=tuple(median.tolist()),
        part=part,
        px_retires_n2=px_retires_n2,
        debord_case=debord_case,
    )

    if len(quadrant_medians) < 3:
        return ComponentReport(
            decision=DECISION_LAMA,
            skip_reason=REASON_QUADRANTS_INSUFFICIENT,
            temps=time.perf_counter() - t0,
            **base_kwargs,
            **common,
        )

    coh = 0.0
    for i in range(len(quadrant_medians)):
        for j in range(i + 1, len(quadrant_medians)):
            diff = float(np.max(np.abs(quadrant_medians[i] - quadrant_medians[j])))
            coh = max(coh, diff)

    is_uniform = part >= cfg.uniform_share and coh <= cfg.ring_quadrant_max

    if not is_uniform:
        lama_reason = REASON_NOT_UNIFORM if part < cfg.uniform_share else REASON_QUADRANTS
        return ComponentReport(
            decision=DECISION_LAMA,
            skip_reason=lama_reason,
            ecart_quadrants=coh,
            temps=time.perf_counter() - t0,
            **base_kwargs,
            **common,
        )

    # --- Uni : zone à ne jamais repeindre (contour de bulle, consignes 2/3/8/9) ---
    no_fill_zone, clip_bulle = _bubble_no_fill_zone(
        image, core, (x1, y1, x2, y2), median, blk_list, bubble_clips, cfg
    )

    # Bande exclue de l'anneau par ring_inner (jamais échantillonnée) : sert à
    # mesurer, a posteriori, la fidélité du remplissage au bord.
    dilated_inner_band = dilated_inner & ~core
    if np.any(dilated_inner_band):
        border_ys, border_xs = np.nonzero(dilated_inner_band)
        border_pixels = channel_view[border_ys, border_xs].reshape(-1, n_channels)
        residu_bord = float(np.mean(_max_channel_abs_diff(border_pixels, median)))
    else:
        residu_bord = 0.0

    # Consigne 3 : seul `core_fill` est démasqué, jamais `core` en entier — le
    # contour de bulle (et tout pixel protégé) reste masqué, donc soumis à LaMa.
    core_fill = core & ~protected_crop & ~no_fill_zone
    # Consigne 4 : no_touch inclut désormais l'intérieur de bulle dilaté, en plus
    # du garde-fou N2 et des pixels encore masqués d'une AUTRE composante
    # (mask_entry, pas le masque live : indépendance à l'ordre des labels, M5).
    no_touch = protected_crop | ((mask_entry_crop > 0) & ~core) | no_fill_zone
    _blend_uniform_fill(image[y1:y2, x1:x2], core, core_fill, median, cfg.feather_px, no_touch)
    mask_crop[core_fill] = 0

    return ComponentReport(
        decision=DECISION_UNI,
        skip_reason=None,
        ecart_quadrants=coh,
        residu_bord=residu_bord,
        clip_bulle=clip_bulle,
        temps=time.perf_counter() - t0,
        **base_kwargs,
        **common,
    )


def _blend_uniform_fill(
    image_crop: np.ndarray,
    core: np.ndarray,
    core_fill: np.ndarray,
    median: np.ndarray,
    feather_px: int,
    no_touch: np.ndarray,
) -> None:
    """Remplit `core_fill` avec `median`, fondu gaussien pour éviter un bord dur.

    Mute `image_crop` EN PLACE (vue sur un tableau déjà possédé par l'appelant).
    Consigne 4 (jalon 2, corrige B1) : ordre `soft[core_fill]=1` PUIS
    `soft[no_touch]=0` — `no_touch` prime toujours, y compris sur `core_fill`
    (contour de bulle, pixel encore masqué d'une autre composante). L'ordre
    précédent (core écrasait no_touch) laissait le fondu voiler un contour de
    bulle ou un trait protégé.
    """
    soft = (
        imk.gaussian_blur(core.astype(np.uint8) * 255, float(max(1, feather_px))).astype(np.float32)
        / 255.0
    )
    soft = np.clip(soft, 0.0, 1.0)
    soft[core_fill] = 1.0
    soft[no_touch] = 0.0
    is_2d = image_crop.ndim == 2
    channel_view = _as_channel_view(image_crop)
    soft_c = soft[..., np.newaxis]
    fill = np.broadcast_to(median, channel_view.shape).astype(np.float32)
    blended = channel_view.astype(np.float32) * (1.0 - soft_c) + fill * soft_c
    blended = np.clip(np.round(blended), 0, 255).astype(image_crop.dtype)
    if is_2d:
        image_crop[...] = blended[..., 0]
    else:
        image_crop[...] = blended
