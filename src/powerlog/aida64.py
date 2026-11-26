from __future__ import annotations

import ctypes
import locale
import math
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass

MAX_XML_BYTES = 1024 * 1024


class SourceError(Exception):
    """An unavailable or inconsistent AIDA64 snapshot."""


@dataclass(frozen=True)
class Sensor:
    id: str
    label: str
    watts: float


def parse_snapshot(raw: bytes) -> list[Sensor]:
    """Read AIDA64's null-terminated XML fragments without assuming sensor IDs."""
    if len(raw) > MAX_XML_BYTES:
        raise SourceError("共享内存数据过大，未读取。")
    raw = raw.split(b"\0", 1)[0]
    text = None
    declaration = re.match(
        rb'(?:\xef\xbb\xbf)?\s*<\?xml\b[^?]*?\bencoding\s*=\s*([\'"])([A-Za-z][A-Za-z0-9._-]*)\1',
        raw,
        re.IGNORECASE,
    )
    encodings = (
        (declaration[2].decode("ascii"),)
        if declaration
        else dict.fromkeys(("utf-8-sig", "gb18030", locale.getpreferredencoding(False)))
    )
    # Permissive Windows ANSI codecs can decode GB18030 bytes into mojibake.
    for encoding in encodings:
        try:
            text = raw.decode(encoding).lstrip("\ufeff")
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        raise SourceError("无法识别 AIDA64 数据编码。")
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise SourceError("不支持的共享内存 XML 格式。")
    text = re.sub(r"^\s*<\?xml[^?]*\?>", "", text).strip()
    if not text:
        raise SourceError("AIDA64 尚未导出传感器数据。")
    try:
        root = ET.fromstring(f"<snapshot>{text}</snapshot>")
    except ET.ParseError as exc:
        raise SourceError("AIDA64 数据正在更新或格式不完整，请稍后重试。") from exc
    sensors = []
    seen = set()
    for node in root.iter():
        category = node.tag.rsplit("}", 1)[-1].lower()
        if category not in {"pwr", "power"}:
            continue
        fields = {child.tag.rsplit("}", 1)[-1].lower(): child.text or "" for child in node}
        sensor_id = fields.get("id", "").strip()
        label = fields.get("label", sensor_id).strip() or sensor_id
        value = fields.get("value", "").strip()
        match = re.fullmatch(r"([+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+))\s*(mW|kW|W)?", value)
        if not sensor_id or not match:
            continue
        unit = match[2] or fields.get("unit", "W").strip() or "W"
        factor = {"W": 1, "mW": 0.001, "kW": 1000}.get(unit)
        if factor is None:
            continue
        watts = float(match[1].replace(",", ".")) * factor
        if not math.isfinite(watts) or watts < 0:
            continue
        if sensor_id in seen:
            raise SourceError(f"AIDA64 导出了重复的传感器 ID：{sensor_id}")
        seen.add(sensor_id)
        sensors.append(Sensor(sensor_id, label, watts))
    return sensors


class SharedMemorySource:
    """Open an existing mapping read-only; never create a missing AIDA64 mapping."""

    def __init__(self, mapping_name="AIDA64_SensorValues"):
        self.mapping_name = mapping_name

    def read(self) -> list[Sensor]:
        error = None
        for _ in range(3):
            try:
                return parse_snapshot(self._copy_mapping())
            except SourceError as exc:
                error = exc
        raise error

    def _copy_mapping(self) -> bytes:
        if sys.platform != "win32":
            raise SourceError("实时读取需要 Windows 和正在运行的 AIDA64。")
        from ctypes import wintypes

        class MemoryInfo(ctypes.Structure):
            _fields_ = [
                ("base", ctypes.c_void_p),
                ("allocation_base", ctypes.c_void_p),
                ("allocation_protect", wintypes.DWORD),
                ("region_size", ctypes.c_size_t),
                ("state", wintypes.DWORD),
                ("protect", wintypes.DWORD),
                ("type", wintypes.DWORD),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenFileMappingW.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.OpenFileMappingW.restype = wintypes.HANDLE
        kernel.MapViewOfFile.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_size_t,
        )
        kernel.MapViewOfFile.restype = ctypes.c_void_p
        kernel.VirtualQuery.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(MemoryInfo),
            ctypes.c_size_t,
        )
        kernel.VirtualQuery.restype = ctypes.c_size_t
        kernel.UnmapViewOfFile.argtypes = (ctypes.c_void_p,)
        kernel.UnmapViewOfFile.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenFileMappingW(0x0004, False, self.mapping_name)
        if not handle:
            code = ctypes.get_last_error()
            if code == 5:
                raise SourceError("无权读取 AIDA64。请让两个程序使用相同的用户和权限级别。")
            raise SourceError("未找到 AIDA64 共享内存。请启动 AIDA64 并启用共享内存导出。")
        view = None
        try:
            view = kernel.MapViewOfFile(handle, 0x0004, 0, 0, 0)
            if not view:
                raise SourceError("无法映射 AIDA64 共享内存。")
            info = MemoryInfo()
            if not kernel.VirtualQuery(view, ctypes.byref(info), ctypes.sizeof(info)):
                raise SourceError("无法确定 AIDA64 共享内存大小。")
            size = min(info.region_size, MAX_XML_BYTES)
            first = ctypes.string_at(view, size).split(b"\0", 1)[0]
            second = ctypes.string_at(view, size).split(b"\0", 1)[0]
            if first != second:
                raise SourceError("AIDA64 正在更新共享内存。")
            if len(first) == size:
                raise SourceError("AIDA64 共享内存缺少结束标记。")
            return first
        finally:
            if view:
                kernel.UnmapViewOfFile(view)
            kernel.CloseHandle(handle)
