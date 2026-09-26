"""Hotfix 2026-09-27 : détection, reconnaissance, segmentation et traduction analysent le texte
sur la photo d'origine, jamais sur l'image nettoyée (patchs). Sans ce correctif, « Détecter »
sur une page déjà nettoyée ne trouvait aucune bulle et remplaçait les blocs existants par zéro."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from PySide6 import QtGui, QtWidgets

from modules.view.original import OriginalViewImageViewer
from pipeline.block_detection import BlockDetectionHandler

ROOT = Path(__file__).resolve().parent.parent

# (fichier, nombre d'appels attendus) — tout appel d'analyse du texte de la page courante.
_ANALYSIS_CALL_SITES = {
    "pipeline/block_detection.py": 1,
    "pipeline/ocr_handler.py": 1,
    "pipeline/translation_handler.py": 1,
    "app/controllers/manual_workflow.py": 2,
}


def test_analysis_call_sites_exclude_cleaning_patches():
    for rel, expected in _ANALYSIS_CALL_SITES.items():
        source = (ROOT / rel).read_text()
        calls = re.findall(r"image_viewer\.get_image_array\(([^)]*)\)", source)
        assert len(calls) == expected, (rel, calls)
        assert all("include_patches=False" in args for args in calls), (rel, calls)


def test_detection_sees_original_photo_not_cleaning_patch(qtbot):
    viewer = OriginalViewImageViewer(None)
    qtbot.addWidget(viewer)
    photo = np.zeros((60, 80, 3), dtype=np.uint8)
    photo[:] = (200, 0, 0)
    viewer.display_image_array(photo, fit=True)

    patch = QtGui.QPixmap(20, 20)
    patch.fill(QtGui.QColor("white"))
    item = QtWidgets.QGraphicsPixmapItem(patch)
    item.setData(0, "hash-du-patch")  # marqueur des patchs (PatchCommandBase.HASH_KEY)
    item.setPos(10, 10)
    viewer._scene.addItem(item)

    # Garde-fou du test : l'image affichée contient bien le patch.
    shown = viewer.get_image_array()
    assert tuple(shown[15, 15]) == (255, 255, 255)

    seen = {}

    class _Detector:
        def detect(self, image):
            seen["image"] = image
            return []

    handler = BlockDetectionHandler(
        SimpleNamespace(image_viewer=viewer, webtoon_mode=False, settings_page=None)
    )
    handler.block_detector_cache = _Detector()
    handler.detect_blocks()

    analysed = seen["image"]
    assert analysed.shape[:2] == (60, 80)
    assert tuple(analysed[15, 15]) == (200, 0, 0)
    assert (analysed == photo).all()
