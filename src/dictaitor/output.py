"""Where the finished text goes once the safe phrase is spoken."""

from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import Config
from .i18n import t


def send(text: str, config: Config) -> str:
    """Deliver `text`; returns a short description of what happened."""
    cfg = config["output"]
    mode = cfg["mode"]
    if mode == "stdout":
        print(text, flush=True)
        return t("wypisano na stdout", "printed to stdout")
    if mode == "file":
        path = Path(cfg["file"] or "dictaitor.txt").expanduser()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
        return t(f"dopisano do {path}", f"appended to {path}")
    if mode == "command":
        subprocess.run(shlex.split(cfg["command"]), input=text, text=True, check=True)
        return t(f"przekazano do: {cfg['command']}", f"passed to: {cfg['command']}")
    if mode == "type":
        from pynput.keyboard import Controller  # optional dependency

        Controller().type(text)
        return t("wpisano w aktywne okno", "typed into the active window")
    if mode == "clipboard":
        import pyperclip  # optional dependency

        pyperclip.copy(text)
        return t("skopiowano do schowka", "copied to the clipboard")
    print(t(f"Nieznany output.mode={mode!r}, wypisuję:", f"Unknown output.mode={mode!r}, printing:"), file=sys.stderr)
    print(text)
    return t("wypisano", "printed")
