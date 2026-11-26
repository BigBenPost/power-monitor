import csv
from datetime import timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QSystemTrayIcon

from powerlog.aida64 import Sensor
from powerlog.controller import Controller
from powerlog.demo import DemoSource
from powerlog.storage import Store
from powerlog.ui import MainWindow


@pytest.fixture
def window(qtbot, qapp, tmp_path, monkeypatch):
    qapp.setFont(QFont("Noto Sans CJK SC", 10))
    qapp.setStyle("Fusion")
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    store = Store(tmp_path / "demo.sqlite3")
    source = DemoSource(store)
    ctrl = Controller(store, source, source.clock)
    result = MainWindow(ctrl, demo=True)
    qtbot.addWidget(result)
    result.show()
    with qtbot.waitSignal(ctrl.updated, timeout=5000):
        ctrl.start()
    yield result
    result.settings_page.dirty = False
    result.quitting = True
    ctrl.stop()
    qtbot.waitUntil(lambda: ctrl.worker is None, timeout=5000)
    result.close()
    store.close()


def test_navigation_and_chart_date_selection(window, qtbot):
    assert window.energy_label.text() != "—"
    assert "W" in window.power_label.text()
    qtbot.mouseClick(window.nav_buttons[1], Qt.MouseButton.LeftButton)
    assert window.pages.currentIndex() == 1
    previous = window.ctrl.clock().date() - timedelta(days=2)
    window.open_history(previous)
    assert window.history_chart.day == previous
    assert len(window.history_chart.points) > 0
    window.show_page(0)
    qtbot.mouseClick(window.period_buttons[1], Qt.MouseButton.LeftButton)
    assert len(window.bars.days) == 30


def test_save_sensor_choices_tariff_overhead_and_preserve_draft(window, qtbot):
    window.show_page(2)
    page = window.settings_page
    row = page.ids.index("PCPUCORE1")
    page.sensors_table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    page.tariff.setValue(0.85)
    page.overhead.setValue(25)
    window.refresh()
    assert "PCPUCORE1" in page.checked_ids()
    assert page.tariff.value() == 0.85
    with qtbot.waitSignal(window.ctrl.updated, timeout=5000):
        qtbot.mouseClick(page.save_button, Qt.MouseButton.LeftButton)
    saved = window.ctrl.store.load_settings()
    assert saved.tariff == 0.85
    assert saved.overhead_watts == 25
    assert "PCPUCORE1" in saved.sensor_ids
    assert not page.dirty


def test_read_failure_clears_live_power_and_keeps_history(window, qtbot):
    qtbot.waitUntil(lambda: window.ctrl.worker is None)
    total = window.energy_label.text()
    window.ctrl.receive([], "AIDA64 未启动")
    assert window.power_label.text() == "— W"
    assert window.energy_label.text() == total
    assert window.notice.isVisible()
    assert "未启动" in window.notice_label.text()
    assert window.ctrl.recorder.previous is None


def test_csv_exports_measured_data_and_empty_days(window, tmp_path):
    path = tmp_path / "energy.csv"
    window.write_csv(path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.reader(stream))
    assert len(rows) == 31
    assert rows[1][1] == ""
    today = window.ctrl.store.daily(window.ctrl.clock().date())
    assert float(rows[-1][1]) == pytest.approx(today.kwh, abs=1e-6)
    assert float(rows[-1][2]) == pytest.approx(today.kwh * 0.6, abs=1e-4)


def test_no_exported_power_has_clear_empty_state(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    store = Store(tmp_path / "empty.sqlite3")
    ctrl = Controller(store, None)
    win = MainWindow(ctrl)
    qtbot.addWidget(win)
    try:
        win.show()
        ctrl.receive([Sensor("CPU", "CPU Package", 50)], "")
        assert win.energy_label.text() == "—"
        assert "选择" in win.notice_label.text()
        assert win.settings_page.ids == ["CPU"]
        assert win.settings_page.checked_ids() == ()
    finally:
        win.quitting = True
        win.close()
        store.close()


@pytest.mark.parametrize("width,height", [(1000, 740), (1280, 910), (1600, 1050)])
def test_pages_render_at_supported_window_sizes(window, qtbot, width, height):
    window.resize(width, height)
    for index in range(3):
        window.show_page(index)
        qtbot.wait(10)
        image = window.grab().toImage()
        assert not image.isNull()
        scroll = window.pages.currentWidget()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert window.width() == width


def test_stale_reading_is_not_presented_as_live(window, qtbot):
    qtbot.waitUntil(lambda: window.ctrl.worker is None)
    then = window.ctrl.clock()
    window.ctrl.clock = lambda: then + timedelta(seconds=91)
    window.refresh()
    assert window.power_label.text() == "— W"
    assert window.notice.isVisible()
