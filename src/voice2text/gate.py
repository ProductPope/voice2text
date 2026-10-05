"""The send gate: nothing leaves the draft until the safe phrase is spoken."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .composer import Word
from .config import Config
from .textutil import matches_phrase, split_punct


class Action(Enum):
    CONTINUE = "continue"
    SEND = "send"
    CANCEL = "cancel"


@dataclass
class GateResult:
    action: Action
    words: list[Word]  # the chunk's words with the control phrase removed


class Gate:
    def __init__(self, config: Config):
        g = config["gate"]
        self.send_phrase: str = g["send_phrase"]
        self.cancel_phrase: str = g["cancel_phrase"]
        self.threshold: float = g["match_threshold"]
        self.require_pause: bool = g["require_pause"]

    def _tail_match(self, words: list[Word], phrase: str) -> int:
        """Number of trailing words matching `phrase`, or 0."""
        if not phrase:
            return 0
        n = len(phrase.split())
        # Whisper sometimes merges or splits words, so try neighbouring lengths.
        for size in (n, n - 1, n + 1):
            if size <= 0 or size > len(words):
                continue
            tail = [split_punct(w.text)[0] for w in words[-size:]]
            if matches_phrase(tail, phrase, self.threshold):
                return size
        return 0

    def check(self, words: list[Word], followed_by_pause: bool = True) -> GateResult:
        """Inspect one transcribed chunk.

        A chunk normally ends because the speaker went silent, so the phrase
        at its end is "followed by a pause". If the chunk was cut for length
        instead, the phrase is not trusted when `require_pause` is on.
        """
        if not words or (self.require_pause and not followed_by_pause):
            return GateResult(Action.CONTINUE, words)
        for phrase, action in ((self.cancel_phrase, Action.CANCEL), (self.send_phrase, Action.SEND)):
            n = self._tail_match(words, phrase)
            if n:
                return GateResult(action, words[:-n])
        return GateResult(Action.CONTINUE, words)
