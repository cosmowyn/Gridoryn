# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from app_metadata import APP_NAME


project_root = Path(__file__).resolve().parent
icon_path = project_root / "build_assets" / "icons" / f"{APP_NAME}.icns"
icon_args = [str(icon_path)] if icon_path.exists() else []


a = Analysis(
    [str(project_root / "main.py")],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_args,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name=APP_NAME,
)
app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(icon_path) if icon_path.exists() else None,
    bundle_identifier=None,
)
