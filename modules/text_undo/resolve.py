"""Résolution de la cible des annulations de texte (spec 04, jalon 3, 3a-ter, ADR-022).

Duck typing sur `main` (`image_viewer`, `text_ctrl`, `blk_list`, `curr_img_idx`, `image_files`,
`curr_tblock`, `s_text_edit`, `t_text_edit`) : importe `shiboken6` (validité des items Qt) mais ni
`controller.py` ni `app.controllers`. La sélection elle-même est dans `match.py` (pur).

Décisions de Philippe (2026-09-28) :
- **D2** : quand l'item vivant n'existe plus, `TextEditCommand`/`RestoreVersionCommand` écrivent le
  texte sur le **bloc vivant** de la page affichée s'il est résolu (champ du panneau mis à jour
  sous `blockSignals` si `curr_tblock is blk`), sinon aucune mutation ; `TextFormatCommand` : aucun
  effet. **Jamais d'exception, jamais de recréation d'item, jamais de message** (journal INFO).
- **Exception écrite à l'ADR-012** : le chemin « bloc seul » de `TextEditCommand` écrit
  `blk.translation` sans `modules.history.versions.set_text`, comme le chemin nominal amont
  (`apply_text_from_command`) ; `flush_pending` rattrape en `manual` au prochain enregistrement.

Chemin **nominal** (item vivant et attaché à la scène) : inchangé, y compris pour l'objet passé à
`apply_text_from_command`, sauf **M3** — si le bloc mémorisé n'est plus vivant (absent de
`main.blk_list` par identité, p. ex. après un nouveau Détecter), on ne l'écrit pas : on le remplace
par le bloc apparié à l'item, ou `None`."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import shiboken6

from modules.text_undo import match
from modules.text_undo.match import Anchor

logger = logging.getLogger(__name__)

# Doivent rester égaux à `modules.history.versions.FIELD_TRANSLATION` / `FIELD_TEXT` (vérifié par
# `tests/test_text_undo.py`) ; dupliqués ici pour que ce module n'importe pas l'historique.
FIELD_TRANSLATION = "translation"
FIELD_TEXT = "text"

REASON_NOMINAL = "nominal"
REASON_NOMINAL_DEAD_BLOCK = "nominal, bloc mémorisé mort remplacé"
REASON_SUBSTITUTED = "item substitué"
REASON_BLOCK_ONLY = "bloc seul"
REASON_BLOCK_CHANGED = "texte du bloc changé depuis"


def default_is_valid(obj: Any) -> bool:
    """`shiboken6.isValid(None)` et `isValid(objet non Shiboken)` renvoient vrai (critic m2) :
    `None` est exclu explicitement."""
    return obj is not None and shiboken6.isValid(obj)


@dataclass(frozen=True)
class TextTarget:
    """Cible résolue : `item` (à mettre à jour, ou `None` -> chemin bloc seul), `blk` (bloc vivant
    à écrire, ou `None`). Rien de résolu (`item` et `blk` à `None`) = aucune mutation."""

    item: Any | None
    blk: Any | None
    reason: str

    @property
    def resolved(self) -> bool:
        return self.item is not None or self.blk is not None


# --- Utilitaires ---------------------------------------------------------------------------------


def current_page(main: Any) -> str | None:
    idx = getattr(main, "curr_img_idx", -1)
    files = getattr(main, "image_files", None) or []
    if isinstance(idx, int) and 0 <= idx < len(files):
        return files[idx]
    return None


def is_attached(item: Any, scene: Any, is_valid: Callable[[Any], bool]) -> bool:
    """Item non nul, valide côté C++ et attaché à `scene` (jamais d'exception)."""
    if item is None:
        return False
    try:
        return bool(is_valid(item)) and item.scene() is scene
    except Exception:  # noqa: BLE001 - objet détruit entre-temps : simplement pas attaché
        logger.debug("modules.text_undo.resolve: sonde d'attache en échec.", exc_info=True)
        return False


def anchor_from_item(page: str | None, item: Any, *, with_text: bool = False) -> Anchor | None:
    try:
        pos = item.pos()
        return Anchor(
            page,
            float(pos.x()),
            float(pos.y()),
            float(item.rotation()),
            item.toPlainText() if with_text else None,
        )
    except Exception:  # noqa: BLE001 - item détruit : pas d'ancre
        logger.debug("modules.text_undo.resolve: ancre d'item impossible.", exc_info=True)
        return None


def anchor_from_block(page: str | None, blk: Any) -> Anchor | None:
    try:
        return Anchor(page, float(blk.xyxy[0]), float(blk.xyxy[1]), float(blk.angle))
    except Exception:  # noqa: BLE001 - bloc incomplet : pas d'ancre
        logger.debug("modules.text_undo.resolve: ancre de bloc impossible.", exc_info=True)
        return None


def _block_reference(blk: Any) -> match.Reference | None:
    anchor = anchor_from_block(None, blk) if blk is not None else None
    return anchor.reference if anchor is not None else None


def update_panel(main: Any, blk: Any, field: str, value: str) -> None:
    """Répercute `value` sur le champ du panneau si `blk` est le bloc affiché. M5 (ADR-012) :
    écrire dans un champ sans bloquer les signaux réécrirait l'autre (`update_text_block`) ; on
    bloque les deux par prudence."""
    if getattr(main, "curr_tblock", None) is not blk or blk is None:
        return
    main.s_text_edit.blockSignals(True)
    main.t_text_edit.blockSignals(True)
    try:
        if field == FIELD_TEXT:
            main.s_text_edit.setPlainText(value)
        else:
            main.t_text_edit.setPlainText(value)
    finally:
        main.s_text_edit.blockSignals(False)
        main.t_text_edit.blockSignals(False)


# --- Texte (TextEditCommand, RestoreVersionCommand) ----------------------------------------------


def resolve_text_target(
    main: Any,
    *,
    item: Any,
    blk: Any,
    anchor: Anchor | None,
    expected: str,
    field: str = FIELD_TRANSLATION,
    want_item: bool = True,
    verify_live_block: bool = True,
    is_valid: Callable[[Any], bool] = default_is_valid,
) -> TextTarget:
    """Résout la cible d'une annulation/d'un rétablissement de texte.

    `expected` : texte que l'item (et, en chemin bloc seul, `getattr(blk, field)`) doit afficher
    **avant** l'application (annuler -> `new_text`, rétablir -> `old_text`). `want_item=False` :
    aucun item concerné (champ source de `RestoreVersionCommand`, ou bloc jamais rendu à la
    construction). `verify_live_block=False` : bloc vivant écrit sans vérifier son texte (chemin
    nominal de `RestoreVersionCommand` quand elle n'a jamais eu d'item — comportement d'origine)."""
    viewer = main.image_viewer
    scene = viewer._scene
    text_ctrl = main.text_ctrl
    blk_list = main.blk_list
    live_blk = blk if match.contains_by_identity(blk_list, blk) else None

    # 1. Chemin nominal : item vivant et attaché.
    if want_item and is_attached(item, scene, is_valid):
        if blk is not None and live_blk is None:
            logger.info(
                "modules.text_undo.resolve: bloc mémorisé mort, remplacé par le bloc de l'item."
            )
            return TextTarget(
                item, text_ctrl._find_text_block_for_item(item), REASON_NOMINAL_DEAD_BLOCK
            )
        return TextTarget(item, blk, REASON_NOMINAL)

    # 2. Page d'ancre différente : rien n'est résolu.
    if anchor is not None and not match.same_page(anchor.page, current_page(main)):
        return TextTarget(None, None, match.REASON_OTHER_PAGE)

    # 3. Référence de position : bloc vivant, sinon ancre, sinon position du bloc mort.
    reference = _block_reference(live_blk)
    if reference is None and anchor is not None:
        reference = anchor.reference
    if reference is None:
        reference = _block_reference(blk)

    # 4. Recherche d'un item recréé parmi `viewer.text_items` attachés à la scène.
    if want_item and reference is not None:
        candidates = [c for c in viewer.text_items if is_attached(c, scene, is_valid)]
        pick = match.pick_item(
            candidates,
            reference=reference,
            expected_text=expected,
            is_valid=is_valid,
            blk=live_blk,
            block_of=text_ctrl._find_text_block_for_item,
        )
        if pick.item is not None:
            matched = (
                live_blk if live_blk is not None else text_ctrl._find_text_block_for_item(pick.item)
            )
            return TextTarget(pick.item, matched, REASON_SUBSTITUTED)
        logger.info("modules.text_undo.resolve: aucun item retenu (%s).", pick.reason)

    # 5. Chemin bloc seul (D2).
    if live_blk is not None:
        if not verify_live_block or getattr(live_blk, field, None) == expected:
            return TextTarget(None, live_blk, REASON_BLOCK_ONLY)
        return TextTarget(None, None, REASON_BLOCK_CHANGED)
    block_pick = match.pick_block(blk_list, reference=reference, field=field, expected=expected)
    if block_pick.item is not None:
        return TextTarget(None, block_pick.item, REASON_BLOCK_ONLY)
    return TextTarget(None, None, block_pick.reason)


def apply_text_edit(
    cmd: Any, text: str, html: str | None, *, is_valid: Callable[[Any], bool] = default_is_valid
) -> None:
    """Corps de `TextEditCommand._apply` (redo et undo). Jamais d'exception, jamais de message."""
    main = cmd.main
    # old_text != new_text par construction (`_commit_pending_text_command` n'en crée pas sinon) :
    # le texte à appliquer désigne la direction, donc le texte attendu avant application.
    expected = cmd.old_text if text == cmd.new_text else cmd.new_text

    anchor = getattr(cmd, "_fork_anchor", None)
    if anchor is None:
        anchor = _initial_anchor(main, cmd.text_item, cmd.blk, is_valid)
        cmd._fork_anchor = anchor

    target = resolve_text_target(
        main,
        item=cmd.text_item,
        blk=cmd.blk,
        anchor=anchor,
        expected=expected,
        field=FIELD_TRANSLATION,
        is_valid=is_valid,
    )

    if target.item is not None:
        main.text_ctrl.apply_text_from_command(target.item, text, html=html, blk=target.blk)
        if target.reason != REASON_NOMINAL:
            cmd.text_item = target.item  # les applications suivantes redeviennent nominales
        refresh_anchor(cmd, main, target.item, target.blk, is_valid)
        return

    if target.blk is not None:
        write_block_only(main, target.blk, text)
        refresh_anchor(cmd, main, None, target.blk, is_valid)
        return

    logger.info(
        "modules.text_undo.resolve: TextEditCommand sans effet (%s) : ni item ni bloc résolus.",
        target.reason,
    )


def _initial_anchor(
    main: Any, item: Any, blk: Any, is_valid: Callable[[Any], bool]
) -> Anchor | None:
    page = current_page(main)
    if is_attached(item, main.image_viewer._scene, is_valid):
        anchor = anchor_from_item(page, item)
        if anchor is not None:
            return anchor
    return anchor_from_block(page, blk) if blk is not None else None


def refresh_anchor(
    cmd: Any, main: Any, item: Any, blk: Any, is_valid: Callable[[Any], bool] = default_is_valid
) -> None:
    """Ancre = position de l'objet visé à la dernière application **réussie** (critic m8)."""
    page = current_page(main)
    anchor = None
    if item is not None and is_valid(item):
        anchor = anchor_from_item(page, item)
    if anchor is None and blk is not None:
        anchor = anchor_from_block(page, blk)
    if anchor is not None:
        cmd._fork_anchor = anchor


def write_block_only(main: Any, blk: Any, text: str, field: str = FIELD_TRANSLATION) -> None:
    """Chemin D2 de `TextEditCommand` : écrit le bloc vivant (sans `set_text`, exception à
    l'ADR-012, voir docstring du module) et le champ du panneau si `blk` est affiché."""
    setattr(blk, field, text)
    update_panel(main, blk, field, text)


# --- Format (TextFormatCommand) ------------------------------------------------------------------


def resolve_format_target(
    cmd: Any, scene: Any, properties: Any, *, is_valid: Callable[[Any], bool] = default_is_valid
) -> Any | None:
    """Corps de `TextFormatCommand._get_item`. Nominal : `cmd.item` s'il est vivant et attaché à
    `scene` (dictionnaires `__dict__` complets, inchangés). Sinon, parmi les `TextBlockItem` de
    `scene.items()` (`TextFormatCommand` n'a pas `main`, m7) : position/rotation de l'ancre, texte
    identique à celui vu à la dernière application (le format ne change pas le texte), unique.
    À la substitution, `old_dict`/`new_dict` sont réduits **une fois** à `FORMAT_KEYS`.
    `None` = aucun effet (D2). Pas de contrôle de page : la commande n'a pas accès à `main`, et
    `QUndoGroup` n'annule que la pile de la page affichée."""
    if is_attached(cmd.item, scene, is_valid):
        anchor = anchor_from_item(None, cmd.item, with_text=True)
        if anchor is not None:
            cmd._fork_anchor = anchor
        return cmd.item

    from app.ui.canvas.text_item import TextBlockItem  # local : garde ce module léger à l'import

    anchor = getattr(cmd, "_fork_anchor", None)
    if anchor is None:
        # Posée « plus tard » : le premier appel n'a trouvé aucun item -> position de la commande.
        position = getattr(properties, "position", None)
        if position is None:
            logger.info("modules.text_undo.resolve: TextFormatCommand sans effet (aucune ancre).")
            return None
        anchor = Anchor(
            None, float(position[0]), float(position[1]), float(getattr(properties, "rotation", 0))
        )

    try:
        candidates = [c for c in scene.items() if isinstance(c, TextBlockItem)]
    except Exception:  # noqa: BLE001 - scène en cours de destruction : aucun effet, journalisé
        logger.info("modules.text_undo.resolve: lecture de la scène impossible.", exc_info=True)
        return None
    pick = match.pick_item(
        candidates, reference=anchor.reference, expected_text=anchor.text, is_valid=is_valid
    )
    if pick.item is None:
        logger.info("modules.text_undo.resolve: TextFormatCommand sans effet (%s).", pick.reason)
        return None

    cmd.old_dict = match.reduce_to_format(cmd.old_dict)
    if cmd.new_dict is not None:
        cmd.new_dict = match.reduce_to_format(cmd.new_dict)
    cmd.item = pick.item
    refreshed = anchor_from_item(None, pick.item, with_text=True)
    if refreshed is not None:
        cmd._fork_anchor = refreshed
    return pick.item
