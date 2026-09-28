"""Macros d'annulation sûres pour le nettoyage et la segmentation (spec 04, jalon 3,
sous-étape 3a-bis — option D retenue par le critic).

Contexte (ADR-020, ADR-021) : la macro « nettoyage »/« segmentation » n'est plus ouverte au clic
et fermée dans un rappel ultérieur (un tour de boucle Qt plus tard) — si l'utilisateur change de
page entre les deux, `endMacro()` referme la mauvaise pile et l'ancienne reste bloquée avec une
macro jamais close (Annuler refusé jusqu'à la fermeture de l'app). Elle est désormais ouverte
**dans le rappel de succès lui-même**, de façon synchrone, et refermée dans le même appel.

`macro.py` (pur, aucun import PySide6 — voir ADR-012/ADR-014/ADR-020 pour le précédent de
découplage) : `in_macro` (macro liée à la pile active à l'appel, pour les rappels multi-pages),
`page_bound` (macro liée à la page affichée au clic — abandonne si elle a changé, décision D1 de
Philippe 2026-09-28), messages d'abandon.
`ui.py` (PySide6) : verrou d'annulation pendant le calcul (`main._undo_locked_by`, boutons
Annuler/Rétablir de la barre de titre désactivés, raccourci refusé — 1 ligne dans
`app/controllers/shortcuts.py`), filet de sécurité (chien de garde) si l'opération qui a posé le
verrou n'est jamais passée par un rappel (file vidée par une annulation avant démarrage,
ADR-019), et les fabriques `guard_cleaning`/`guard_segmentation` utilisées par
`app/controllers/manual_workflow.py`.

Docstring seulement ici — n'importer `macro`/`ui` que depuis les fichiers amont qui en ont besoin
(`app/controllers/manual_workflow.py`, `pipeline/inpainting.py` ne l'importe pas : il ne fait plus
que ne pas fermer de macro) et `controller.py` (`install_undo_guard`), jamais depuis ce fichier."""

from __future__ import annotations
