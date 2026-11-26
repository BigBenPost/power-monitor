import sqlite3
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from powerlog.aida64 import Sensor, SourceError
from powerlog.storage import Recorder, Settings, Store, day_bounds


@pytest.fixture
def store(tmp_path):
    result = Store(tmp_path / "powerlog.sqlite3")
    result.save_settings(Settings(("CPU",)))
    yield result
    result.close()


def test_one_hour_constant_power(store):
    recorder = Recorder(store)
    start = datetime(2026, 11, 18, 8, tzinfo=UTC)
    for minute in range(61):
        recorder.record([Sensor("CPU", "CPU", 100)], start + timedelta(minutes=minute))
    total = store.daily(start.date(), UTC)
    assert total.kwh == pytest.approx(0.1)
    assert total.recorded_seconds == 3600
    assert total.peak_watts == 100


def test_variable_power_and_midnight_split(store):
    recorder = Recorder(store)
    start = datetime(2026, 11, 18, 23, 59, 30, tzinfo=UTC)
    recorder.record([Sensor("CPU", "CPU", 0)], start)
    recorder.record([Sensor("CPU", "CPU", 120)], start + timedelta(minutes=1))
    before = store.daily(start.date(), UTC)
    after = store.daily(start.date() + timedelta(days=1), UTC)
    assert before.kwh == pytest.approx(0.00025)
    assert after.kwh == pytest.approx(0.00075)
    assert before.recorded_seconds == after.recorded_seconds == 30
    assert before.kwh + after.kwh == pytest.approx(0.001)


@pytest.mark.parametrize("gap", [91, 3600, 86400])
def test_sleep_gaps_are_not_billed(store, gap):
    recorder = Recorder(store)
    start = datetime(2026, 11, 18, 8, tzinfo=UTC)
    sensors = [Sensor("CPU", "CPU", 100)]
    recorder.record(sensors, start)
    recorder.record(sensors, start + timedelta(seconds=gap))
    assert store.db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0] == 0
    recorder.record(sensors, start + timedelta(seconds=gap + 60))
    assert store.db.execute("SELECT COUNT(*) FROM intervals").fetchone()[0] == 1


def test_missing_selected_sensor_never_uses_partial_total(store):
    store.save_settings(Settings(("CPU", "GPU")))
    recorder = Recorder(store)
    now = datetime(2026, 11, 18, 8, tzinfo=UTC)
    both = [Sensor("CPU", "CPU", 50), Sensor("GPU", "GPU", 150)]
    recorder.record(both, now)
    with pytest.raises(SourceError, match="GPU"):
        recorder.record(both[:1], now + timedelta(minutes=1))
    recorder.record(both, now + timedelta(minutes=2))
    assert store.daily(now.date(), UTC).recorded_seconds == 0
    assert store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 2


def test_manual_break_failure_and_config_change_do_not_bridge(store):
    recorder = Recorder(store)
    now = datetime(2026, 11, 18, 8, tzinfo=UTC)
    sensors = [Sensor("CPU", "CPU", 60)]
    recorder.record(sensors, now)
    recorder.break_chain()
    recorder.record(sensors, now + timedelta(minutes=1))
    store.save_settings(Settings(("CPU",), overhead_watts=40))
    recorder.record(sensors, now + timedelta(minutes=2))
    recorder.record(sensors, now + timedelta(minutes=3))
    total = store.daily(now.date(), UTC)
    assert total.recorded_seconds == 60
    assert total.kwh == pytest.approx(100 / 60000)


def test_tariff_change_and_id_reorder_do_not_break_energy(store):
    recorder = Recorder(store)
    now = datetime(2026, 11, 18, 8, tzinfo=UTC)
    store.save_settings(Settings(("CPU", "GPU"), tariff=0.6))
    sensors = [Sensor("CPU", "CPU", 60), Sensor("GPU", "GPU", 40)]
    recorder.record(sensors, now)
    store.save_settings(Settings(("GPU", "CPU"), tariff=1.2))
    recorder.record(sensors, now + timedelta(seconds=60))
    assert store.daily(now.date(), UTC).recorded_seconds == 60


def test_restart_retains_history_but_does_not_fill_downtime(tmp_path):
    path = tmp_path / "history.sqlite3"
    now = datetime(2026, 11, 18, 8, tzinfo=UTC)
    sensors = [Sensor("CPU", "CPU", 100)]
    with_store = Store(path)
    with_store.save_settings(Settings(("CPU",)))
    first = Recorder(with_store)
    first.record(sensors, now)
    first.record(sensors, now + timedelta(minutes=1))
    with_store.close()
    reopened = Store(path)
    try:
        Recorder(reopened).record(sensors, now + timedelta(minutes=2))
        assert reopened.daily(now.date(), UTC).recorded_seconds == 60
        assert reopened.load_settings().sensor_ids == ("CPU",)
    finally:
        reopened.close()


