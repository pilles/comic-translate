"""Orchestration du nettoyage additionnel : `clean_page`.

Pur numpy/imkit. Aucun import Qt ni `pipeline/inpainting.py` — `bubble_cleanup`
est INJECTÉ par l'appelant (`InpaintingHandler._apply_fast_bubble_cleanup`),
jamais importé ici (conception B3).
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Callable, Optional

import numpy as np

from modules.utils.image_utils import _resolve_block_crop_bounds, build_bubble_clip_mask

from .config import INERT, CleaningConfig, is_inert
from .lines import apply_line_protection
from .uniform import (
    CLIP_ABSENT,
    CLIP_ELLIPSE,
    CLIP_SEGMENTATION,
    ComponentReport,
    clean_uniform_components,
)

logger = logging.getLogger("modules.cleaning")

BubbleCleanup = Callable[[np.ndarray, np.ndarray, Optional[list]], tuple]


def cleaning_config_from_settings_page(settings_page) -> CleaningConfig:
    """Construit `CleaningConfig` depuis les widgets Réglages > Outils.

    Modelé sur `modules.utils.pipeline_config.get_config`. Lecture défensive :
    widgets absents (settings_page factice, anciens tests) => INERT, jamais
    d'exception remontée jusqu'à l'appelant.
    """
    if settings_page is None:
        return INERT
    try:
        ui = settings_page.ui
        uniform_fill = bool(ui.uniform_fill_checkbox.isChecked())
        protect_lines = bool(ui.protect_lines_checkbox.isChecked())
        free_dilate_iterations = int(ui.free_margin_spinbox.value())
    except AttributeError:
        return INERT
    # Borne 0-6 (bug #2) : le QSpinBox réel (tools_page.py, setMinimum(0)/
    # setMaximum(6)) borne déjà la valeur, mais un objet factice ou un futur
    # appelant direct ne le garantit pas. Hors plage => repli documenté (3).
    if not 0 <= free_dilate_iterations <= 6:
        free_dilate_iterations = INERT.free_dilate_iterations
    return CleaningConfig(
        uniform_fill=uniform_fill,
        protect_lines=protect_lines,
        free_dilate_iterations=free_dilate_iterations,
    )


def _compute_bubble_clips(
    image: np.ndarray, blk_list: list, cfg: CleaningConfig
) -> dict[int, tuple[np.ndarray | None, str]]:
    """Clips de contour de bulle, calculés UNE fois après `bubble_cleanup`, sur
    l'image déjà fast-remplie (consigne 8), indexés par index de bloc.

    Chaque valeur est `(clip, origine)` : `origine` ∈ {"segmentation", "ellipse",
    "absent"} (consigne 9, colonne CSV `clip_bulle`) — obtenue en comparant le
    clip réel à l'ellipse de repli pure (même appel, `image=None`), sans exposer
    de nouvel argument sur `build_bubble_clip_mask` (fichier d'origine, non
    modifié). `build_bubble_clip_mask` attend `bounds` = la fenêtre à laquelle
    `mask_shape` correspond (voir `modules/utils/image_utils.py`) ; en passant la
    page entière comme fenêtre, le clip retourné est directement en coordonnées
    image absolues, indexable par les crops de composante de `uniform.py`.
    """
    h, w = image.shape[:2]
    bounds_full = (0, 0, w, h)
    clips: dict[int, tuple[np.ndarray | None, str]] = {}
    for idx, blk in enumerate(blk_list):
        if getattr(blk, "text_class", None) != "text_bubble":
            continue
        bubble_xyxy = getattr(blk, "bubble_xyxy", None)
        if bubble_xyxy is None or len(bubble_xyxy) < 4:
            clips[idx] = (None, CLIP_ABSENT)
            continue
        inset = cfg.bubble_ring_exclusion
        clip = build_bubble_clip_mask(
            (h, w), bounds_full, bubble_xyxy, inset=inset, image=image, seed_bbox=blk.xyxy
        )
        if clip is None:
            clips[idx] = (None, CLIP_ABSENT)
            continue
        ellipse_only = build_bubble_clip_mask(
            (h, w), bounds_full, bubble_xyxy, inset=inset, image=None, seed_bbox=blk.xyxy
        )
        kind = CLIP_ELLIPSE if np.array_equal(clip, ellipse_only) else CLIP_SEGMENTATION
        clips[idx] = (clip, kind)
    return clips


def clean_page(
    image: np.ndarray | None,
    mask: np.ndarray | None,
    blk_list: list | None,
    cfg: CleaningConfig,
    *,
    protect_mask: np.ndarray | None = None,
    bubble_cleanup: BubbleCleanup | None = None,
) -> tuple[np.ndarray | None, np.ndarray | None, int, list[ComponentReport]]:
    """N2 -> bubble_cleanup (intact) -> N1, sur le résidu.

    Contrat (critic pass2 consigne #2) :
    - config inerte (`is_inert(cfg)`) : passe-plat STRICT.
      - `bubble_cleanup=None` : identité d'objet (`out is image`, `out is mask`).
      - `bubble_cleanup` injecté : renvoie VERBATIM son 3-uplet (aucune copie
        ajoutée par ce module), `report=[]`.
    - config active : n'écrit jamais dans `image`/`mask` reçus (copie paresseuse
      dès la première écriture réelle) ; `bubble_cleanup` reste le seul
      responsable du nettoyage des bulles, jamais touché.
    - `cleaned_blocks` (3e élément) reste le compte de bulles nettoyées par
      `bubble_cleanup` seul (critic pass2 consigne #7 / M9) : les composantes
      "uni" ne l'incrémentent jamais, pour ne pas activer l'élagage des petites
      composantes résiduelles (`_drop_tiny_residual_components`) sur une page
      sans bulle.
    """
    blk_list = blk_list or []

    def _delegate(img, msk):
        if bubble_cleanup is None:
            return img, msk, 0, []
        out_image, out_mask, cleaned_blocks = bubble_cleanup(img, msk, blk_list or None)
        return out_image, out_mask, cleaned_blocks, []

    if image is None or mask is None:
        return image, mask, 0, []
    if is_inert(cfg):
        return _delegate(image, mask)
    if not np.any(mask):
        return _delegate(image, mask)

    # --- N2 : protection des traits, une fois par page, avant tout le reste ---
    working_mask = mask.copy()
    protected_halo = np.zeros(mask.shape[:2], dtype=bool)
    px_retires_n2_by_pixel = np.zeros(mask.shape[:2], dtype=bool)
    if cfg.protect_lines:
        mask_before = working_mask.copy()
        protected_halo, _removed_total = apply_line_protection(
            working_mask, image, blk_list, cfg, protect_mask=protect_mask
        )
        px_retires_n2_by_pixel = (mask_before > 0) & (working_mask == 0)

    # --- Bulles : code d'origine, inchangé, sur le masque déjà nettoyé des traits ---
    if bubble_cleanup is not None:
        cleaned_image, residual_mask, cleaned_blocks = bubble_cleanup(
            image, working_mask, blk_list or None
        )
    else:
        cleaned_image, residual_mask, cleaned_blocks = image.copy(), working_mask, 0

    # --- N1 : remplissage uni sur le résidu, par composantes connexes ---
    report: list[ComponentReport] = []
    if cfg.uniform_fill:
        bubble_clips = _compute_bubble_clips(cleaned_image, blk_list, cfg)
        report = clean_uniform_components(
            cleaned_image,
            residual_mask,
            blk_list,
            cfg,
            protected_halo=protected_halo,
            protect_mask=protect_mask,
            seed_bounds_fn=_resolve_block_crop_bounds,
            px_retires_n2_by_pixel=px_retires_n2_by_pixel,
            bubble_clips=bubble_clips,
        )

    # Une seule ligne d'agrégat par page (sécurité mineure #8) ; le détail par
    # composante ne va qu'en logger.debug (modules/cleaning/uniform.py).
    # Jamais atteint en config inerte (retour anticipé plus haut) : silencieux.
    decisions = Counter(r.decision for r in report)
    per_block: dict[int, set[str]] = {}
    for r in report:
        if r.bloc is not None:
            per_block.setdefault(r.bloc, set()).add(r.decision)
    mixed_blocks = sum(
        1 for decisions_for_block in per_block.values() if len(decisions_for_block) > 1
    )
    logger.info(
        "cleaning: page composantes=%d uni=%d lama=%d skip=%d blocs_mixtes=%d",
        len(report),
        decisions.get("uni", 0),
        decisions.get("lama", 0),
        decisions.get("skip", 0),
        mixed_blocks,
    )

    return cleaned_image, residual_mask, cleaned_blocks, report
