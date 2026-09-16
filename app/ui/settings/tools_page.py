from PySide6 import QtWidgets
from ..dayu_widgets.label import MLabel
from ..dayu_widgets.check_box import MCheckBox
from ..dayu_widgets.spin_box import MSpinBox
from .utils import create_title_and_combo, set_combo_box_width
from modules.utils.device import is_gpu_available
from modules.cleaning import UI_DEFAULTS  # fork: source unique des valeurs par défaut (specs/02)

class ToolsPage(QtWidgets.QWidget):
    def __init__(
        self, 
        translators: list[str], 
        ocr_engines: list[str], 
        detectors: list[str],
        inpainters: list[str], 
        inpaint_strategy: list[str], 
        parent=None
    ):
        super().__init__(parent)
        self.translators = translators
        self.ocr_engines = ocr_engines
        self.detectors = detectors
        self.inpainters = inpainters
        self.inpaint_strategy = inpaint_strategy

        layout = QtWidgets.QVBoxLayout(self)

        translator_widget, self.translator_combo = create_title_and_combo(self.tr("Translator"), self.translators, h4=True)
        set_combo_box_width(self.translator_combo, self.translators)

        ocr_widget, self.ocr_combo = create_title_and_combo(self.tr("OCR"), self.ocr_engines, h4=True)
        set_combo_box_width(self.ocr_combo, self.ocr_engines)

        detector_widget, self.detector_combo = create_title_and_combo(self.tr("Text Detector"), self.detectors, h4=True)
        set_combo_box_width(self.detector_combo, self.detectors)

        inpainting_label = MLabel(self.tr("Image Cleaning")).h4()
        inpainter_widget, self.inpainter_combo = create_title_and_combo(self.tr("Inpainter"), self.inpainters, h4=False)
        set_combo_box_width(self.inpainter_combo, self.inpainters)
        self.inpainter_combo.setCurrentText(self.tr("AOT"))

        inpaint_strategy_widget, self.inpaint_strategy_combo = create_title_and_combo(self.tr("HD Strategy"), self.inpaint_strategy, h4=False)
        set_combo_box_width(self.inpaint_strategy_combo, self.inpaint_strategy)
        self.inpaint_strategy_combo.setCurrentText(self.tr("Resize"))

        # HD Strategy detail widgets
        self.hd_strategy_widgets = QtWidgets.QWidget()
        self.hd_strategy_layout = QtWidgets.QVBoxLayout(self.hd_strategy_widgets)

        # Resize panel
        self.resize_widget = QtWidgets.QWidget()
        about_resize_layout = QtWidgets.QVBoxLayout(self.resize_widget)
        resize_layout = QtWidgets.QHBoxLayout()
        resize_label = MLabel(self.tr("Resize Limit:"))
        about_resize_label = MLabel(self.tr("Resize the longer side of the image to a specific size,\nthen do inpainting on the resized image."))
        self.resize_spinbox = MSpinBox().small()
        self.resize_spinbox.setFixedWidth(70)
        self.resize_spinbox.setMaximum(3000)
        self.resize_spinbox.setValue(960)
        resize_layout.addWidget(resize_label)
        resize_layout.addWidget(self.resize_spinbox)
        resize_layout.addStretch()
        about_resize_layout.addWidget(about_resize_label)
        about_resize_layout.addLayout(resize_layout)
        about_resize_layout.setContentsMargins(5, 5, 5, 5)
        about_resize_layout.addStretch()

        # Crop panel
        self.crop_widget = QtWidgets.QWidget()
        crop_layout = QtWidgets.QVBoxLayout(self.crop_widget)
        about_crop_label = MLabel(self.tr("Crop masking area from the original image to do inpainting."))
        crop_margin_layout = QtWidgets.QHBoxLayout()
        crop_margin_label = MLabel(self.tr("Crop Margin:"))
        self.crop_margin_spinbox = MSpinBox().small()
        self.crop_margin_spinbox.setFixedWidth(70)
        self.crop_margin_spinbox.setMaximum(3000)
        self.crop_margin_spinbox.setValue(512)
        crop_margin_layout.addWidget(crop_margin_label)
        crop_margin_layout.addWidget(self.crop_margin_spinbox)
        crop_margin_layout.addStretch()

        crop_trigger_layout = QtWidgets.QHBoxLayout()
        crop_trigger_label = MLabel(self.tr("Crop Trigger Size:"))
        self.crop_trigger_spinbox = MSpinBox().small()
        self.crop_trigger_spinbox.setFixedWidth(70)
        self.crop_trigger_spinbox.setMaximum(3000)
        self.crop_trigger_spinbox.setValue(512)
        crop_trigger_layout.addWidget(crop_trigger_label)
        crop_trigger_layout.addWidget(self.crop_trigger_spinbox)
        crop_trigger_layout.addStretch()

        crop_layout.addWidget(about_crop_label)
        crop_layout.addLayout(crop_margin_layout)
        crop_layout.addLayout(crop_trigger_layout)
        crop_layout.setContentsMargins(5, 5, 5, 5)

        self.hd_strategy_layout.addWidget(self.resize_widget)
        self.hd_strategy_layout.addWidget(self.crop_widget)

        self.resize_widget.show()
        self.crop_widget.hide()
        self.inpaint_strategy_combo.currentIndexChanged.connect(self._update_hd_strategy_widgets)


        self.use_gpu_checkbox = MCheckBox(self.tr("Use GPU"))
        if not is_gpu_available():
            self.use_gpu_checkbox.setVisible(False)

        # fork: réglages du nettoyage additionnel (specs/02-nettoyage-legendes.md)
        # Défauts et bornes tirés de UI_DEFAULTS (source unique, modules/cleaning/config.py).
        self.uniform_fill_checkbox = MCheckBox(self.tr("Automatic flat fill"))
        self.uniform_fill_checkbox.setChecked(UI_DEFAULTS.uniform_fill)
        self.uniform_fill_checkbox.setToolTip(
            self.tr(
                "Fills a caption's surroundings with a flat color instead of "
                "running the neural inpainter, when the area right around the "
                "text is uniform enough."
            )
        )

        self.protect_lines_checkbox = MCheckBox(
            self.tr("Protect thin straight lines (panel borders)")
        )
        self.protect_lines_checkbox.setChecked(UI_DEFAULTS.protect_lines)
        self.protect_lines_checkbox.setToolTip(
            self.tr(
                "Removes long thin dark lines from the cleaning mask (panel "
                "borders, frames). Does not detect panels."
            )
        )

        free_margin_layout = QtWidgets.QHBoxLayout()
        free_margin_label = MLabel(self.tr("Margin around free text (iterations)"))
        self.free_margin_spinbox = MSpinBox().small()
        self.free_margin_spinbox.setFixedWidth(70)
        self.free_margin_spinbox.setMinimum(0)
        self.free_margin_spinbox.setMaximum(6)
        self.free_margin_spinbox.setValue(UI_DEFAULTS.free_dilate_iterations)
        free_margin_layout.addWidget(free_margin_label)
        free_margin_layout.addWidget(self.free_margin_spinbox)
        free_margin_layout.addStretch()

        self.cleaning_widgets = QtWidgets.QWidget()
        cleaning_layout = QtWidgets.QVBoxLayout(self.cleaning_widgets)
        cleaning_layout.setContentsMargins(5, 5, 5, 5)
        cleaning_layout.addWidget(self.uniform_fill_checkbox)
        cleaning_layout.addWidget(self.protect_lines_checkbox)
        cleaning_layout.addLayout(free_margin_layout)

        layout.addWidget(translator_widget)
        layout.addSpacing(10)
        layout.addWidget(detector_widget)
        layout.addSpacing(10)
        layout.addWidget(ocr_widget)
        layout.addSpacing(10)
        layout.addWidget(inpainting_label)
        layout.addWidget(inpainter_widget)
        layout.addWidget(inpaint_strategy_widget)
        layout.addWidget(self.hd_strategy_widgets)
        layout.addSpacing(10)
        layout.addWidget(self.cleaning_widgets)  # fork
        layout.addSpacing(10)
        layout.addWidget(self.use_gpu_checkbox)
        layout.addStretch(1)

        self._update_hd_strategy_widgets(self.inpaint_strategy_combo.currentIndex())

    def _update_hd_strategy_widgets(self, index: int):
        strategy = self.inpaint_strategy_combo.itemText(index)
        self.resize_widget.setVisible(strategy == self.tr("Resize"))
        self.crop_widget.setVisible(strategy == self.tr("Crop"))
        if strategy == self.tr("Original"):
            self.hd_strategy_widgets.setFixedHeight(0)
        else:
            self.hd_strategy_widgets.setFixedHeight(self.hd_strategy_widgets.sizeHint().height())