def test_clock_rollback_cannot_double_count_even_after_reset(store):
    sensors = [Sensor("CPU", "CPU", 100)]
    now = datetime(2026, 11, 18, 8, tzinfo=UTC)
    recorder = Recorder(store)
    recorder.record(sensors, now)
    recorder.record(sensors, now + timedelta(minutes=1))
    with pytest.raises(SourceError):
        recorder.record(sensors, now - timedelta(minutes=2))
    recorder = Recorder(store)
    with pytest.raises(SourceError):
        recorder.record(sensors, now + timedelta(seconds=30))
    recorder.record(sensors, now + timedelta(minutes=2))
    assert store.daily(now.date(), UTC).recorded_seconds == 60


def test_zero_power_is_valid_but_no_sensor_selection_is_not(store):
    recorder = Recorder(store)
    now = datetime(2026, 11, 18, 8, tzinfo=UTC)
    recorder.record([Sensor("CPU", "CPU", 0)], now)
    recorder.record([Sensor("CPU", "CPU", 0)], now + timedelta(seconds=60))
    assert store.daily(now.date(), UTC).kwh == 0
    assert store.daily(now.date(), UTC).recorded_seconds == 60
    store.save_settings(Settings())
    with pytest.raises(SourceError, match="选择"):
        recorder.record([Sensor("CPU", "CPU", 100)], now + timedelta(minutes=2))


@pytest.mark.parametrize("watts", [-1, float("inf"), float("nan")])
def test_invalid_power_does_not_enter_database(store, watts):
    with pytest.raises(SourceError):
        Recorder(store).record([Sensor("CPU", "CPU", watts)], datetime.now(UTC))
    assert store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0


@pytest.mark.parametrize("day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25)])
def test_dst_local_day_boundaries(day, hours):
    lower, upper = day_bounds(day, ZoneInfo("America/New_York"))
    assert upper - lower == hours * 3600


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sensor_ids": ("CPU", "CPU")},
        {"tariff": -1},
        {"tariff": float("nan")},
        {"overhead_watts": float("inf")},
        {"overhead_watts": -1},
    ],
)
def test_invalid_settings_rejected(kwargs):
    with pytest.raises(ValueError):
        Settings(**kwargs)


def test_newer_database_is_preserved(tmp_path):
    path = tmp_path / "future.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=42")
    with pytest.raises(ValueError, match="升级"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 42


def test_overflowing_total_does_not_enter_database(store):
    store.save_settings(Settings(("CPU", "GPU")))
    with pytest.raises(SourceError, match="合计"):
        Recorder(store).record(
            [Sensor("CPU", "CPU", 1e308), Sensor("GPU", "GPU", 1e308)], datetime.now(UTC)
        )
    assert store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 0


def test_signature_normalizes_equivalent_numeric_overhead():
    assert (
        Settings(("CPU",), overhead_watts=0).signature
        == Settings(("CPU",), overhead_watts=0.0).signature
    )


def test_daily_cache_invalidates_both_sides_of_midnight_and_timezone(store):
    recorder = Recorder(store)
    start = datetime(2026, 11, 18, 23, 59, 30, tzinfo=UTC)
    next_day = start.date() + timedelta(days=1)
    tokyo = ZoneInfo("Asia/Tokyo")
    assert store.daily(start.date(), UTC).kwh == 0
    assert store.daily(next_day, UTC).kwh == 0
    assert store.daily(next_day, tokyo).kwh == 0
    sensors = [Sensor("CPU", "CPU", 100)]
    recorder.record(sensors, start)
    recorder.record(sensors, start + timedelta(seconds=60))
    assert store.daily(start.date(), UTC).recorded_seconds == 30
    assert store.daily(next_day, UTC).recorded_seconds == 30
    assert store.daily(next_day, tokyo).recorded_seconds == 60
    queries = []
    store.db.set_trace_callback(queries.append)
    store.daily(start.date(), UTC)
    store.daily(next_day, UTC)
    store.daily(next_day, tokyo)
    store.db.set_trace_callback(None)
    assert queries == []


def test_failed_interval_insert_rolls_back_sample_and_recovers(store):
    recorder = Recorder(store)
    start = datetime(2026, 11, 18, 8, tzinfo=UTC)
    sensors = [Sensor("CPU", "CPU", 100)]
    recorder.record(sensors, start)
    store.db.execute("""CREATE TRIGGER fail_interval BEFORE INSERT ON intervals
                        BEGIN SELECT RAISE(FAIL, 'test interval failure'); END""")
    with pytest.raises(sqlite3.Error, match="interval failure"):
        recorder.record(sensors, start + timedelta(seconds=60))
    assert store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == 1
    assert recorder.previous is None
    assert store.daily(start.date(), UTC).recorded_seconds == 0
    store.db.execute("DROP TRIGGER fail_interval")
    recorder.record(sensors, start + timedelta(seconds=120))
    assert store.daily(start.date(), UTC).recorded_seconds == 0
    recorder.record(sensors, start + timedelta(seconds=180))
    assert store.daily(start.date(), UTC).recorded_seconds == 60


def test_initialization_failure_closes_connection(tmp_path, monkeypatch):
    path = tmp_path / "broken.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE intervals (incompatible TEXT)")
    connect = sqlite3.connect
    connections = []

    def track(*args, **kwargs):
        db = connect(*args, **kwargs)
        connections.append(db)
        return db

    monkeypatch.setattr("powerlog.storage.sqlite3.connect", track)
    with pytest.raises(sqlite3.Error):
        Store(path)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[0].execute("SELECT 1")
