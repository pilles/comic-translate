"""Vue « Voir l'original » (spec 03, jalon B). Sous-classe d'`ImageViewer` qui
peint un voile recouvrant tout calque (patchs, texte, tracés) par-dessus la
photo d'origine, sans jamais la masquer ni la dupliquer — la photo (`self.photo`)
reste l'unique source peinte, revue à chaque repaint (aucun état mis en cache).

Importe PySide6 — n'importer ce module que depuis `app/ui/main_window/window.py`
(la sous-classe, remplace `ImageViewer`) et
`app/ui/main_window/builders/workspace.py` (`attach_original_button`), jamais
depuis `modules/history/` ou un autre paquet pur (voir CLAUDE.md, carte des
modules).

Conception validée (architect + critic, 2 passages) : voile peint par la vue
(`drawForeground`), jamais de levée temporaire, jamais de cache de `self.photo`,
filtre d'événements applicatif parenté à la fenêtre principale, `return False`
toujours (aucun événement avalé)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QGuiApplication, QKeyEvent
from PySide6.QtWidgets import QApplication, QBoxLayout

from app.ui.canvas.image_viewer import ImageViewer
from app.ui.dayu_widgets.push_button import MPushButton

if TYPE_CHECKING:
    from controller import ComicTranslate

_BUTTON_TEXT = "Original"
_BUTTON_TOOLTIP = (
    "Afficher la page d'origine (Alt maintenu hors saisie). "
    "Pendant l'affichage, les éléments restent cliquables."
)

# Logique recopiée de `app/controllers/shortcuts.py:71-80`
# (`ShortcutController._is_text_input_focused`) : widgets de saisie qui
# inhibent le maintien d'Alt — touche de composition sur clavier macOS
# français (ex. Alt+O -> œ), qui ferait sinon clignoter la page en pleine
# frappe. Ce module ne doit pas importer `app.controllers.shortcuts`
# (dépendance inverse UI -> contrôleur) : la logique est recopiée, pas réutilisée.
_EDITABLE_WIDGET_TYPES = (
    QtWidgets.QLineEdit,
    QtWidgets.QTextEdit,
    QtWidgets.QPlainTextEdit,
    QtWidgets.QAbstractSpinBox,
    QtWidgets.QKeySequenceEdit,
)

_HANDLED_EVENT_TYPES = frozenset(
    {
        QEvent.Type.KeyPress,
        QEvent.Type.KeyRelease,
        QEvent.Type.MouseButtonPress,
        QEvent.Type.WindowDeactivate,
        QEvent.Type.ApplicationStateChange,
    }
)


class OriginalViewImageViewer(ImageViewer):
    """`ImageViewer` capable de peindre un voile montrant la photo d'origine
    seule, par-dessus tout calque (patchs, texte, tracés). `_original_view_button`
    et `_original_view_alt_held` sont posés par `attach_original_button` /
    `_OriginalViewEventFilter` ; `None`/`False` tant que le bouton n'est pas
    encore attaché (fenêtre en construction)."""

    def __init__(self, parent):
        super().__init__(parent)
        self._original_view_button: MPushButton | None = None
        self._original_view_alt_held = False

    def _veil_active(self) -> bool:
        button = self._original_view_button
        if button is not None and button.isChecked():
            return True
        return bool(self._original_view_alt_held) and self.window().isActiveWindow()

    def drawForeground(self, painter: QtGui.QPainter, rect: QtCore.QRectF) -> None:  # noqa: N802
        super().drawForeground(painter, rect)

        # C1 (bloquante) : jamais de voile en webtoon ni sans photo, quel que
        # soit l'état du bouton — ne jamais compter sur setEnabled(False) seul :
        # `clear_scene` recrée une `self.photo` vide (image_viewer.py:333-341,
        # webtoon_manager.py:67) et le bouton peut rester coché en changeant de
        # mode (toggled étouffé par blockSignals, webtoons.py:259-261).
        if self.webtoon_mode or self.photo.pixmap().isNull():
            return
        if not self._veil_active():
            return

        painter.fillRect(rect, self.backgroundBrush())

        # C9 : marge de 1 px pour absorber un arrondi défavorable de
        # mapFromScene aux bords de `rect`, puis intersection avec les
        # bornes réelles de la photo.
        source = self.photo.mapFromScene(rect).boundingRect().adjusted(-1, -1, 1, 1)
        source = source.intersected(self.photo.boundingRect())
        if source.isEmpty():
            return
        target = self.photo.mapRectToScene(source)
        painter.drawPixmap(target, self.photo.pixmap(), source)


def _is_text_input_focused() -> bool:
    """Recopié de `app/controllers/shortcuts.py:71-80`
    (`ShortcutController._is_text_input_focused`)."""
    focus_widget = QApplication.focusWidget()
    return isinstance(focus_widget, _EDITABLE_WIDGET_TYPES)


def _any_text_item_editing(viewer: OriginalViewImageViewer) -> bool:
    # C4 : itère `viewer.text_items` (pas `scene.items()`), `getattr` défensif.
    return any(getattr(item, "editing_mode", False) for item in viewer.text_items)


def _workspace_is_active(main: "ComicTranslate") -> bool:
    # Recopié de `app/controllers/shortcuts.py:65-69`
    # (`ShortcutController._workspace_is_active`).
    try:
        return main._center_stack.currentWidget() is main.main_content_widget
    except AttributeError:
        return False


class _OriginalViewEventFilter(QObject):
    """Filtre applicatif pour la touche Alt maintenue (bascule voile hors
    saisie). Parenté à la fenêtre principale, installé sur l'application
    (précédent : `app/ui/main_window/frame.py::EdgeResizer`). N'avale jamais
    d'événement : `return False` dans tous les cas, sortie immédiate hors des
    types traités."""

    def __init__(self, main: "ComicTranslate", button: MPushButton) -> None:
        super().__init__(main)
        self._main = main
        self._button = button
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        etype = event.type()
        if etype not in _HANDLED_EVENT_TYPES:
            return False

        viewer = self._main.image_viewer

        # C2 (bloquante) : Alt relâché hors de la fenêtre (feuille native,
        # changement d'app) sans `QEvent.KeyRelease` reçu par ce filtre —
        # revérifié sur tout KeyPress/KeyRelease/MouseButtonPress suivant.
        if (
            etype
            in (
                QEvent.Type.KeyPress,
                QEvent.Type.KeyRelease,
                QEvent.Type.MouseButtonPress,
            )
            and viewer._original_view_alt_held
            and not (QGuiApplication.queryKeyboardModifiers() & Qt.KeyboardModifier.AltModifier)
        ):
            self._disarm(viewer)

        if etype == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Alt and not event.isAutoRepeat() and self._can_arm(viewer):
                self._arm(viewer)
        elif etype == QEvent.Type.KeyRelease and isinstance(event, QKeyEvent):
            if event.key() == Qt.Key.Key_Alt:
                self._disarm(viewer)
        elif etype == QEvent.Type.WindowDeactivate:
            self._disarm(viewer)
        elif etype == QEvent.Type.ApplicationStateChange:
            app = QApplication.instance()
            if app is not None and app.applicationState() != Qt.ApplicationState.ApplicationActive:
                self._disarm(viewer)

        return False

    def _can_arm(self, viewer: OriginalViewImageViewer) -> bool:
        main = self._main
        if not _workspace_is_active(main):
            return False
        if QApplication.activeModalWidget() is not None:
            return False
        if not main.isActiveWindow():
            return False
        if _is_text_input_focused():
            return False
        if _any_text_item_editing(viewer):
            return False
        if viewer.webtoon_mode:
            return False
        return True

    def _arm(self, viewer: OriginalViewImageViewer) -> None:
        viewer._original_view_alt_held = True
        self._button.setDown(True)
        viewer.viewport().update()

    def _disarm(self, viewer: OriginalViewImageViewer) -> None:
        if not viewer._original_view_alt_held:
            return
        viewer._original_view_alt_held = False
        self._button.setDown(False)
        viewer.viewport().update()


def attach_original_button(main: "ComicTranslate", layout: QBoxLayout) -> MPushButton:
    """Ajoute le bouton bascule « Original » à `layout` (`misc_lay`, voir
    `app/ui/main_window/builders/workspace.py`), juste avant son
    `addStretch()` terminal, et installe le filtre Alt applicatif. Précédent
    d'attache : `modules/history/ui.py::attach_block_history_button`."""
    viewer = main.image_viewer
    button = MPushButton(main.tr(_BUTTON_TEXT))
    button.setCheckable(True)
    button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    button.setToolTip(main.tr(_BUTTON_TOOLTIP))
    button.toggled.connect(lambda _checked: viewer.viewport().update())

    # C5 : insérer avant le `addStretch()` terminal (dernier item de `misc_lay`).
    layout.insertWidget(layout.count() - 1, button)

    viewer._original_view_button = button

    # C3 : cosmétique seulement — les gardes qui font foi (`viewer.webtoon_mode`)
    # sont revérifiées à l'armement, au clic du bouton et à la peinture, jamais
    # ce seul signal (émis avant le changement de mode et étouffé par
    # `blockSignals` en cours de bascule, `webtoons.py:259-261`).
    main.webtoon_toggle.toggled.connect(lambda _checked: button.setEnabled(not viewer.webtoon_mode))

    main._original_view_filter = _OriginalViewEventFilter(main, button)

    return button
