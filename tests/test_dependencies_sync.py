"""Tests F1 : tools/sync_deps.py (spec 01 §5).

Vérifie que le miroir `pyproject.toml` <-> `requirements.txt` du dépôt réel
est synchronisé (`--check`), et couvre la logique pure de diff/parsing sans
toucher aux fichiers du dépôt.
"""

from __future__ import annotations

import pytest
from packaging.requirements import Requirement

from tools import sync_deps


def test_check_passes_on_real_repo_files():
    """Non-régression : le dépôt livré doit être synchronisé (exit 0)."""
    assert sync_deps.main(["--check"]) == 0


def test_diff_requirements_empty_when_identical():
    reqs = [Requirement("foo>=1.0"), Requirement("bar")]
    assert sync_deps.diff_requirements(reqs, reqs) == []


def test_diff_requirements_reports_missing_entries():
    from_requirements = [Requirement("foo>=1.0"), Requirement("bar")]
    from_pyproject = [Requirement("foo>=1.0")]
    diffs = sync_deps.diff_requirements(from_requirements, from_pyproject)
    assert diffs
    assert any("bar" in d for d in diffs)


def test_parse_pyproject_dependencies_missing_markers_raises():
    with pytest.raises(sync_deps.SyncDepsError):
        sync_deps.parse_pyproject_dependencies('[project]\nname = "x"\n')


def test_parse_pyproject_dependencies_duplicate_markers_raises():
    text = (
        f'{sync_deps.MARKER_BEGIN}\n"foo",\n{sync_deps.MARKER_END}\n'
        f'{sync_deps.MARKER_BEGIN}\n"bar",\n{sync_deps.MARKER_END}\n'
    )
    with pytest.raises(sync_deps.SyncDepsError):
        sync_deps.parse_pyproject_dependencies(text)
