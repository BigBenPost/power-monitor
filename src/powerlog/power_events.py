from __future__ import annotations

import ctypes
import sys

from PySide6.QtCore import QAbstractNativeEventFilter

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 4
RESUME_EVENTS = {6, 7, 18}


class PowerEventFilter(QAbstractNativeEventFilter):
    """Invalidate the integration chain even for very short Windows suspends."""

    def __init__(self, controller):
        super().__init__()
        self.controller = controller

    def nativeEventFilter(self, event_type, message):
        if sys.platform == "win32" and bytes(event_type) in {
            b"windows_generic_MSG",
            b"windows_dispatcher_MSG",
        }:
            from ctypes import wintypes

            msg = ctypes.cast(int(message), ctypes.POINTER(wintypes.MSG)).contents
            if msg.message == WM_POWERBROADCAST:
                if msg.wParam == PBT_APMSUSPEND:
                    self.controller.suspend()
                elif msg.wParam in RESUME_EVENTS:
                    self.controller.resume()
        return False, 0
