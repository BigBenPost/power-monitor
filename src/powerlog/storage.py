from __future__ import annotations

import json
import math
import sqlite3
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path

from powerlog.aida64 import Sensor, SourceError

SAMPLE_SECONDS = 60
MAX_GAP_SECONDS = 90


@dataclass(frozen=True)
class Settings:
    sensor_ids: tuple[str, ...] = ()
    tariff: float = 0.6
    overhead_watts: float = 0
    close_to_tray: bool = True

    def __post_init__(self):
        if not all(isinstance(key, str) and key for key in self.sensor_ids):
            raise ValueError("传感器 ID 无效。")
        if len(set(self.sensor_ids)) != len(self.sensor_ids):
            raise ValueError("传感器 ID 重复。")
        if not math.isfinite(self.tariff) or not 0 <= self.tariff <= 100:
            raise ValueError("电价必须在 0–100 元 / kWh 之间。")
        if not math.isfinite(self.overhead_watts) or not 0 <= self.overhead_watts <= 10000:
            raise ValueError("额外功率必须在 0–10000 W 之间。")

    @property
    def signature(self) -> str:
        return json.dumps(
            [sorted(self.sensor_ids), float(self.overhead_watts)], separators=(",", ":")
        )


@dataclass(frozen=True)
class Reading:
    timestamp: float
    watts: float
    components: dict[str, float]
    signature: str


@dataclass(frozen=True)
class DayTotal:
    day: date
    kwh: float
    recorded_seconds: float
    peak_watts: float


def day_bounds(day: date, zone: tzinfo | None = None) -> tuple[float, float]:
    # Resolve each local midnight separately so DST days can be 23 or 25 hours.
    return tuple(
        datetime.combine(day + timedelta(days=i), time.min, tzinfo=zone).astimezone(UTC).timestamp()
        for i in (0, 1)
    )


