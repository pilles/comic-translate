"""Coquille de la nouvelle disposition (spec 04, jalon 2, sous-étape 2a).

Paquet pur pour ce module d'entrée et pour `manifest.py`/`context.py` : aucun import PySide6
ici, jamais (vérifié par `tests/test_shell.py`, sous-processus qui inspecte `sys.modules`,
précédent : `modules/pagestate/__init__.py`). `layout.py` et `panel.py` importent PySide6 et ne
sont importés que depuis `app/ui/main_window/window.py` (le premier) et `modules/shell/layout.py`
(le second) — jamais depuis ce fichier."""

from __future__ import annotations
