from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QMessageBox

from powerlog import __version__
from powerlog.aida64 import SharedMemorySource
from powerlog.controller import Controller
from powerlog.demo import DemoSource
from powerlog.power_events import PowerEventFilter
from powerlog.storage import Store
from powerlog.ui import MainWindow


def main(argv=None):
    parser = argparse.ArgumentParser(description="Powerlog · AIDA64 每日耗电估算")
    parser.add_argument("--version", action="version", version=f"Powerlog {__version__}")
    parser.add_argument("--demo", action="store_true", help="使用独立演示数据，不读写真实记录")
    parser.add_argument("--data-dir", type=Path, help="数据目录，默认使用本机应用数据目录")
    parser.add_argument("--screenshot", type=Path, help="保存当前窗口截图后退出（需配合 --demo）")
    args = parser.parse_args(argv)
    if args.screenshot and not args.demo:
        parser.error("--screenshot 需要 --demo，以免打断真实采样")
    if os.name == "nt":
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Powerlog.Desktop")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("Powerlog")
    app.setApplicationVersion(__version__)
    app.setApplicationDisplayName("电量 · Powerlog")
    app.setStyle("Fusion")
    for family in ("Microsoft YaHei UI", "Microsoft YaHei", "Noto Sans CJK SC", "Segoe UI"):
        if family in QFontDatabase.families():
            app.setFont(QFont(family, 10))
            break
    app.setQuitOnLastWindowClosed(False)
    temporary = (
        tempfile.TemporaryDirectory(prefix="powerlog-demo-")
        if args.demo and not args.data_dir
        else None
    )
    directory = (
        Path(temporary.name)
        if temporary
        else args.data_dir
        or Path(
            QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        )
    )
    store = controller = lock = power_events = None
    exit_code = 0
    try:
        directory.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(directory / ("demo.lock" if args.demo else "powerlog.lock")))
        if not lock.tryLock(0):
            QMessageBox.information(
                None, "Powerlog 已在运行", "同一数据目录已有程序在运行，请从任务栏或托盘打开。"
            )
            return
        store = Store(directory / ("demo.sqlite3" if args.demo else "powerlog.sqlite3"))
        source = DemoSource(store) if args.demo else SharedMemorySource()
        controller = Controller(store, source, source.clock if args.demo else None)
        if not args.demo:
            power_events = PowerEventFilter(controller)
            app.installNativeEventFilter(power_events)
        window = MainWindow(controller, args.demo)
        app.aboutToQuit.connect(controller.stop)
        window.show()
        if args.screenshot:
            requested = False

            def capture():
                nonlocal exit_code
                args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                if not window.grab().save(str(args.screenshot)):
                    exit_code = 1
                window.quitting = True
                app.quit()

            def schedule_capture():
                nonlocal requested
                if not requested:
                    requested = True
                    QTimer.singleShot(150, capture)

            controller.updated.connect(schedule_capture)
        controller.start()
        result = app.exec()
        exit_code = max(exit_code, result)
    except (OSError, ValueError, sqlite3.Error) as exc:
        QMessageBox.critical(None, "Powerlog 无法启动", f"无法打开本机数据。\n{exc}")
        exit_code = 1
    finally:
        if power_events:
            app.removeNativeEventFilter(power_events)
        if controller:
            controller.stop()
        if store:
            store.close()
        if lock:
            lock.unlock()
        if temporary:
            temporary.cleanup()
    if exit_code:
        raise SystemExit(exit_code)
