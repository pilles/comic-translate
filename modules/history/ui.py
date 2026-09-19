"""Bouton « Historique du bloc » (spec 03, jalon A). Importe PySide6 —
n'importer ce module que depuis
`app/ui/main_window/builders/workspace.py`, jamais depuis
`modules/history/__init__.py` (qui reste pur, voir ADR-012)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6 import QtWidgets

from modules.history import commands, versions

if TYPE_CHECKING:
    from controller import ComicTranslate

_BUTTON_SVG = "detail_line.svg"
_BUTTON_TOOLTIP = "Historique du bloc"
_EMPTY_SELECTION_LABEL = "Aucun bloc sélectionné"
_NO_HISTORY_LABEL = "Aucun historique pour ce bloc"
_EMPTY_VALUE_PREVIEW = "(vide)"
_PREVIEW_MAX_CHARS = 40

_ORIGIN_LABELS = {
    versions.ORIGIN_OCR: "OCR",
    versions.ORIGIN_CACHE_OCR: "OCR (cache)",
    versions.ORIGIN_TRANSLATION: "Traduction",
    versions.ORIGIN_CACHE: "Traduction (cache)",
    versions.ORIGIN_MANUAL: "Édition manuelle",
    versions.ORIGIN_PRIOR: "Valeur d'origine",
    versions.ORIGIN_SEARCH_REPLACE: "Rechercher/Remplacer",
    versions.ORIGIN_RESTORE: "Restauration",
}


def attach_block_history_button(
    main: "ComicTranslate", layout: QtWidgets.QLayout
) -> QtWidgets.QToolButton:
    """Ajoute le bouton d'historique à `layout` (t_combo_text_layout, voir
    `workspace.py`). Toujours actif : la désactivation « pas de bloc » se
    traduit par un menu grisé, pas par un bouton désactivé (M7)."""
    button = main.create_tool_button(svg=_BUTTON_SVG)
    button.setToolTip(main.tr(_BUTTON_TOOLTIP))
    button.clicked.connect(lambda: _show_history_menu(main, button))
    layout.addWidget(button)
    return button


def _format_preview(value: str) -> str:
    if not value:
        return _EMPTY_VALUE_PREVIEW
    normalized = " ".join(value.split())
    if len(normalized) > _PREVIEW_MAX_CHARS:
        normalized = normalized[:_PREVIEW_MAX_CHARS].rstrip() + "…"
    # Échapper le mnémonique Qt : un seul '&' déclencherait un raccourci.
    return normalized.replace("&", "&&")


def _format_entry_label(entry: "versions.HistoryEntry") -> str:
    try:
        hh_mm = datetime.fromisoformat(entry["at"]).strftime("%H:%M")
    except ValueError:
        hh_mm = "--:--"
    origin_label = _ORIGIN_LABELS.get(entry["origin"], entry["origin"])
    meta = entry.get("meta") or {}
    meta_value = meta.get("model") or meta.get("ocr") or ""
    preview = _format_preview(entry["value"])
    if meta_value:
        return f"{hh_mm} · {origin_label} ({meta_value}) · « {preview} »"
    return f"{hh_mm} · {origin_label} · « {preview} »"


def _add_field_actions(
    menu: QtWidgets.QMenu,
    main: "ComicTranslate",
    blk,
    entries: list["versions.HistoryEntry"],
    heads: dict[str, "versions.HistoryEntry"],
) -> None:
    for entry in reversed(entries):  # plus récent en haut
        action = menu.addAction(_format_entry_label(entry))
        if heads.get(entry["field"]) is entry:
            action.setCheckable(True)
            action.setChecked(True)
            action.setEnabled(False)
            continue
        action.triggered.connect(lambda checked=False, e=entry: _restore(main, blk, e))


def _restore(main: "ComicTranslate", blk, entry: "versions.HistoryEntry") -> None:
    command = commands.RestoreVersionCommand(main, blk, entry)
    main.push_command(command)
    main.mark_project_dirty()


def build_history_menu(main: "ComicTranslate", parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
    """Construit le `QMenu` d'historique, sans l'exécuter (`.exec`) — séparé
    de `_show_history_menu` pour rester testable sans boucle d'événements
    modale (`QMenu.exec` ne respecte pas toujours le monkeypatch Python côté
    Shiboken/Qt ; le séparer évite tout risque de blocage en test)."""
    menu = QtWidgets.QMenu(parent)

    blk = getattr(main, "curr_tblock", None)
    if blk is None:
        action = menu.addAction(main.tr(_EMPTY_SELECTION_LABEL))
        action.setEnabled(False)
        return menu

    entries = list(versions.versions_of(blk))
    if not entries:
        # Bloc sélectionné mais jamais journalisé (ex : projet antérieur au
        # jalon A, rechargé sans `versions`) — menu grisé, pas de menu vide.
        action = menu.addAction(main.tr(_NO_HISTORY_LABEL))
        action.setEnabled(False)
        return menu

    heads: dict[str, versions.HistoryEntry] = {}
    for entry in entries:
        heads[entry["field"]] = entry  # dernière écriture -> tête du champ

    translation_entries = [e for e in entries if e["field"] == versions.FIELD_TRANSLATION]
    text_entries = [e for e in entries if e["field"] == versions.FIELD_TEXT]

    _add_field_actions(menu, main, blk, translation_entries, heads)
    if translation_entries and text_entries:
        menu.addSeparator()
    _add_field_actions(menu, main, blk, text_entries, heads)

    return menu


def _show_history_menu(main: "ComicTranslate", button: QtWidgets.QToolButton) -> None:
    menu = build_history_menu(main, button)
    menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
