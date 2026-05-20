# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import shutil


build_root = Path(SPECPATH).resolve()
root = build_root.parent
src_root = root / "src"
artifact_name = os.environ.get("MUSIC_SEARCH_ARTIFACT_NAME", "MusicSearch")
datas = [
    (str(src_root / "web"), "web"),
    (str(build_root / "VERSION"), "."),
]
binaries = []


def add_binary(name):
    local = root / "bin" / name
    source = local if local.exists() else shutil.which(name)
    if source:
        binaries.append((str(source), "bin"))


for binary_name in ("ffmpeg", "vibra", "pactl"):
    add_binary(binary_name)


a = Analysis(
    [str(src_root / "app.py")],
    pathex=[str(src_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=artifact_name,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
