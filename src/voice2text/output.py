"""Where the finished text goes once the safe phrase is spoken."""

from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import Config


def send(text: str, config: Config) -> str:
    """Deliver `text`; returns a short description of what happened."""
    cfg = config["output"]
    mode = cfg["mode"]
    if mode == "stdout":
        print(text, flush=True)
        return "wypisano na stdout"
    if mode == "file":
        path = Path(cfg["file"] or "voice2text.txt").expanduser()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"--- {datetime.now():%Y-%m-%d %H:%M:%S}\n{text}\n")
        return f"dopisano do {path}"
    if mode == "command":
        subprocess.run(shlex.split(cfg["command"]), input=text, text=True, check=True)
        return f"przekazano do: {cfg['command']}"
    if mode == "type":
        from pynput.keyboard import Controller  # optional dependency

        Controller().type(text)
        return "wpisano w aktywne okno"
    if mode == "clipboard":
        import pyperclip  # optional dependency

        pyperclip.copy(text)
        return "skopiowano do schowka"
    print(f"Nieznany output.mode={mode!r}, wypisuję:", file=sys.stderr)
    print(text)
    return "wypisano"
