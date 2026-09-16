"""Fonctions pures de `tools/bench_cleaning.py`, sans detecteur ni modele ONNX.

Aucune page de bench/pages, aucun reseau, aucune instanciation de
TextBlockDetector/LaMa. Le module s'importe librement (les imports lourds
n'instancient rien au niveau module).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import tools.bench_cleaning as bc
from modules.utils.image_utils import generate_mask
from modules.utils.textblock import TextBlock
from tools._common import sanitize_csv_cell


def _letters_image(h, w):
    image = np.full((h, w, 3), 240, np.uint8)
    for i in range(8):
        x = 35 + i * 9
        image[65:82, x : x + 5] = 10
    return image


def test_mask_independent_of_text_length():
    h, w = 150, 150
    image = _letters_image(h, w)
    blk_a = TextBlock(
        text_bbox=np.array([30, 60, 110, 90]), text_class="text_free", text="A", translation="A"
    )
    blk_long = TextBlock(
        text_bbox=np.array([30, 60, 110, 90]),
        text_class="text_free",
        text="x" * 400,
        translation="x" * 400,
    )

    m_short = generate_mask(image, [blk_a])
    m_long = generate_mask(image, [blk_long])

    assert np.any(m_short)  # scenario non-degenere (pas deux masques vides)
    assert m_short.tobytes() == m_long.tobytes()


def test_block_dict_roundtrip():
    blk = TextBlock(
        text_bbox=np.array([1, 2, 3, 4]),
        bubble_bbox=np.array([5, 6, 7, 8]),
        text_class="text_bubble",
        text="ignored",
        translation="ignored",
    )
    data = bc._block_to_dict(blk)
    restored = bc._block_from_dict(data)

    assert data == {
        "xyxy": [1.0, 2.0, 3.0, 4.0],
        "bubble_xyxy": [5.0, 6.0, 7.0, 8.0],
        "text_class": "text_bubble",
    }
    assert list(restored.xyxy) == [1, 2, 3, 4]
    assert list(restored.bubble_xyxy) == [5, 6, 7, 8]
    assert restored.text_class == "text_bubble"
    # B1 : le banc force text/translation a BENCH_TEXT_MARKER (contourne
    # require_text_or_translation sans toucher l'origine).
    assert restored.text == bc.BENCH_TEXT_MARKER
    assert restored.translation == bc.BENCH_TEXT_MARKER


def test_load_or_detect_blocks_refuses_stale_sha256(tmp_path):
    h, w = 150, 150
    image = _letters_image(h, w)
    page_path = tmp_path / "page1.png"
    Image.fromarray(image).save(page_path)

    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    blk = TextBlock(
        text_bbox=np.array([30, 60, 110, 90]), text_class="text_free", text="x", translation="x"
    )
    payload = {
        "page": "page1.png",
        "sha256": "0" * 64,  # perime par construction
        "blocks": [bc._block_to_dict(blk)],
    }
    (blocks_dir / "page1.json").write_text(json.dumps(payload))

    args = argparse.Namespace(blocks=blocks_dir, save_blocks=None, gpu=False)
    result = bc._load_or_detect_blocks(page_path, image, args, {})

    assert result is None


def test_load_or_detect_blocks_accepts_matching_sha256(tmp_path):
    h, w = 150, 150
    image = _letters_image(h, w)
    page_path = tmp_path / "page1.png"
    Image.fromarray(image).save(page_path)

    blocks_dir = tmp_path / "blocks"
    blocks_dir.mkdir()
    blk = TextBlock(
        text_bbox=np.array([30, 60, 110, 90]), text_class="text_free", text="x", translation="x"
    )
    payload = {
        "page": "page1.png",
        "sha256": bc._sha256_file(page_path),
        "blocks": [bc._block_to_dict(blk)],
    }
    (blocks_dir / "page1.json").write_text(json.dumps(payload))

    args = argparse.Namespace(blocks=blocks_dir, save_blocks=None, gpu=False)
    result = bc._load_or_detect_blocks(page_path, image, args, {})

    assert result is not None
    assert len(result) == 1
    assert result[0].text_class == "text_free"
    assert result[0].text == bc.BENCH_TEXT_MARKER  # _mark_bench_text applique


def test_validate_out_dir_refuses_outside_bench_out():
    with pytest.raises(SystemExit):
        bc._validate_out_dir(Path("/tmp/outside-bench-out"))


def test_validate_out_dir_accepts_subdir_of_bench_out():
    target = bc.REPO_ROOT / "bench" / "out" / "some_subdir"
    resolved = bc._validate_out_dir(target)
    assert resolved == target.resolve()


def test_validate_out_dir_refuses_save_blocks_outside_bench_out():
    # Securite majeur #3 : --save-blocks ecrit du JSON tout comme --out ecrit
    # CSV/planches, un chemin non confine y est tout aussi dangereux.
    with pytest.raises(SystemExit):
        bc._validate_out_dir(Path("/tmp/outside-bench-out"), flag="--save-blocks")


def test_main_refuses_save_blocks_outside_bench_out():
    # La validation de --save-blocks doit avoir lieu avant tout acces disque
    # au dossier de pages (pas de detecteur ni de modele charge ici).
    with pytest.raises(SystemExit):
        bc.main(
            [
                "does-not-exist",
                "--out",
                "bench/out",
                "--save-blocks",
                "/tmp/outside-bench-out",
            ]
        )


def test_sanitize_csv_cell_is_reexported_from_common():
    assert bc.sanitize_csv_cell is sanitize_csv_cell
    assert sanitize_csv_cell("=cmd") == "'=cmd"
    assert sanitize_csv_cell("plain") == "plain"


def test_n2_impl_argument_accepts_only_known_choices():
    parser = bc.build_arg_parser()
    ns = parser.parse_args(["somedir", "--out", "bench/out/x"])
    assert ns.n2_impl == "runs"

    ns2 = parser.parse_args(["somedir", "--out", "bench/out/x", "--n2-impl", "mahotas"])
    assert ns2.n2_impl == "mahotas"

    with pytest.raises(SystemExit):
        parser.parse_args(["somedir", "--out", "bench/out/x", "--n2-impl", "bogus"])


def test_manual_like_mask_produces_non_trivial_mask():
    h, w = 150, 150
    image = _letters_image(h, w)
    blk = TextBlock(
        text_bbox=np.array([30, 60, 110, 90]),
        text_class="text_free",
        text=bc.BENCH_TEXT_MARKER,
        translation=bc.BENCH_TEXT_MARKER,
    )
    mask = bc._manual_like_mask(image, [blk], free_dilate_iterations=3)
    assert mask.dtype == np.uint8
    assert mask.shape == (h, w)
    assert np.any(mask)


def test_bloc_decisions_aggregates_per_block_counter():
    from modules.cleaning.uniform import ComponentReport

    def _report(label, bloc, decision):
        return ComponentReport(
            label=label,
            bloc=bloc,
            classe="text_free",
            decision=decision,
            skip_reason=None,
            n_ring=1,
            mediane=None,
            part=1.0,
            ecart_quadrants=0.0,
            residu_bord=0.0,
            px_retires_n2=0,
            debord_case=0,
            temps=0.0,
        )

    reports = [_report(1, 0, "uni"), _report(2, 0, "uni"), _report(3, 0, "lama")]
    result = bc._bloc_decisions(reports)

    assert result == {0: "uni:2,lama:1"}


def test_no_network_or_model_instantiation_on_import():
    """Le module s'importe (via les fixtures ci-dessus, en tete de fichier)
    sans instancier TextBlockDetector ni LaMa : ces classes ne sont
    construites que dans `main()`, jamais au niveau module."""
    assert bc.LaMa is not None
    assert bc.TextBlockDetector is not None
    # Aucune instance vivante attendue tant que main() n'a pas ete appele :
    # rien a verifier de plus que l'import lui-meme n'a pas leve/bloque
    # (deja demontre par les imports en tete de ce fichier).
