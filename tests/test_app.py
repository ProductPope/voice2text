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

    def start(self, context=""):
        self.started += 1
        self.context = context

    def stop(self):
        draft, self.draft = self.draft, ""
        return draft

    def confirm(self, done):
        text, self.pending = self.pending, None
        done(Event(Action.SEND, "", sent=text, info=getattr(self, "info", "")))

    def cancel_pending(self):
        self.cancelled += 1

    def learn_correction(self, corrected):
        self.corrections = getattr(self, "corrections", []) + [corrected]
        return [("postgres", "PostgreSQL")] if "PostgreSQL" in corrected else []


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

    def ask_correction(self, text):
        self.asked = text


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


def test_correct_last_flow():
    c, platform, engine, ui, clock = make()
    c.correct()
    assert "Nic jeszcze" in ui.notes[-1]
    c.toggle()
    say_safe_phrase(c, engine, "Baza to postgres.")
    clock.fire()
    c.correct()
    assert ui.asked == "Baza to postgres."
    assert c.apply_correction("Baza to PostgreSQL.", copy=True) == [("postgres", "PostgreSQL")]
    assert platform.clipboard == "Baza to PostgreSQL." and "Zapamiętane" in ui.notes[-1]
    assert c.apply_correction("Baza to PostgreSQL.") == []  # unchanged: nothing to learn


def test_correct_hotkey_registration():
    c, platform, engine, ui, clock = make()
    assert c.register_correct_hotkey() == "ctrl+alt+k"
    platform.press("ctrl+alt+k")
    assert "Nic jeszcze" in ui.notes[-1]
    c2, p2, *_ = make(correct_hotkey="ctrl+alt+z")
    assert c2.register_correct_hotkey() is None


# ------------------------------------------------------------- Qt dialogs


@pytest.fixture
def qapp():
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_correction_dialog_reports_edit(qapp):
    from dictaitor.app.dialogs import CorrectionDialog

    got = []
    d = CorrectionDialog("Baza to postgres.", lambda text, copy: got.append((text, copy)))
    d.edit.setPlainText("Baza to PostgreSQL.")
    d.save_copy.click()
    assert got == [("Baza to PostgreSQL.", True)]


def test_settings_dialog_saves_to_config_file(qapp, tmp_path):
    from dictaitor.app.dialogs import SettingsDialog
    from dictaitor.config import Config

    path = tmp_path / "config.toml"
    saved = []
    d = SettingsDialog(Config(), path, lambda phrase: None, lambda: saved.append(True))
    d.send_phrase.setText("zatwierdzam bez zmian")
    d.hotkey.setText("F9")
    d.abort.setValue(1.2)
    d.delivery.setCurrentIndex(d.delivery.findData("paste"))
    d._save()
    cfg = Config.load(path)
    assert cfg["gate"]["send_phrase"] == "zatwierdzam bez zmian"
    assert (cfg["app"]["hotkey"], cfg["app"]["abort_seconds"], cfg["app"]["delivery"]) == ("f9", 1.2, "paste")
    assert saved == [True]


def test_settings_dialog_refuses_altgr_hotkey(qapp, tmp_path, monkeypatch):
    from dictaitor.app import dialogs
    from dictaitor.config import Config

    warnings = []
    monkeypatch.setattr(dialogs.QMessageBox, "warning", lambda *a: warnings.append(a[-1]))
    d = dialogs.SettingsDialog(Config(), tmp_path / "c.toml", lambda p: None, lambda: None)
    d.hotkey.setText("ctrl+alt+z")
    d._save()
    assert "AltGr" in warnings[0] and not (tmp_path / "c.toml").exists()


def test_rules_dialog_lists_and_deletes(qapp):
    from dictaitor.app.dialogs import RulesDialog
    from dictaitor.config import Config
    from dictaitor.learning import LearnedStore

    store = LearnedStore()
    store.add_replacement("ajfon", "iPhone", weight=2)
    store.add_replacement("postgres", "PostgreSQL")
    d = RulesDialog(store, Config())
    assert d.table.rowCount() == 2 and "aktywne od 2" in d.table.item(1, 2).text()
    d.table.selectRow(0)
    d._delete()
    assert list(store.replacements) == ["postgres"]


