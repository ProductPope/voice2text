"""Qt layer: tray icon, draft overlay, background engine. Logic lives in controller.py."""

from __future__ import annotations

import html
import logging
import os
import sys
import threading

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QMessageBox, QSystemTrayIcon, QVBoxLayout, QWidget

from ..audio import chunker_for, microphone_frames
from ..config import Config, home_dir
from ..diagnostics import install_excepthook, setup_logging
from ..learning import LearnedStore
from ..phrase import check_phrase
from ..pipeline import Pipeline
from ..session import Session
from .controller import Controller, State
from .dialogs import CorrectionDialog, PhraseTestDialog, RulesDialog, SettingsDialog, bring_to_front, open_path
from .platform import FakePlatform, get_platform

log = logging.getLogger("dictaitor.app")

COLORS = {
    State.LOADING: "#9aa0a6",
    State.IDLE: "#5f6368",
    State.LISTENING: "#d93025",
    State.PENDING: "#f29900",
    State.SENDING: "#1a73e8",
}
STATUS = {
    State.LOADING: "Ładuję model mowy…",
    State.IDLE: "Gotowy",
    State.LISTENING: "Słucham – powiedz hasło, żeby wpisać",
    State.PENDING: "Hasło rozpoznane",
    State.SENDING: "Wpisuję",
}


def dot_icon(color: str, cloud: bool = False) -> QIcon:
    """Coloured dot; a white ring means text may go to the cloud (Claude)."""
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
    if cloud:
        pen = p.pen()
        pen.setColor(QColor("#ffffff"))
        pen.setWidth(8)
        p.setPen(pen)
    else:
        p.setPen(Qt.NoPen)
    p.drawEllipse(6, 6, 52, 52)
    p.end()
    return QIcon(pix)


