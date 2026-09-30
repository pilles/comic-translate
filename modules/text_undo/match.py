"""Sélection pure du candidat visé par une annulation de texte (spec 04, jalon 3, 3a-ter, ADR-022).

Aucun import de PySide6 ni de shiboken6 : les items et les blocs sont manipulés par duck typing
(`pos()`, `rotation()`, `toPlainText()` ; `xyxy`, `angle`, champ de texte) et la validité d'un item
Qt (`shiboken6.isValid`) est **injectée** par l'appelant (`is_valid`) — c'est ce qui rend ce module
testable hors `--gui` avec de faux items.

Règles de sélection (critic M2) :
1. un candidat `None` ou invalide (`is_valid` faux ou qui lève) est ignoré ;
2. une sonde (`pos()`, `rotation()`, `toPlainText()`) qui lève est ignorée (item détruit entre-temps) ;
3. position et rotation doivent rester dans les tolérances amont de `_find_text_block_for_item`
   (±5 px, ±1°) par rapport à la référence ;
4. le texte affiché doit être **exactement** le texte attendu, même avec un seul candidat
   (jamais écraser un contenu changé entre-temps) ;
5. si le bloc est connu, l'item doit lui être apparié (contrôle croisé item/bloc) ;
6. plus proche d'abord ; **égalité de distance -> refus** (aucun item), jamais un choix qui dépend
   de l'ordre instable de `viewer.text_items`."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Sequence

logger = logging.getLogger(__name__)

POSITION_TOLERANCE_PX = 5
ROTATION_TOLERANCE_DEG = 1
_TIE_EPSILON = 1e-6

# Liste blanche des attributs de format recopiés sur un item **substitué** par
# `TextFormatCommand` (critic, sous-étape 3a-ter). Vérifiée contre les setters de
# `app/ui/canvas/text_item.py` : `set_font`/`set_font_size` (font_family, font_size),
# `set_alignment` (alignment), `set_line_spacing` (line_spacing), `set_color` (text_color),
# `set_outline` (outline, outline_color, outline_width, selection_outlines), `set_bold`/
# `set_italic`/`set_underline`, `set_direction` (direction) — et `TextItemProperties` (mêmes
# champs). Volontairement absents : `layout`, `vertical` (propres au document de l'item),
# `_ct_text_changed_slot`/`_ct_signals_connected` (câblage des signaux de l'item d'origine),
# `selected`, `editing_mode`, `resizing`… (état d'interaction).
FORMAT_KEYS: tuple[str, ...] = (
    "font_family",
    "font_size",
    "text_color",
    "alignment",
    "line_spacing",
    "outline",
    "outline_color",
    "outline_width",
    "bold",
    "italic",
    "underline",
    "direction",
    "selection_outlines",
)

# Raisons de refus (journal et tests).
REASON_OK = "ok"
REASON_NO_CANDIDATE = "aucun candidat"
REASON_AMBIGUOUS = "égalité de distance"
REASON_NO_REFERENCE = "aucune référence de position"
REASON_OTHER_PAGE = "page d'ancre différente"

Reference = tuple[float, float, float]  # (x, y, rotation)


@dataclass(frozen=True)
class Anchor:
    """Position de l'objet visé à la dernière application réussie. `page` vaut `None` quand la
    page n'est pas connue (`TextFormatCommand` n'a pas accès à `main`) : aucun contrôle de page.
    `text` (texte brut de l'item) sert de texte attendu pour `TextFormatCommand`, qui ne connaît
    pas le texte de l'item."""

    page: str | None
    x: float
    y: float
    rotation: float
    text: str | None = None

    @property
    def reference(self) -> Reference:
        return (self.x, self.y, self.rotation)


@dataclass(frozen=True)
class Pick:
    item: Any | None
    reason: str

    @property
    def ok(self) -> bool:
        return self.item is not None


def same_page(anchor_page: str | None, current_page: str | None) -> bool:
    """Vrai si l'une des deux pages est inconnue (`None`) ou si elles sont égales."""
    if anchor_page is None or current_page is None:
        return True
    return anchor_page == current_page


def contains_by_identity(items: Iterable[Any], obj: Any) -> bool:
    return obj is not None and any(candidate is obj for candidate in items)


def _within(x: float, y: float, rotation: float, ref: Reference) -> bool:
    return (
        abs(x - ref[0]) <= POSITION_TOLERANCE_PX
        and abs(y - ref[1]) <= POSITION_TOLERANCE_PX
        and abs(rotation - ref[2]) <= ROTATION_TOLERANCE_DEG
    )


def _key(x: float, y: float, rotation: float, ref: Reference) -> tuple[float, float]:
    return (
        round(math.hypot(x - ref[0], y - ref[1]) / _TIE_EPSILON) * _TIE_EPSILON,
        round(abs(rotation - ref[2]) / _TIE_EPSILON) * _TIE_EPSILON,
    )


def _safe_valid(obj: Any, is_valid: Callable[[Any], bool]) -> bool:
    if obj is None:
        return False
    try:
        return bool(is_valid(obj))
    except Exception:  # noqa: BLE001 - une sonde de validité qui lève = objet inutilisable
        logger.debug("modules.text_undo.match: sonde de validité en échec.", exc_info=True)
        return False


def _pick_min(scored: list[tuple[tuple[float, float], Any]]) -> Pick:
    if not scored:
        return Pick(None, REASON_NO_CANDIDATE)
    best = min(key for key, _ in scored)
    winners = [obj for key, obj in scored if key == best]
    if len(winners) > 1:
        return Pick(None, REASON_AMBIGUOUS)
    return Pick(winners[0], REASON_OK)


def pick_item(
    candidates: Iterable[Any],
    *,
    reference: Reference | None,
    expected_text: str | None,
    is_valid: Callable[[Any], bool],
    blk: Any | None = None,
    block_of: Callable[[Any], Any] | None = None,
) -> Pick:
    """Choisit l'item de texte visé (règles de la docstring du module). `expected_text=None`
    désactive la vérification du texte (ancre sans texte connu). `blk`/`block_of` : contrôle
    croisé, actif seulement si les deux sont fournis (`block_of(item) is blk`)."""
    if reference is None:
        return Pick(None, REASON_NO_REFERENCE)

    scored: list[tuple[tuple[float, float], Any]] = []
    for candidate in candidates:
        if not _safe_valid(candidate, is_valid):
            continue
        try:
            pos = candidate.pos()
            x, y, rotation = float(pos.x()), float(pos.y()), float(candidate.rotation())
            text = candidate.toPlainText() if expected_text is not None else None
        except Exception:  # noqa: BLE001 - item détruit entre le filtre et la sonde
            logger.debug("modules.text_undo.match: sonde d'item en échec.", exc_info=True)
            continue
        if not _within(x, y, rotation, reference):
            continue
        if expected_text is not None and text != expected_text:
            continue
        if blk is not None and block_of is not None:
            try:
                matched = block_of(candidate)
            except Exception:  # noqa: BLE001 - même raison que ci-dessus
                logger.debug(
                    "modules.text_undo.match: appariement item/bloc en échec.", exc_info=True
                )
                continue
            if matched is not blk:
                continue
        scored.append((_key(x, y, rotation, reference), candidate))
    return _pick_min(scored)


def pick_block(
    blocks: Sequence[Any],
    *,
    reference: Reference | None,
    field: str,
    expected: str,
) -> Pick:
    """Choisit, parmi les blocs **vivants** de la page affichée, celui dont la position est dans
    les tolérances de `reference` et dont `field` vaut exactement `expected`. Même refus sur
    égalité que `pick_item`. Le résultat est dans `Pick.item` (un bloc)."""
    if reference is None:
        return Pick(None, REASON_NO_REFERENCE)

    scored: list[tuple[tuple[float, float], Any]] = []
    for blk in blocks:
        if blk is None:
            continue
        try:
            x, y = float(blk.xyxy[0]), float(blk.xyxy[1])
            rotation = float(blk.angle)
            value = getattr(blk, field, None)
        except Exception:  # noqa: BLE001 - bloc incomplet : ignoré, jamais bloquant
            logger.debug("modules.text_undo.match: sonde de bloc en échec.", exc_info=True)
            continue
        if not _within(x, y, rotation, reference) or value != expected:
            continue
        scored.append((_key(x, y, rotation, reference), blk))
    return _pick_min(scored)


def reduce_to_format(state: dict[str, Any]) -> dict[str, Any]:
    """Réduit un `__dict__` d'item à la liste blanche `FORMAT_KEYS` (une seule fois, à la
    substitution d'item de `TextFormatCommand`). `selection_outlines` est copiée (liste)."""
    reduced: dict[str, Any] = {}
    for key in FORMAT_KEYS:
        if key not in state:
            continue
        value = state[key]
        reduced[key] = list(value) if key == "selection_outlines" else value
    return reduced
