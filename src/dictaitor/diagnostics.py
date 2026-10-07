"""Local diagnostics: a small log file to attach to bug reports.

Never logs what you dictated - only events, lengths, timings and errors.
The log stays in the dictAItor data folder; nothing is uploaded.
"""

from __future__ import annotations

import logging
import platform
import sys
import threading
from collections.abc import Callable
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import __version__
from .i18n import t

log = logging.getLogger("dictaitor")


def setup_logging(home: Path) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "dictaitor.log"
    handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.info(
        "start dictAItor %s, Python %s, %s %s, frozen=%s",
        __version__,
        platform.python_version(),
        platform.system(),
        platform.release(),
        getattr(sys, "frozen", False),
    )
    return path


def install_excepthook(report: Callable[[str], None]) -> None:
    """Unhandled errors go to the log and to a tray notification instead of vanishing."""

    def handle(exc_type, exc, tb):
        log.error("unhandled error", exc_info=(exc_type, exc, tb))
        try:
            report(
                t(
                    f"Wystąpił nieoczekiwany błąd ({exc_type.__name__}). Szczegóły są w dzienniku – menu kółka.",
                    f"An unexpected error occurred ({exc_type.__name__}). Details are in the log – see the tray menu.",
                )
            )
        except Exception:
            pass

    sys.excepthook = handle
    threading.excepthook = lambda args: handle(args.exc_type, args.exc_value, args.exc_traceback)


def model_is_cached(model: str) -> bool:
    """False means the first start will download the model (hundreds of MB)."""
    try:
        from faster_whisper.utils import download_model

        download_model(model, local_files_only=True)
        return True
    except Exception:
        return False
