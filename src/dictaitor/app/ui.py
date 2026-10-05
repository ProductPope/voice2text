"""Qt layer: tray icon, draft overlay, background engine. Logic lives in controller.py."""

from __future__ import annotations

import html
import os
import subprocess
import sys
import threading

from PySide6.QtCore import QLockFile, QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QSystemTrayIcon, QVBoxLayout, QWidget

from ..audio import chunker_for, microphone_frames
from ..config import Config, home_dir
from ..learning import LearnedStore
from ..pipeline import Pipeline
from ..session import Event, Session
from .controller import Controller, State
from .platform import FakePlatform, get_platform

COLORS = {
    State.LOADING: "#9aa0a6",
    State.IDLE: "#5f6368",
    State.LISTENING: "#d93025",
    State.PENDING: "#f29900",
}
STATUS = {
    State.LOADING: "Ładuję model mowy…",
    State.IDLE: "Gotowy",
    State.LISTENING: "Słucham – powiedz hasło, żeby wpisać",
    State.PENDING: "Hasło rozpoznane",
}


def dot_icon(color: str) -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(color))
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

    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.store = LearnedStore.load(home_dir() / "learned.json")
        self.session: Session | None = None
        self.transcriber = None
        self._lock = threading.Lock()
        self._listening = threading.Event()
        self._thread: threading.Thread | None = None

    def load(self) -> None:
        threading.Thread(target=self._load, daemon=True, name="dictaitor-load").start()

    def _load(self) -> None:
        try:
            from ..transcriber import Transcriber

            vocab = self.store.vocabulary(self.config["learning"]["min_occurrences"])
            self.transcriber = Transcriber(self.config, vocab)
            self.session = Session(self.config, self.store, sink=lambda text: "", confirm=True)
            c = self.transcriber.choice
            where = "karta graficzna" if c.device == "cuda" else "procesor"
            note = f" ({self.transcriber.warning})" if self.transcriber.warning else ""
            self.ready.emit(f"Model {c.model}, {where}{note}")
        except Exception as exc:
            self.failed.emit(f"Nie udało się załadować modelu: {exc}")

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            self._listening.clear()
            self._thread.join(timeout=2)
        with self._lock:
            self.session.reset()
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
            self.failed.emit(f"Problem z mikrofonem: {exc}")

    def stop(self) -> str:
        self._listening.clear()
        with self._lock:
            draft = self.session.draft() if self.session else ""
            if self.session:
                self.session.reset()
        return draft

    def confirm(self) -> Event:
        with self._lock:
            return self.session.confirm_send()

    def cancel_pending(self) -> None:
        with self._lock:
            self.session.cancel_pending()


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
        if state in (State.LISTENING, State.PENDING):
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
    def __init__(self, tray: QSystemTrayIcon, overlay: Overlay):
        self.tray = tray
        self.overlay = overlay

    def show(self, state: State, draft: str = "", detail: str = "") -> None:
        self.tray.setIcon(dot_icon(COLORS[state]))
        self.tray.setToolTip(f"dictAItor – {STATUS[state]}")
        self.overlay.update_view(state, draft, detail)

    def preview(self, text: str) -> None:
        self.overlay.show_preview(text)

    def notify(self, message: str) -> None:
        self.tray.showMessage("dictAItor", message, QSystemTrayIcon.Information, 5000)


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


def open_path(path) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - opens with the user's default app
    else:
        subprocess.Popen(["xdg-open", str(path)])


def main() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("dictAItor")

    home = home_dir()
    home.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(home / "app.lock"))
    if not lock.tryLock(100):
        print("dictAItor już działa (ikona w zasobniku).")
        return 0

    config = Config.load()
    app_cfg = dict(config["app"])
    platform = get_platform()
    if os.name != "nt":
        platform = QtClipboardPlatform()
        app_cfg["delivery"] = "clipboard"

    tray = QSystemTrayIcon(dot_icon(COLORS[State.LOADING]))
    overlay = Overlay()
    ui = QtUI(tray, overlay)
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

    menu = QMenu()
    dictate = QAction("Dyktuj")
    dictate.triggered.connect(controller.toggle)
    recover = QAction("Skopiuj ostatni niewysłany szkic")
    recover.triggered.connect(
        lambda: ui.notify("Szkic jest w schowku." if controller.copy_last_unsent() else "Brak niewysłanego szkicu.")
    )
    settings = QAction("Ustawienia (Notatnik)")

    def open_settings():
        path = home / "config.toml"
        if not path.exists():
            from importlib import resources

            path.write_bytes((resources.files("dictaitor") / "config.example.toml").read_bytes())
        open_path(path)

    settings.triggered.connect(open_settings)
    quit_action = QAction("Zakończ")
    quit_action.triggered.connect(app.quit)
    for action in (dictate, recover, settings):
        menu.addAction(action)
    menu.addSeparator()
    menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: reason == QSystemTrayIcon.Trigger and controller.toggle())
    tray.show()

    for warning in config.warnings:
        ui.notify(warning)
    spec = controller.register_hotkey()
    if spec:
        dictate.setText(f"Dyktuj ({spec.upper()})")
    ui.show(State.LOADING)
    engine.load()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
