import os

import pytest

from dictaitor.app import hotkeys
from dictaitor.app.controller import ESCAPE, Controller, State, choose_delivery
from dictaitor.app.platform import FakePlatform
from dictaitor.config import DEFAULTS
from dictaitor.gate import Action
from dictaitor.session import Event

# ------------------------------------------------------------------ hotkeys


def test_parse_hotkey():
    hk = hotkeys.parse("Ctrl+Alt+D")
    assert (hk.modifiers, hk.vk) == (hotkeys.MOD_CONTROL | hotkeys.MOD_ALT, ord("D"))
    assert hotkeys.parse("f9").vk == 0x78
    assert hotkeys.parse("ctrl+shift+space").vk == 0x20


@pytest.mark.parametrize("spec", ["ctrl+alt+z", "ctrl+alt+a", "ctrl+alt+l", "alt+ctrl+s"])
def test_altgr_letters_are_refused(spec):
    with pytest.raises(hotkeys.HotkeyError, match="AltGr"):
        hotkeys.parse(spec)


@pytest.mark.parametrize("spec", ["d", "ctrl+", "hyper+d", "ctrl+ą"])
def test_invalid_hotkeys(spec):
    with pytest.raises(hotkeys.HotkeyError):
        hotkeys.parse(spec)


# --------------------------------------------------------------- controller


class FakeEngine:
    def __init__(self):
        self.started = 0
        self.draft = ""
        self.pending = None
        self.cancelled = 0

    def start(self):
        self.started += 1

    def stop(self):
        draft, self.draft = self.draft, ""
        return draft

    def confirm(self):
        text, self.pending = self.pending, None
        return Event(Action.SEND, "", sent=text)

    def cancel_pending(self):
        self.cancelled += 1


class FakeUI:
    def __init__(self):
        self.states = []
        self.notes = []
        self.previews = []

    def show(self, state, draft="", detail=""):
        self.states.append((state, draft))

    def preview(self, text):
        self.previews.append(text)

    def notify(self, message):
        self.notes.append(message)


class Clock:
    def __init__(self):
        self.timers = []

    def schedule(self, seconds, fn):
        entry = [seconds, fn, True]
        self.timers.append(entry)

        def cancel():
            entry[2] = False

        return cancel

    def fire(self):
        for entry in self.timers:
            if entry[2]:
                entry[2] = False
                entry[1]()


def make(**cfg):
    app_cfg = {**DEFAULTS["app"], **cfg}
    platform, engine, ui, clock = FakePlatform(), FakeEngine(), FakeUI(), Clock()
    c = Controller(platform, engine, ui, clock.schedule, app_cfg)
    c.on_ready("test")
    return c, platform, engine, ui, clock


def say_safe_phrase(c, engine, text):
    engine.pending = text
    c.on_event(Event(Action.PENDING, text))


def test_full_flow_types_into_remembered_window():
    c, platform, engine, ui, clock = make()
    platform.window = 42
    c.toggle()
    assert c.state is State.LISTENING and engine.started == 1
    c.on_event(Event(Action.CONTINUE, "Cześć"))
    say_safe_phrase(c, engine, "Cześć Ania.")
    assert c.state is State.PENDING and platform.typed == []
    assert ESCAPE in platform.hotkeys  # Esc is live only during the countdown
    clock.fire()
    assert platform.typed == ["Cześć Ania."]
    assert c.state is State.IDLE and ESCAPE not in platform.hotkeys


def test_escape_keeps_draft_and_keeps_listening():
    c, platform, engine, ui, clock = make()
    c.toggle()
    say_safe_phrase(c, engine, "Nie wysyłaj.")
    platform.press("esc")
    assert c.state is State.LISTENING and engine.cancelled == 1
    clock.fire()  # the cancelled timer must not deliver anything
    assert platform.typed == [] and platform.pasted == [] and platform.clipboard == ""


def test_window_changed_goes_to_clipboard():
    c, platform, engine, ui, clock = make()
    platform.window = 1
    c.toggle()
    platform.window = 2  # user clicked somewhere else meanwhile
    say_safe_phrase(c, engine, "Tekst.")
    clock.fire()
    assert platform.typed == [] and platform.clipboard == "Tekst."
    assert "schowku" in ui.notes[-1]


def test_admin_window_goes_to_clipboard():
    c, platform, engine, ui, clock = make()
    platform.elevated.add(1)
    c.toggle()
    say_safe_phrase(c, engine, "Tekst.")
    clock.fire()
    assert platform.clipboard == "Tekst." and "administrator" in ui.notes[-1]


