from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal

from powerlog.aida64 import Sensor, SourceError
from powerlog.storage import MAX_GAP_SECONDS, SAMPLE_SECONDS, Recorder, Store

CLOCK_TOLERANCE_SECONDS = 2
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Snapshot:
    sensors: list[Sensor]
    error: str
    at: datetime
    elapsed: float
    generation: int


class Reader(QThread):
    result = Signal(object)

    def __init__(self, source, clock, elapsed_clock, generation, parent=None):
        super().__init__(parent)
        self.source, self.clock = source, clock
        self.elapsed_clock, self.generation = elapsed_clock, generation

    def run(self):
        try:
            sensors, error = self.source.read(), ""
        except SourceError as exc:
            sensors, error = [], str(exc)
        except Exception as exc:
            logger.exception("Unexpected AIDA64 read failure")
            sensors, error = [], str(exc) or "读取 AIDA64 失败。"
        # Timestamp in the reader, before the result waits in the GUI event queue.
        self.result.emit(
            Snapshot(sensors, error, self.clock(), self.elapsed_clock(), self.generation)
        )


class Controller(QObject):
    updated = Signal()

    def __init__(self, store: Store, source, clock=None, elapsed_clock=None):
        super().__init__()
        self.store, self.source = store, source
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.elapsed_clock = elapsed_clock or time.monotonic
        self.recorder = Recorder(store)
        self.sensors = []
        self.reading = None
        self.reading_elapsed = None
        self.connected = False
        self.error = "正在连接 AIDA64…"
        self.worker = None
        self.generation = 0
        self.poll_pending = False
        self.suspended = False
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(SAMPLE_SECONDS * 1000)
        self.timer.timeout.connect(self.poll)
        self.stopping = False

    def start(self):
        self.timer.start()
        self.poll()

    def poll(self):
        if self.stopping or self.suspended:
            return
        if self.worker is not None:
            self.poll_pending = True
            return
        self.worker = Reader(self.source, self.clock, self.elapsed_clock, self.generation, self)
        self.worker.result.connect(self.receive)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.clear_worker)
        self.worker.start()

    def clear_worker(self):
        self.worker = None
        if self.poll_pending:
            self.poll_pending = False
            self.poll()

    def break_chain(self):
        self.recorder.break_chain()
        self.reading = None
        self.reading_elapsed = None

    def reset_sampling(self, message="等待新的有效采样；空档时间不会计入耗电量。"):
        self.generation += 1
        self.break_chain()
        self.error = message
        self.updated.emit()

    def suspend(self):
        self.suspended = True
        self.timer.stop()
        self.reset_sampling("系统已休眠，恢复后将重新开始采样。")

    def resume(self):
        if self.stopping:
            return
        self.suspended = False
        self.reset_sampling("系统已恢复，等待新的有效采样。")
        self.timer.start()
        self.poll()

    def is_fresh(self, now=None):
        if self.reading is None or self.reading_elapsed is None:
            return False
        age = (now or self.clock()).timestamp() - self.reading.timestamp
        elapsed = self.elapsed_clock() - self.reading_elapsed
        return (
            0 <= age <= MAX_GAP_SECONDS
            and 0 <= elapsed <= MAX_GAP_SECONDS
            and abs(age - elapsed) <= CLOCK_TOLERANCE_SECONDS
        )

    def receive(self, snapshot: Snapshot):
        if self.stopping or self.suspended or snapshot.generation != self.generation:
            return
        self.connected = not bool(snapshot.error)
        self.error = snapshot.error
        previous, previous_elapsed = self.reading, self.reading_elapsed
        self.reading = self.reading_elapsed = None
        if snapshot.error:
            self.break_chain()
        else:
            self.sensors = snapshot.sensors
            age = self.clock().timestamp() - snapshot.at.timestamp()
            elapsed = self.elapsed_clock() - snapshot.elapsed
            if (
                not 0 <= age <= MAX_GAP_SECONDS
                or not 0 <= elapsed <= MAX_GAP_SECONDS
                or abs(age - elapsed) > CLOCK_TOLERANCE_SECONDS
            ):
                self.break_chain()
                self.error = "采样已过期或系统时间发生变化，等待新的有效采样。"
            else:
                if previous is not None and previous_elapsed is not None:
                    wall_gap = snapshot.at.timestamp() - previous.timestamp
                    elapsed_gap = snapshot.elapsed - previous_elapsed
                    if elapsed_gap <= 0 or abs(wall_gap - elapsed_gap) > CLOCK_TOLERANCE_SECONDS:
                        self.recorder.break_chain()
                try:
                    self.reading = self.recorder.record(snapshot.sensors, snapshot.at)
                    self.reading_elapsed = snapshot.elapsed
                except (SourceError, ValueError, sqlite3.Error) as exc:
                    self.break_chain()
                    self.error = str(exc)
        self.updated.emit()

    def stop(self):
        self.stopping = True
        self.timer.stop()
        if self.worker:
            self.worker.wait()
