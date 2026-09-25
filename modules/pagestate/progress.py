"""Calcul pur de l'avancement d'une page (spec 04, jalon 1).

Aucune dépendance à PySide6 ici : ce module doit rester importable depuis un
thread worker et depuis les tests sans `--gui` (même contrainte que
`modules/history/versions.py`, voir ADR-012). Cinq étapes, deux statuts par
étape (FAITE si son compteur est strictement positif, sinon ABSENTE) :
`detect` (nombre de blocs), `ocr` (blocs dont `text` est non vide après
`.strip()`), `translate` (idem sur `translation`), `clean` (nombre de zones
nettoyées, fourni par l'appelant), `render` (nombre d'items de texte rendus,
fourni par l'appelant — voir `modules/pagestate/collect.py` pour la source de
chaque compte).

Robustesse (consigne critic m7, conception validée) : une donnée pourrie
(bloc sans attribut `text`, valeur `None`, valeur non-chaîne) ne fait tomber
que le compte concerné, jamais toute la ligne — chaque lecture de champ est
défensive et journalise au plus une fois par champ (`_warn_once`, précédent :
`modules/history/versions.py::_warn_max_value_chars_once`)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

STEPS = ("detect", "ocr", "translate", "clean", "render")

# Champs lus sur chaque bloc — mêmes noms que `modules.history` (attributs
# réels de `modules.utils.textblock.TextBlock`), constante locale pour ne pas
# coupler ce paquet pur à `modules.history`.
_FIELD_TEXT = "text"
_FIELD_TRANSLATION = "translation"

_STEP_TO_ATTR = {
    "detect": "n_blocks",
    "ocr": "n_text",
    "translate": "n_translated",
    "clean": "n_patches",
    "render": "n_rendered",
}

_warned_fields: set[str] = set()


def _warn_field_once(field: str) -> None:
    if field in _warned_fields:
        return
    _warned_fields.add(field)
    logger.warning(
        "modules.pagestate: champ %r illisible sur au moins un bloc, compte dégradé pour ce bloc.",
        field,
    )


@dataclass(frozen=True)
class PageProgress:
    """Avancement figé d'une page. Un compteur à 0 signifie « étape absente »."""

    n_blocks: int
    n_text: int
    n_translated: int
    n_patches: int
    n_rendered: int

    def done(self, step: str) -> bool:
        """`True` si `step` (un élément de `STEPS`) est FAITE."""
        attr = _STEP_TO_ATTR.get(step)
        if attr is None:
            raise ValueError(f"modules.pagestate: étape inconnue {step!r}, attendu un de {STEPS}")
        return getattr(self, attr) > 0


def _text_field(blk: object, field: str) -> str:
    """Lecture défensive de `blk.<field>` : chaîne vide si l'attribut est
    absent, `None`, non-chaîne, ou si l'accès lève — jamais d'exception hors
    de cette fonction."""
    try:
        value = getattr(blk, field, "")
    except Exception:
        _warn_field_once(field)
        return ""
    if value is None:
        return ""
    if not isinstance(value, str):
        _warn_field_once(field)
        return ""
    return value


def compute_progress(blocks: object, n_patches: int, n_rendered: int) -> PageProgress:
    """Construit un `PageProgress` à partir de la liste de blocs `blocks`
    (référence déjà prise localement par l'appelant, voir
    `modules/pagestate/collect.py`) et des comptes `clean`/`render` déjà
    calculés par l'appelant (sources hors de ce module pur : patchs de
    nettoyage, items de rendu)."""
    try:
        block_list = list(blocks or [])
    except TypeError:
        block_list = []

    n_blocks = len(block_list)
    n_text = sum(1 for blk in block_list if _text_field(blk, _FIELD_TEXT).strip())
    n_translated = sum(1 for blk in block_list if _text_field(blk, _FIELD_TRANSLATION).strip())

    n_patches = n_patches if isinstance(n_patches, int) and n_patches > 0 else 0
    n_rendered = n_rendered if isinstance(n_rendered, int) and n_rendered > 0 else 0

    return PageProgress(n_blocks, n_text, n_translated, n_patches, n_rendered)