def clipped_energy(
    start: float, end: float, w0: float, w1: float, lower: float, upper: float
) -> tuple[float, float]:
    a, b = max(start, lower), min(end, upper)
    if b <= a or end <= start:
        return 0, 0
    left = w0 + (w1 - w0) * (a - start) / (end - start)
    right = w0 + (w1 - w0) * (b - start) / (end - start)
    return (left + right) / 2 * (b - a) / 3_600_000, b - a


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path, timeout=5)
        try:
            self._initialize()
        except Exception:
            self.db.close()
            raise
        self._daily_cache = OrderedDict()
        self._cache_changes = self.db.total_changes

    @property
    def revision(self):
        return self.db.total_changes

    def _initialize(self):
        if self.db.execute("PRAGMA user_version").fetchone()[0] > 1:
            raise ValueError("此数据文件来自更新版本的 Powerlog，请先升级程序。")
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS samples (
                ts REAL PRIMARY KEY, watts REAL NOT NULL, components TEXT NOT NULL,
                signature TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS intervals (
                start REAL PRIMARY KEY, end REAL NOT NULL,
                w0 REAL NOT NULL, w1 REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS intervals_end ON intervals(end);
            PRAGMA user_version=1;
        """)

    def close(self):
        self.db.close()

    def load_settings(self) -> Settings:
        row = self.db.execute("SELECT value FROM settings WHERE key='preferences'").fetchone()
        if not row:
            return Settings()
        try:
            data = json.loads(row[0])
            if not isinstance(data, dict) or not isinstance(data.get("sensor_ids", []), list):
                raise ValueError("偏好设置格式无效。")
            data["sensor_ids"] = tuple(data.get("sensor_ids", ()))
            return Settings(**data)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("无法读取偏好设置，请保留数据文件并检查设置。") from exc

    def save_settings(self, settings: Settings):
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES ('preferences', ?)",
                (json.dumps(asdict(settings)),),
            )

    def append(self, current: Reading, previous: Reading | None):
        self._check_cache()
        linked = (
            previous is not None
            and current.signature == previous.signature
            and 0 < current.timestamp - previous.timestamp <= MAX_GAP_SECONDS
        )
        with self.db:
            latest = self.db.execute("SELECT MAX(ts) FROM samples").fetchone()[0]
            if latest is not None and current.timestamp <= latest:
                raise SourceError("系统时间早于已有记录，暂停累计以避免重复计算。")
            self.db.execute(
                "INSERT INTO samples VALUES (?, ?, ?, ?)",
                (
                    current.timestamp,
                    current.watts,
                    json.dumps(current.components),
                    current.signature,
                ),
            )
            if linked:
                self.db.execute(
                    "INSERT INTO intervals VALUES (?, ?, ?, ?)",
                    (
                        previous.timestamp,
                        current.timestamp,
                        previous.watts,
                        current.watts,
                    ),
                )
        # Preserve historical totals; invalidate every local day touched by the new data.
        start = previous.timestamp if linked else current.timestamp
        for key in list(self._daily_cache):
            _, lower, upper = key
            if start < upper and current.timestamp >= lower:
                del self._daily_cache[key]
        self._cache_changes = self.db.total_changes

    def _check_cache(self):
        # Also cover writes made directly on this connection, e.g. demo initialization.
        if self._cache_changes != self.db.total_changes:
            self._daily_cache.clear()
            self._cache_changes = self.db.total_changes

    def daily(self, day: date, zone: tzinfo | None = None) -> DayTotal:
        lower, upper = day_bounds(day, zone)
        self._check_cache()
        key = (day, lower, upper)
        if key in self._daily_cache:
            self._daily_cache.move_to_end(key)
            return self._daily_cache[key]
        # All persisted intervals are at most MAX_GAP_SECONDS long. Bound their
        # start times so old-day queries do not scan every later record.
        rows = self.db.execute(
            "SELECT start, end, w0, w1 FROM intervals WHERE start >= ? AND start < ?",
            (lower - MAX_GAP_SECONDS, upper),
        )
        kwh, seconds = 0.0, 0.0
        for start, end, w0, w1 in rows:
            energy, elapsed = clipped_energy(start, end, w0, w1, lower, upper)
            kwh += energy
            seconds += elapsed
        peak = self.db.execute(
            "SELECT MAX(watts) FROM samples WHERE ts >= ? AND ts < ?",
            (lower, upper),
        ).fetchone()[0]
        result = DayTotal(day, kwh, seconds, peak or 0)
        self._daily_cache[key] = result
        if len(self._daily_cache) > 128:
            self._daily_cache.popitem(last=False)
        return result

    def days(self, end: date, count: int, zone: tzinfo | None = None) -> list[DayTotal]:
        return [self.daily(end - timedelta(days=i), zone) for i in reversed(range(count))]

    def points(self, day: date, zone: tzinfo | None = None) -> list[tuple[float, float]]:
        lower, upper = day_bounds(day, zone)
        return self.db.execute(
            "SELECT ts, watts FROM samples WHERE ts >= ? AND ts < ? ORDER BY ts",
            (lower, upper),
        ).fetchall()

    def intervals(self, day: date, zone: tzinfo | None = None) -> list[tuple[float, float]]:
        lower, upper = day_bounds(day, zone)
        return [
            (start, end)
            for start, end in self.db.execute(
                "SELECT start, end FROM intervals WHERE start >= ? AND start < ? ORDER BY start",
                (lower - MAX_GAP_SECONDS, upper),
            )
            if end > lower
        ]


class Recorder:
    def __init__(self, store: Store):
        self.store = store
        self.previous: Reading | None = None

    def break_chain(self):
        self.previous = None

    def record(self, sensors: list[Sensor], at: datetime) -> Reading:
        settings = self.store.load_settings()
        if not settings.sensor_ids:
            self.break_chain()
            raise SourceError("请先在偏好设置中选择功率传感器。")
        available = {sensor.id: sensor for sensor in sensors}
        missing = set(settings.sensor_ids) - available.keys()
        if missing:
            self.break_chain()
            raise SourceError("所选传感器暂不可用：" + "、".join(sorted(missing)))
        if at.tzinfo is None:
            raise ValueError("采样时间必须包含时区。")
        components = {key: available[key].watts for key in settings.sensor_ids}
        if settings.overhead_watts:
            components["__overhead__"] = settings.overhead_watts
        if any(not math.isfinite(w) or w < 0 for w in components.values()):
            self.break_chain()
            raise SourceError("传感器功率无效，本次未累计。")
        total = sum(components.values())
        if not math.isfinite(total):
            self.break_chain()
            raise SourceError("传感器合计功率无效，本次未累计。")
        current = Reading(at.timestamp(), total, components, settings.signature)
        if self.previous and current.timestamp <= self.previous.timestamp:
            self.break_chain()
            raise SourceError("系统时间发生回退，本次未累计。")
        try:
            self.store.append(current, self.previous)
        except (sqlite3.Error, SourceError):
            self.break_chain()
            raise
        self.previous = current
        return current
