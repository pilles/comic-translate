"""Panneau de droite (spec 04, jalon 2, sous-étape 2c). Construit la pile Page/Bulle
(`QStackedWidget`) du haut du panneau, plus les groupes « Rendu du texte » et « Outils » en bas,
communs aux deux contextes (les réglages de rendu ont un double usage : sans sélection, ils
règlent le prochain « Rendre », `app/controllers/text.py:~925-1003`) — sans toucher un seul widget
amont : ce module ne fait que fabriquer des conteneurs, des layouts vides et des libellés neufs.
Le remplissage (widgets amont réels) est fait par `modules/shell/layout.py`, qui reçoit le
squelette renvoyé par `build_panel_skeleton` et y insère les widgets déplacés. La bascule entre les
deux pages de la pile est pilotée par `modules/shell/watcher.py`, jamais par ce module (qui ne
construit qu'un état initial : la page « Page », index 0, affichée en premier).

Importe PySide6 — n'importer ce module que depuis `modules/shell/layout.py`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore, QtWidgets

from app.ui.dayu_widgets.divider import MDivider
from app.ui.dayu_widgets.label import MLabel

_SOURCE_LANG_LABEL = "Langue source"
_TARGET_LANG_LABEL = "Langue cible"
_HINT_LABEL = "Sélectionnez une bulle pour voir son texte"
_RENDER_GROUP_LABEL = "Rendu du texte"
_TOOLS_GROUP_LABEL = "Outils"

_RIGHT_PANEL_MIN_WIDTH = 280
_TOP_STACK_STRETCH = 1

# Espacements resserrés (correctif hauteur des champs texte, retour tester 2a) : le panneau est
# étroit (280 px) et dense — mêmes ordres de grandeur que `app/ui/search_replace_panel.py`
# (colonne voisine dans le même splitter gauche), qui utilise déjà marges/espacements 0-6 px.
_PANEL_MARGIN = 6
_PANEL_SPACING = 4
_PANE_SPACING = 4
_ROW_SPACING = 6


@dataclass
class PanelSkeleton:
    """Squelette vide du panneau de droite : conteneur prêt à afficher, et les layouts où
    `modules/shell/layout.py` doit encore insérer les widgets amont (dans cet ordre, pour chacun).

    `stack`/`page_index`/`bubble_index` : pile Page/Bulle du haut du panneau, basculée par
    `modules/shell/watcher.py` — jamais par ce module ni par `layout.py`."""

    container: QtWidgets.QWidget

    stack: QtWidgets.QStackedWidget
    page_index: int
    bubble_index: int

    # Page (rien de sélectionné).
    page_source_lang_row: (
        QtWidgets.QHBoxLayout
    )  # reçoit : label « Langue source » (déjà posé), s_combo (stretch)
    page_target_lang_row: (
        QtWidgets.QHBoxLayout
    )  # reçoit : label « Langue cible » (déjà posé), t_combo (stretch)
    page_actions_row: QtWidgets.QHBoxLayout  # reçoit : set_all_button, puis un stretch

    # Bulle (une bulle sélectionnée). Libellés dynamiques (`bubble_source_caption`/
    # `bubble_target_caption`) : texte initial neutre, réécrit par `modules/shell/watcher.py` à
    # chaque évaluation du contexte (pas de signal fiable sur `s_combo`/`t_combo`, voir
    # `modules/shell/context.py`).
    bubble_source_caption: QtWidgets.QLabel
    bubble_source_layout: QtWidgets.QVBoxLayout  # reçoit : s_text_edit (stretch) — libellé posé
    bubble_target_caption: QtWidgets.QLabel
    bubble_target_layout: QtWidgets.QVBoxLayout  # reçoit : t_text_edit (stretch) — libellé posé
    bubble_actions_row: QtWidgets.QHBoxLayout  # reçoit : block_history_button, puis un stretch

    # Groupe « Rendu du texte ». Le nom de police est seul sur sa rangée (correctif troncature,
    # retour tester 2a : partagée avec les deux menus de taille fixe (60 px chacun), elle n'avait
    # plus assez de largeur dans les 280 px du panneau pour afficher un nom de police complet).
    font_name_row_layout: QtWidgets.QHBoxLayout  # font_dropdown seul, pleine largeur
    font_size_row_layout: QtWidgets.QHBoxLayout  # font_size_dropdown, line_spacing_dropdown
    style_row_layout: (
        QtWidgets.QHBoxLayout
    )  # block_font_color_button, alignment_tool_group, bold/italic/underline
    outline_row_layout: (
        QtWidgets.QHBoxLayout
    )  # outline_checkbox, outline_font_color_button, outline_width_dropdown

    # Groupe « Outils » : rangée 1 = pan | boîte ; rangée 2 = taille | pinceau ; rangée 3 = curseur.
    tools_row1_pan_layout: QtWidgets.QHBoxLayout  # pan_button
    tools_row1_box_layout: (
        QtWidgets.QHBoxLayout
    )  # box_button, delete_button, clear_rectangles_button, draw_blklist_blks
    tools_row2_size_layout: QtWidgets.QHBoxLayout  # change_all_blocks_size_{dec,diff,inc}
    tools_row2_brush_layout: (
        QtWidgets.QHBoxLayout
    )  # brush_button, eraser_button, clear_brush_strokes_button
    tools_row3_layout: QtWidgets.QHBoxLayout  # brush_eraser_slider


def _label_row(label_text: str) -> QtWidgets.QHBoxLayout:
    """Rangée fixe : un libellé statique, puis le widget amont (ajouté plus tard par
    `layout.py`, stretch=1)."""
    row = QtWidgets.QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(_ROW_SPACING)
    row.addWidget(QtWidgets.QLabel(label_text))
    return row


def _caption_pane(
    initial_caption: str,
) -> tuple[QtWidgets.QWidget, QtWidgets.QLabel, QtWidgets.QVBoxLayout]:
    """Volet du `QSplitter` Bulle : un libellé dynamique, puis le champ texte (ajouté plus tard
    par `layout.py`, stretch=1) qui absorbe le reste du volet."""
    pane = QtWidgets.QWidget()
    pane_layout = QtWidgets.QVBoxLayout(pane)
    pane_layout.setContentsMargins(0, 0, 0, 0)
    pane_layout.setSpacing(_PANE_SPACING)

    caption = QtWidgets.QLabel(initial_caption)
    pane_layout.addWidget(caption)

    return pane, caption, pane_layout


def build_panel_skeleton(main: Any) -> PanelSkeleton:
    """Construit le squelette à vide. N'accède à aucun widget amont : `main` ne sert qu'à
    traduire les libellés (`main.tr`)."""
    container = QtWidgets.QWidget()
    container.setMinimumWidth(_RIGHT_PANEL_MIN_WIDTH)
    panel_layout = QtWidgets.QVBoxLayout(container)
    panel_layout.setContentsMargins(_PANEL_MARGIN, _PANEL_MARGIN, _PANEL_MARGIN, _PANEL_MARGIN)
    panel_layout.setSpacing(_PANEL_SPACING)

    stack = QtWidgets.QStackedWidget()

    # --- Page (rien de sélectionné) ---------------------------------------------------------
    page_widget = QtWidgets.QWidget()
    page_layout = QtWidgets.QVBoxLayout(page_widget)
    page_layout.setContentsMargins(0, 0, 0, 0)
    page_layout.setSpacing(_PANE_SPACING)

    page_source_lang_row = _label_row(main.tr(_SOURCE_LANG_LABEL))
    page_target_lang_row = _label_row(main.tr(_TARGET_LANG_LABEL))
    page_actions_row = QtWidgets.QHBoxLayout()

    hint_label = MLabel(main.tr(_HINT_LABEL)).secondary()
    hint_label.setWordWrap(True)

    page_layout.addLayout(page_source_lang_row)
    page_layout.addLayout(page_target_lang_row)
    page_layout.addLayout(page_actions_row)
    page_layout.addWidget(hint_label)
    page_layout.addStretch(1)

    # --- Bulle (une bulle sélectionnée) ------------------------------------------------------
    bubble_widget = QtWidgets.QWidget()
    bubble_layout = QtWidgets.QVBoxLayout(bubble_widget)
    bubble_layout.setContentsMargins(0, 0, 0, 0)
    bubble_layout.setSpacing(_PANE_SPACING)

    bubble_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
    source_pane, bubble_source_caption, bubble_source_layout = _caption_pane("")
    target_pane, bubble_target_caption, bubble_target_layout = _caption_pane("")
    bubble_splitter.addWidget(source_pane)
    bubble_splitter.addWidget(target_pane)
    bubble_splitter.setStretchFactor(0, 1)
    bubble_splitter.setStretchFactor(1, 1)

    bubble_actions_row = QtWidgets.QHBoxLayout()

    bubble_layout.addWidget(bubble_splitter, 1)
    bubble_layout.addLayout(bubble_actions_row)

    stack.addWidget(page_widget)
    stack.addWidget(bubble_widget)
    page_index = stack.indexOf(page_widget)
    bubble_index = stack.indexOf(bubble_widget)

    # --- Rendu du texte / Outils (communs aux deux contextes, sous la pile) -------------------
    font_name_row_layout = QtWidgets.QHBoxLayout()
    font_size_row_layout = QtWidgets.QHBoxLayout()
    style_row_layout = QtWidgets.QHBoxLayout()
    outline_row_layout = QtWidgets.QHBoxLayout()

    tools_row1_layout = QtWidgets.QHBoxLayout()
    tools_row1_pan_layout = QtWidgets.QHBoxLayout()
    tools_row1_box_layout = QtWidgets.QHBoxLayout()
    tools_row1_layout.addLayout(tools_row1_pan_layout)
    tools_row1_layout.addWidget(MDivider(orientation=QtCore.Qt.Orientation.Vertical))
    tools_row1_layout.addLayout(tools_row1_box_layout)

    tools_row2_layout = QtWidgets.QHBoxLayout()
    tools_row2_size_layout = QtWidgets.QHBoxLayout()
    tools_row2_brush_layout = QtWidgets.QHBoxLayout()
    tools_row2_layout.addLayout(tools_row2_size_layout)
    tools_row2_layout.addWidget(MDivider(orientation=QtCore.Qt.Orientation.Vertical))
    tools_row2_layout.addLayout(tools_row2_brush_layout)

    tools_row3_layout = QtWidgets.QHBoxLayout()

    panel_layout.addWidget(stack, _TOP_STACK_STRETCH)
    panel_layout.addWidget(MDivider(main.tr(_RENDER_GROUP_LABEL)))
    panel_layout.addLayout(font_name_row_layout)
    panel_layout.addLayout(font_size_row_layout)
    panel_layout.addLayout(style_row_layout)
    panel_layout.addLayout(outline_row_layout)
    panel_layout.addWidget(MDivider(main.tr(_TOOLS_GROUP_LABEL)))
    panel_layout.addLayout(tools_row1_layout)
    panel_layout.addLayout(tools_row2_layout)
    panel_layout.addLayout(tools_row3_layout)

    return PanelSkeleton(
        container=container,
        stack=stack,
        page_index=page_index,
        bubble_index=bubble_index,
        page_source_lang_row=page_source_lang_row,
        page_target_lang_row=page_target_lang_row,
        page_actions_row=page_actions_row,
        bubble_source_caption=bubble_source_caption,
        bubble_source_layout=bubble_source_layout,
        bubble_target_caption=bubble_target_caption,
        bubble_target_layout=bubble_target_layout,
        bubble_actions_row=bubble_actions_row,
        font_name_row_layout=font_name_row_layout,
        font_size_row_layout=font_size_row_layout,
        style_row_layout=style_row_layout,
        outline_row_layout=outline_row_layout,
        tools_row1_pan_layout=tools_row1_pan_layout,
        tools_row1_box_layout=tools_row1_box_layout,
        tools_row2_size_layout=tools_row2_size_layout,
        tools_row2_brush_layout=tools_row2_brush_layout,
        tools_row3_layout=tools_row3_layout,
    )
