from __future__ import annotations

import os
import platform
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Callable

from app_metadata import APP_NAME, APP_PROFILE, APP_VERSION
from app_paths import app_data_dir


def logs_dir() -> Path:
    path = Path(app_data_dir()) / "logs"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception:
        return Path(app_data_dir())
    return path


def current_log_path() -> Path:
    ts = datetime.now().strftime("%Y-%m-%d")
    return logs_dir() / f"{APP_NAME.lower()}_{ts}.log"


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
        f"context: {context or 'runtime'}",
        f"exception_type: {getattr(exc_type, '__name__', type(exc_value).__name__)}",
        f"message: {exc_value}",
    ]
    for key, value in environment_snapshot(db_path=db_path).items():
        lines.append(f"{key}: {value}")
    lines.append("traceback:")
    lines.extend(traceback.format_exception(exc_type or type(exc_value), exc_value, exc_tb))
    return "\n".join(lines).rstrip() + "\n"


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
