# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for orga-drone (Windows onefolder build)."""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

block_cipher = None

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src" / "orga_drone"

datas = [
    (str(SRC / "templates"), "orga_drone/templates"),
    (str(SRC / "static"), "orga_drone/static"),
    (str(SRC / "locales"), "orga_drone/locales"),
]
datas += collect_data_files("imageio_ffmpeg")

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "orga_drone.app",
    "orga_drone.__main__",
]

tmp_ret = collect_all("orga_drone")
datas += tmp_ret[0]
hiddenimports += tmp_ret[2]

tmp_ret = collect_all("uvicorn")
datas += tmp_ret[0]
binaries = list(tmp_ret[1])
hiddenimports += tmp_ret[2]

tmp_ret = collect_all("imageio_ffmpeg")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

a = Analysis(
    [str(Path(SPECPATH) / "run_orga_drone.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="orga-drone",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="orga-drone",
)
