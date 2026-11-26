import mmap
import sys
import uuid

import pytest

from powerlog.aida64 import MAX_XML_BYTES, Sensor, SharedMemorySource, SourceError, parse_snapshot

SNAPSHOT = b"""<pwr><id>PCPUPKG</id><label>CPU Package</label><value>62.5</value></pwr>
<pwr><id>PGPU1</id><label>GPU Power</label><value>124 W</value></pwr>"""


def test_fragments_and_non_power_categories():
    raw = SNAPSHOT + b"<temp><id>TCPU</id><label>CPU</label><value>60</value></temp>\0unused"
    assert parse_snapshot(raw) == [
        Sensor("PCPUPKG", "CPU Package", 62.5),
        Sensor("PGPU1", "GPU Power", 124),
    ]


@pytest.mark.parametrize("encoding", ["utf-8-sig", "gb18030"])
def test_nested_root_declaration_and_chinese_labels(encoding):
    xml = (
        '<?xml version="1.0"?><root><pwr><id>PCPU</id><label>处理器封装</label>'
        "<value>0,125 kW</value></pwr></root>"
    )
    assert parse_snapshot(xml.encode(encoding)) == [Sensor("PCPU", "处理器封装", 125)]


@pytest.mark.parametrize("preferred", ["cp1252", "cp1251", "ascii"])
def test_gb18030_labels_do_not_depend_on_windows_ansi_locale(monkeypatch, preferred):
    monkeypatch.setattr("powerlog.aida64.locale.getpreferredencoding", lambda _set: preferred)
    xml = "<pwr><id>P</id><label>处理器封装</label><value>125 W</value></pwr>"
    assert parse_snapshot(xml.encode("gb18030")) == [Sensor("P", "处理器封装", 125)]


@pytest.mark.parametrize("encoding,label", [("windows-1252", "Météo"), ("utf-8-sig", "处理器")])
def test_explicit_encoding_takes_precedence_over_fallbacks(encoding, label):
    declared = "utf-8" if encoding == "utf-8-sig" else encoding
    xml = (
        f'<?xml version="1.0" encoding="{declared}"?>'
        f"<pwr><id>P</id><label>{label}</label><value>1</value></pwr>"
    )
    assert parse_snapshot(xml.encode(encoding)) == [Sensor("P", label, 1)]


def test_bad_declared_encoding_is_not_silently_reinterpreted():
    raw = b'<?xml version="1.0" encoding="ascii"?><pwr><id>P</id><label>\xe9</label></pwr>'
    with pytest.raises(SourceError, match="编码"):
        parse_snapshot(raw)


@pytest.mark.parametrize(
    "value,unit,expected",
    [
        ("500", "mW", 0.5),
        ("0", "W", 0),
        (".5 W", "", 0.5),
        ("1.25 kW", "", 1250),
    ],
)
def test_supported_units(value, unit, expected):
    xml = f"<pwr><id>P</id><label>Power</label><value>{value}</value><unit>{unit}</unit></pwr>"
    assert parse_snapshot(xml.encode())[0].watts == expected


@pytest.mark.parametrize("value", ["N/A", "-1", "NaN", "inf", "12 V", "1,000,000"])
def test_unusable_power_is_omitted_not_made_zero(value):
    assert parse_snapshot(f"<pwr><id>P</id><value>{value}</value></pwr>".encode()) == []


@pytest.mark.parametrize("raw", [b"", b"<pwr>", b"<!DOCTYPE x><root/>", b"x" * (MAX_XML_BYTES + 1)])
def test_malformed_or_unbounded_snapshot_rejected(raw):
    with pytest.raises(SourceError):
        parse_snapshot(raw)


def test_duplicate_id_is_rejected():
    with pytest.raises(SourceError, match="重复"):
        parse_snapshot(SNAPSHOT + SNAPSHOT)


def test_torn_snapshot_retried_then_recovers(monkeypatch):
    source = SharedMemorySource()
    snapshots = iter((b"<pwr>", SNAPSHOT))
    monkeypatch.setattr(source, "_copy_mapping", lambda: next(snapshots))
    assert len(source.read()) == 2


def test_retries_are_bounded(monkeypatch):
    source = SharedMemorySource()
    calls = []

    def read():
        calls.append(1)
        raise SourceError("unavailable")

    monkeypatch.setattr(source, "_copy_mapping", read)
    with pytest.raises(SourceError, match="unavailable"):
        source.read()
    assert len(calls) == 3


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 named shared memory")
def test_real_windows_mapping_read_and_writer_exit():
    name = "Powerlog-test-" + uuid.uuid4().hex
    source = SharedMemorySource(name)
    with mmap.mmap(-1, 4096, tagname=name, access=mmap.ACCESS_WRITE) as writer:
        writer.write(SNAPSHOT + b"\0")
        assert source.read()[0] == Sensor("PCPUPKG", "CPU Package", 62.5)
        writer.seek(0)
        assert writer.read(len(SNAPSHOT)) == SNAPSHOT
    with pytest.raises(SourceError):
        source.read()


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows message")
def test_live_reader_has_actionable_platform_error():
    with pytest.raises(SourceError, match="Windows"):
        SharedMemorySource().read()
