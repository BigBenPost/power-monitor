from __future__ import annotations

import sqlite3
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal

from powerlog.aida64 import SourceError
from powerlog.storage import SAMPLE_SECONDS, Recorder, Store


class Reader(QThread):
    result = Signal(object, str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source

    def run(self):
        try:
            self.result.emit(self.source.read(), "")
        except Exception as exc:
            self.result.emit([], str(exc) or "读取 AIDA64 失败。")


class Controller(QObject):
    updated = Signal()

    def __init__(self, store: Store, source, clock=None):
        super().__init__()
        self.store, self.source = store, source
        self.clock = clock or (lambda: datetime.now().astimezone())
        self.recorder = Recorder(store)
        self.sensors = []
        self.reading = None
        self.connected = False
        self.error = "正在连接 AIDA64…"
        self.worker = None
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(SAMPLE_SECONDS * 1000)
        self.timer.timeout.connect(self.poll)
        self.stopping = False

    def start(self):
        self.timer.start()
        self.poll()

    def poll(self):
        if self.stopping or self.worker is not None:
            return
        self.worker = Reader(self.source, self)
        self.worker.result.connect(self.receive)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.finished.connect(self.clear_worker)
        self.worker.start()

    def clear_worker(self):
        self.worker = None

    def receive(self, sensors, error):
        if self.stopping:
            return
        self.connected = not bool(error)
        self.error = error
        self.reading = None
        if error:
            self.recorder.break_chain()
        else:
            self.sensors = sensors
            try:
                self.reading = self.recorder.record(sensors, self.clock())
            except (SourceError, ValueError, sqlite3.Error) as exc:
                self.recorder.break_chain()
                self.error = str(exc)
        self.updated.emit()

    def stop(self):
        self.stopping = True
        self.timer.stop()
        if self.worker:
            self.worker.wait()
