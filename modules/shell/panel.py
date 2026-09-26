"""Panneau de droite (spec 04, jalon 2, sous-étape 2a). Construit la disposition provisoire —
section unique Page+Bulle, groupe « Rendu du texte », groupe « Outils » — sans toucher un seul
widget amont : ce module ne fait que fabriquer des conteneurs, des layouts vides et des libellés
neufs. Le remplissage (widgets amont réels) est fait par `modules/shell/layout.py`, qui reçoit le
squelette renvoyé par `build_panel_skeleton` et y insère les widgets déplacés.

Importe PySide6 — n'importer ce module que depuis `modules/shell/layout.py`.

Préparation de la sous-étape 2c (pile Page/Bulle) : `PanelSkeleton.source_layout`/`target_layout`
accueillent aujourd'hui à la fois les widgets « Page » (`s_combo`/`t_combo`) et « Bulle »
(`s_text_edit`/`t_text_edit`) dans une seule section visible en permanence. En 2c, cette section
unique deviendra une pile (`QStackedWidget`) avec une vue Page et une vue Bulle distinctes ; les
noms de champs ci-dessous sont déjà séparés en conséquence pour que ce jalon n'ait pas à réécrire
`layout.py`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore, QtWidgets

from app.ui.dayu_widgets.divider import MDivider

_SOURCE_LABEL = "Source"
_TARGET_LABEL = "Traduction"
_RENDER_GROUP_LABEL = "Rendu du texte"
_TOOLS_GROUP_LABEL = "Outils"

_RIGHT_PANEL_MIN_WIDTH = 280
_TOP_SPLITTER_STRETCH = 1

# Espacements resserrés (correctif hauteur des champs texte, retour tester) : le panneau est
# étroit (280 px) et dense — mêmes ordres de grandeur que `app/ui/search_replace_panel.py`
# (colonne voisine dans le même splitter gauche), qui utilise déjà marges/espacements 0-6 px.
_PANEL_MARGIN = 6
_PANEL_SPACING = 4
_PANE_SPACING = 4
_COMBO_ROW_SPACING = 6


@dataclass
class PanelSkeleton:
    """Squelette vide du panneau de droite : conteneur prêt à afficher, et les layouts où
    `modules/shell/layout.py` doit encore insérer les widgets amont (dans cet ordre, pour chacun)."""

    container: QtWidgets.QWidget

    # Section Page/Bulle provisoire (2a : une seule section, voir docstring de module). Le
    # libellé et la liste de langue partagent une rangée (correctif hauteur des champs texte,
    # retour tester du 2026-09-26) : seule cette rangée a une hauteur fixe, le champ texte
    # absorbe tout le reste de l'espace de son volet du `QSplitter` vertical.
    source_combo_row: (
        QtWidgets.QHBoxLayout
    )  # reçoit : label « Source » (déjà posé), s_combo (stretch)
    source_layout: (
        QtWidgets.QVBoxLayout
    )  # reçoit : s_text_edit (stretch) — la rangée ci-dessus est déjà posée (item 0)
    target_combo_row: (
        QtWidgets.QHBoxLayout
    )  # reçoit : label « Traduction » (déjà posé), t_combo (stretch)
    target_layout: (
        QtWidgets.QVBoxLayout
    )  # reçoit : t_text_edit (stretch) — la rangée ci-dessus est déjà posée (item 0)
    actions_layout: (
        QtWidgets.QHBoxLayout
    )  # reçoit : block_history_button, set_all_button, puis un stretch

    # Groupe « Rendu du texte ». Le nom de police est seul sur sa rangée (correctif troncature,
    # retour tester : partagée avec les deux menus de taille fixe (60 px chacun), elle n'avait
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


def _combo_row_pane(
    label_text: str,
) -> tuple[QtWidgets.QWidget, QtWidgets.QHBoxLayout, QtWidgets.QVBoxLayout]:
    """Volet de `top_splitter` : une rangée fixe (libellé + emplacement du menu de langue), puis
    le champ texte (ajouté plus tard par `layout.py`, stretch=1) qui absorbe le reste du volet."""
    pane = QtWidgets.QWidget()
    pane_layout = QtWidgets.QVBoxLayout(pane)
    pane_layout.setContentsMargins(0, 0, 0, 0)
    pane_layout.setSpacing(_PANE_SPACING)

    combo_row = QtWidgets.QHBoxLayout()
    combo_row.setContentsMargins(0, 0, 0, 0)
    combo_row.setSpacing(_COMBO_ROW_SPACING)
    combo_row.addWidget(QtWidgets.QLabel(label_text))
    pane_layout.addLayout(combo_row)

    return pane, combo_row, pane_layout


def build_panel_skeleton(main: Any) -> PanelSkeleton:
    """Construit le squelette à vide. N'accède à aucun widget amont : `main` ne sert qu'à
    traduire les libellés (`main.tr`)."""
    container = QtWidgets.QWidget()
    container.setMinimumWidth(_RIGHT_PANEL_MIN_WIDTH)
    panel_layout = QtWidgets.QVBoxLayout(container)
    panel_layout.setContentsMargins(_PANEL_MARGIN, _PANEL_MARGIN, _PANEL_MARGIN, _PANEL_MARGIN)
    panel_layout.setSpacing(_PANEL_SPACING)

    top_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)

    source_pane, source_combo_row, source_layout = _combo_row_pane(main.tr(_SOURCE_LABEL))
    target_pane, target_combo_row, target_layout = _combo_row_pane(main.tr(_TARGET_LABEL))

    top_splitter.addWidget(source_pane)
    top_splitter.addWidget(target_pane)
    top_splitter.setStretchFactor(0, 1)
    top_splitter.setStretchFactor(1, 1)

    actions_layout = QtWidgets.QHBoxLayout()

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

    panel_layout.addWidget(top_splitter, _TOP_SPLITTER_STRETCH)
    panel_layout.addLayout(actions_layout)
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
        source_combo_row=source_combo_row,
        source_layout=source_layout,
        target_combo_row=target_combo_row,
        target_layout=target_layout,
        actions_layout=actions_layout,
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
