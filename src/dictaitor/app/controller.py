"""App logic without any GUI code, so every rule here is unit-tested.

Flow: hotkey -> remember the active window -> listen -> safe phrase ->
short countdown (Esc keeps the draft) -> deliver into the remembered window,
or to the clipboard when typing there would be unsafe.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from ..gate import Action
from ..i18n import t
from ..session import Event
from . import hotkeys
from .platform import Platform

ESCAPE = hotkeys.Hotkey("esc", 0, 0x1B)
log = logging.getLogger("dictaitor.app")


class State(Enum):
    LOADING = "loading"
    IDLE = "idle"
    LISTENING = "listening"
    PENDING = "pending"
    SENDING = "sending"  # optional AI clean-up running, then delivery


@dataclass
class Delivery:
    method: str  # "type" | "paste" | "clipboard"
    reason: str = ""


class Engine(Protocol):
    def start(self, context: str = "") -> None: ...
    def stop(self) -> str: ...  # returns the unsent draft
    def confirm(self, done: Callable[[Event], None]) -> None: ...  # may finish on another tick
    def cancel_pending(self) -> None: ...
    def learn_correction(self, corrected: str) -> list[tuple[str, str]]: ...
    def send_now(self) -> None: ...  # finish the utterance in progress, then request a send


class UI(Protocol):
    def show(self, state: State, draft: str = "", detail: str = "") -> None: ...
    def preview(self, text: str) -> None: ...
    def notify(self, message: str) -> None: ...
    def ask_correction(self, text: str) -> None: ...  # calls Controller.apply_correction later


Schedule = Callable[[float, Callable[[], None]], Callable[[], None]]  # returns a cancel function


def choose_delivery(text: str, target: int, platform: Platform, mode: str, paste_over: int) -> Delivery:
    if mode == "clipboard":
        return Delivery("clipboard")
    current = platform.foreground_window()
    if target and current != target and platform.is_own_window(current):
        # Our own overlay/dialog got the focus; hand it back to where you were.
        platform.focus_window(target)
        current = platform.foreground_window()
    if not target or current != target:
        return Delivery(
            "clipboard",
            t(
                "Aktywne okno się zmieniło – tekst czeka w schowku (Ctrl+V).",
                "The active window changed – the text is on the clipboard (Ctrl+V).",
            ),
        )
    if platform.is_elevated_window(target):
        return Delivery(
            "clipboard",
            t(
                "To okno działa jako administrator i Windows nie pozwala do niego pisać – tekst jest w schowku.",
                "That window runs as administrator and Windows won't let other apps type into it"
                " – the text is on the clipboard.",
            ),
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
        self._button_send = False  # "Wyślij" clicked: deliver without the Esc countdown

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
                log.info("dictation hotkey: %s", spec)
                self.hotkey = hk
                if spec != self.cfg["hotkey"]:
                    reason = (
                        problems[0]
                        if problems
                        else t(
                            f"{self.cfg['hotkey']} jest zajęty przez inny program",
                            f"{self.cfg['hotkey']} is taken by another program",
                        )
                    )
                    self.ui.notify(t(f"{reason}. Używam {spec}.", f"{reason}. Using {spec}."))
                return spec
            problems.append(t(f"{spec} jest zajęty przez inny program", f"{spec} is taken by another program"))
        self.ui.notify(
            t(
                "Nie udało się ustawić żadnego skrótu – użyj menu w zasobniku.",
                "Couldn't set any hotkey – use the tray menu.",
            )
        )
        return None

    def register_correct_hotkey(self) -> str | None:
        spec = self.cfg.get("correct_hotkey", "")
        if not spec:
            return None
        try:
            hk = hotkeys.parse(spec)
        except hotkeys.HotkeyError as exc:
            self.ui.notify(t(f"Skrót „popraw ostatni”: {exc}", f"“Correct last” hotkey: {exc}"))
            return None
        if self.platform.register_hotkey(hk, self.correct):
            return spec
        self.ui.notify(
            t(
                f"Skrót „popraw ostatni” ({spec}) jest zajęty – użyj menu w zasobniku.",
                f"The “correct last” hotkey ({spec}) is taken – use the tray menu.",
            )
        )
        return None

    def on_ready(self, description: str) -> None:
        self._set(State.IDLE, detail=description)

    def on_failed(self, message: str) -> None:
        log.warning("failure in state %s: %s", self.state.value, message)
        if self.state in (State.LISTENING, State.PENDING, State.SENDING):
            self._stop_countdown()
            draft = self.engine.stop()
            if draft:
                self.last_unsent = draft
            self._set(State.IDLE)
        self.ui.notify(message)

    # ------------------------------------------------------------ actions

    def toggle(self) -> None:
        if self.state is State.LOADING:
            self.ui.notify(
                t(
                    "Jeszcze ładuję model mowy – za chwilę będzie gotowy.",
                    "Still loading the speech model – almost ready.",
                )
            )
        elif self.state is State.IDLE:
            self.target = self.platform.foreground_window()
            title = self.platform.window_title(self.target)
            self.engine.start(title)
            self._set(State.LISTENING, detail=title)
        elif self.state is State.LISTENING:
            # Hotkey again = stop without sending. Keep the draft recoverable.
            draft = self.engine.stop()
            if draft:
                self.last_unsent = draft
                self.ui.notify(
                    t(
                        "Przerwano – nic nie wysłano. Szkic można odzyskać z menu w zasobniku.",
                        "Stopped – nothing was sent. You can recover the draft from the tray menu.",
                    )
                )
            self._set(State.IDLE)
        elif self.state is State.PENDING:
            self.escape()
        elif self.state is State.SENDING:
            self.ui.notify(t("Kończę przygotowywanie tekstu – chwilę.", "Finishing the text – one moment."))

    def send_now(self) -> None:
        """The overlay's "Wyślij" button."""
        if self.state is State.LISTENING:
            self._button_send = True
            self.engine.send_now()
        elif self.state is State.PENDING:
            self._finish()  # already counting down: skip the rest of the wait

    def cancel(self) -> None:
        """The overlay's "Anuluj" button: never sends anything."""
        if self.state is State.PENDING:
            self.escape()  # stop the countdown, keep dictating
        elif self.state is State.LISTENING:
            self.toggle()  # stop listening; the draft stays recoverable from the tray menu

    def escape(self) -> None:
        if self.state is not State.PENDING:
            return
        self._stop_countdown()
        self.engine.cancel_pending()
        self._set(
            State.LISTENING,
            detail=t(
                "Anulowano wysyłkę – mów dalej albo powiedz hasło ponownie.",
                "Send cancelled – keep talking or say the phrase again.",
            ),
        )

    def on_preview(self, text: str) -> None:
        if self.state is State.LISTENING:
            self.ui.preview(text)

    def on_event(self, event: Event) -> None:
        if self.state not in (State.LISTENING, State.PENDING):
            return
        if event.action is Action.CONTINUE:
            if self._button_send and event.info:
                self._button_send = False
                self.ui.notify(event.info)
            self._set(State.LISTENING, draft=event.draft or self._last_draft)
        elif event.action is Action.CANCEL:
            self.engine.stop()
            self._set(State.IDLE)
            self.ui.notify(
                t("Anulowano – szkic wyczyszczony, nic nie wysłano.", "Cancelled – draft cleared, nothing was sent.")
            )
        elif event.action is Action.PENDING and self.state is State.LISTENING:
            seconds = float(self.cfg["abort_seconds"])
            if seconds <= 0 or self._button_send:
                self._button_send = False
                self.state = State.PENDING
                self._finish()
                return
            self._set(
                State.PENDING,
                draft=event.draft,
                detail=t(f"Wpisuję za {seconds:.1f} s – Esc anuluje", f"Typing in {seconds:.1f} s – Esc cancels"),
            )
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
        detail = t("porządkuję tekst…", "tidying up the text…") if self.cfg.get("intent_mode", "off") != "off" else ""
        self._set(State.SENDING, detail=detail)
        self.engine.confirm(self._on_confirmed)

    def _on_confirmed(self, event: Event) -> None:
        if self.state is not State.SENDING:
            return
        self.engine.stop()
        self._set(State.IDLE)
        text = event.sent or ""
        notes = event.info.strip("; ")
        if text:
            self.deliver(text)
        if notes:
            self.ui.notify(notes)

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
            log.exception("delivery by %s failed", delivery.method)
            self.platform.set_clipboard(text)
            delivery = Delivery(
                "clipboard",
                t(
                    f"Nie udało się wpisać ({exc}) – tekst jest w schowku.",
                    f"Couldn't type ({exc}) – the text is on the clipboard.",
                ),
            )
        # Only the method and length are logged, never the text itself.
        log.info("delivered %d chars by %s %s", len(text), delivery.method, delivery.reason[:40])
        self.last_sent = text
        if delivery.reason:
            self.ui.notify(delivery.reason)
        return delivery

    def correct(self) -> None:
        """Ctrl+Alt+K: fix the last sent text so dictAItor learns from it."""
        if self.state in (State.LISTENING, State.PENDING, State.SENDING):
            self.ui.notify(t("Najpierw dokończ albo przerwij dyktowanie.", "Finish or stop dictating first."))
        elif not self.last_sent:
            self.ui.notify(
                t("Nic jeszcze nie zostało wysłane w tej sesji.", "Nothing has been sent in this session yet.")
            )
        else:
            self.ui.ask_correction(self.last_sent)

    def apply_correction(self, corrected: str, copy: bool = False) -> list[tuple[str, str]]:
        corrected = corrected.strip()
        if not corrected or corrected == self.last_sent:
            return []
        learned = self.engine.learn_correction(corrected)
        self.last_sent = corrected
        if copy:
            self.platform.set_clipboard(corrected)
        if learned:
            rules = ", ".join(f"„{a}” → „{b}”" for a, b in learned)
            self.ui.notify(
                t(
                    f"Zapamiętane: {rules}. Po kolejnych takich poprawkach będę to robić sam.",
                    f"Noted: {rules}. After a few more corrections like this I'll do it myself.",
                )
            )
        else:
            clip = t(" Poprawiony tekst jest w schowku.", " The corrected text is on the clipboard.") if copy else ""
            self.ui.notify(t("Zapamiętane (styl i pauzy).", "Noted (style and pauses).") + clip)
        return learned

    def copy_last_unsent(self) -> bool:
        if not self.last_unsent:
            return False
        self.platform.set_clipboard(self.last_unsent)
        return True

    @property
    def _last_draft(self) -> str:
        return getattr(self, "_draft", "")

    def _set(self, state: State, draft: str = "", detail: str = "") -> None:
        if draft:
            self._draft = draft
        if state is State.IDLE:
            self._draft = ""
            self._button_send = False
        if state is not self.state:
            log.info("state %s -> %s", self.state.value, state.value)
        self.state = state
        self.ui.show(state, draft, detail)
