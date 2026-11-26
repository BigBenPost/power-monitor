import ctypes
import sys
import threading
from datetime import UTC, datetime, timedelta

import pytest

from powerlog.aida64 import Sensor
from powerlog.controller import Controller, Snapshot
from powerlog.power_events import PowerEventFilter
from powerlog.storage import Settings, Store

SENSORS = [Sensor("CPU", "CPU", 100)]


class Clock:
    def __init__(self):
        self.wall = datetime(2026, 11, 26, 23, 59, tzinfo=UTC)
        self.tick = 0.0

    def advance(self, seconds, elapsed=None):
        self.wall += timedelta(seconds=seconds)
        self.tick += seconds if elapsed is None else elapsed


class Source:
    def read(self):
        return SENSORS


@pytest.fixture
def controller(qtbot, tmp_path):
    store = Store(tmp_path / "controller.sqlite3")
    store.save_settings(Settings(("CPU",)))
    clock = Clock()
    ctrl = Controller(store, Source(), lambda: clock.wall, lambda: clock.tick)
    yield ctrl, clock
    ctrl.stop()
    qtbot.waitUntil(lambda: ctrl.worker is None)
    store.close()


def snapshot(ctrl, clock, *, error=""):
    return Snapshot(SENSORS, error, clock.wall, clock.tick, ctrl.generation)


def test_delayed_thread_delivery_uses_capture_time_and_correct_day(controller, qtbot):
    ctrl, clock = controller
    ctrl.receive(snapshot(ctrl, clock))
    clock.advance(30)
    ctrl.poll()
    assert ctrl.worker.wait(5000)  # Leave the result queued in the GUI thread.
    captured = clock.wall
    clock.advance(50)
    qtbot.waitUntil(lambda: ctrl.worker is None)
    assert ctrl.reading.timestamp == captured.timestamp()
    assert ctrl.is_fresh()
    before = ctrl.store.daily(captured.date(), UTC)
    after = ctrl.store.daily(clock.wall.date(), UTC)
    assert before.recorded_seconds == 30
    assert before.kwh == pytest.approx(100 * 30 / 3600000)
    assert after.recorded_seconds == 0


def test_expired_queued_result_breaks_chain(controller):
    ctrl, clock = controller
    ctrl.receive(snapshot(ctrl, clock))
    clock.advance(60)
    queued = snapshot(ctrl, clock)
    clock.advance(91)
    ctrl.receive(queued)
    assert ctrl.reading is None
    assert ctrl.recorder.previous is None
    assert "过期" in ctrl.error
    assert ctrl.store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1


@pytest.mark.parametrize("wall,elapsed", [(30, 60), (80, 60), (60, 100)])
def test_clock_discontinuity_does_not_bridge_intervals(controller, wall, elapsed):
    ctrl, clock = controller
    ctrl.receive(snapshot(ctrl, clock))
    clock.advance(wall, elapsed)
    ctrl.receive(snapshot(ctrl, clock))
    assert ctrl.store.db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0] == 0
    clock.advance(60)
    ctrl.receive(snapshot(ctrl, clock))
    assert ctrl.store.db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0] == 1


@pytest.mark.parametrize("sleep_seconds", [10, 3600])
def test_suspend_discards_inflight_results_and_restarts_chain(
    controller, monkeypatch, sleep_seconds
):
    ctrl, clock = controller
    ctrl.receive(snapshot(ctrl, clock))
    old = snapshot(ctrl, clock)
    ctrl.suspend()
    clock.advance(sleep_seconds)
    ctrl.receive(old)
    monkeypatch.setattr(ctrl, "poll", lambda: None)
    ctrl.resume()
    ctrl.receive(old)
    assert ctrl.reading is None
    ctrl.receive(snapshot(ctrl, clock))
    assert ctrl.store.db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0] == 0
    clock.advance(60)
    ctrl.receive(snapshot(ctrl, clock))
    assert ctrl.store.db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0] == 1


def test_settings_change_discards_inflight_read_and_polls_again(controller, qtbot):
    ctrl, clock = controller
    release = threading.Event()

    class BlockingSource:
        def read(self):
            assert release.wait(5)
            return SENSORS

    ctrl.source = BlockingSource()
    ctrl.poll()
    try:
        ctrl.store.save_settings(Settings(("CPU",), overhead_watts=25))
        ctrl.reset_sampling()
        ctrl.poll()
    finally:
        release.set()
    qtbot.waitUntil(lambda: ctrl.worker is None and ctrl.reading is not None, timeout=5000)
    assert ctrl.reading.watts == 125
    assert ctrl.store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1
    assert ctrl.store.db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0] == 0


def test_read_and_write_failures_break_chain_and_recover(controller):
    ctrl, clock = controller
    ctrl.receive(snapshot(ctrl, clock))
    clock.advance(60)
    ctrl.receive(snapshot(ctrl, clock, error="AIDA64 unavailable"))
    assert not ctrl.connected
    assert ctrl.recorder.previous is None
    ctrl.store.db.execute("PRAGMA query_only=ON")
    clock.advance(60)
    ctrl.receive(snapshot(ctrl, clock))
    assert ctrl.reading is None
    assert ctrl.error
    ctrl.store.db.execute("PRAGMA query_only=OFF")
    clock.advance(60)
    ctrl.receive(snapshot(ctrl, clock))
    assert ctrl.is_fresh()
    assert ctrl.store.db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0] == 0


def test_wall_clock_change_invalidates_live_reading(controller):
    ctrl, clock = controller
    ctrl.receive(snapshot(ctrl, clock))
    clock.advance(10, 30)
    assert not ctrl.is_fresh()


def test_stop_ignores_already_queued_result(controller, qtbot):
    ctrl, clock = controller
    ctrl.poll()
    assert ctrl.worker.wait(5000)
    ctrl.stop()
    qtbot.waitUntil(lambda: ctrl.worker is None)
    assert ctrl.reading is None


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 message layout")
def test_native_power_messages(controller, monkeypatch):
    from ctypes import wintypes

    ctrl, clock = controller
    monkeypatch.setattr(ctrl, "poll", lambda: None)
    events = PowerEventFilter(ctrl)
    msg = wintypes.MSG()
    msg.message = 0x0218
    msg.wParam = 4
    events.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
    assert ctrl.suspended
    msg.wParam = 18
    events.nativeEventFilter(b"windows_generic_MSG", ctypes.addressof(msg))
    assert not ctrl.suspended
    assert ctrl.generation == 2
