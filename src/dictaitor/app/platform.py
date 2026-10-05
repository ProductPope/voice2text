"""What the app needs from the operating system, behind one small interface."""

from __future__ import annotations

import os
from typing import Callable, Protocol

from .hotkeys import Hotkey


class Platform(Protocol):
    def foreground_window(self) -> int: ...
    def window_title(self, window: int) -> str: ...
    def is_elevated_window(self, window: int) -> bool: ...
    def focus_window(self, window: int) -> bool: ...
    def is_own_window(self, window: int) -> bool: ...
    def type_text(self, text: str) -> None: ...
    def paste_text(self, text: str) -> None: ...
    def set_clipboard(self, text: str) -> None: ...
    def register_hotkey(self, hotkey: Hotkey, callback: Callable[[], None]) -> bool: ...
    def unregister_hotkey(self, hotkey: Hotkey) -> None: ...


class FakePlatform:
    """In-memory stand-in for tests and for running the app on non-Windows systems."""

    def __init__(self):
        self.window = 1
        self.elevated: set[int] = set()
        self.typed: list[str] = []
        self.pasted: list[str] = []
        self.clipboard = ""
        self.hotkeys: dict[Hotkey, Callable[[], None]] = {}
        self.taken: set[str] = set()
        self.own: set[int] = set()  # windows belonging to dictAItor itself

    def foreground_window(self) -> int:
        return self.window

    def window_title(self, window: int) -> str:
        return f"okno {window}"

    def is_elevated_window(self, window: int) -> bool:
        return window in self.elevated

    def focus_window(self, window: int) -> bool:
        self.window = window
        return True

    def is_own_window(self, window: int) -> bool:
        return window in self.own

    def type_text(self, text: str) -> None:
        self.typed.append(text)

    def paste_text(self, text: str) -> None:
        self.pasted.append(text)

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text

    def register_hotkey(self, hotkey: Hotkey, callback: Callable[[], None]) -> bool:
        if hotkey.text.lower() in self.taken:
            return False
        self.hotkeys[hotkey] = callback
        return True

    def unregister_hotkey(self, hotkey: Hotkey) -> None:
        self.hotkeys.pop(hotkey, None)

    def press(self, text: str) -> None:
        for hk, cb in list(self.hotkeys.items()):
            if hk.text.lower() == text.lower():
                cb()


def get_platform() -> Platform:
    if os.name == "nt":
        from .win32 import WindowsPlatform

        return WindowsPlatform()
    return FakePlatform()
