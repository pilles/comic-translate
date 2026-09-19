"""Historique de versions par bloc (spec 03, jalon A).

N'expose que l'API pure de `versions.py` — aucun import PySide6 ici, jamais
(vérifié par `tests/test_block_versions_no_qt_import.py`). `commands.py`
(QUndoCommand) et `ui.py` (QMenu) importent PySide6 et ne sont importés que
depuis `app/ui/main_window/builders/workspace.py`.
"""

from __future__ import annotations

from modules.history.versions import (
    FIELD_TEXT,
    FIELD_TRANSLATION,
    MAX_CHARS_PER_BLOCK,
    MAX_VALUE_CHARS,
    MAX_VERSIONS_PER_BLOCK,
    ORIGIN_CACHE,
    ORIGIN_CACHE_OCR,
    ORIGIN_MANUAL,
    ORIGIN_OCR,
    ORIGIN_PRIOR,
    ORIGIN_RESTORE,
    ORIGIN_SEARCH_REPLACE,
    ORIGIN_TRANSLATION,
    HistoryEntry,
    flush_pending,
    pop_head_if_origin,
    prune,
    record_diff,
    set_many,
    set_text,
    snapshot,
    versions_of,
)

__all__ = [
    "FIELD_TEXT",
    "FIELD_TRANSLATION",
    "MAX_CHARS_PER_BLOCK",
    "MAX_VALUE_CHARS",
    "MAX_VERSIONS_PER_BLOCK",
    "ORIGIN_CACHE",
    "ORIGIN_CACHE_OCR",
    "ORIGIN_MANUAL",
    "ORIGIN_OCR",
    "ORIGIN_PRIOR",
    "ORIGIN_RESTORE",
    "ORIGIN_SEARCH_REPLACE",
    "ORIGIN_TRANSLATION",
    "HistoryEntry",
    "flush_pending",
    "pop_head_if_origin",
    "prune",
    "record_diff",
    "set_many",
    "set_text",
    "snapshot",
    "versions_of",
]
