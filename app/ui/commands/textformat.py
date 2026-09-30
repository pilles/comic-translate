from PySide6.QtGui import QUndoCommand
from .base import RectCommandBase
from modules.text_undo.resolve import resolve_format_target  # fork: cible résolue à chaque application (3a-ter, ADR-022)

class TextFormatCommand(QUndoCommand, RectCommandBase):
    def __init__(self, viewer, item):
        super().__init__()
        self.scene = viewer._scene
        self.item = item
        self.old_dict = item.__dict__.copy()
        self.old_item_prp = self.save_txt_item_properties(item)
        self.old_html = item.toHtml()
        
        # Placeholders for new state, to be finalized after modifications
        self.new_dict = None
        self.new_item_prp = None
        self.new_html = None

    def finalize_new_state(self):
        self.new_dict = self.item.__dict__.copy()
        self.new_item_prp = self.save_txt_item_properties(self.item)
        self.new_html = self.item.toHtml()

    def _get_item(self, properties):
        return resolve_format_target(self, self.scene, properties)  # fork: item recréé/détruit -> résolution + liste blanche de format (3a-ter, ADR-022) ; remplace le repli find_matching_txt_item

    def redo(self):
        if self.new_dict is None:
            return
        matching_item = self._get_item(self.old_item_prp)
        if matching_item:
            matching_item.set_text(self.new_html, self.new_item_prp.width)
            matching_item.__dict__.update(self.new_dict)
            matching_item.update()

    def undo(self):
        matching_item = self._get_item(self.new_item_prp)
        if matching_item:
            matching_item.set_text(self.old_html, self.old_item_prp.width)
            matching_item.__dict__.update(self.old_dict)
            matching_item.update()