class Engine(QObject):
    """Model + microphone + session, running on background threads."""

    ready = Signal(str)
    failed = Signal(str)
    event = Signal(object)
    preview = Signal(str)
    confirmed = Signal(object, object)  # (callback, Event) - delivered on the Qt thread
    heard = Signal(str)  # phrase test: one utterance transcribed
    downloading = Signal(str)  # first start: the model is being downloaded
    capture_done = Signal()

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.store = LearnedStore.load(home_dir() / "learned.json")
        self.session: Session | None = None
        self.transcriber = None
        self._lock = threading.Lock()
        self._listening = threading.Event()
        self._capture_stop = threading.Event()
        self._thread: threading.Thread | None = None

    def load(self) -> None:
        threading.Thread(target=self._load, daemon=True, name="dictaitor-load").start()

    def _load(self) -> None:
        import time

        from ..diagnostics import model_is_cached
        from ..transcriber import resolve_model

        started = time.perf_counter()
        try:
            from ..transcriber import Transcriber

            choice = resolve_model(self.config)
            if not model_is_cached(choice.model):
                self.downloading.emit(choice.model)

            vocab = self.store.vocabulary(self.config["learning"]["min_occurrences"])
            self.transcriber = Transcriber(self.config, vocab)
            self.session = Session(self.config, self.store, sink=lambda text: "", confirm=True)
            c = self.transcriber.choice
            where = "karta graficzna" if c.device == "cuda" else "procesor"
            note = f" ({self.transcriber.warning})" if self.transcriber.warning else ""
            log.info("model %s on %s/%s loaded in %.1fs %s", c.model, c.device, c.compute_type,
                     time.perf_counter() - started, self.transcriber.warning)
            self.ready.emit(f"Model {c.model}, {where}{note}")
        except Exception as exc:
            log.exception("model load failed")
            self.failed.emit(f"Nie udało się załadować modelu: {exc}")

    def start(self, context: str = "") -> None:
        if self._thread and self._thread.is_alive():
            self._listening.clear()
            self._thread.join(timeout=2)
        with self._lock:
            self.session.reset()
            self.session.context = context
        self._listening.set()
        self._thread = threading.Thread(target=self._listen, daemon=True, name="dictaitor-mic")
        self._thread.start()

    def _listen(self) -> None:
        pipe = Pipeline(
            self.session, self.transcriber, chunker_for(self.config), self.config["audio"]["preview_interval"]
        )
        pipe.lock = self._lock
        try:
            for frame in microphone_frames():  # the microphone is open only inside this loop
                if not self._listening.is_set():
                    break
                event = pipe.push(frame)
                if event is not None:
                    self.event.emit(event)
                elif pipe.preview_due():
                    text = pipe.preview()
                    if text and self._listening.is_set():
                        self.preview.emit(text)
        except Exception as exc:
            log.exception("microphone loop failed")
            self.failed.emit(f"Problem z mikrofonem: {exc}")

    def stop(self) -> str:
        self._listening.clear()
        with self._lock:
            draft = self.session.draft() if self.session else ""
            if self.session:
                self.session.reset()
        return draft

    def confirm(self, done) -> None:
        """Finish the send off the UI thread: the optional AI step can take seconds."""

        def run():
            with self._lock:
                event = self.session.confirm_send()
            self.confirmed.emit(done, event)

        threading.Thread(target=run, daemon=True, name="dictaitor-send").start()

    def cancel_pending(self) -> None:
        with self._lock:
            self.session.cancel_pending()

    def learn_correction(self, corrected: str) -> list[tuple[str, str]]:
        with self._lock:
            learned = self.session.learn_correction(corrected)
        if learned and self.transcriber:
            # New names become hotwords right away.
            vocab = self.store.vocabulary(self.config["learning"]["min_occurrences"])
            self.transcriber.set_vocabulary(list(self.config["rules"]["vocabulary"]) + vocab)
        return learned

    def capture(self, utterances: int) -> None:
        """Phrase test: transcribe the next few utterances, nothing goes to the session."""

        def run():
            chunker = chunker_for(self.config)
            got = 0
            try:
                for frame in microphone_frames():
                    chunk = chunker.push(frame)
                    if chunk is not None:
                        text = " ".join(w.text for w in self.transcriber.transcribe(chunk.audio, chunk.offset)).strip()
                        if text:
                            self.heard.emit(text)
                            got += 1
                    if got >= utterances or self._capture_stop.is_set():
                        break
            except Exception as exc:
                self.failed.emit(f"Problem z mikrofonem: {exc}")
            self.capture_done.emit()

        self._capture_stop.clear()
        threading.Thread(target=run, daemon=True, name="dictaitor-phrase-test").start()

    def stop_capture(self) -> None:
        self._capture_stop.set()