def test_phrase_test_dialog_shows_verdict(qapp):
    from dictaitor.app.dialogs import PhraseTestDialog
    from dictaitor.phrase import check_phrase

    d = PhraseTestDialog("zatwierdzam bez zmian")
    d.add_heard("zatwierdzam bez zmian")
    d.show_result(check_phrase("zatwierdzam bez zmian", ["zatwierdzam bez zmian"] * 3, 0.8))
    assert "dobre" in d.label.text()


def test_window_title_is_passed_for_style_profiles():
    c, platform, engine, ui, clock = make()
    platform.window = 7
    c.toggle()
    assert engine.context == "okno 7"


def test_ai_notes_are_shown_after_delivery():
    c, platform, engine, ui, clock = make(intent_mode="local")
    engine.info = "; porządkowanie AI pominięte: lokalny model nie odpowiada"
    c.toggle()
    say_safe_phrase(c, engine, "Tekst.")
    clock.fire()
    assert platform.typed == ["Tekst."] and ui.notes[-1].startswith("porządkowanie AI pominięte")


def test_esc_is_ignored_while_sending():
    c, platform, engine, ui, clock = make()
    engine.confirm = lambda done: None  # AI still working
    c.toggle()
    say_safe_phrase(c, engine, "Tekst.")
    clock.fire()
    assert c.state is State.SENDING
    c.escape()
    c.toggle()
    assert c.state is State.SENDING and "chwilę" in ui.notes[-1]


def test_settings_enabling_claude_needs_consent_and_key(qapp, tmp_path, monkeypatch):
    from dictaitor.app import dialogs
    from dictaitor.config import Config

    stored = {}
    monkeypatch.setattr(dialogs.intent, "get_api_key", lambda: stored.get("key"))
    monkeypatch.setattr(dialogs.intent, "set_api_key", lambda k: stored.update(key=k))
    answers = [dialogs.QMessageBox.No, dialogs.QMessageBox.Yes]
    monkeypatch.setattr(dialogs.QMessageBox, "question", lambda *a: answers.pop(0))
    path = tmp_path / "config.toml"
    d = dialogs.SettingsDialog(Config(), path, lambda p: None, lambda: None)
    d.intent_mode.setCurrentIndex(d.intent_mode.findData("claude"))
    d.api_key.setText("sk-ant-test")
    d._save()  # consent declined -> nothing saved
    assert not path.exists() and stored == {}
    d._save()
    cfg = Config.load(path)
    assert cfg["intent"]["mode"] == "claude" and stored == {"key": "sk-ant-test"}
    assert "sk-ant" not in path.read_text(encoding="utf-8")  # the key never lands in config files


# ------------------------------------------------------------ diagnostics


def test_log_never_contains_dictated_text(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="dictaitor")
    c, platform, engine, ui, clock = make()
    c.register_hotkey()
    c.toggle()
    say_safe_phrase(c, engine, "Tajne hasło do banku 1234.")
    clock.fire()
    assert platform.typed == ["Tajne hasło do banku 1234."]
    assert "delivered 26 chars by type" in caplog.text
    assert "Tajne" not in caplog.text and "1234" not in caplog.text


def test_setup_logging_and_excepthook(tmp_path, monkeypatch):
    import sys
    import threading

    from dictaitor import diagnostics

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    path = diagnostics.setup_logging(tmp_path)
    reports = []
    diagnostics.install_excepthook(reports.append)
    try:
        raise ValueError("boom")
    except ValueError:
        sys.excepthook(*sys.exc_info())
    for h in diagnostics.log.handlers:
        h.flush()
    text = path.read_text(encoding="utf-8")
    assert "start dictAItor" in text and "ValueError: boom" in text
    assert "ValueError" in reports[0]
    for h in list(diagnostics.log.handlers):
        diagnostics.log.removeHandler(h)
        h.close()


def test_model_cache_check_handles_unknown_model():
    from dictaitor.diagnostics import model_is_cached

    assert model_is_cached("definitely-not-a-model") is False
