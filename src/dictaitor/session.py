"""One dictation session: chunks in, text out only after the safe phrase."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass

from . import output
from .composer import Composer, Word
from .config import Config, home_dir
from .gate import Action, Gate
from .i18n import t
from .intent import refine
from .learning import LearnedStore, apply_replacements


@dataclass
class Event:
    action: Action
    draft: str
    sent: str | None = None
    info: str = ""


def edit_in_editor(text: str) -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "nano")
    with tempfile.NamedTemporaryFile("w+", suffix=".txt", delete=False, encoding="utf-8") as fh:
        fh.write(text)
        path = fh.name
    try:
        subprocess.run([editor, path], check=False)
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    finally:
        os.unlink(path)


class Session:
    def __init__(
        self,
        config: Config,
        store: LearnedStore | None = None,
        sink: Callable[[str], str] | None = None,
        reviewer: Callable[[str], str] | None = None,
        confirm: bool = False,
    ):
        self.config = config
        self.store = store or LearnedStore.load(home_dir() / "learned.json")
        self.sink = sink or (lambda text: output.send(text, config))
        self.reviewer = reviewer or edit_in_editor
        self.gate = Gate(config)
        self.confirm = confirm
        self.pending: str | None = None
        # What was last sent, kept so "correct last" (Ctrl+Alt+K) can learn from it.
        self.last_sent = ""
        self.last_boundaries: list = []
        # Title of the window being dictated into, for per-app style profiles.
        self.context = ""
        self._new_composer()

    def _new_composer(self) -> None:
        comma, sentence = self.store.thresholds(self.config)
        self.composer = Composer(self.config, comma_gap=comma, sentence_gap=sentence)

    def rules(self) -> dict[str, str]:
        learned = self.store.active_replacements(self.config["learning"]["min_occurrences"])
        # Explicit rules from config.toml always win over learned ones.
        return {**learned, **self.config["rules"]["replacements"]}

    def draft(self) -> str:
        return apply_replacements(self.composer.render(), self.rules())

    def reset(self) -> None:
        """Start a fresh dictation (thresholds re-read, as they may have been learned)."""
        self.pending = None
        self._new_composer()

    def feed(self, words: list[Word], followed_by_pause: bool = True) -> Event:
        if self.pending is not None:
            # Speech during the countdown is ignored; the draft is frozen.
            return Event(Action.PENDING, self.pending)
        result = self.gate.check(words, followed_by_pause)
        self.last_marker = self.composer.add_words(result.words)
        self.last_had_command = self.composer.last_had_command
        if result.action is Action.CANCEL:
            self._new_composer()
            return Event(Action.CANCEL, "", info="anulowano, szkic wyczyszczony")
        if result.action is Action.SEND:
            if self.confirm:
                draft = self.draft()
                if not draft:
                    return Event(
                        Action.CONTINUE, "", info=t("pusty szkic, nic nie wysłano", "empty draft, nothing was sent")
                    )
                self.pending = draft
                return Event(Action.PENDING, draft)
            return self._send()
        return Event(Action.CONTINUE, self.draft())

    def request_send(self) -> Event:
        """The "Wyślij" button: same as saying the safe phrase."""
        if self.pending is not None:
            return Event(Action.PENDING, self.pending)
        draft = self.draft()
        if not draft:
            return Event(
                Action.CONTINUE, "", info=t("Nic jeszcze nie zostało podyktowane.", "Nothing has been dictated yet.")
            )
        if self.confirm:
            self.pending = draft
            return Event(Action.PENDING, draft)
        return self._send()

    def replace_since(self, marker: int, words: list[Word]) -> Event:
        """Swap the last chunk(s) for a better transcription of the same audio."""
        self.composer.rollback(marker)
        self.composer.add_words(words)
        return Event(Action.CONTINUE, self.draft())

    def confirm_send(self) -> Event:
        self.pending = None
        return self._send()

    def cancel_pending(self) -> None:
        """Esc during the countdown: nothing is sent, dictation can continue."""
        self.pending = None

    def learn_correction(self, corrected: str) -> list[tuple[str, str]]:
        """The user fixed the last sent text afterwards: learn words, pauses and style."""
        corrected = corrected.strip()
        if not self.last_sent or not corrected or corrected == self.last_sent:
            return []
        learned = self.store.learn_words(self.last_sent, corrected)
        self.store.learn_pauses(corrected, self.last_boundaries)
        self.store.add_example(self.last_sent, corrected)
        self.store.save()
        self.last_sent, self.last_boundaries = corrected, []  # pauses are learned once
        return learned

    def _send(self) -> Event:
        draft = self.draft()
        if not draft:
            return Event(Action.CONTINUE, "", info=t("pusty szkic, nic nie wysłano", "empty draft, nothing was sent"))
        boundaries = list(self.composer.boundaries)
        final = draft
        notes = []
        refined = refine(final, self.config, self.store.examples, self.context)
        final = refined.text
        if refined.note:
            notes.append(refined.note)
        if self.config["review"]["enabled"]:
            shown = final
            final = self.reviewer(shown)
            if not final:
                self._new_composer()
                return Event(
                    Action.CANCEL,
                    "",
                    info=t("pusty tekst po edycji, nic nie wysłano", "empty text after editing, nothing was sent"),
                )
            # Only the user's own edits teach word rules (not the LLM's);
            # pauses are matched against the raw draft they were measured on.
            learned = self.store.learn_words(shown, final)
            self.store.learn_pauses(final, boundaries)
            self.store.save()
            if learned:
                notes.append(t("zapamiętano: ", "learned: ") + ", ".join(f"{a} → {b}" for a, b in learned))
        notes.insert(0, self.sink(final))
        self.last_sent, self.last_boundaries = final, boundaries
        self._new_composer()
        return Event(Action.SEND, "", sent=final, info="; ".join(notes))
