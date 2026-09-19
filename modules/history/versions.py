"""Historique de versions par bloc (spec 03, jalon A) — module pur.

Aucune dépendance à PySide6 ici : ce module doit rester importable depuis un
worker (thread non-GUI) et depuis les tests sans `--gui`. Les versions sont
stockées sur `TextBlock.versions` (créé paresseusement, jamais déclaré dans
`TextBlock.__init__` — voir `modules/utils/textblock.py`), une liste de
dictionnaires `HistoryEntry` composée uniquement de types simples (str, dict)
pour rester sérialisable telle quelle par `ProjectEncoder`/msgpack, sans
encodeur dédié.

Règles d'enregistrement (voir specs/03-inventaire.md, ADR-012) :
- `set_text` est le point d'entrée unique pour écrire un champ en journalisant
  la version précédente si elle divergeait de la tête du journal (pré-état).
- `snapshot`/`record_diff` couvrent les processeurs (OCR, traduction), qui
  écrivent le champ eux-mêmes avant que le diff ne soit enregistré.
- `flush_pending` rattrape les écritures non instrumentées (frappe directe
  dans les champs source/traduction) juste avant une sauvegarde d'état de
  page ; c'est aussi le seul point qui élague le journal (`prune`), pour
  rester sur le fil GUI (voir M1 : append depuis un worker est sûr, prune ne
  l'est pas).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Iterable, TypedDict

if TYPE_CHECKING:
    from modules.utils.textblock import TextBlock

logger = logging.getLogger(__name__)

# Plafonds (ADR-012) : bornent le poids du projet sans empêcher un historique
# utile sur une page activement travaillée. Non garantis avant le premier
# `flush_pending` de la page (append en place, jamais de prune hors fil GUI).
MAX_VERSIONS_PER_BLOCK = 12
MAX_VALUE_CHARS = 2000
MAX_CHARS_PER_BLOCK = 6000

# Champs journalisés.
FIELD_TEXT = "text"
FIELD_TRANSLATION = "translation"

# Origines.
ORIGIN_OCR = "ocr"
ORIGIN_CACHE_OCR = "cache_ocr"
ORIGIN_TRANSLATION = "translation"
ORIGIN_CACHE = "cache"
ORIGIN_MANUAL = "manual"
ORIGIN_PRIOR = "prior"
# Réservée, non instrumentée au jalon A (coupe retenue par l'orchestrateur :
# les deux sites de app/controllers/search_replace.py ne sont pas câblés ;
# le pré-état de set_text/flush_pending rattrape ces écritures au prochain
# flush). Conservée pour ne pas casser un futur câblage.
ORIGIN_SEARCH_REPLACE = "search_replace"
ORIGIN_RESTORE = "restore"


class HistoryEntry(TypedDict):
    field: str
    value: str
    origin: str
    at: str
    meta: dict[str, str]


_warned_max_value_chars = False


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _coerce_meta(meta: dict[str, str] | None) -> dict[str, str]:
    if not meta:
        return {}
    return {str(k): str(v) for k, v in meta.items()}


def _journal_ro(blk: "TextBlock") -> list[HistoryEntry]:
    """Lecture seule : jamais de création paresseuse de l'attribut."""
    return getattr(blk, "versions", None) or []


def _journal_rw(blk: "TextBlock") -> list[HistoryEntry]:
    """Écriture : crée `versions` si absent, append en place ensuite (jamais
    de réaffectation — un `RectCommandBase` peut faire pointer deux
    `TextBlock` vivants vers la même liste, voir ADR-012)."""
    return blk.__dict__.setdefault("versions", [])


def _head_for_field(journal: list[HistoryEntry], field: str) -> HistoryEntry | None:
    for entry in reversed(journal):
        if entry["field"] == field:
            return entry
    return None


def _append_entry(
    journal: list[HistoryEntry],
    field: str,
    value: str,
    origin: str,
    meta: dict[str, str] | None,
) -> HistoryEntry:
    entry: HistoryEntry = {
        "field": field,
        "value": value,
        "origin": origin,
        "at": _now_iso(),
        "meta": _coerce_meta(meta),
    }
    journal.append(entry)
    return entry


