"""Run with: QT_QPA_PLATFORM=offscreen uv run --locked python scripts/benchmark_refresh.py"""

import argparse
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter

from PySide6.QtWidgets import QApplication

from powerlog.aida64 import Sensor
from powerlog.controller import Controller
from powerlog.storage import Recorder, Settings, Store, day_bounds
from powerlog.ui import MainWindow


def main():
    parser = argparse.ArgumentParser(
        description="Benchmark refreshes using minute-resolution history"
    )
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    if args.days < 1:
        parser.error("--days must be positive")
    app = QApplication([])
    now = datetime.now().astimezone()
    count = args.days * 24 * 60
    start = now.timestamp() - count * 60
    with tempfile.TemporaryDirectory(prefix="powerlog-benchmark-") as directory:
        store = Store(Path(directory) / "benchmark.sqlite3")
        settings = Settings(("CPU",))
        store.save_settings(settings)
        with store.db:
            store.db.executemany(
                "INSERT INTO samples VALUES (?,100,?,?)",
                ((start + i * 60, '{"CPU":100}', settings.signature) for i in range(count)),
            )
            store.db.executemany(
                "INSERT INTO intervals VALUES (?,?,100,100)",
                ((start + i * 60, start + (i + 1) * 60) for i in range(count - 1)),
            )
        ctrl = Controller(store, None, lambda: now)
        window = MainWindow(ctrl)
        window.period = 30
        started = perf_counter()
        window.show()
        app.processEvents()
        cold_ms = (perf_counter() - started) * 1000

        def measure(hidden, changed):
            if hidden:
                window.hide()
            if changed:
                Recorder(store).record([Sensor("CPU", "CPU", 100)], now)
            queries = []
            store.db.set_trace_callback(queries.append)
            started = perf_counter()
            window.refresh()
            elapsed = (perf_counter() - started) * 1000
            store.db.set_trace_callback(None)
            return {"ms": round(elapsed, 3), "sql_statements": len(queries)}

        old_day = now.date() - timedelta(days=args.days - 1)
        lower, upper = day_bounds(old_day)
        query_plan = store.db.execute(
            "EXPLAIN QUERY PLAN SELECT start,end,w0,w1 FROM intervals WHERE start>=? AND start<?",
            (lower - 90, upper),
        ).fetchall()
        print(
            json.dumps(
                {
                    "days": args.days,
                    "samples": count,
                    "cold_render_ms": round(cold_ms, 3),
                    "visible_unchanged": measure(False, False),
                    "visible_new_sample": measure(False, True),
                    "hidden_unchanged": measure(True, False),
                    "old_day_query_plan": query_plan,
                },
                indent=2,
            )
        )
        window.quitting = True
        window.close()
        ctrl.stop()
        store.close()


if __name__ == "__main__":
    main()
