from __future__ import annotations

import json
import math
import time
from datetime import datetime, timedelta

from powerlog.aida64 import Sensor
from powerlog.storage import Settings, Store


class DemoSource:
    def __init__(self, store: Store):
        self.started = time.monotonic()
        self.base = datetime.now().astimezone().replace(hour=18, minute=42, second=0, microsecond=0)
        settings = Settings(("PCPUPKG", "PGPU1"))
        store.save_settings(settings)
        if store.db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]:
            return
        samples, intervals = [], []
        for offset in reversed(range(7)):
            day = self.base - timedelta(days=offset)
            stamp = day.replace(hour=8, minute=0)
            end = day if offset == 0 else day.replace(hour=20, minute=0)
            previous = None
            while stamp <= end:
                minutes = (stamp - day.replace(hour=8, minute=0)).total_seconds() / 60
                watts = self.value(minutes, offset)
                components = {"PCPUPKG": round(watts / 3, 1), "PGPU1": round(watts * 2 / 3, 1)}
                ts = stamp.timestamp()
                samples.append((ts, watts, json.dumps(components), settings.signature))
                if previous:
                    intervals.append((previous[0], ts, previous[1], watts))
                previous = ts, watts
                stamp += timedelta(minutes=1)
        with store.db:
            store.db.executemany("INSERT INTO samples VALUES (?, ?, ?, ?)", samples)
            store.db.executemany("INSERT INTO intervals VALUES (?, ?, ?, ?)", intervals)

    @staticmethod
    def value(minutes, offset):
        return round(
            max(
                30,
                (
                    85
                    + 16 * math.sin(minutes / 26)
                    + 9 * math.sin(minutes / 5.7)
                    + 110 * math.exp(-(((minutes - 420) / 98) ** 2))
                    + 113 * math.exp(-(((minutes - 642) / 65) ** 2))
                )
                * (1 + 0.07 * math.sin(offset)),
            ),
            1,
        )

    def clock(self):
        return self.base + timedelta(seconds=time.monotonic() - self.started)

    def read(self):
        total = self.value(642 + (time.monotonic() - self.started) / 60, 0)
        cpu = round(total / 3, 1)
        return [
            Sensor("PCPUPKG", "CPU Package", cpu),
            Sensor("PGPU1", "GPU Power", round(total - cpu, 1)),
            Sensor("PCPUCORE1", "CPU Core #1", 14.5),
        ]
