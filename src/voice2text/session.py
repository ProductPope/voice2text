"""One dictation session: chunks in, text out only after the safe phrase."""

from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from typing import Callable

from . import output
from .composer import Composer, Word
from .config import Config, home_dir
from .gate import Action, Gate
from .learning import LearnedStore, apply_replacements
from .polish import PolishError, polish


@dataclass
class Event:
    action: Action
    draft: str
    sent: str | None = None
    info: str = ""


def edit_in_editor(text: str) -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "nano"
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
    ):
        self.config = config
        self.store = store or LearnedStore.load(home_dir() / "learned.json")
        self.sink = sink or (lambda text: output.send(text, config))
        self.reviewer = reviewer or edit_in_editor
        self.gate = Gate(config)
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

    def feed(self, words: list[Word], followed_by_pause: bool = True) -> Event:
        result = self.gate.check(words, followed_by_pause)
        self.composer.add_words(result.words)
        if result.action is Action.CANCEL:
            self._new_composer()
            return Event(Action.CANCEL, "", info="anulowano, szkic wyczyszczony")
        if result.action is Action.SEND:
            return self._send()
        return Event(Action.CONTINUE, self.draft())

    def _send(self) -> Event:
        draft = self.draft()
        if not draft:
            return Event(Action.CONTINUE, "", info="pusty szkic, nic nie wysłano")
        boundaries = list(self.composer.boundaries)
        final = draft
        notes = []
        if self.config["polish"]["enabled"]:
            try:
                final = polish(final, self.config)
            except PolishError as exc:
                notes.append(str(exc))
        if self.config["review"]["enabled"]:
            shown = final
            final = self.reviewer(shown)
            if not final:
                self._new_composer()
                return Event(Action.CANCEL, "", info="pusty tekst po edycji, nic nie wysłano")
            # Only the user's own edits teach word rules (not the LLM's);
            # pauses are matched against the raw draft they were measured on.
            learned = self.store.learn_words(shown, final)
            self.store.learn_pauses(final, boundaries)
            self.store.save()
            if learned:
                notes.append("zapamiętano: " + ", ".join(f"{a} → {b}" for a, b in learned))
        notes.insert(0, self.sink(final))
        self._new_composer()
        return Event(Action.SEND, "", sent=final, info="; ".join(notes))
