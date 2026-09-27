"""Manifeste des widgets amont pris en charge par le shell (spec 04, jalon 2, sous-étape 2a).

Seul fichier de `modules/shell` à revoir systématiquement à chaque rebase sur
`filvyb`/`upstream` : si `app/ui/main_window/builders/workspace.py` renomme, ajoute ou retire un
widget, ce fichier (et lui seul) doit suivre. Pur — aucun import PySide6 — les tuples ne
contiennent que des noms d'attributs de `main` (`ComicTranslateUI`/`ComicTranslate`), vérifiés
dynamiquement à l'exécution par `modules/shell/layout.py` (existence, type `QWidget`, vivant,
descendant du contenu amont).

Chaque nom apparaît dans exactement une zone (`tests/test_shell.py` le vérifie). Zones :

- HEADER / PROGRESS : bandeau supérieur pleine largeur, identique à l'amont.
- LEFT / CENTER / OVERLAY : les trois colonnes du `QSplitter` central (le badge Original est
  hors flux, positionné par-dessus le centre).
- PAGE / BUBBLE : les deux pages de la pile Page/Bulle du panneau de droite
  (`QStackedWidget`, `modules/shell/panel.py`), basculée par `modules/shell/watcher.py` selon
  `modules/shell/context.panel_context` (spec 04, jalon 2, sous-étape 2c).
- RENDER / TOOLS : les deux groupes du bas du panneau de droite.
- PARKED : rangé hors du flux visible, masqué explicitement (`setVisible(False)`, y compris en
  repli) — `manual_radio`/`automatic_radio`/`webtoon_toggle` (spec 04, jalon 2, sous-étape 2b :
  plus de mode Manuel/Automatique, plus de webtoon dans la nouvelle interface). Jamais déplacés
  (retirés de `HEADER`), jamais détruits : lus par `app/controllers/projects.py`,
  `controller.py`, `modules/view/original.py`, `app/controllers/webtoons.py`.
- EXTERNAL : jamais déplacé par le shell — `window.py` reparente lui-même ce widget dans la barre
  de titre, immédiatement après l'appel à `build_workspace_shell`."""

from __future__ import annotations

HEADER: tuple[str, ...] = (
    "hbutton_group",
    "loading",
    "translate_button",
    "cancel_button",
    "batch_report_button",
)

PROGRESS: tuple[str, ...] = ("progress_bar",)

LEFT: tuple[str, ...] = ("page_list", "search_panel")

CENTER: tuple[str, ...] = ("central_stack",)

OVERLAY: tuple[str, ...] = ("original_view_button",)

PAGE: tuple[str, ...] = ("s_combo", "t_combo", "set_all_button")

BUBBLE: tuple[str, ...] = ("s_text_edit", "t_text_edit", "block_history_button")

RENDER: tuple[str, ...] = (
    "font_dropdown",
    "font_size_dropdown",
    "line_spacing_dropdown",
    "block_font_color_button",
    "alignment_tool_group",
    "bold_button",
    "italic_button",
    "underline_button",
    "outline_checkbox",
    "outline_font_color_button",
    "outline_width_dropdown",
)

TOOLS: tuple[str, ...] = (
    "pan_button",
    "box_button",
    "delete_button",
    "clear_rectangles_button",
    "draw_blklist_blks",
    "change_all_blocks_size_dec",
    "change_all_blocks_size_diff",
    "change_all_blocks_size_inc",
    "brush_button",
    "eraser_button",
    "clear_brush_strokes_button",
    "brush_eraser_slider",
)

PARKED: tuple[str, ...] = ("manual_radio", "automatic_radio", "webtoon_toggle")

EXTERNAL: tuple[str, ...] = ("undo_tool_group",)

# Zones déplacées par le shell (validées, journalisées, reparentées) — tout sauf PARKED (jamais
# déplacé, masqué sur place) et EXTERNAL (jamais touché par le shell).
MOVED_ZONES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("HEADER", HEADER),
    ("PROGRESS", PROGRESS),
    ("LEFT", LEFT),
    ("CENTER", CENTER),
    ("OVERLAY", OVERLAY),
    ("PAGE", PAGE),
    ("BUBBLE", BUBBLE),
    ("RENDER", RENDER),
    ("TOOLS", TOOLS),
)

# Toutes les zones, y compris celles que le shell ne déplace jamais — pour les vérifications
# d'absence de doublon / disjonction (`tests/test_shell.py`).
ALL_ZONES: tuple[tuple[str, tuple[str, ...]], ...] = MOVED_ZONES + (
    ("PARKED", PARKED),
    ("EXTERNAL", EXTERNAL),
)
