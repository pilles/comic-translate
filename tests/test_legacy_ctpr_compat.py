"""Compatibilité « projet antérieur » (mission tester, point 2) : un `.ctpr`
créé AVANT le jalon A (donc sans `versions` sur aucun bloc) doit se charger
sans exception, et la première écriture instrumentée sur un bloc rechargé
doit produire un pré-état `prior` (la traduction du projet antérieur) suivi
de la nouvelle valeur.

Le fichier `.ctpr` n'est PAS versionné (contient une page de BD, voir
`CLAUDE.md` « Interdits ») : son chemin est lu depuis la variable
d'environnement `COMIC_TRANSLATE_LEGACY_CTPR`. Le test est ignoré (`skip`)
si la variable est absente ou pointe vers un fichier inexistant.

`--gui` requis (voir `tests/conftest.py::_GUI_ONLY_FILES`) : charge un vrai
`.ctpr` dans une vraie `ComicTranslate`, comme `tests/test_history_restore.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.projects.project_state_v2 import load_state_from_proj_file_v2
from modules.history import ui, versions

_ENV_VAR = "COMIC_TRANSLATE_LEGACY_CTPR"
_env_path = os.environ.get(_ENV_VAR, "")
LEGACY_CTPR_PATH = Path(_env_path) if _env_path else None

pytestmark = pytest.mark.skipif(
    not LEGACY_CTPR_PATH or not LEGACY_CTPR_PATH.exists(),
    reason=(
        f"pas de .ctpr antérieur au jalon A disponible : définir {_ENV_VAR} "
        "vers un fichier .ctpr créé avant la spec 03 jalon A pour activer ce test."
    ),
)


@pytest.fixture
def main(qtbot):
    from controller import ComicTranslate

    instance = ComicTranslate()
    qtbot.addWidget(instance)
    instance._skip_close_prompt = True
    yield instance


def _first_blk_list(main):
    for state in main.image_states.values():
        blk_list = state.get("blk_list")
        if blk_list:
            return blk_list
    return []


def test_legacy_ctpr_loads_without_exception_and_blocks_have_no_versions(main):
    load_state_from_proj_file_v2(main, str(LEGACY_CTPR_PATH))  # ne doit pas lever

    blk_list = _first_blk_list(main)
    assert blk_list, "le .ctpr antérieur doit contenir au moins un bloc pour ce test"

    for blk in blk_list:
        assert versions.versions_of(blk) == []


def test_legacy_ctpr_history_menu_builds_without_exception_grayed_or_empty(main):
    load_state_from_proj_file_v2(main, str(LEGACY_CTPR_PATH))
    blk_list = _first_blk_list(main)
    main.curr_tblock = blk_list[0] if blk_list else None

    menu = ui.build_history_menu(main, main.block_history_button)  # ne doit pas lever

    actions = menu.actions()
    assert len(actions) >= 1
    # Bloc sans versions -> soit le placeholder "aucun bloc", soit aucune
    # action utilisable (toutes désactivées : rien à restaurer).
    if main.curr_tblock is None:
        assert not actions[0].isEnabled()
    else:
        assert all(not a.isEnabled() for a in actions if not a.isSeparator())


def test_legacy_ctpr_first_write_creates_prior_then_new_entry(main):
    load_state_from_proj_file_v2(main, str(LEGACY_CTPR_PATH))
    blk_list = _first_blk_list(main)
    assert blk_list
    blk = blk_list[0]
    previous_translation = getattr(blk, "translation", "") or ""

    changed = versions.set_text(blk, "translation", "x", "translation", {"model": "Custom"})

    entries = versions.versions_of(blk, "translation")
    assert changed is True
    assert blk.translation == "x"
    if previous_translation:
        assert [e["value"] for e in entries] == [previous_translation, "x"]
        assert [e["origin"] for e in entries] == [versions.ORIGIN_PRIOR, "translation"]
    else:
        # Bloc antérieur sans traduction : pas de pré-état (cur falsy).
        assert [e["value"] for e in entries] == ["x"]
        assert [e["origin"] for e in entries] == ["translation"]
