"""Tests de `modules/cleaning/config.py` (specs/02, critic pass2 consignes 2/6/7)."""

from __future__ import annotations

import pytest

from modules.cleaning.apply import cleaning_config_from_settings_page
from modules.cleaning.config import INERT, UI_DEFAULTS, CleaningConfig, is_inert


def test_inert_values():
    assert INERT.uniform_fill is False
    assert INERT.protect_lines is False
    assert INERT.free_dilate_iterations == 3
    assert is_inert(INERT) is True


def test_ui_defaults_values():
    assert UI_DEFAULTS.uniform_fill is True
    assert UI_DEFAULTS.protect_lines is True
    assert UI_DEFAULTS.free_dilate_iterations == 3
    assert is_inert(UI_DEFAULTS) is False


def test_cleaning_config_from_settings_page_none_is_inert():
    assert cleaning_config_from_settings_page(None) == INERT


class _Widget:
    """Canard minimal pour `isChecked()` / `value()` (widgets Qt réels non requis)."""

    def __init__(self, checked: bool = False, value: int = 0):
        self._checked = checked
        self._value = value

    def isChecked(self) -> bool:
        return self._checked

    def value(self) -> int:
        return self._value


class _UI:
    def __init__(self, uniform_fill: bool, protect_lines: bool, margin: int):
        self.uniform_fill_checkbox = _Widget(checked=uniform_fill)
        self.protect_lines_checkbox = _Widget(checked=protect_lines)
        self.free_margin_spinbox = _Widget(value=margin)


class _SettingsPage:
    def __init__(self, ui: _UI):
        self.ui = ui


def test_cleaning_config_from_settings_page_duck_object():
    cfg = cleaning_config_from_settings_page(_SettingsPage(_UI(True, False, 5)))
    assert cfg == CleaningConfig(uniform_fill=True, protect_lines=False, free_dilate_iterations=5)


def test_cleaning_config_from_settings_page_missing_widgets_is_inert():
    class _EmptyUI:
        pass

    settings_page = _SettingsPage(_EmptyUI())
    assert cleaning_config_from_settings_page(settings_page) == INERT


def test_cleaning_config_from_settings_page_clamps_out_of_range_margin():
    cfg_high = cleaning_config_from_settings_page(_SettingsPage(_UI(True, True, 99)))
    cfg_low = cleaning_config_from_settings_page(_SettingsPage(_UI(True, True, -5)))
    assert cfg_high.free_dilate_iterations == 3
    assert cfg_low.free_dilate_iterations == 3


def test_config_rejects_even_line_length():
    with pytest.raises(ValueError):
        CleaningConfig(line_length=60)


def test_config_rejects_band_margin_too_small():
    with pytest.raises(ValueError):
        CleaningConfig(line_length=61, line_band_margin=10)
