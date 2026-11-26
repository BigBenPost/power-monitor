import runpy
from pathlib import Path

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

project = Path(SPECPATH)
release = runpy.run_path(str(project / "src" / "powerlog" / "__init__.py"))["__version__"]
brand = runpy.run_path(str(project / "src" / "powerlog" / "brand.py"))
version_tuple = tuple(int(part) for part in release.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=version_tuple,
        prodvers=version_tuple,
        mask=0x3F,
        flags=0,
        OS=0x40004,
        fileType=1,
        subtype=0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", brand["AUTHOR_NAME"]),
                        StringStruct(
                            "FileDescription", "Powerlog - Local electricity usage monitor"
                        ),
                        StringStruct("FileVersion", release),
                        StringStruct("InternalName", "Powerlog"),
                        StringStruct("OriginalFilename", "Powerlog.exe"),
                        StringStruct("ProductName", "Powerlog"),
                        StringStruct("ProductVersion", release),
                        StringStruct("Comments", f"Contact: {brand['CONTACT_EMAIL']}"),
                    ],
                ),
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

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
    version=version_info,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Powerlog")
