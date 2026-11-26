from datetime import UTC, datetime, timedelta

from powerlog.demo import DemoSource
from powerlog.storage import Recorder, Settings, Store


def test_reopen_demo_preserves_settings_and_advances_past_latest(tmp_path):
    path = tmp_path / "demo.sqlite3"
    now = datetime(2026, 11, 26, 18, 42, tzinfo=UTC)
    store = Store(path)
    source = DemoSource(store, now=now)
    last = now + timedelta(minutes=10)
    Recorder(store).record(source.read(), last)
    settings = Settings(("PCPUPKG",), tariff=0.9, overhead_watts=10, close_to_tray=False)
    store.save_settings(settings)
    count = store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    store.close()
    store = Store(path)
    try:
        source = DemoSource(store, now=now)
        assert store.load_settings() == settings
        assert source.base.timestamp() == last.timestamp() + 60
        assert store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == count
        reading = Recorder(store).record(source.read(), source.clock())
        assert reading.timestamp > last.timestamp()
        assert reading.components["__overhead__"] == 10
    finally:
        store.close()
