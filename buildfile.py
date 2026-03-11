#!/usr/bin/env python3
"""
Cross-platform PyInstaller build helper for stable local releases.

Behavior:
- Builds the app from the active project metadata.
- Uses stable local icon/splash assets when present.
- Supports optional environment overrides for icon and splash selection.
- Stages a versioned release artifact under ``dist/release/``.

Notes:
- The stable build path is intentionally non-interactive so it is
  reproducible and release-friendly.
- Splash is skipped on macOS because PyInstaller splash support is limited
  there.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from app_metadata import APP_NAME, APP_VERSION


ENTRY_SCRIPT = "main.py"
VENV_DIR = ".venv"
PYTHON_ENV_VAR = "GRIDORYN_PYTHON"
ICON_ENV_VAR = "GRIDORYN_ICON"
SPLASH_ENV_VAR = "GRIDORYN_SPLASH"


def _is_windows() -> bool:
    return os.name == "nt"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _platform_tag() -> str:
    if _is_windows():
        return "windows"
    if _is_macos():
        return "macos"
    return "linux"


def _release_basename() -> str:
    return f"{APP_NAME}-{APP_VERSION}-{_platform_tag()}"


def _venv_python(venv_dir: Path) -> Path:
    if _is_windows():
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _active_venv_python() -> Path | None:
    exe = Path(sys.executable).resolve()
    if not exe.exists():
        return None
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        return exe
    virtual_env = os.getenv("VIRTUAL_ENV", "").strip()
    if virtual_env:
        try:
            venv_root = Path(virtual_env).resolve()
            if exe.is_relative_to(venv_root):
                return exe
        except Exception:
            pass
    return None


def _resolve_build_python(project_root: Path) -> Path:
    env_python = os.getenv(PYTHON_ENV_VAR, "").strip()
    if env_python:
        candidate = Path(env_python).expanduser().resolve()
        if not candidate.exists():
            raise FileNotFoundError(
                f"{PYTHON_ENV_VAR} points to a missing Python executable:\n  {candidate}"
            )
        return candidate

    active_python = _active_venv_python()
    if active_python is not None:
        return active_python

    venv = (project_root / VENV_DIR).resolve()
    py = _venv_python(venv)
    if py.exists():
        return py

    raise FileNotFoundError(
        f"Could not find virtualenv Python at:\n  {py}\n"
        f"Activate your venv before running buildfile.py, set {PYTHON_ENV_VAR}, "
        f"or ensure '{VENV_DIR}' exists in the project root."
    )


def _ensure_pyinstaller(venv_python: Path) -> None:
    try:
        subprocess.run(
            [
                str(venv_python),
                "-c",
                (
                    "import PyInstaller, sys; "
                    "print('PyInstaller OK', PyInstaller.__version__, "
                    "sys.executable)"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        print(
            "PyInstaller not importable in the selected build interpreter. "
            f"Attempting install into:\n  {venv_python}"
        )
        subprocess.run(
            [
                str(venv_python),
                "-m",
                "pip",
                "install",
                "-U",
                "pyinstaller",
                "pyinstaller-hooks-contrib",
            ],
            check=True,
        )
        subprocess.run(
            [
                str(venv_python),
                "-c",
                (
                    "import PyInstaller, sys; "
                    "print('PyInstaller OK', PyInstaller.__version__, "
                    "sys.executable)"
                ),
            ],
            check=True,
            capture_output=True,
            text=True,
        )


def _write_release_manifest(
    dist_dir: Path,
    source_artifact: Path,
    staged_artifact: Path,
) -> Path:
    manifest_path = dist_dir / "release_manifest.json"
    payload = {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "platform": _platform_tag(),
        "source_artifact": str(source_artifact),
        "release_artifact": str(staged_artifact),
    }
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return manifest_path


def _stage_release_artifact(source_artifact: Path, dist_dir: Path) -> Path:
    release_dir = dist_dir / "release"
    release_dir.mkdir(parents=True, exist_ok=True)

    if source_artifact.is_dir():
        target = release_dir / _release_basename()
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(source_artifact, target)
    else:
        target = release_dir / f"{_release_basename()}{source_artifact.suffix}"
        if target.exists():
            target.unlink(missing_ok=True)
        shutil.copy2(source_artifact, target)

    _write_release_manifest(dist_dir, source_artifact, target)
    return target


def _validate_icon_path(icon_path: str) -> None:
    ext = Path(icon_path).suffix.lower()
    if _is_windows():
        if ext not in (".ico", ".png", ".jpg", ".jpeg", ".bmp"):
            raise ValueError(
                "On Windows, the icon must be .ico or a common image format "
                "that can be converted to .ico."
            )
    elif _is_macos():
        if ext not in (
            ".icns",
            ".png",
            ".jpg",
            ".jpeg",
            ".bmp",
            ".tif",
            ".tiff",
            ".gif",
        ):
            raise ValueError(
                "On macOS, icon must be .icns or a common image format."
            )
    else:
        if ext not in (".png", ".ico", ".icns"):
            raise ValueError(
                "On Linux, please use .png (preferred) or .ico/.icns."
            )


def _require_tool(tool_name: str) -> None:
    if shutil.which(tool_name) is None:
        raise RuntimeError(
            f"Required tool '{tool_name}' not found on PATH.\n"
            f"On macOS, '{tool_name}' should normally be available."
        )


def _convert_image_to_icns_mac(
    image_path: Path,
    project_root: Path,
    app_name: str,
) -> Path:
    """
    Convert a supported image to ``.icns`` on macOS using ``sips`` and
    ``iconutil``.
    """
    if not _is_macos():
        raise RuntimeError(
            "ICNS conversion is only supported on macOS in this script."
        )

    _require_tool("sips")
    _require_tool("iconutil")

    out_dir = project_root / "build_assets" / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)

    iconset_dir = out_dir / f"{app_name}.iconset"
    if iconset_dir.exists():
        shutil.rmtree(iconset_dir, ignore_errors=True)
    iconset_dir.mkdir(parents=True, exist_ok=True)

    sizes = [16, 32, 128, 256, 512]
    for base in sizes:
        out_png_1x = iconset_dir / f"icon_{base}x{base}.png"
        subprocess.run(
            [
                "sips",
                "-z",
                str(base),
                str(base),
                str(image_path),
                "--out",
                str(out_png_1x),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        out_png_2x = iconset_dir / f"icon_{base}x{base}@2x.png"
        subprocess.run(
            [
                "sips",
                "-z",
                str(base * 2),
                str(base * 2),
                str(image_path),
                "--out",
                str(out_png_2x),
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    out_icns = out_dir / f"{app_name}.icns"
    if out_icns.exists():
        out_icns.unlink(missing_ok=True)

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(out_icns)],
        check=True,
        capture_output=True,
        text=True,
    )
    shutil.rmtree(iconset_dir, ignore_errors=True)

    if not out_icns.exists():
        raise RuntimeError("ICNS conversion failed: output file was not created.")
    return out_icns


def _convert_image_to_ico_qt(
    image_path: Path,
    project_root: Path,
    app_name: str,
) -> Path:
    try:
        from PySide6.QtGui import QImage
    except Exception as exc:
        raise RuntimeError(
            "Could not import PySide6 to convert the Windows icon to .ico."
        ) from exc

    out_dir = project_root / "build_assets" / "icons"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_ico = out_dir / f"{app_name}.ico"

    image = QImage(str(image_path))
    if image.isNull():
        raise RuntimeError(f"Could not load icon image for ICO conversion: {image_path}")

    out_ico.unlink(missing_ok=True)
    if not image.save(str(out_ico), "ICO") or not out_ico.exists():
        raise RuntimeError(
            f"ICO conversion failed for '{image_path}'. "
            "Provide a valid .ico file or a readable source image."
        )
    return out_ico


def _env_asset_path(var_name: str) -> Path | None:
    raw_value = os.getenv(var_name, "").strip()
    if not raw_value:
        return None

    asset_path = Path(raw_value).expanduser().resolve()
    if not asset_path.exists():
        raise FileNotFoundError(
            f"{var_name} points to a missing file:\n  {asset_path}"
        )
    return asset_path


def _default_icon_candidates(project_root: Path) -> list[Path]:
    icons_dir = project_root / "build_assets" / "icons"
    if _is_windows():
        return [
            icons_dir / f"{APP_NAME}.ico",
            project_root / "icon.ico",
            icons_dir / f"{APP_NAME}.png",
            project_root / "icon.png",
        ]
    if _is_macos():
        return [
            icons_dir / f"{APP_NAME}.icns",
            icons_dir / f"{APP_NAME}.png",
            project_root / "icon.png",
        ]
    return [
        icons_dir / f"{APP_NAME}.png",
        icons_dir / f"{APP_NAME}.ico",
        icons_dir / f"{APP_NAME}.icns",
        project_root / "icon.png",
        project_root / "icon.ico",
    ]


def _resolve_icon(project_root: Path) -> str | None:
    env_icon = _env_asset_path(ICON_ENV_VAR)
    if env_icon is not None:
        _validate_icon_path(str(env_icon))
        if _is_windows() and env_icon.suffix.lower() != ".ico":
            return str(_convert_image_to_ico_qt(env_icon, project_root, APP_NAME))
        if _is_macos() and env_icon.suffix.lower() != ".icns":
            return str(_convert_image_to_icns_mac(env_icon, project_root, APP_NAME))
        return str(env_icon)

    for candidate in _default_icon_candidates(project_root):
        if not candidate.exists():
            continue
        _validate_icon_path(str(candidate))
        if _is_windows() and candidate.suffix.lower() != ".ico":
            return str(_convert_image_to_ico_qt(candidate, project_root, APP_NAME))
        if _is_macos() and candidate.suffix.lower() != ".icns":
            return str(
                _convert_image_to_icns_mac(candidate, project_root, APP_NAME)
            )
        return str(candidate)
    return None


def _resolve_splash(project_root: Path) -> str | None:
    if _is_macos():
        return None

    env_splash = _env_asset_path(SPLASH_ENV_VAR)
    if env_splash is not None:
        return str(env_splash)

    default_candidates = [
        project_root / "resources" / "splash.png",
        project_root / "splash.png",
    ]
    for candidate in default_candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _pyinstaller_cmd(
    venv_python: Path,
    entry_script: Path,
    app_name: str,
    splash: str | None,
    icon: str | None,
) -> list[str]:
    cmd = [
        str(venv_python),
        "-m",
        "PyInstaller",
        str(entry_script),
        "--name",
        app_name,
        "--noconfirm",
        "--clean",
        "--windowed",
        "--log-level",
        "INFO",
    ]

    if _is_windows():
        cmd.append("--onefile")
    else:
        cmd.append("--onedir")

    if splash and not _is_macos():
        cmd.extend(["--splash", splash])

    if icon:
        cmd.extend(["--icon", icon])

    resources_dir = entry_script.parent / "resources"
    if resources_dir.exists() and resources_dir.is_dir():
        sep = ";" if _is_windows() else ":"
        cmd.extend(["--add-data", f"{resources_dir}{sep}resources"])

    icons_dir = entry_script.parent / "build_assets" / "icons"
    if icons_dir.exists() and icons_dir.is_dir():
        sep = ";" if _is_windows() else ":"
        cmd.extend(["--add-data", f"{icons_dir}{sep}build_assets/icons"])

    return cmd


def main() -> int:
    project_root = Path(__file__).resolve().parent
    entry_script = (project_root / ENTRY_SCRIPT).resolve()
    if not entry_script.exists():
        print(f"ERROR: entry script not found: {entry_script}")
        return 1

    print(f"OS: {platform.system()}  |  Project: {project_root}")

    venv_python = _resolve_build_python(project_root)
    print(f"Using build Python: {venv_python}")
    _ensure_pyinstaller(venv_python)

    if _is_macos():
        print("Note: PyInstaller splash is skipped on macOS.")

    splash = _resolve_splash(project_root)
    icon = _resolve_icon(project_root)

    if splash:
        print(f"Using splash asset: {splash}")
    else:
        print("No splash asset configured.")

    if icon:
        print(f"Using icon asset: {icon}")
    else:
        print("No icon asset configured for this platform.")

    for directory_name in ("build", "dist"):
        path = project_root / directory_name
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    cmd = _pyinstaller_cmd(
        venv_python=venv_python,
        entry_script=entry_script,
        app_name=APP_NAME,
        splash=splash,
        icon=icon,
    )

    print("\nRunning:")
    print(" ".join(f'"{part}"' if " " in part else part for part in cmd))
    print()

    try:
        result = subprocess.run(
            cmd,
            cwd=str(project_root),
            text=True,
            capture_output=True,
        )
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        if result.returncode != 0:
            print("\nBuild failed.")
            return result.returncode
    except Exception as exc:
        print("\nBuild failed.")
        print(str(exc))
        return 1

    out_path = project_root / "dist"
    if _is_windows():
        expected = out_path / f"{APP_NAME}.exe"
    else:
        expected = out_path / APP_NAME

    if not expected.exists():
        print("\nERROR: PyInstaller returned success, but expected output was not found:")
        print(f"Expected: {expected}")

        if out_path.exists():
            print("\nContents of dist/:")
            for artifact in out_path.rglob("*"):
                rel = artifact.relative_to(out_path)
                print(f"  {rel}")
        else:
            print("\nNote: dist/ folder does not exist at all.")

        print("\nPossible causes:")
        print("- Antivirus/EDR quarantined the output immediately.")
        print("- Build actually failed but only logged to stderr.")
        print("- APP_NAME mismatch vs produced artifact name.")
        return 2

    staged_artifact = _stage_release_artifact(expected, out_path)

    print("\nBuild complete.")
    print(f"Output folder: {out_path}")
    print(f"Release artifact: {staged_artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