def test_multiline_text_is_pasted_never_typed():
    c, platform, engine, ui, clock = make()
    c.toggle()
    say_safe_phrase(c, engine, "Linia 1.\nLinia 2.")
    clock.fire()
    assert platform.pasted == ["Linia 1.\nLinia 2."] and platform.typed == []


def test_zero_abort_window_delivers_immediately():
    c, platform, engine, ui, clock = make(abort_seconds=0)
    c.toggle()
    say_safe_phrase(c, engine, "Od razu.")
    assert platform.typed == ["Od razu."]


def test_hotkey_again_stops_without_sending_and_keeps_draft():
    c, platform, engine, ui, clock = make()
    c.toggle()
    engine.draft = "Niedokończone"
    c.toggle()
    assert c.state is State.IDLE and platform.typed == []
    assert c.copy_last_unsent() and platform.clipboard == "Niedokończone"


def test_microphone_failure_returns_to_idle():
    c, platform, engine, ui, clock = make()
    c.toggle()
    engine.draft = "Coś"
    c.on_failed("Problem z mikrofonem")
    assert c.state is State.IDLE and c.last_unsent == "Coś" and ui.notes[-1] == "Problem z mikrofonem"


def test_cancel_phrase_stops():
    c, platform, engine, ui, clock = make()
    c.toggle()
    c.on_event(Event(Action.CANCEL, ""))
    assert c.state is State.IDLE and "Anulowano" in ui.notes[-1]


def test_typing_failure_falls_back_to_clipboard():
    c, platform, engine, ui, clock = make()

    def broken(text):
        raise OSError("zablokowane")

    platform.type_text = broken
    c.toggle()
    say_safe_phrase(c, engine, "Tekst.")
    clock.fire()
    assert platform.clipboard == "Tekst." and "zablokowane" in ui.notes[-1]


def test_hotkey_fallback_when_taken():
    c, platform, engine, ui, clock = make()
    platform.taken.add("ctrl+alt+d")
    assert c.register_hotkey() == "f9"
    assert "zajęty" in ui.notes[-1]


def test_altgr_hotkey_in_config_is_replaced():
    c, platform, engine, ui, clock = make(hotkey="ctrl+alt+z")
    assert c.register_hotkey() == "ctrl+alt+d"
    assert "AltGr" in ui.notes[-1]


def test_hotkey_while_loading_only_informs():
    platform, engine, ui, clock = FakePlatform(), FakeEngine(), FakeUI(), Clock()
    c = Controller(platform, engine, ui, clock.schedule, dict(DEFAULTS["app"]))
    c.toggle()
    assert c.state is State.LOADING and engine.started == 0 and "ładuję" in ui.notes[-1]


def test_long_text_is_pasted():
    p = FakePlatform()
    assert choose_delivery("x" * 301, 1, p, "auto", 300).method == "paste"
    assert choose_delivery("krótko", 1, p, "auto", 300).method == "type"
    assert choose_delivery("krótko", 1, p, "clipboard", 300).method == "clipboard"


# ----------------------------------------------------------------------- Qt


def test_overlay_and_tray_build_offscreen():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from dictaitor.app.ui import COLORS, Overlay, QtUI, dot_icon

    app = QApplication.instance() or QApplication([])
    overlay = Overlay()
    ui = QtUI(QSystemTrayIcon(dot_icon(COLORS[State.IDLE])), overlay)
    ui.show(State.LISTENING, "Cześć <b>Ania</b>", "Notatnik")
    ui.preview("i jeszcze")
    assert "&lt;b&gt;" in overlay.draft.text() and "i jeszcze" in overlay.draft.text()
    ui.show(State.IDLE)
    assert app is not None


# ------------------------------------------------------------- Windows only


@pytest.mark.skipif(os.name != "nt", reason="Windows API")
def test_windows_hotkey_register_and_clipboard_roundtrip():
    from dictaitor.app.win32 import WindowsPlatform

    p = WindowsPlatform()
    hk = hotkeys.parse("ctrl+alt+shift+f12")
    assert p.register_hotkey(hk, lambda: None)
    assert not p.register_hotkey(hk, lambda: None)  # second owner is refused
    p.unregister_hotkey(hk)
    p.set_clipboard("zażółć gęślą jaźń")
    assert p.get_clipboard() == "zażółć gęślą jaźń"
    assert isinstance(p.foreground_window(), int)
