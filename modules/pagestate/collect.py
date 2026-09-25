"""Lecture de l'avancement d'une page depuis l'état vivant de l'application
(spec 04, jalon 1) — module pur.

Duck typing sur `main` uniquement (attributs `webtoon_mode`, `_batch_active`,
`image_files`, `curr_img_idx`, `image_data`, `blk_list`, `image_states`,
`image_patches`, `image_viewer.text_items`, `image_viewer._scene`) : aucun
import de PySide6 ni de `controller.ComicTranslate` ici (voir
`tests/test_pagestate.py`, sous-processus qui vérifie l'absence de PySide6
dans `sys.modules`). Lecture seule partout — ce module n'écrit jamais dans
`image_states`, `blk_list`, `image_patches` ni le viewer.

Ne lève jamais (consigne critic m7) : chaque source (blocs, patchs, rendu)
est lue séparément sous son propre `try/except`, pour qu'une donnée pourrie
ne fasse tomber que l'étape concernée, jamais toute la ligne. Chaque famille
d'échec est journalisée une seule fois (`_warn_once`, précédent :
`modules/history/versions.py::_warn_max_value_chars_once`)."""

from __future__ import annotations

import logging
from typing import Any

from modules.pagestate.progress import PageProgress, compute_progress

logger = logging.getLogger(__name__)

_warned_contexts: set[str] = set()


def _warn_once(context: str) -> None:
    if context in _warned_contexts:
        return
    _warned_contexts.add(context)
    logger.warning("modules.pagestate: lecture dégradée (%s).", context)
    logger.debug("modules.pagestate: détail de la dégradation (%s)", context, exc_info=True)


def live_path(main: Any) -> str | None:
    """Chemin de la page « vivante » (blocs = `main.blk_list`, rendu = les
    items de la scène active), ou `None` si aucune page ne joue ce rôle :
    mode webtoon, lot en cours, `curr_img_idx` hors de `[0, len(image_files))`
    (y compris `-1`), ou page jamais chargée dans `image_data`."""
    try:
        if getattr(main, "webtoon_mode", False):
            return None
        if getattr(main, "_batch_active", False):
            return None

        image_files = getattr(main, "image_files", None) or []
        idx = getattr(main, "curr_img_idx", -1)
        if not isinstance(idx, int) or not (0 <= idx < len(image_files)):
            return None

        path = image_files[idx]

        image_data = getattr(main, "image_data", None)
        if not isinstance(image_data, dict) or image_data.get(path) is None:
            return None

        return path
    except Exception:
        _warn_once("live_path")
        return None


def _blocks_for(main: Any, path: str, current: str | None) -> list[Any]:
    try:
        if path == current:
            blk_list = getattr(main, "blk_list", None) or []
            return list(blk_list)

        image_states = getattr(main, "image_states", None)
        if not isinstance(image_states, dict):
            return []
        state = image_states.get(path)
        if not isinstance(state, dict):
            return []
        blk_list = state.get("blk_list") or []
        return list(blk_list)
    except Exception:
        _warn_once("blocs")
        return []


def _count_patches(main: Any, path: str) -> int:
    try:
        image_patches = getattr(main, "image_patches", None)
        if not isinstance(image_patches, dict):
            return 0
        patches = image_patches.get(path) or []
        return len(list(patches))
    except Exception:
        _warn_once("patchs")
        return 0


def _rendered_for(main: Any, path: str, current: str | None) -> int:
    try:
        if path == current:
            viewer = getattr(main, "image_viewer", None)
            if viewer is None:
                return 0
            scene = getattr(viewer, "_scene", None)
            items = list(getattr(viewer, "text_items", None) or [])
            count = 0
            for item in items:
                try:
                    if item.scene() is scene:
                        count += 1
                except Exception:
                    # Item Qt détruit entre deux lectures (page en cours de
                    # rechargement) : ne compte pas, ne fait pas tomber le reste.
                    continue
            return count

        image_states = getattr(main, "image_states", None)
        if not isinstance(image_states, dict):
            return 0
        state = image_states.get(path)
        if not isinstance(state, dict):
            return 0
        viewer_state = state.get("viewer_state")
        if not isinstance(viewer_state, dict):
            return 0
        text_items_state = viewer_state.get("text_items_state") or []
        return len(list(text_items_state))
    except Exception:
        _warn_once("rendu")
        return 0


def page_progress(main: Any, path: str) -> PageProgress:
    """Avancement de `path`. Source unique pour l'UI (`modules/pagestate/ui.py`)
    et pour les tests. Ne lève jamais."""
    current = live_path(main)
    blocks = _blocks_for(main, path, current)
    n_patches = _count_patches(main, path)
    n_rendered = _rendered_for(main, path, current)
    return compute_progress(blocks, n_patches, n_rendered)
