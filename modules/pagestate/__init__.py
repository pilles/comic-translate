"""État d'avancement par page (spec 04, jalon 1).

N'expose que l'API pure de `progress.py`/`collect.py` — aucun import PySide6
ici, jamais (vérifié par `tests/test_pagestate.py`, sous-processus qui
inspecte `sys.modules`, précédent : `modules/history/__init__.py`). `ui.py`
importe PySide6 et n'est importé que depuis
`app/ui/main_window/builders/workspace.py` / `controller.py`."""

from __future__ import annotations

from modules.pagestate.collect import live_path, page_progress
from modules.pagestate.progress import STEPS, PageProgress, compute_progress

__all__ = [
    "STEPS",
    "PageProgress",
    "compute_progress",
    "live_path",
    "page_progress",
]