class Overlay(QWidget):
    """Small always-on-top card with the live draft. Never takes keyboard focus."""

    def __init__(self):
        super().__init__(
            None,
            Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TranslucentBackground)
        card = QWidget(self)
        card.setObjectName("card")
        card.setStyleSheet(
            "#card { background: rgba(32,33,36,235); border-radius: 12px; }"
            "QLabel { color: #e8eaed; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        self.status = QLabel()
        bold = QFont()
        bold.setBold(True)
        self.status.setFont(bold)
        self.draft = QLabel()
        self.draft.setWordWrap(True)
        self.draft.setTextFormat(Qt.RichText)
        layout.addWidget(self.status)
        layout.addWidget(self.draft)
        self.setFixedWidth(560)
        self._draft_text = ""
        self._hide_timer = QTimer(self, singleShot=True, timeout=self.hide)

    def update_view(self, state: State, draft: str, detail: str) -> None:
        self._hide_timer.stop()
        color = COLORS[state]
        status = STATUS[state] + (f" – {detail}" if detail else "")
        self.status.setText(f'<span style="color:{color}">●</span> {status}')
        if state in (State.LISTENING, State.PENDING, State.SENDING):
            if draft or state is State.PENDING:
                self._draft_text = draft
            self._render(self._draft_text, "")
            self._place()
            self.show()
        else:
            self._draft_text = ""
            self._render("", "")
            self._hide_timer.start(1500)

    def show_preview(self, text: str) -> None:
        self._render(self._draft_text, text)

    def _render(self, draft: str, preview: str) -> None:
        def esc(t: str) -> str:
            return html.escape(t, quote=False).replace("\n", "<br>")

        body = esc(draft)
        if preview:
            body += f' <span style="color:#9aa0a6"><i>{esc(preview)}</i></span>'
        self.draft.setText(body or '<span style="color:#9aa0a6">…</span>')
        self.adjustSize()

    def _place(self) -> None:
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        self.move(screen.center().x() - self.width() // 2, screen.bottom() - self.height() - 40)


class QtUI:
    def __init__(self, tray: QSystemTrayIcon, overlay: Overlay, cloud: bool = False):
        self.tray = tray
        self.overlay = overlay
        self.cloud = cloud  # Claude enabled: text leaves the computer, so say so everywhere

    def show(self, state: State, draft: str = "", detail: str = "") -> None:
        self.tray.setIcon(dot_icon(COLORS[state], self.cloud))
        suffix = " – porządkowanie przez Claude (chmura)" if self.cloud else ""
        self.tray.setToolTip(f"dictAItor – {STATUS[state]}{suffix}")
        self.overlay.update_view(state, draft, detail)

    def preview(self, text: str) -> None:
        self.overlay.show_preview(text)

    def notify(self, message: str) -> None:
        self.tray.showMessage("dictAItor", message, QSystemTrayIcon.Information, 5000)

    def ask_correction(self, text: str) -> None:
        self.dialog = CorrectionDialog(text, self.on_correction)
        bring_to_front(self.dialog)

    on_correction = None  # set to Controller.apply_correction in main()


class _Bridge(QObject):
    """Hotkeys fire on a Windows thread; this hops them onto the Qt thread."""

    call = Signal(object)

    def __init__(self):
        super().__init__()
        self.call.connect(lambda fn: fn())


class QtClipboardPlatform(FakePlatform):
    """Non-Windows fallback: no typing or global hotkeys, clipboard only."""

    def set_clipboard(self, text: str) -> None:
        QGuiApplication.clipboard().setText(text)

    type_text = paste_text = set_clipboard


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("dictAItor")

    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(home / "app.lock"))
    if not lock.tryLock(5000):  # a restarting instance may still be closing
        QMessageBox.information(None, "dictAItor", "dictAItor już działa – szukaj kółka przy zegarze (strzałka ^).")
        return 0
    log_path = setup_logging(home)

    config = Config.load()
    app_cfg = dict(config["app"])
    app_cfg["intent_mode"] = config["intent"]["mode"]
    platform = get_platform()
    if os.name != "nt":
        platform = QtClipboardPlatform()
        app_cfg["delivery"] = "clipboard"

    tray = QSystemTrayIcon(dot_icon(COLORS[State.LOADING]))
    overlay = Overlay()
    ui = QtUI(tray, overlay, cloud=config["intent"]["mode"] == "claude")
    engine = Engine(config)
    bridge = _Bridge()

    def schedule(seconds, fn):
        timer = QTimer(singleShot=True)
        timer.timeout.connect(fn)
        timer.start(int(seconds * 1000))
        return timer.stop

    controller = Controller(platform, engine, ui, schedule, app_cfg)

    class ThreadSafePlatform:
        """Wraps hotkey callbacks so they run on the Qt thread."""

        def __getattr__(self, name):
            return getattr(platform, name)

        def register_hotkey(self, hotkey, callback):
            return platform.register_hotkey(hotkey, lambda: bridge.call.emit(callback))

    controller.platform = ThreadSafePlatform()
    engine.ready.connect(controller.on_ready)
    engine.failed.connect(controller.on_failed)
    engine.event.connect(controller.on_event)
    engine.preview.connect(controller.on_preview)
    engine.confirmed.connect(lambda done, event: done(event))

    ui.on_correction = controller.apply_correction
    install_excepthook(lambda message: bridge.call.emit(lambda: ui.notify(message)))
    engine.downloading.connect(
        lambda model: ui.notify(
            f"Pierwsze uruchomienie: pobieram model mowy „{model}” (kilkaset MB). "
            "To potrwa kilka minut – kółko zmieni kolor, gdy będzie gotowe."
        )
    )
    config_path = home / "config.toml"
    windows: dict = {}  # keeps open dialogs alive

    def restart():
        from PySide6.QtCore import QProcess

        lock.unlock()
        args = [] if getattr(sys, "frozen", False) else ["-m", "dictaitor.app"]
        QProcess.startDetached(sys.executable, args)
        app.quit()

    def open_rules():
        windows["rules"] = RulesDialog(engine.store, config)
        bring_to_front(windows["rules"])

    def test_phrase(phrase: str):
        if controller.state is not State.IDLE:
            ui.notify("Test hasła działa, gdy model jest gotowy i nie dyktujesz.")
            return
        dialog = PhraseTestDialog(phrase)
        windows["phrase"] = dialog
        heard = []

        def on_heard(text):
            heard.append(text)
            dialog.add_heard(text)

        def on_done():
            engine.heard.disconnect(on_heard)
            engine.capture_done.disconnect(on_done)
            if heard:
                g = config["gate"]
                dialog.show_result(check_phrase(phrase, heard, g["match_threshold"], g["cancel_phrase"]))

        engine.heard.connect(on_heard)
        engine.capture_done.connect(on_done)
        dialog.rejected.connect(engine.stop_capture)
        bring_to_front(dialog)
        engine.capture(dialog.times)

    def saved():
        answer = QMessageBox.question(
            None, "dictAItor", "Zapisano. Uruchomić aplikację ponownie, żeby zmiany zadziałały?"
        )
        if answer == QMessageBox.Yes:
            restart()

    def open_settings():
        windows["settings"] = SettingsDialog(config, config_path, test_phrase, saved)
        bring_to_front(windows["settings"])

    menu = QMenu()
    dictate = QAction("Dyktuj")
    dictate.triggered.connect(controller.toggle)
    correct = QAction("Popraw ostatni tekst")
    correct.triggered.connect(controller.correct)
    rules = QAction("Czego się nauczyłem…")
    rules.triggered.connect(open_rules)
    recover = QAction("Skopiuj ostatni niewysłany szkic")
    recover.triggered.connect(
        lambda: ui.notify("Szkic jest w schowku." if controller.copy_last_unsent() else "Brak niewysłanego szkicu.")
    )
    show_log = QAction("Dziennik błędów (do zgłoszenia problemu)")
    show_log.triggered.connect(lambda: open_path(log_path))
    settings = QAction("Ustawienia…")
    settings.triggered.connect(open_settings)
    restart_action = QAction("Uruchom ponownie")
    restart_action.triggered.connect(restart)
    quit_action = QAction("Zakończ")
    quit_action.triggered.connect(app.quit)
    for action in (dictate, correct, rules, recover):
        menu.addAction(action)
    menu.addSeparator()
    for action in (settings, show_log, restart_action, quit_action):
        menu.addAction(action)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: reason == QSystemTrayIcon.Trigger and controller.toggle())
    tray.show()

    for warning in config.warnings:
        ui.notify(warning)
    spec = controller.register_hotkey()
    if spec:
        dictate.setText(f"Dyktuj ({spec.upper()})")
    correct_spec = controller.register_correct_hotkey()
    if correct_spec:
        correct.setText(f"Popraw ostatni tekst ({correct_spec.upper()})")
    ui.show(State.LOADING)
    engine.load()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
