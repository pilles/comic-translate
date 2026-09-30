from PySide6.QtGui import QUndoCommand
from modules.text_undo.resolve import apply_text_edit  # fork: cible résolue à chaque application (3a-ter, ADR-022)


class TextEditCommand(QUndoCommand):
    def __init__(self, main, text_item, old_text: str, new_text: str,
                 old_html: str | None = None, new_html: str | None = None, blk=None):
        super().__init__()
        self.main = main
        self.text_item = text_item
        self.old_text = old_text
        self.new_text = new_text
        self.old_html = old_html
        self.new_html = new_html
        self.blk = blk

    def _apply(self, text: str, html: str | None):
        apply_text_edit(self, text, html)  # fork: item recréé/détruit -> résolution (3a-ter, ADR-022) ; nominal = apply_text_from_command inchangé

    def redo(self):
        self._apply(self.new_text, self.new_html)

    def undo(self):
        self._apply(self.old_text, self.old_html)
