"""Hors GUI (spec 04, jalon 2, sous-étape 2a) : `modules.shell.manifest` (pur) et
`modules.shell.context` (pur). `modules.shell.layout`/`modules.shell.panel` importent PySide6 —
testés en `--gui` (`tests/test_shell_ui.py`), jamais ici.

Précédent pour le sous-processus « pas de PySide6 dans `sys.modules` » :
`tests/test_pagestate.py::test_modules_pagestate_does_not_import_pyside6_transitively`."""

from __future__ import annotations

import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

from modules.shell import manifest
from modules.shell.context import language_caption

REPO_ROOT = Path(__file__).resolve().parent.parent


# --- Manifeste : pas de doublon, zones disjointes --------------------------------------------


def test_manifest_zones_have_no_internal_duplicate():
    for zone_name, names in manifest.ALL_ZONES:
        counts = Counter(names)
        duplicates = [name for name, count in counts.items() if count > 1]
        assert not duplicates, f"doublon dans {zone_name} : {duplicates}"


def test_manifest_zones_are_pairwise_disjoint():
    seen: dict[str, str] = {}
    for zone_name, names in manifest.ALL_ZONES:
        for name in names:
            assert name not in seen, f"{name} apparaît à la fois dans {seen[name]} et {zone_name}"
            seen[name] = zone_name


def test_moved_zones_exclude_parked_and_external():
    moved_names = {name for _zone, names in manifest.MOVED_ZONES for name in names}
    assert "undo_tool_group" not in moved_names
    for name in manifest.PARKED:
        assert name not in moved_names


def test_all_zones_is_moved_zones_plus_parked_and_external():
    all_names = {name for _zone, names in manifest.ALL_ZONES for name in names}
    moved_names = {name for _zone, names in manifest.MOVED_ZONES for name in names}
    expected = moved_names | set(manifest.PARKED) | set(manifest.EXTERNAL)
    assert all_names == expected


# --- context.language_caption -----------------------------------------------------------------


def test_language_caption_with_text():
    assert language_caption("Source", "English") == "Source · English"


def test_language_caption_empty_combo_text_falls_back_to_prefix():
    assert language_caption("Source", "") == "Source"
    assert language_caption("Source", "   ") == "Source"


# --- Aucun import PySide6 (paquet pur) ---------------------------------------------------------


def test_modules_shell_does_not_import_pyside6_transitively():
    code = (
        "import sys\n"
        "import modules.shell\n"
        "import modules.shell.manifest\n"
        "import modules.shell.context\n"
        "leaked = sorted(k for k in sys.modules if k == 'PySide6' or k.startswith('PySide6.'))\n"
        "assert not leaked, leaked\n"
        "print('OK')\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"stdout={proc.stdout}\nstderr={proc.stderr}"
    assert proc.stdout.strip().splitlines()[-1] == "OK"
