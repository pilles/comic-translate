"""Annulations de texte robustes aux items recréés (spec 04, jalon 3, sous-étape 3a-ter, ADR-022).

Contexte (ADR-020, limite MAJ1) : `TextEditCommand`, `TextFormatCommand` et `RestoreVersionCommand`
mémorisent l'objet `TextBlockItem` sur lequel ils ont été créés. Or la scène est reconstruite à
chaque changement de page (`display_image_array` -> `scene.clear()`, puis `load_state`) et par le
reset : l'item mémorisé est alors détruit (`RuntimeError: already deleted`) ou détaché (aucun effet
visible alors que le bloc change).

Décision de Philippe (2026-09-28, option A du critic) : à chaque application, la commande
**résout** sa cible au lieu de supposer que l'objet mémorisé est encore vivant.

- `match.py` (pur : ni PySide6 ni shiboken6, importable hors `--gui`) : sélection d'un candidat par
  ancre (page, position, rotation à la dernière application réussie) ou position de bloc,
  tolérances amont (±5 px / ±1°), vérification du texte attendu, refus en cas d'égalité, liste
  blanche de format (`FORMAT_KEYS`) pour `TextFormatCommand`.
- `resolve.py` (duck typing sur `main`, importe `shiboken6`) : `resolve_text_target`,
  `apply_text_edit`, `resolve_format_target`, écriture « bloc seul » (chemin D2).

Ce fichier reste sans import : ne jamais y importer `resolve` (PySide6/shiboken6)."""
