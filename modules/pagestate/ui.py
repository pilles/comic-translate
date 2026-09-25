"""Piste d'avancement par page dans la liste de pages (spec 04, jalon 1).
Importe PySide6 — n'importer ce module que depuis `controller.py`
(`attach_page_state`), jamais depuis `modules/pagestate/__init__.py` (qui
reste pur, voir ADR-012 pour le précédent de découplage). N'importe rien de
`app.*` : lit `page_list` et son délégué existant par introspection Qt
publique (`itemDelegate()`), sans dépendre de `app.ui.list_view`.

Conception validée (spec 04 jalon 1) : délégué composé par-dessus le délégué
existant (`app.ui.list_view.PageListItemDelegate`), peint après lui sans
modifier son option, avec dégradation silencieuse si l'attache ou la lecture
échoue — l'application doit démarrer même si ce jalon est en panne. Aucune
écriture nulle part (lecture seule, cf. `modules/pagestate/collect.py`)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from PySide6.QtCore import QEvent, QObject, QPoint, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QToolTip

from modules.pagestate import collect
from modules.pagestate.progress import STEPS, PageProgress

if TYPE_CHECKING:
    from controller import ComicTranslate

logger = logging.getLogger(__name__)

# Géométrie par défaut, recopiée de `app/ui/list_view.py:13-16`
# (`PageListItemDelegate.MARGIN_X`/`THUMB_SIZE`/`GAP`) — lue en priorité sur
# le délégué existant via `getattr`, ces constantes ne servent que de repli.
_DEFAULT_MARGIN_X = 8
_DEFAULT_THUMB_WIDTH = 35
_DEFAULT_GAP = 10

_TRACK_Y_TOP_OFFSET = 11
_TRACK_Y_BOTTOM_OFFSET = 6
_TRACK_MIN_WIDTH = 20
_SEGMENT_GAP = 2.0

# Case éteinte : même rectangle qu'une case pleine, couleur du texte à faible
# opacité. Un trait `palette.mid` atténué était invisible sur thème sombre
# (écart mesuré de 5 niveaux sur 255, 2026-09-23).
_ABSENT_ALPHA = 60
_SKIPPED_OPACITY_FACTOR = 0.5

_REFRESH_THROTTLE_MS = 30
_WATCHDOG_INTERVAL_MS = 500

_TOOLTIP_LABELS = {
    "detect": ("Détectée ({n} blocs)", "Pas encore détectée"),
    "ocr": ("Reconnue {text}/{total}", "Pas encore reconnue"),
    "translate": ("Traduite {translated}/{total}", "Pas encore traduite"),
    "clean": ("Nettoyée ({n} zones)", "Pas encore nettoyée"),
    "render": ("Rendue ({n} textes)", "Pas encore rendue"),
}

_warned_once: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key in _warned_once:
        return
    _warned_once.add(key)
    logger.warning(message)
    logger.debug("modules.pagestate.ui: détail de %s", key, exc_info=True)


def _format_tooltip(progress: PageProgress) -> str:
    parts: list[str] = []
    for step in STEPS:
        done_fmt, absent_label = _TOOLTIP_LABELS[step]
        if not progress.done(step):
            parts.append(absent_label)
            continue
        if step == "detect":
            parts.append(done_fmt.format(n=progress.n_blocks))
        elif step == "ocr":
            parts.append(done_fmt.format(text=progress.n_text, total=progress.n_blocks))
        elif step == "translate":
            parts.append(done_fmt.format(translated=progress.n_translated, total=progress.n_blocks))
        elif step == "clean":
            parts.append(done_fmt.format(n=progress.n_patches))
        else:  # render
            parts.append(done_fmt.format(n=progress.n_rendered))
    return " · ".join(parts)


class PageStateDelegate(QStyledItemDelegate):
    """Délégué composé : délègue peinture/`sizeHint`/info-bulle au délégué
    existant (`inner`), puis superpose la piste d'avancement par-dessus (bande
    basse de la ligne). N'appelle que l'API publique de `inner`
    (`paint`/`sizeHint`/`helpEvent`), jamais un de ses membres privés
    (précédent : `modules/view/original.py`, règle CLAUDE.md)."""

    def __init__(
        self,
        inner: QStyledItemDelegate,
        provider: Callable[[str], PageProgress],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._inner = inner
        self._provider = provider

    def paint(self, painter, option, index) -> None:  # noqa: N802
        self._inner.paint(painter, option, index)
        try:
            self._paint_track(painter, option, index)
        except Exception:
            _warn_once("paint", "modules.pagestate.ui: échec de peinture de la piste d'avancement.")

    def sizeHint(self, option, index):  # noqa: N802
        return self._inner.sizeHint(option, index)

    def helpEvent(self, event, view, option, index) -> bool:  # noqa: N802
        if event.type() == QEvent.Type.ToolTip and index.isValid():
            path = index.data(Qt.ItemDataRole.UserRole)
            if isinstance(path, str) and path:
                text = self._tooltip_text_for(path)
                if text:
                    QToolTip.showText(event.globalPos(), text, view)
                    return True
        return self._inner.helpEvent(event, view, option, index)

    def _tooltip_text_for(self, path: str) -> str | None:
        try:
            progress = self._provider(path)
            return _format_tooltip(progress)
        except Exception:
            _warn_once(
                "tooltip", "modules.pagestate.ui: échec de calcul de l'info-bulle d'avancement."
            )
            return None

    def _track_geometry(self, option) -> tuple[float, float, float, float] | None:
        inner = self._inner
        margin = getattr(inner, "MARGIN_X", _DEFAULT_MARGIN_X)
        gap = getattr(inner, "GAP", _DEFAULT_GAP)
        thumb_size = getattr(inner, "THUMB_SIZE", None)
        thumb_width = (
            thumb_size.width()
            if thumb_size is not None and hasattr(thumb_size, "width")
            else _DEFAULT_THUMB_WIDTH
        )

        rect = option.rect
        x_left = rect.left() + margin + thumb_width + gap
        x_right = rect.right() - margin
        x_right = min(x_right, self._scrollbar_left(option) - margin)
        if x_right - x_left < _TRACK_MIN_WIDTH:
            return None

        y_top = rect.bottom() - _TRACK_Y_TOP_OFFSET
        y_bottom = rect.bottom() - _TRACK_Y_BOTTOM_OFFSET
        return (x_left, x_right, y_top, y_bottom)

    @staticmethod
    def _scrollbar_left(option) -> float:
        """Abscisse gauche de la barre de défilement verticale quand elle
        recouvre la ligne (barres superposées de macOS), sinon +inf."""
        widget = getattr(option, "widget", None)
        try:
            bar = widget.verticalScrollBar()
            viewport = widget.viewport()
            if bar is None or not bar.isVisible():
                return float("inf")
            left = bar.mapTo(widget, QPoint(0, 0)).x() - viewport.mapTo(widget, QPoint(0, 0)).x()
            return float(left) if left < viewport.width() else float("inf")
        except Exception:
            return float("inf")

    def _paint_track(self, painter, option, index) -> None:
        path = index.data(Qt.ItemDataRole.UserRole)
        if not isinstance(path, str) or not path:
            return

        geometry = self._track_geometry(option)
        if geometry is None:
            return
        x_left, x_right, y_top, y_bottom = geometry

        progress = self._provider(path)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        font_data = index.data(Qt.ItemDataRole.FontRole)
        skipped = isinstance(font_data, QFont) and font_data.strikeOut()

        accent = (
            option.palette.highlightedText().color()
            if selected
            else option.palette.highlight().color()
        )
        absent = QColor(
            option.palette.highlightedText().color() if selected else option.palette.text().color()
        )
        absent.setAlpha(_ABSENT_ALPHA)

        painter.save()
        try:
            if skipped:
                painter.setOpacity(painter.opacity() * _SKIPPED_OPACITY_FACTOR)

            total_width = x_right - x_left
            seg_width = (total_width - _SEGMENT_GAP * (len(STEPS) - 1)) / len(STEPS)
            if seg_width <= 0:
                return

            x = float(x_left)
            for step in STEPS:
                seg_rect = QRectF(x, float(y_top), seg_width, float(y_bottom - y_top))
                painter.fillRect(seg_rect, accent if progress.done(step) else absent)
                x += seg_width + _SEGMENT_GAP
        finally:
            painter.restore()


class _Refresher(QObject):
    """Étrangle les demandes de repaint : les slots connectés aux signaux
    applicatifs ne lisent jamais l'état, ils appellent seulement `request()`
    (consigne critic m6)."""

    def __init__(self, page_list: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._page_list = page_list
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_REFRESH_THROTTLE_MS)
        self._timer.timeout.connect(self._on_timeout)

    def request(self) -> None:
        if self._timer.isActive():
            return
        self._timer.start()

    def _on_timeout(self) -> None:
        try:
            self._page_list.viewport().update()
        except RuntimeError:
            # Widget Qt déjà détruit (fenêtre fermée pendant le délai
            # d'étranglement) : rien à rafraîchir, sans conséquence.
            pass


_SIGNALS_TO_WATCH: tuple[tuple[str | None, str], ...] = (
    ("undo_group", "indexChanged"),
    (None, "render_state_ready"),
    (None, "patches_processed"),
    (None, "image_skipped"),
    (None, "progress_update"),
    ("s_text_edit", "textChanged"),
    ("t_text_edit", "textChanged"),
)


def _connect_watched_signals(main: Any, refresher: _Refresher) -> None:
    for holder_attr, signal_name in _SIGNALS_TO_WATCH:
        label = f"{holder_attr or 'main'}.{signal_name}"
        holder = main if holder_attr is None else getattr(main, holder_attr, None)
        if holder is None:
            _warn_once(
                f"signal:{label}",
                f"modules.pagestate.ui: {label} absent, rafraîchissement dégradé.",
            )
            continue
        signal = getattr(holder, signal_name, None)
        if signal is None:
            _warn_once(
                f"signal:{label}",
                f"modules.pagestate.ui: {label} absent, rafraîchissement dégradé.",
            )
            continue
        try:
            signal.connect(lambda *_args: refresher.request())
        except Exception:
            _warn_once(f"signal:{label}", f"modules.pagestate.ui: connexion de {label} en échec.")


def _install_watchdog(main: Any, page_list: Any) -> QTimer:
    """Chien de garde (500 ms, parent `page_list`) : rattrape les cas où un
    signal de `_SIGNALS_TO_WATCH` n'a pas suffi. Ne recalcule une signature
    (chemin + 5 booléens FAITE/ABSENTE) que pour les lignes visibles, et ne
    demande une repeinte que si elle a changé."""
    timer = QTimer(page_list)
    timer.setInterval(_WATCHDOG_INTERVAL_MS)
    last_signature: list[tuple[Any, ...] | None] = [None]

    def _tick() -> None:
        try:
            if not page_list.isVisible():
                return
            image_files = getattr(main, "image_files", None) or []
            if not image_files:
                return

            model = page_list.model()
            if model is None:
                return
            viewport_rect = page_list.viewport().rect()

            signature: list[Any] = []
            for row in range(page_list.count()):
                index = model.index(row, 0)
                if not index.isValid():
                    continue
                if not page_list.visualRect(index).intersects(viewport_rect):
                    continue
                path = index.data(Qt.ItemDataRole.UserRole)
                if not isinstance(path, str) or not path:
                    continue
                progress = collect.page_progress(main, path)
                signature.append((path, *(progress.done(step) for step in STEPS)))

            signature_tuple = tuple(signature)
            if signature_tuple != last_signature[0]:
                last_signature[0] = signature_tuple
                page_list.viewport().update()
        except Exception:
            _warn_once(
                "watchdog", "modules.pagestate.ui: échec du chien de garde de rafraîchissement."
            )

    timer.timeout.connect(_tick)
    timer.start()
    return timer


def attach_page_state(main: "ComicTranslate") -> PageStateDelegate | None:
    """Attache la piste d'avancement au `page_list` de `main`, par
    composition (précédent : `modules.history.ui.attach_block_history_button`,
    `modules.view.original.attach_original_button`). Ne lève jamais : une
    attache ratée journalise et renvoie `None`, l'application doit démarrer
    quand même (spec 04, jalon 1)."""
    try:
        page_list = getattr(main, "page_list", None)
        if page_list is None:
            logger.warning(
                "modules.pagestate.ui: pas de page_list exploitable, piste non attachée."
            )
            return None

        get_delegate = getattr(page_list, "itemDelegate", None)
        set_delegate = getattr(page_list, "setItemDelegate", None)
        if get_delegate is None or set_delegate is None:
            logger.warning("modules.pagestate.ui: page_list sans délégué Qt, piste non attachée.")
            return None

        inner = get_delegate()
        if inner is None:
            logger.warning("modules.pagestate.ui: pas de délégué existant, piste non attachée.")
            return None

        def _provider(path: str) -> PageProgress:
            return collect.page_progress(main, path)

        delegate = PageStateDelegate(inner, _provider, parent=page_list)
        set_delegate(delegate)

        # Garde une référence Python à `inner` (ADR-012 : un `QObject` enfant
        # de `page_list` reste vivant côté Qt, mais sans référence Python le
        # wrapper peut être recréé/perdu avant la prochaine lecture).
        main._page_state_inner_delegate = inner
        main._page_state_delegate = delegate

        refresher = _Refresher(page_list, parent=page_list)
        main._page_state_refresher = refresher
        _connect_watched_signals(main, refresher)

        main._page_state_watchdog = _install_watchdog(main, page_list)

        return delegate
    except Exception:
        logger.exception("modules.pagestate.ui: attache de la piste d'avancement en échec.")
        return None
