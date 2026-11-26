from pathlib import Path

project = Path(SPECPATH)

a = Analysis(
    [str(project / "src" / "powerlog" / "__main__.py")],
    pathex=[str(project / "src")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Powerlog",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(project / "assets" / "powerlog.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Powerlog")
