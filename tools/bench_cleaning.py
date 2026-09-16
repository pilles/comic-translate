#!/usr/bin/env python3
"""Banc visuel de nettoyage (specs/02-nettoyage-legendes.md).

Exerce le vrai code de l'app (`modules.detection.processor.TextBlockDetector`,
`pipeline.inpainting.InpaintingHandler._apply_fast_bubble_cleanup`,
`modules.cleaning.clean_page`, `modules.inpainting.lama.LaMa`) contre les pages
de `bench/pages/` (ignoré par git, jamais de page de BD versionnée).

Usage :
    uv run python tools/bench_cleaning.py bench/pages --save-blocks bench/out/blocks --out bench/out
    uv run python tools/bench_cleaning.py bench/pages --blocks bench/out/blocks --manual-mask --out bench/out/manual
    uv run python tools/bench_cleaning.py bench/pages --blocks bench/out/blocks --sweep --out bench/out

Ne prend jamais la décision finale sur les réglages : la planche 4 vues (par
page) est faite pour être jugée à l'oeil par Philippe. `UI_DEFAULTS`
(`modules/cleaning/config.py`) reste la seule source des valeurs livrées.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import locale
import logging
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
import imkit as imk  # noqa: E402

from modules.cleaning import INERT, UI_DEFAULTS, CleaningConfig, clean_page  # noqa: E402
from modules.detection.processor import TextBlockDetector  # noqa: E402
from modules.inpainting.lama import LaMa  # noqa: E402
from modules.inpainting.schema import Config as InpaintConfig  # noqa: E402
from modules.utils.device import get_providers, resolve_device  # noqa: E402
from modules.utils.image_utils import generate_mask  # noqa: E402
from modules.utils.textblock import TextBlock  # noqa: E402
from pipeline.inpainting import InpaintingHandler  # noqa: E402
from tools._common import sanitize_csv_cell  # noqa: E402

BENCH_TEXT_MARKER = "BENCH"  # cf. conception B1 : contourne require_text_or_translation
DEFAULT_MIN_SIZE = 32 * 1024  # 32 kB
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
BENCH_OUT_ROOT = (REPO_ROOT / "bench" / "out").resolve()
PLANCHE_VIEW_WIDTH = 480  # largeur d'affichage de chaque vue de la planche 4 vues

FASTFILL_LOGGER_NAME = "pipeline.inpainting"
CLEANING_LOGGER_NAME = "modules.cleaning"

# --- Grille de calibration (--sweep), une variation à la fois depuis UI_DEFAULTS ---
SWEEP_GRID: dict[str, list[Any]] = {
    "ring_inner": [2, 4, 6],
    "ring_outer": [6, 8, 12],
    "ring_min_pixels": [100, 200, 400],
    "color_tolerance": [8, 12, 16, 24],
    "uniform_share": [0.75, 0.85, 0.92],
    "ring_quadrant_max": [6, 10, 16],
    "line_length": [31, 45, 61, 91],
    "line_dark_max": [96, 128, 160],
    "line_halo": [1, 2, 4],
    "line_max_thickness": [5, 7, 11],
    "free_dilate_iterations": [1, 2, 3],
    # Jalon 2 (critic pass2 étape 3) :
    "bubble_overlap_max": [0.10, 0.20, 1.0],
    "line_detector": ["components", "runs"],
}


@dataclass
class _BenchDetectionSettings:
    """Substitut minimal (canard) de `SettingsPage` pour `TextBlockDetector`."""

    gpu: bool = False

    def get_tool_selection(self, tool_type: str) -> str:
        return "RT-DETR-v2"

    def is_gpu_enabled(self) -> bool:
        return self.gpu


@dataclass
class PageResult:
    page: str
    t_mask_before_ms: float
    t_clean_before_ms: float
    t_lama_before_ms: float
    t_mask_after_ms: float
    t_clean_after_ms: float
    t_lama_after_ms: float
    n_blocks: int
    n_text_free: int
    n_uni: int
    n_lama: int
    n_skip: int
    skip_breakdown: Counter
    mixed_blocks: int
    bubble_ok: int
    bubble_echec: int
    bubble_absent: int


class _FastFillLogCapture(logging.Handler):
    """Capture les lignes `Inpaint fast-fill: block[...]` (critic pass2 consigne #3).

    L'absence de ligne pour un bloc bulle = "absent" (le bloc est sorti par un
    `continue` sans overlap résiduel, avant tout appel à `_fast_fill_block`).
    """

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.outcomes: dict[int, str] = {}

    def emit(self, record: logging.LogRecord) -> None:
        if record.name != FASTFILL_LOGGER_NAME:
            return
        msg = record.msg if isinstance(record.msg, str) else ""
        if not msg.startswith("Inpaint fast-fill: block[%d]"):
            return
        if not record.args:
            return
        try:
            block_idx = int(record.args[0])
        except (TypeError, ValueError):
            return
        if "cleaned overlap=" in msg:
            self.outcomes[block_idx] = "ok"
        elif "failed" in msg:
            self.outcomes[block_idx] = "echec"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return "inconnu"


def _block_to_dict(blk: TextBlock) -> dict[str, Any]:
    xyxy = [float(v) for v in blk.xyxy] if blk.xyxy is not None else None
    bubble_xyxy = getattr(blk, "bubble_xyxy", None)
    bubble = [float(v) for v in bubble_xyxy] if bubble_xyxy is not None else None
    return {
        "xyxy": xyxy,
        "bubble_xyxy": bubble,
        "text_class": getattr(blk, "text_class", "") or "",
    }


def _block_from_dict(data: dict[str, Any]) -> TextBlock:
    # Origine : filter_and_fix_bboxes renvoie un dtype int (content.py) ; les
    # coordonnées passent ensuite par adjust_text_line_coordinates puis un
    # slicing numpy qui exige des indices entiers. Reconvertir en int ici pour
    # que le JSON rechargé se comporte comme un bloc fraîchement détecté.
    xyxy = data.get("xyxy")
    bubble_xyxy = data.get("bubble_xyxy")
    return TextBlock(
        text_bbox=np.array(xyxy, dtype=int) if xyxy is not None else None,
        bubble_bbox=np.array(bubble_xyxy, dtype=int) if bubble_xyxy is not None else None,
        text_class=data.get("text_class", ""),
        text=BENCH_TEXT_MARKER,
        translation=BENCH_TEXT_MARKER,
    )


def _mark_bench_text(blocks: list[TextBlock]) -> None:
    # fork de banc (conception B1) : contourne require_text_or_translation sans
    # toucher à l'origine. Écart documenté : le lot filtre aussi
    # is_renderable_translation, le banc exerce tous les blocs (sur-approximation
    # volontaire).
    for blk in blocks:
        blk.text = BENCH_TEXT_MARKER
        blk.translation = BENCH_TEXT_MARKER


def _list_pages(pages_dir: Path, only: list[str] | None, min_size: int) -> list[Path]:
    candidates = sorted(p for p in pages_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
    if only:
        wanted = set(only)
        candidates = [p for p in candidates if p.name in wanted]
    kept = []
    for p in candidates:
        size = p.stat().st_size
        if size < min_size:
            print(f"  ignore {p.name} : {size} o < --min-size {min_size} o")
            continue
        kept.append(p)
    return kept


def _detect_blocks(image: np.ndarray, use_gpu: bool) -> tuple[list[TextBlock], TextBlockDetector]:
    settings = _BenchDetectionSettings(gpu=use_gpu)
    detector = TextBlockDetector(settings)
    blocks = detector.detect(image)
    _mark_bench_text(blocks)
    return blocks, detector


def _load_or_detect_blocks(
    page_path: Path,
    image: np.ndarray,
    args: argparse.Namespace,
    detector_cache: dict[str, TextBlockDetector],
) -> list[TextBlock] | None:
    if args.blocks is not None:
        json_path = Path(args.blocks) / f"{page_path.stem}.json"
        if not json_path.exists():
            print(
                f"  refus : {json_path} absent (relancer avec --save-blocks)",
                file=sys.stderr,
            )
            return None
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        current_sha = _sha256_file(page_path)
        if payload.get("sha256") != current_sha:
            print(
                f"  refus : hash périmé pour {page_path.name} "
                f"(json={payload.get('sha256')}, image={current_sha})",
                file=sys.stderr,
            )
            return None
        blocks = [_block_from_dict(d) for d in payload.get("blocks", [])]
        _mark_bench_text(blocks)
        return blocks

    blocks, detector = _detect_blocks(image, args.gpu)
    detector_cache["detector"] = detector

    if args.save_blocks is not None:
        out_dir = Path(args.save_blocks)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "page": page_path.name,
            "sha256": _sha256_file(page_path),
            "blocks": [_block_to_dict(b) for b in blocks],
        }
        (out_dir / f"{page_path.stem}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
    return blocks


def _manual_like_mask(
    image: np.ndarray, blocks: list[TextBlock], free_dilate_iterations: int
) -> np.ndarray:
    """Approxime le masque du flux manuel (critic pass2 consigne #9 / M7).

    `imk.find_contours(crop_mask) -> imk.fill_poly -> dilate 1 px (plume) ->
    dilate 5x5 x marge (re-dilatation "Clean")`. `crop_mask` de départ = EXACTEMENT
    ce que `make_segmentation_stroke_data` utilise pour tracer le trait "Segment" :
    `build_block_mask_data(..., free_dilate_iterations=free_dilate_iterations)`,
    DÉJÀ dilaté une première fois (cf. M7 ci-dessous, cause du bug initial).

    M7 (corrigé) : la première version de cette approximation appelait
    `build_block_mask_data(..., free_dilate_iterations=0)` (masque de contenu
    BRUT, avant toute dilatation) au lieu de la marge réellement utilisée par
    "Segment". Or `make_segmentation_stroke_data` dilate déjà une fois avant de
    tracer le contour ; "Clean" (`generate_mask_from_strokes`) redilate ENSUITE
    une seconde fois (double dilatation, déjà documentée dans la conception :
    ≈13 px effectifs à marge=3, contre 6 px en lot). En partant du masque NON
    dilaté, cette approximation ne reproduisait qu'UNE dilatation sur les deux,
    d'où un écart mesuré de ~37 % (`tests/test_manual_mask_equivalence.py`,
    1444/3904 px) — pas une histoire de contreformes, de plume ou de conversion
    QImage, mais une dilatation entière manquante. Mesuré après correction :
    écart résiduel < 2 % (contreformes bouchées par `fill_poly`, cf. M7 note
    consigne #9 ; test resserré en conséquence).
    """
    from modules.utils.image_utils import build_block_mask_data

    h, w = image.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    for blk in blocks:
        crop_mask, bounds = build_block_mask_data(
            image,
            blk,
            default_padding=5,
            require_text_or_translation=False,
            clip_to_bubble=True,
            free_dilate_iterations=free_dilate_iterations,
        )
        if crop_mask is None or bounds is None:
            continue
        cx1, cy1, cx2, cy2 = bounds
        contours, _ = imk.find_contours(crop_mask)
        if not contours:
            continue
        filled = np.zeros_like(crop_mask)
        imk.fill_poly(filled, [c.reshape(-1, 2) for c in contours], color=255)
        pen_kernel = np.ones((3, 3), np.uint8)
        filled = imk.dilate(filled, pen_kernel, iterations=1)
        # M7 (corrigé) : la seconde dilatation ("Clean") doit s'appliquer à
        # l'échelle de la PAGE, pas dans le rectangle de recadrage de
        # `build_block_mask_data` — celui-ci n'a été dimensionné que pour la
        # première dilatation (Segment) et tronquait la seconde à ses bords,
        # sous-estimant systématiquement le masque final (cause du premier
        # diagnostic ~28 % après la correction de la dilatation manquante).
        block_canvas = np.zeros((h, w), dtype=np.uint8)
        block_canvas[cy1:cy2, cx1:cx2] = filled
        clean_kernel = np.ones((5, 5), np.uint8)
        block_canvas = imk.dilate(
            block_canvas, clean_kernel, iterations=max(0, free_dilate_iterations)
        )
        mask = np.bitwise_or(mask, block_canvas)
    return mask


def _pyside6_available() -> bool:
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return False
    return True


def _ensure_qt_app():
    """Une QApplication par process (offscreen) ; Qt refuse d'en recréer une."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    # Meme piege locale que comic.py::main() (ADR-009) : reset LC_NUMERIC apres
    # la creation de QApplication, avant tout import numerique differe (numpy/onnxruntime).
    locale.setlocale(locale.LC_NUMERIC, "C")
    return app


def _manual_qt_mask(
    image: np.ndarray, blocks: list[TextBlock], free_dilate_iterations: int
) -> np.ndarray:
    """Masque manuel EXACT (M7, option retenue par défaut) : rejoue le vrai chemin Qt.

    `DrawingManager.make_segmentation_stroke_data` (Segment) puis
    `ImageViewer.get_mask_for_inpainting` (Clean), offscreen
    (`QT_QPA_PLATFORM=offscreen`), comme `tests/test_manual_mask_equivalence.py
    --gui`. Écart avec l'app réelle : nul par construction (même code exécuté),
    sous réserve d'un `QApplication` correctement initialisé en mode offscreen.
    """
    from PySide6 import QtGui
    from PySide6.QtGui import QBrush, QColor, QPen
    from PySide6.QtWidgets import QGraphicsPathItem

    _ensure_qt_app()
    from app.ui.canvas.image_viewer import ImageViewer

    h, w = image.shape[:2]
    viewer = ImageViewer(None)
    contiguous = np.ascontiguousarray(image)
    qimage = QtGui.QImage(contiguous.data, w, h, 3 * w, QtGui.QImage.Format_RGB888)
    viewer.setPhoto(QtGui.QPixmap.fromImage(qimage))
    viewer.empty = False
    viewer._bench_qimage_backing = contiguous  # garde une reference vivante (buffer non copie)

    any_stroke = False
    for blk in blocks:
        stroke = viewer.drawing_manager.make_segmentation_stroke_data(
            blk, image=image, free_dilate_iterations=free_dilate_iterations
        )
        if stroke is None:
            continue
        item = QGraphicsPathItem(stroke["path"])
        item.setPen(QPen(QColor(stroke["pen"]), stroke["width"]))
        item.setBrush(QBrush(QColor(stroke["brush"])))
        viewer._scene.addItem(item)
        any_stroke = True

    if not any_stroke:
        return np.zeros((h, w), dtype=np.uint8)

    mask = viewer.get_mask_for_inpainting(free_dilate_iterations=free_dilate_iterations)
    return mask if mask is not None else np.zeros((h, w), dtype=np.uint8)


def _run_lama(
    lama: LaMa, image: np.ndarray, mask: np.ndarray, inpaint_cfg: InpaintConfig
) -> np.ndarray:
    if mask is None or not np.any(mask):
        return image.copy()
    result = lama(image, mask, inpaint_cfg)
    return imk.convert_scale_abs(result)


def _measure_n2_mahotas(image: np.ndarray, blocks: list[TextBlock], cfg: CleaningConfig) -> float:
    """Mesure comparée `--n2-impl mahotas` (critic pass2 consigne #8/#10).

    Réimplémentation locale au banc, uniquement pour la mesure : la
    détection réellement utilisée par `clean_page` reste `run_ge` (O(N)).
    """
    from modules.cleaning.lines import _line_band_bounds  # noqa: SLF001 (mesure uniquement)

    t0 = time.perf_counter()
    for blk in blocks:
        if getattr(blk, "text_class", None) != "text_free":
            continue
        xyxy = getattr(blk, "xyxy", None)
        if xyxy is None or len(xyxy) < 4:
            continue
        bx1, by1, bx2, by2 = _line_band_bounds(xyxy, image.shape[:2], cfg.line_band_margin)
        if bx2 <= bx1 or by2 <= by1:
            continue
        crop = image[by1:by2, bx1:bx2]
        if crop.size == 0:
            continue
        gray = imk.to_gray(crop)
        otsu_val, _ = imk.otsu_threshold(gray)
        dark_thresh = float(cfg.line_dark_max)
        if 0 < otsu_val < cfg.line_dark_max:
            dark_thresh = float(otsu_val)
        dark = gray <= dark_thresh
        long_h = imk.morphology_ex(dark, imk.MORPH_OPEN, np.ones((1, cfg.line_length))) > 0
        thick_v = imk.morphology_ex(dark, imk.MORPH_OPEN, np.ones((cfg.line_max_thickness, 1))) > 0
        _trait_h = long_h & ~thick_v
        long_v = imk.morphology_ex(dark, imk.MORPH_OPEN, np.ones((cfg.line_length, 1))) > 0
        thick_h = imk.morphology_ex(dark, imk.MORPH_OPEN, np.ones((1, cfg.line_max_thickness))) > 0
        _trait_v = long_v & ~thick_h
    return (time.perf_counter() - t0) * 1000.0


def _draw_mask_overlay(image: np.ndarray, mask: np.ndarray) -> Image.Image:
    base = Image.fromarray(image).convert("RGB")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    red = np.zeros((*mask.shape, 4), dtype=np.uint8)
    red[mask > 0] = (255, 0, 0, 120)
    overlay = Image.fromarray(red, mode="RGBA")
    composed = Image.alpha_composite(base.convert("RGBA"), overlay)
    return composed.convert("RGB")


def _make_planche(
    original: np.ndarray,
    mask: np.ndarray,
    before: np.ndarray,
    after: np.ndarray,
    out_path: Path,
) -> None:
    views = [
        ("original", Image.fromarray(original).convert("RGB")),
        ("masque", _draw_mask_overlay(original, mask)),
        ("avant", Image.fromarray(before).convert("RGB")),
        ("apres", Image.fromarray(after).convert("RGB")),
    ]
    scaled = []
    for label, im in views:
        ratio = PLANCHE_VIEW_WIDTH / im.width
        im = im.resize((PLANCHE_VIEW_WIDTH, max(1, int(im.height * ratio))))
        scaled.append((label, im))
    height = max(im.height for _label, im in scaled) + 24
    canvas = Image.new("RGB", (PLANCHE_VIEW_WIDTH * len(scaled), height), (32, 32, 32))
    draw = ImageDraw.Draw(canvas)
    for idx, (label, im) in enumerate(scaled):
        x = idx * PLANCHE_VIEW_WIDTH
        canvas.paste(im, (x, 24))
        draw.text((x + 4, 4), label, fill=(255, 255, 255))
    canvas.save(out_path)


def _bloc_decisions(reports) -> dict[int, str]:
    per_block: dict[int, Counter] = {}
    for r in reports:
        if r.bloc is None:
            continue
        per_block.setdefault(r.bloc, Counter())[r.decision] += 1
    return {
        idx: ",".join(f"{decision}:{count}" for decision, count in counter.most_common())
        for idx, counter in per_block.items()
    }


def _manual_mask_gap_note(
    args: argparse.Namespace,
    pages: list[Path],
    all_blocks: dict[str, list[TextBlock]],
) -> str:
    """Note pour l'en-tête du rapport (M7) : mode retenu + écart mesuré.

    Mesure l'écart une seule fois (première page exploitable), pas par page :
    en mode 'approx', comparer contre le vrai chemin Qt à chaque page annulerait
    l'intérêt de l'approximation (éviter Qt/offscreen par page).
    """
    if args.manual_mask is None:
        return "désactivé : masque du lot (generate_mask), sans objet"
    if args.manual_mask == "qt":
        return "mode qt : chemin DrawingManager/ImageViewer réel, écart nul par construction"

    # mode == "approx"
    if not _pyside6_available():
        return (
            "mode approx : écart non mesuré ici (PySide6 indisponible) — "
            "voir tests/test_manual_mask_equivalence.py --gui"
        )
    sample_page = pages[0]
    sample_blocks = all_blocks[sample_page.stem]
    image = imk.read_image(str(sample_page))
    approx_mask = _manual_like_mask(image, sample_blocks, UI_DEFAULTS.free_dilate_iterations)
    qt_mask = _manual_qt_mask(image, sample_blocks, UI_DEFAULTS.free_dilate_iterations)
    diff = int(np.count_nonzero((approx_mask > 0) != (qt_mask > 0)))
    union = int(np.count_nonzero((approx_mask > 0) | (qt_mask > 0)))
    ratio = diff / union if union else 0.0
    return (
        f"mode approx : écart mesuré {ratio:.1%} vs qt sur {sample_page.name} "
        f"({diff}/{union} px) — voir tests/test_manual_mask_equivalence.py --gui"
    )


def _process_page(
    page_path: Path,
    blocks: list[TextBlock],
    args: argparse.Namespace,
    lama: LaMa,
    inpaint_cfg: InpaintConfig,
    csv_rows: list[list[Any]],
) -> PageResult | None:
    image = imk.read_image(str(page_path))
    handler = InpaintingHandler(None)  # critic pass2 : licite, aucun accès main_page

    if args.manual_mask == "qt":
        mask_before = _manual_qt_mask(image, blocks, INERT.free_dilate_iterations)
        mask_after = _manual_qt_mask(image, blocks, UI_DEFAULTS.free_dilate_iterations)
    elif args.manual_mask == "approx":
        mask_before = _manual_like_mask(image, blocks, INERT.free_dilate_iterations)
        mask_after = _manual_like_mask(image, blocks, UI_DEFAULTS.free_dilate_iterations)
    else:
        mask_before = generate_mask(
            image, blocks, free_dilate_iterations=INERT.free_dilate_iterations
        )
        mask_after = generate_mask(
            image, blocks, free_dilate_iterations=UI_DEFAULTS.free_dilate_iterations
        )

    fastfill_capture = _FastFillLogCapture()
    fastfill_logger = logging.getLogger(FASTFILL_LOGGER_NAME)
    fastfill_logger.addHandler(fastfill_capture)
    previous_level = fastfill_logger.level  # securite mineure #9 : restaure, ne fige pas INFO
    fastfill_logger.setLevel(logging.INFO)

    try:
        t0 = time.perf_counter()
        out_before, mask_before_residual, _cleaned_before, report_before = clean_page(
            image,
            mask_before,
            blocks,
            INERT,
            bubble_cleanup=handler._apply_fast_bubble_cleanup,
        )
        t_clean_before_ms = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        image_before = _run_lama(lama, out_before, mask_before_residual, inpaint_cfg)
        t_lama_before_ms = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        out_after, mask_after_residual, _cleaned_after, report_after = clean_page(
            image,
            mask_after,
            blocks,
            UI_DEFAULTS,
            bubble_cleanup=handler._apply_fast_bubble_cleanup,
        )
        t_clean_after_ms = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        image_after = _run_lama(lama, out_after, mask_after_residual, inpaint_cfg)
        t_lama_after_ms = (time.perf_counter() - t0) * 1000.0
    finally:
        fastfill_logger.removeHandler(fastfill_capture)
        fastfill_logger.setLevel(previous_level)

    n2_mahotas_ms = None
    if args.n2_impl == "mahotas":
        n2_mahotas_ms = _measure_n2_mahotas(image, blocks, UI_DEFAULTS)

    text_free_indices = {
        idx for idx, blk in enumerate(blocks) if getattr(blk, "text_class", None) == "text_free"
    }
    bubble_indices = {
        idx for idx, blk in enumerate(blocks) if getattr(blk, "text_class", None) == "text_bubble"
    }

    n_uni = sum(1 for r in report_after if r.decision == "uni")
    n_lama = sum(1 for r in report_after if r.decision == "lama")
    n_skip = sum(1 for r in report_after if r.decision == "skip")
    skip_breakdown = Counter(r.skip_reason for r in report_after if r.skip_reason)
    bloc_decisions = _bloc_decisions(report_after)
    mixed_blocks = sum(1 for combo in bloc_decisions.values() if "uni" in combo and "lama" in combo)

    bubble_ok = sum(1 for idx in bubble_indices if fastfill_capture.outcomes.get(idx) == "ok")
    bubble_echec = sum(1 for idx in bubble_indices if fastfill_capture.outcomes.get(idx) == "echec")
    bubble_absent = len(bubble_indices) - bubble_ok - bubble_echec

    for r in report_after:
        csv_rows.append(
            [
                page_path.name,
                r.bloc,
                r.classe,
                r.decision,
                r.skip_reason or "",
                r.n_ring,
                *(r.mediane if r.mediane else (None, None, None)),
                r.part,
                r.ecart_quadrants,
                r.residu_bord,
                r.px_retires_n2,
                r.debord_case,
                f"{r.temps * 1000:.3f}",
                bloc_decisions.get(r.bloc, "") if r.bloc is not None else "",
                fastfill_capture.outcomes.get(r.bloc, "absent") if r.bloc in bubble_indices else "",
                # --- Jalon 2 (critic pass2 étape 3, consigne 10) ---
                r.n_ring_geom,
                r.purge_masque,
                r.purge_protege,
                r.purge_bulle,
                r.part_bulle,
                r.clip_bulle,
                r.aire_core,
                r.bbox_core,
                r.distance_bloc_le_plus_proche,
            ]
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _make_planche(
        image,
        mask_after,
        image_before,
        image_after,
        out_dir / f"{page_path.stem}_planche.png",
    )

    print(
        f"  {page_path.name} : avant={t_clean_before_ms + t_lama_before_ms:.0f}ms "
        f"apres={t_clean_after_ms + t_lama_after_ms:.0f}ms "
        f"uni={n_uni} lama={n_lama} skip={n_skip} "
        f"skip_reasons={dict(skip_breakdown)} blocs_mixtes={mixed_blocks} "
        f"bulles(ok={bubble_ok},echec={bubble_echec},absent={bubble_absent})"
        + (f" n2_mahotas={n2_mahotas_ms:.1f}ms" if n2_mahotas_ms is not None else "")
    )

    return PageResult(
        page=page_path.name,
        t_mask_before_ms=0.0,
        t_clean_before_ms=t_clean_before_ms,
        t_lama_before_ms=t_lama_before_ms,
        t_mask_after_ms=0.0,
        t_clean_after_ms=t_clean_after_ms,
        t_lama_after_ms=t_lama_after_ms,
        n_blocks=len(blocks),
        n_text_free=len(text_free_indices),
        n_uni=n_uni,
        n_lama=n_lama,
        n_skip=n_skip,
        skip_breakdown=skip_breakdown,
        mixed_blocks=mixed_blocks,
        bubble_ok=bubble_ok,
        bubble_echec=bubble_echec,
        bubble_absent=bubble_absent,
    )


def _run_sweep(pages: list[Path], all_blocks: dict[str, list[TextBlock]], out_dir: Path) -> None:
    sweep_path = out_dir / "sweep.csv"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[list[Any]] = []
    summaries: list[tuple[str, Any, float, int]] = []  # (param, value, uni_share, mixed_blocks)

    for param, values in SWEEP_GRID.items():
        for value in values:
            cfg = CleaningConfig(**{**asdict(UI_DEFAULTS), param: value})
            total_uni = 0
            total_eligible_or_uni = 0
            total_mixed = 0
            for page_path in pages:
                blocks = all_blocks[page_path.stem]
                image = imk.read_image(str(page_path))
                handler = InpaintingHandler(None)
                mask = generate_mask(
                    image, blocks, free_dilate_iterations=cfg.free_dilate_iterations
                )
                _out_img, _out_mask, _cleaned, report = clean_page(
                    image,
                    mask,
                    blocks,
                    cfg,
                    bubble_cleanup=handler._apply_fast_bubble_cleanup,
                )
                bloc_decisions = _bloc_decisions(report)
                total_mixed += sum(
                    1 for combo in bloc_decisions.values() if "uni" in combo and "lama" in combo
                )
                for r in report:
                    if r.decision in ("uni", "lama"):
                        total_eligible_or_uni += 1
                        if r.decision == "uni":
                            total_uni += 1
                    rows.append(
                        [
                            page_path.name,
                            param,
                            value,
                            r.bloc,
                            r.classe,
                            r.decision,
                            r.skip_reason or "",
                            r.n_ring,
                            r.part,
                            r.ecart_quadrants,
                        ]
                    )
            uni_share = total_uni / total_eligible_or_uni if total_eligible_or_uni else 0.0
            summaries.append((param, value, uni_share, total_mixed))

    with sweep_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "page",
                "param",
                "value",
                "bloc",
                "classe",
                "decision",
                "skip_reason",
                "n_ring",
                "part",
                "ecart_quadrants",
            ]
        )
        for row in rows:
            writer.writerow(sanitize_csv_cell(cell) for cell in row)

    print(f"\nSweep : {sweep_path} ({len(rows)} lignes)")
    print("Meilleur jeu par critère (part uni maximale, sans bloc mixte) :")
    no_mixed = [s for s in summaries if s[3] == 0]
    pool = no_mixed if no_mixed else summaries
    best = max(pool, key=lambda s: s[2])
    print(f"  {best[0]}={best[1]} -> part_uni={best[2]:.3f} blocs_mixtes={best[3]}")
    for param in SWEEP_GRID:
        param_summaries = [s for s in summaries if s[0] == param]
        best_for_param = max(param_summaries, key=lambda s: (s[3] == 0, s[2]))
        print(
            f"  {param}: meilleure valeur={best_for_param[1]} "
            f"part_uni={best_for_param[2]:.3f} blocs_mixtes={best_for_param[3]}"
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("pages_dir", type=Path, help="Dossier de pages (ex. bench/pages)")
    parser.add_argument("--pages", nargs="*", default=None, help="Restreindre à ces fichiers")
    parser.add_argument(
        "--min-size", type=int, default=DEFAULT_MIN_SIZE, help="Taille mini en octets"
    )
    parser.add_argument(
        "--save-blocks", type=Path, default=None, help="Écrit les blocs détectés (JSON)"
    )
    parser.add_argument(
        "--blocks",
        type=Path,
        default=None,
        help="Relit les blocs (JSON), priorité sur la détection",
    )
    parser.add_argument(
        "--manual-mask",
        nargs="?",
        const="qt",
        default=None,
        choices=["qt", "approx"],
        help=(
            "Simule le masque du flux manuel (M7). 'qt' : rejoue le vrai chemin "
            "DrawingManager/ImageViewer (offscreen, écart nul par construction) — "
            "défaut si l'option est donnée sans valeur et PySide6 importable. "
            "'approx' : approximation numpy (find_contours -> fill_poly -> dilate), "
            "écart mesuré imprimé dans l'en-tête du rapport. Sans l'option : masque "
            "du lot (generate_mask)."
        ),
    )
    parser.add_argument("--gpu", action="store_true", default=False, help="GPU (défaut : CPU)")
    parser.add_argument(
        "--out", type=Path, required=True, help="Dossier de sortie, sous bench/out/"
    )
    parser.add_argument(
        "--n2-impl",
        choices=["runs", "mahotas"],
        default="runs",
        help="Mesure comparée N2",
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="Grille de calibration (bench/out/sweep.csv)",
    )
    return parser


def _validate_out_dir(out_dir: Path, flag: str = "--out") -> Path:
    """Confine un chemin de sortie sous `bench/out/` (chemin réel, résolu).

    Sécurité (majeur #3) : appelé aussi pour `--save-blocks`, qui écrit des
    fichiers JSON tout comme `--out` écrit CSV/planches — un chemin non
    confiné y est tout aussi dangereux (écriture arbitraire hors du dépôt).
    """
    resolved = out_dir.resolve()
    if resolved != BENCH_OUT_ROOT and BENCH_OUT_ROOT not in resolved.parents:
        raise SystemExit(f"{flag} doit être sous {BENCH_OUT_ROOT} (reçu {resolved})")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    args.out = _validate_out_dir(args.out)
    if args.save_blocks is not None:
        args.save_blocks = _validate_out_dir(args.save_blocks, flag="--save-blocks")

    # M7 : --manual-mask qt (défaut si demandé sans valeur) exige PySide6 ; repli
    # explicite sur approx si absent (jamais un plantage silencieux du mode).
    if args.manual_mask == "qt" and not _pyside6_available():
        print(
            "Avertissement : --manual-mask qt demandé mais PySide6 n'est pas "
            "importable ; repli sur --manual-mask approx (écart mesuré dans l'en-tête).",
            file=sys.stderr,
        )
        args.manual_mask = "approx"

    if not args.pages_dir.is_dir():
        print(f"Dossier introuvable : {args.pages_dir}", file=sys.stderr)
        return 1

    pages = _list_pages(args.pages_dir, args.pages, args.min_size)
    if not pages:
        print("Aucune page à traiter.", file=sys.stderr)
        return 1

    device = resolve_device(args.gpu, "onnx")
    providers = get_providers(device)  # fork (sécurité mineure #5) : F841, désormais journalisé
    print(
        f"Pages : {len(pages)}  |  device={device}  |  manual_mask={args.manual_mask}  |  "
        f"n2_impl={args.n2_impl}  |  providers={providers}"
    )

    detector_cache: dict[str, TextBlockDetector] = {}
    failures = 0
    all_blocks: dict[str, list[TextBlock]] = {}
    for page_path in pages:
        image = imk.read_image(str(page_path))
        blocks = _load_or_detect_blocks(page_path, image, args, detector_cache)
        if blocks is None:
            failures += 1
            continue
        all_blocks[page_path.stem] = blocks
    pages = [p for p in pages if p.stem in all_blocks]
    if not pages:
        print("Aucune page exploitable (voir refus ci-dessus).", file=sys.stderr)
        return 1

    if args.sweep:
        _run_sweep(pages, all_blocks, args.out)
        return 0

    manual_mask_note = _manual_mask_gap_note(args, pages, all_blocks)
    print(f"Masque manuel : {manual_mask_note}")

    lama = LaMa(device, backend="onnx")
    provider_inpainting = (
        lama.session.get_providers() if getattr(lama, "session", None) is not None else []
    )
    provider_detection = (
        detector_cache["detector"].detector if "detector" in detector_cache else "n/a (--blocks)"
    )
    inpaint_cfg = InpaintConfig()  # hd_strategy="Original" : pas de patch, appel direct

    args.out.mkdir(parents=True, exist_ok=True)
    csv_path = args.out / "report.csv"
    csv_rows: list[list[Any]] = []
    results: list[PageResult] = []

    print(f"Providers : detection={provider_detection}  inpainting={provider_inpainting}")

    for page_path in pages:
        blocks = all_blocks[page_path.stem]
        result = _process_page(page_path, blocks, args, lama, inpaint_cfg, csv_rows)
        if result is not None:
            results.append(result)
        else:
            failures += 1

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        f.write(f"# date={datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"# commit={_git_commit()}\n")
        f.write(f"# config=UI_DEFAULTS ({UI_DEFAULTS})\n")
        f.write(
            f"# device={device} provider_detection={provider_detection} provider_inpainting={provider_inpainting}\n"
        )
        f.write(f"# manual_mask={args.manual_mask} ({manual_mask_note}) n2_impl={args.n2_impl}\n")
        writer = csv.writer(f)
        writer.writerow(
            [
                "page",
                "bloc",
                "classe",
                "decision",
                "skip_reason",
                "n_ring",
                "mediane_r",
                "mediane_g",
                "mediane_b",
                "part",
                "ecart_quadrants",
                "residu_bord",
                "px_retires_n2",
                "debord_case",
                "temps_ms",
                "bloc_decisions",
                "bulle_fastfill",
                "n_ring_geom",
                "purge_masque",
                "purge_protege",
                "purge_bulle",
                "part_bulle",
                "clip_bulle",
                "aire_core",
                "bbox_core",
                "distance_bloc_le_plus_proche",
            ]
        )
        for row in csv_rows:
            writer.writerow(sanitize_csv_cell(cell) for cell in row)

    print(f"\nRapport : {csv_path}")
    print("Synthèse par page :")
    for r in results:
        t_before = r.t_clean_before_ms + r.t_lama_before_ms
        t_after = r.t_clean_after_ms + r.t_lama_after_ms
        pct_uni = (r.n_uni / r.n_text_free * 100.0) if r.n_text_free else 0.0
        print(
            f"  {r.page}: avant={t_before:.0f}ms apres={t_after:.0f}ms "
            f"%uni={pct_uni:.0f}% skip={dict(r.skip_breakdown)} "
            f"mixtes={r.mixed_blocks} bulles(ok={r.bubble_ok},echec={r.bubble_echec},absent={r.bubble_absent})"
        )

    if failures:
        print(
            f"\n{failures} page(s) en échec (hash périmé / blocs manquants).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
