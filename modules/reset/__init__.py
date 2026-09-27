"""Réinitialisation de page (spec 04, jalon 3, sous-étape 3a).

Remet la page affichée dans son état « jamais traitée » : aucun bloc, aucun rectangle, aucun
texte reconnu/traduit, aucun patch de nettoyage, aucun tracé de pinceau/segmentation, aucun texte
rendu. Portée : la page affichée seule, jamais les autres pages ni les réglages (langues, police).
Annulable (Cmd+Z, une seule étape).

`state.py` (pur, aucun import PySide6 — voir ADR-012/ADR-014 pour le précédent de découplage) :
calcul de l'état vierge, fusion à l'annulation, disponibilité du bouton, textes des messages.
`commands.py` (PySide6) : `ResetPageCommand`. `ui.py` (PySide6) : bouton, disponibilité, clic.

Docstring seulement ici — n'importer `commands`/`ui` que depuis `controller.py` (`ui.py`) et
`modules/reset/ui.py` (`commands.py`), jamais depuis ce fichier."""

from __future__ import annotations
