"""Parsing and vetting global hotkeys like "ctrl+alt+d"."""

from __future__ import annotations

from dataclasses import dataclass

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN = 0x1, 0x2, 0x4, 0x8
_MODS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}
_NAMED_KEYS = {
    "space": 0x20, "spacja": 0x20, "esc": 0x1B, "escape": 0x1B, "enter": 0x0D,
    "tab": 0x09, "pause": 0x13, "insert": 0x2D, "home": 0x24, "end": 0x23,
}
_NAMED_KEYS.update({f"f{i}": 0x6F + i for i in range(1, 25)})

# On Polish (and many other) layouts Ctrl+Alt is AltGr: Ctrl+Alt+Z types "ż".
# A global hotkey there would make the letter impossible to type.
ALTGR_LETTERS = set("acelnosxz")

# Tried in order when the configured hotkey is taken by another program.
FALLBACKS = ["ctrl+alt+d", "f9", "ctrl+shift+space", "ctrl+alt+j"]


class HotkeyError(ValueError):
    pass


@dataclass(frozen=True)
class Hotkey:
    text: str
    modifiers: int
    vk: int


def parse(spec: str) -> Hotkey:
    parts = [p.strip().lower() for p in spec.replace(" ", "").split("+") if p.strip()]
    if not parts:
        raise HotkeyError("pusty skrót")
    *mods, key = parts
    modifiers = 0
    for m in mods:
        if m not in _MODS:
            raise HotkeyError(f"nieznany modyfikator: {m}")
        modifiers |= _MODS[m]
    if key in _NAMED_KEYS:
        vk = _NAMED_KEYS[key]
    elif len(key) == 1 and key.isascii() and key.isalnum():
        vk = ord(key.upper())
    else:
        raise HotkeyError(f"nieznany klawisz: {key}")
    if modifiers & MOD_CONTROL and modifiers & MOD_ALT and key in ALTGR_LETTERS:
        raise HotkeyError(
            f"{spec} to na polskiej klawiaturze AltGr+{key.upper()} – zablokowałby wpisywanie polskiej litery"
        )
    if not modifiers and not key.startswith("f"):
        raise HotkeyError(f"{spec}: zwykły klawisz bez Ctrl/Alt przechwyciłby normalne pisanie")
    return Hotkey(spec, modifiers, vk)


def candidates(preferred: str) -> list[str]:
    return [preferred] + [f for f in FALLBACKS if f != preferred.lower()]