def _warn_max_value_chars_once() -> None:
    global _warned_max_value_chars
    if _warned_max_value_chars:
        return
    _warned_max_value_chars = True
    logger.warning(
        "modules.history: valeur de champ > %d caractères, champ écrit sans entrée d'historique.",
        MAX_VALUE_CHARS,
    )


def set_text(
    blk: "TextBlock",
    field: str,
    value: str,
    origin: str,
    meta: dict[str, str] | None = None,
) -> bool:
    """Écrit `value` dans `blk.<field>` et journalise si pertinent.

    Ordre impératif (critic pass 2, consigne Ma) :
    1. valeur courante ; 2. tête du journal DU CHAMP ; 3. pré-état si la
    valeur courante divergeait de la tête (``manual`` si le champ avait déjà
    une tête, ``prior`` sinon — Mc : décision par champ, pas par bloc) ;
    4. relecture de la tête ; 5. dédoublonnage (casefold) contre la nouvelle
    tête ; 6. `setattr` dans tous les cas (Mb) ; 7. `append` si ni
    dédoublonné ni rejeté pour dépassement de `MAX_VALUE_CHARS`.

    Invariant après appel (sauf rejet `MAX_VALUE_CHARS`) :
    ``versions_of(blk, field)[-1]["value"].casefold() == getattr(blk, field).casefold()``.

    Retourne `True` si une nouvelle entrée a été ajoutée pour `value`, `False`
    sinon (dédoublonnée ou rejetée) — le champ est écrit dans tous les cas.
    """
    value = "" if value is None else str(value)
    cur = getattr(blk, field, "") or ""
    journal = _journal_rw(blk)
    head = _head_for_field(journal, field)

    if cur and (head is None or cur.casefold() != head["value"].casefold()):
        prestate_origin = ORIGIN_PRIOR if head is None else ORIGIN_MANUAL
        _append_entry(journal, field, cur, prestate_origin, None)
        head = _head_for_field(journal, field)

    if len(value) > MAX_VALUE_CHARS:
        setattr(blk, field, value)
        _warn_max_value_chars_once()
        return False

    if head is not None and value.casefold() == head["value"].casefold():
        setattr(blk, field, value)
        return False

    setattr(blk, field, value)
    _append_entry(journal, field, value, origin, meta)
    return True


def set_many(
    items: Iterable[tuple["TextBlock", str, str]],
    origin: str,
    meta: dict[str, str] | None = None,
) -> list[bool]:
    """Applique `set_text` à une série de (bloc, champ, valeur) partageant
    la même origine/meta (utilitaire, non requis par un site du jalon A)."""
    return [set_text(blk, field, value, origin, meta) for blk, field, value in items]


def snapshot(blk_list: list["TextBlock"], field: str) -> dict[int, str]:
    """Capture la valeur de `field` avant traitement, indexée par `id(blk)`.

    À utiliser avec `record_diff` autour d'un traitement qui écrit `field`
    lui-même (moteurs OCR/traduction, B4) : le processeur ne peut pas passer
    par `set_text` directement puisqu'il ne contrôle pas l'écriture."""
    return {id(blk): (getattr(blk, field, "") or "") for blk in blk_list}


def record_diff(
    blk_list: list["TextBlock"],
    field: str,
    before: dict[int, str],
    origin: str,
    meta: dict[str, str] | None = None,
) -> None:
    """Journalise, pour chaque bloc déjà traité, la différence entre la
    valeur capturée par `snapshot` et la valeur actuelle du champ (déjà
    écrite par le moteur). Aucune entrée si la valeur n'a pas changé
    (casefold) — évite de journaliser un bloc que le moteur n'a pas touché.
    """
    for blk in blk_list:
        if id(blk) not in before:
            continue
        old_value = before[id(blk)]
        new_value = getattr(blk, field, "") or ""
        if new_value.casefold() == old_value.casefold():
            continue
        # `set_text` lit `cur` pour construire le pré-état : on y remet
        # temporairement la valeur d'avant traitement, puisque le moteur a
        # déjà écrasé le champ avec `new_value`.
        setattr(blk, field, old_value)
        set_text(blk, field, new_value, origin, meta)


