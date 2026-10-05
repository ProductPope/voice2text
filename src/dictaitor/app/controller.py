"""App logic without any GUI code, so every rule here is unit-tested.

Flow: hotkey -> remember the active window -> listen -> safe phrase ->
short countdown (Esc keeps the draft) -> deliver into the remembered window,
or to the clipboard when typing there would be unsafe.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

from ..gate import Action
from ..session import Event
from . import hotkeys
from .platform import Platform

ESCAPE = hotkeys.Hotkey("esc", 0, 0x1B)


class State(Enum):
    LOADING = "loading"
    IDLE = "idle"
    LISTENING = "listening"
    PENDING = "pending"


@dataclass
class Delivery:
    method: str  # "type" | "paste" | "clipboard"
    reason: str = ""


class Engine(Protocol):
    def start(self) -> None: ...
    def stop(self) -> str: ...  # returns the unsent draft
    def confirm(self) -> Event: ...
    def cancel_pending(self) -> None: ...


class UI(Protocol):
    def show(self, state: State, draft: str = "", detail: str = "") -> None: ...
    def preview(self, text: str) -> None: ...
    def notify(self, message: str) -> None: ...


Schedule = Callable[[float, Callable[[], None]], Callable[[], None]]  # returns a cancel function


def choose_delivery(text: str, target: int, platform: Platform, mode: str, paste_over: int) -> Delivery:
    if mode == "clipboard":
        return Delivery("clipboard")
    if not target or platform.foreground_window() != target:
        return Delivery("clipboard", "Aktywne okno się zmieniło – tekst czeka w schowku (Ctrl+V).")
    if platform.is_elevated_window(target):
        return Delivery(
            "clipboard", "To okno działa jako administrator i Windows nie pozwala do niego pisać – tekst jest w schowku."
        )
    # A typed newline is Enter: in a chat or in Claude Code it would send half
    # the message. Multi-line (and long) text is pasted instead.
    if mode == "paste" or "\n" in text or len(text) > paste_over:
        return Delivery("paste")
    return Delivery("type")


class Controller:
    def __init__(self, platform: Platform, engine: Engine, ui: UI, schedule: Schedule, app_config: dict):
        self.platform = platform
        self.engine = engine
        self.ui = ui
        self.schedule = schedule
        self.cfg = app_config
        self.state = State.LOADING
        self.target = 0
        self.last_sent = ""
        self.last_unsent = ""
        self.hotkey: hotkeys.Hotkey | None = None
        self._cancel_timer: Callable[[], None] | None = None

    # ------------------------------------------------------------- setup

    def register_hotkey(self) -> str | None:
        """Register the dictation hotkey, falling back to a free one if taken."""
        problems = []
        for spec in hotkeys.candidates(self.cfg["hotkey"]):
            try:
                hk = hotkeys.parse(spec)
            except hotkeys.HotkeyError as exc:
                problems.append(str(exc))
                continue
            if self.platform.register_hotkey(hk, self.toggle):
                self.hotkey = hk
                if spec != self.cfg["hotkey"]:
                    reason = problems[0] if problems else f"{self.cfg['hotkey']} jest zajęty przez inny program"
                    self.ui.notify(f"{reason}. Używam {spec}.")
                return spec
            problems.append(f"{spec} jest zajęty przez inny program")
        self.ui.notify("Nie udało się ustawić żadnego skrótu – użyj menu w zasobniku.")
        return None

    def on_ready(self, description: str) -> None:
        self._set(State.IDLE, detail=description)

    def on_failed(self, message: str) -> None:
        if self.state in (State.LISTENING, State.PENDING):
            self._stop_countdown()
            draft = self.engine.stop()
            if draft:
                self.last_unsent = draft
            self._set(State.IDLE)
        self.ui.notify(message)

    # ------------------------------------------------------------ actions

    def toggle(self) -> None:
        if self.state is State.LOADING:
            self.ui.notify("Jeszcze ładuję model mowy – za chwilę będzie gotowy.")
        elif self.state is State.IDLE:
            self.target = self.platform.foreground_window()
            self.engine.start()
            self._set(State.LISTENING, detail=self.platform.window_title(self.target))
        elif self.state is State.LISTENING:
            # Hotkey again = stop without sending. Keep the draft recoverable.
            draft = self.engine.stop()
            if draft:
                self.last_unsent = draft
                self.ui.notify("Przerwano – nic nie wysłano. Szkic można odzyskać z menu w zasobniku.")
            self._set(State.IDLE)
        elif self.state is State.PENDING:
            self.escape()

    def escape(self) -> None:
        if self.state is not State.PENDING:
            return
        self._stop_countdown()
        self.engine.cancel_pending()
        self._set(State.LISTENING, detail="Anulowano wysyłkę – mów dalej albo powiedz hasło ponownie.")

    def on_preview(self, text: str) -> None:
        if self.state is State.LISTENING:
            self.ui.preview(text)

    def on_event(self, event: Event) -> None:
        if self.state not in (State.LISTENING, State.PENDING):
            return
        if event.action is Action.CONTINUE:
            self._set(State.LISTENING, draft=event.draft)
        elif event.action is Action.CANCEL:
            self.engine.stop()
            self._set(State.IDLE)
            self.ui.notify("Anulowano – szkic wyczyszczony, nic nie wysłano.")
        elif event.action is Action.PENDING and self.state is State.LISTENING:
            seconds = float(self.cfg["abort_seconds"])
            if seconds <= 0:
                self._finish()
                return
            self._set(State.PENDING, draft=event.draft, detail=f"Wpisuję za {seconds:.1f} s – Esc anuluje")
            self.platform.register_hotkey(ESCAPE, self.escape)
            self._cancel_timer = self.schedule(seconds, self._finish)

    # ----------------------------------------------------------- delivery

    def _stop_countdown(self) -> None:
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
        self.platform.unregister_hotkey(ESCAPE)

    def _finish(self) -> None:
        if self.state is not State.PENDING and self.cfg["abort_seconds"] > 0:
            return
        self._stop_countdown()
        event = self.engine.confirm()
        self.engine.stop()
        text = event.sent or ""
        self._set(State.IDLE)
        if text:
            self.deliver(text)

    def deliver(self, text: str) -> Delivery:
        delivery = choose_delivery(
            text, self.target, self.platform, self.cfg["delivery"], int(self.cfg["paste_over_chars"])
        )
        try:
            if delivery.method == "type":
                self.platform.type_text(text)
            elif delivery.method == "paste":
                self.platform.paste_text(text)
            else:
                self.platform.set_clipboard(text)
        except Exception as exc:
            self.platform.set_clipboard(text)
            delivery = Delivery("clipboard", f"Nie udało się wpisać ({exc}) – tekst jest w schowku.")
        self.last_sent = text
        if delivery.reason:
            self.ui.notify(delivery.reason)
        return delivery

    def copy_last_unsent(self) -> bool:
        if not self.last_unsent:
            return False
        self.platform.set_clipboard(self.last_unsent)
        return True

    def _set(self, state: State, draft: str = "", detail: str = "") -> None:
        self.state = state
        self.ui.show(state, draft, detail)
