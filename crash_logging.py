from __future__ import annotations

import os
import platform
import sys
import threading
import traceback
import json
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Callable

from app_metadata import APP_LOG_SLUG, APP_NAME, APP_PROFILE, APP_VERSION
from app_paths import app_data_dir


LEGACY_LOG_SLUGS = ("customtaskmanager",)


def logs_dir() -> Path:
    path = Path(app_data_dir()) / "logs"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return Path(app_data_dir())
    return path


def current_log_path() -> Path:
    ts = datetime.now().strftime("%Y-%m-%d")
    return logs_dir() / f"{APP_LOG_SLUG}_{ts}.log"


def list_log_paths(limit: int = 20) -> list[Path]:
    try:
        files_by_path: dict[Path, Path] = {}
        for slug in (APP_LOG_SLUG, *LEGACY_LOG_SLUGS):
            for path in logs_dir().glob(f"{slug}_*.log"):
                files_by_path[path] = path
        files = sorted(
            files_by_path.values(),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return []
    return files[: max(1, int(limit or 20))]


def read_log_text(path: str | Path, max_bytes: int = 512_000) -> str:
    try:
        raw = Path(path).read_bytes()
    except Exception:
        return ""
    if max_bytes and len(raw) > int(max_bytes):
        raw = raw[-int(max_bytes) :]
    try:
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def environment_snapshot(db_path: str | None = None) -> dict:
    info = {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "profile": APP_PROFILE,
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "frozen": bool(getattr(sys, "frozen", False)),
        "cwd": os.getcwd(),
    }
    if db_path:
        info["db_path"] = str(db_path)
    return info


def _format_exception_block(
    exc_type: type[BaseException] | None,
    exc_value: BaseException,
    exc_tb: TracebackType | None,
    context: str,
    db_path: str | None,
) -> str:
    lines = [
        "=" * 72,
        f"timestamp: {datetime.now().isoformat(sep=' ', timespec='seconds')}",
        "entry_type: exception",
        f"context: {context or 'runtime'}",
        f"exception_type: {getattr(exc_type, '__name__', type(exc_value).__name__)}",
        f"message: {exc_value}",
    ]
    for key, value in environment_snapshot(db_path=db_path).items():
        lines.append(f"{key}: {value}")
    lines.append("traceback:")
    lines.extend(traceback.format_exception(exc_type or type(exc_value), exc_value, exc_tb))
    return "\n".join(lines).rstrip() + "\n"


def _format_event_block(
    *,
    level: str,
    context: str,
    message: str,
    db_path: str | None,
    details: dict[str, Any] | None = None,
) -> str:
    lines = [
        "=" * 72,
        f"timestamp: {datetime.now().isoformat(sep=' ', timespec='seconds')}",
        "entry_type: event",
        f"level: {str(level or 'INFO').upper()}",
        f"context: {context or 'runtime'}",
        f"message: {message or ''}",
    ]
    for key, value in environment_snapshot(db_path=db_path).items():
        lines.append(f"{key}: {value}")
    if details:
        lines.append("details:")
        try:
            lines.append(json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2))
        except Exception:
            lines.append(repr(details))
    return "\n".join(lines).rstrip() + "\n"


def write_event_log(
    *,
    level: str = "INFO",
    context: str = "runtime",
    message: str,
    db_path: str | None = None,
    details: dict[str, Any] | None = None,
) -> Path | None:
    try:
        path = current_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(
                _format_event_block(
                    level=level,
                    context=context,
                    message=message,
                    db_path=db_path,
                    details=details,
                )
            )
        return path
    except Exception:
        return None


def write_exception_log(
    exc_type: type[BaseException] | None,
    exc_value: BaseException,
    exc_tb: TracebackType | None,
    *,
    context: str = "runtime",
    db_path: str | None = None,
) -> Path | None:
    try:
        path = current_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(_format_exception_block(exc_type, exc_value, exc_tb, context, db_path))
        return path
    except Exception:
        return None


def log_exception(exc: BaseException, *, context: str = "runtime", db_path: str | None = None) -> Path | None:
    return write_exception_log(type(exc), exc, exc.__traceback__, context=context, db_path=db_path)


def log_event(
    message: str,
    *,
    context: str = "runtime",
    level: str = "INFO",
    db_path: str | None = None,
    details: dict[str, Any] | None = None,
) -> Path | None:
    return write_event_log(level=level, context=context, message=message, db_path=db_path, details=details)


def install_exception_hooks(db_path_provider: Callable[[], str | None] | None = None) -> None:
    def _db_path() -> str | None:
        if db_path_provider is None:
            return None
        try:
            return db_path_provider()
        except Exception:
            return None

    old_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        write_exception_log(exc_type, exc_value, exc_tb, context="uncaught", db_path=_db_path())
        try:
            old_hook(exc_type, exc_value, exc_tb)
        except Exception:
            pass

    sys.excepthook = _hook

    def _thread_hook(args: threading.ExceptHookArgs):
        write_exception_log(
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
            context=f"thread:{getattr(args.thread, 'name', 'unknown')}",
            db_path=_db_path(),
        )

    threading.excepthook = _thread_hook

    if hasattr(sys, "unraisablehook"):
        old_unraisable = sys.unraisablehook

        def _unraisable_hook(args):
            exc = getattr(args, "exc_value", RuntimeError("Unraisable exception"))
            tb = getattr(args, "exc_traceback", None)
            obj = getattr(args, "object", None)
            context = f"unraisable:{type(obj).__name__}" if obj is not None else "unraisable"
            write_exception_log(type(exc), exc, tb, context=context, db_path=_db_path())
            try:
                old_unraisable(args)
            except Exception:
                pass

        sys.unraisablehook = _unraisable_hook