def flush_pending(blk_list: list["TextBlock"]) -> None:
    """Rattrape les écritures non instrumentées (frappe directe dans les
    widgets source/traduction) puis élague. Seul point d'appel de `prune` —
    à appeler uniquement depuis le fil GUI, juste avant une sauvegarde
    d'état de page (`app/controllers/image.py:save_image_state`)."""
    for blk in blk_list:
        for field in (FIELD_TEXT, FIELD_TRANSLATION):
            cur = getattr(blk, field, "") or ""
            if not cur:
                continue
            journal_ro = _journal_ro(blk)
            head = _head_for_field(journal_ro, field)
            if head is None or cur.casefold() != head["value"].casefold():
                journal = _journal_rw(blk)
                origin = ORIGIN_PRIOR if head is None else ORIGIN_MANUAL
                _append_entry(journal, field, cur, origin, None)
        prune(blk)


def versions_of(blk: "TextBlock", field: str | None = None) -> list[HistoryEntry]:
    """Lecture défensive : toujours via `getattr`, jamais d'accès direct à
    `blk.versions` (compat avec un bloc jamais journalisé)."""
    journal = _journal_ro(blk)
    if field is None:
        return list(journal)
    return [entry for entry in journal if entry["field"] == field]


def pop_head_if_origin(blk: "TextBlock", field: str, origin: str) -> bool:
    """Retire la dernière entrée de `field` si elle est bien en tête ET de
    l'origine attendue (utilisé par `RestoreVersionCommand.undo` : ne retire
    jamais le pré-état, seulement l'entrée `restore` qu'un `redo` a créée)."""
    journal = getattr(blk, "versions", None)
    if not journal:
        return False
    for i in range(len(journal) - 1, -1, -1):
        if journal[i]["field"] == field:
            if journal[i]["origin"] == origin:
                journal.pop(i)
                return True
            return False
    return False


def prune(blk: "TextBlock") -> None:
    """Élague le journal de `blk` en place (jamais de réaffectation) :
    1. par champ, cap à `MAX_VERSIONS_PER_BLOCK`, FIFO, sauf la plus
       ancienne entrée du champ (épinglée, c'est le « texte d'origine ») ;
    2. budget global `MAX_CHARS_PER_BLOCK` (toutes entrées confondues),
       FIFO en respectant les mêmes épinglages.
    Ne doit être appelé que depuis `flush_pending` (fil GUI, non atomique
    vis-à-vis d'un `append` concurrent depuis un worker)."""
    journal = getattr(blk, "versions", None)
    if not journal:
        return

    fields = {entry["field"] for entry in journal}
    for field in fields:
        field_entries = [entry for entry in journal if entry["field"] == field]
        if len(field_entries) <= MAX_VERSIONS_PER_BLOCK:
            continue
        pinned = field_entries[0]
        keep_recent = field_entries[1:][-(MAX_VERSIONS_PER_BLOCK - 1) :]
        keep_ids = {id(pinned)} | {id(entry) for entry in keep_recent}
        journal[:] = [
            entry for entry in journal if entry["field"] != field or id(entry) in keep_ids
        ]

    total_chars = sum(len(entry["value"]) for entry in journal)
    if total_chars <= MAX_CHARS_PER_BLOCK:
        return

    pinned_ids: set[int] = set()
    for field in fields:
        field_entries = [entry for entry in journal if entry["field"] == field]
        if field_entries:
            pinned_ids.add(id(field_entries[0]))

    i = 0
    while total_chars > MAX_CHARS_PER_BLOCK and i < len(journal):
        entry = journal[i]
        if id(entry) in pinned_ids:
            i += 1
            continue
        total_chars -= len(entry["value"])
        journal.pop(i)
