"""Turns timestamped words into text, interpreting pauses and voice commands.

Nothing is decided while speaking: words are collected into phrases and the
whole draft is re-rendered every time, so a later pause or a correction
("cofnij") can still change earlier punctuation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import Config
from .textutil import capitalize_first, decapitalize_first, norm, split_punct

SENTENCE_END = {".", "?", "!", "…"}


@dataclass
class Word:
    text: str
    start: float
    end: float
    # True for the first word of a transcription chunk. Whisper capitalises
    # chunk starts and ends chunks with a period even mid-sentence, so those
    # hints are not trusted.
    chunk_start: bool = False
    chunk_end: bool = False


@dataclass
class _Token:
    text: str
    hint: str  # punctuation Whisper attached to the word
    start: float
    end: float
    chunk_start: bool
    chunk_end: bool
    # After "cofnij" the pause before the next word is the one that preceded
    # the removed phrase, not the time spent on the mistake.
    gap_before: float | None = None


@dataclass
class _Mark:
    text: str  # explicit punctuation / newline from a voice command


@dataclass
class Phrase:
    items: list = field(default_factory=list)


@dataclass
class Boundary:
    """Gap after a rendered word, kept so the learner can match it to edits."""

    word: str
    gap: float
    punct: str
    after_continuation: bool


class Composer:
    def __init__(self, config: Config, comma_gap: float | None = None, sentence_gap: float | None = None):
        self.config = config
        self.comma_gap = comma_gap if comma_gap is not None else config["pauses"]["comma_gap"]
        self.sentence_gap = sentence_gap if sentence_gap is not None else config["pauses"]["sentence_gap"]
        self.fillers = {norm(f) for f in config["text"]["fillers"]}
        self.continuations = {norm(w) for w in config["text"]["continuations"]}
        self.no_comma_before = {norm(w) for w in config["text"]["no_comma_before"]}
        self.keep_case = {norm(w) for w in config["text"]["keep_case"]} | {
            norm(w) for w in config["rules"]["vocabulary"]
        }
        # Longest commands first so "nowy akapit" wins over a shorter overlap.
        self.commands = sorted(
            ((norm(k).split(), v) for k, v in config["commands"].items()),
            key=lambda kv: -len(kv[0]),
        )
        self.phrases: list[Phrase] = []
        self.boundaries: list[Boundary] = []
        self._gap_after_undo: float | None = None

    # ------------------------------------------------------------------ input

    def add_words(self, words: list[Word]) -> None:
        if not words:
            return
        current = Phrase()
        self.phrases.append(current)
        prev_end: float | None = None
        i = 0
        while i < len(words):
            w = words[i]
            if prev_end is not None and w.start - prev_end >= self.comma_gap and current.items:
                current = Phrase()
                self.phrases.append(current)

            command, length = self._match_command(words, i)
            if command is not None:
                prev_end = words[i + length - 1].end
                i += length
                if command == "@undo":
                    self._undo(current)
                    current = Phrase()
                    self.phrases.append(current)
                elif command == "@clear":
                    self.phrases = [current := Phrase()]
                else:
                    current.items.append(_Mark(command))
                continue

            text, hint = split_punct(w.text)
            prev_end = w.end
            i += 1
            if not text or norm(text) in self.fillers:
                continue
            current.items.append(
                _Token(text, hint, w.start, w.end, w.chunk_start, w.chunk_end, self._gap_after_undo)
            )
            self._gap_after_undo = None
        self.phrases = [p for p in self.phrases if p.items or p is current]

    def _match_command(self, words: list[Word], i: int) -> tuple[str | None, int]:
        for parts, action in self.commands:
            n = len(parts)
            window = [norm(split_punct(w.text)[0]) for w in words[i : i + n]]
            if window == parts:
                return action, n
        return None, 0

    def _undo(self, current: Phrase) -> None:
        """Drop the phrase spoken before "cofnij" (the one since the last pause)."""
        if not current.items:
            self.phrases.remove(current)
            while self.phrases and not self.phrases[-1].items:
                self.phrases.pop()
            if not self.phrases:
                return
            current = self.phrases.pop()
        removed = next((it for it in current.items if isinstance(it, _Token)), None)
        kept = [it for p in self.phrases if p is not current for it in p.items if isinstance(it, _Token)]
        if removed is not None and kept:
            self._gap_after_undo = removed.gap_before if removed.gap_before is not None else removed.start - kept[-1].end
        current.items.clear()

    def clear(self) -> None:
        self.phrases.clear()
        self.boundaries.clear()

    @property
    def empty(self) -> bool:
        return not any(p.items for p in self.phrases)

    # ----------------------------------------------------------------- render

    def _decide(self, tok: _Token, gap: float, next_tok: _Token | None) -> str:
        """Punctuation to place after `tok`, given the silence that follows."""
        after_continuation = norm(tok.text) in self.continuations
        hint = tok.hint
        # Whisper's own punctuation is reliable within continuous speech but
        # not at chunk edges, which are just where the VAD cut the audio.
        artificial_edge = tok.chunk_end or (next_tok is not None and next_tok.chunk_start)
        if next_tok is None:
            return hint if hint in SENTENCE_END else "."
        if after_continuation:
            return ""
        if not artificial_edge and gap < self.comma_gap:
            return hint
        if gap >= self.sentence_gap:
            return hint if hint in SENTENCE_END else "."
        if gap >= self.comma_gap:
            # Thinking pause: questions survive, a VAD-inserted period becomes a comma.
            if hint in {"?", "!"}:
                return hint
            return "" if norm(next_tok.text) in self.no_comma_before else ","
        return "" if hint in SENTENCE_END else hint

    def render(self) -> str:
        items = [it for p in self.phrases for it in p.items]
        self.boundaries = []
        out: list[str] = []
        sentence_start = True
        for idx, it in enumerate(items):
            if isinstance(it, _Mark):
                out.append(it.text)
                if it.text.strip() in SENTENCE_END or "\n" in it.text:
                    sentence_start = True
                continue

            text = it.text
            if sentence_start:
                text = capitalize_first(text)
            elif it.chunk_start and norm(text) not in self.keep_case:
                text = decapitalize_first(text)
            sentence_start = False

            nxt = items[idx + 1] if idx + 1 < len(items) else None
            if isinstance(nxt, _Mark):
                # A spoken "kropka" replaces any punctuation here; a newline keeps
                # a question or exclamation mark Whisper heard.
                punct = it.hint if not nxt.text.strip() and it.hint in {"?", "!"} else ""
            else:
                if nxt is None:
                    gap = 99.0
                elif nxt.gap_before is not None:
                    gap = nxt.gap_before
                else:
                    gap = nxt.start - it.end
                punct = self._decide(it, gap, nxt)
                self.boundaries.append(
                    Boundary(it.text, gap, punct, norm(it.text) in self.continuations)
                )
            if punct in SENTENCE_END:
                sentence_start = True

            sep = "" if not out or out[-1].endswith("\n") else " "
            out.append(sep + text + punct)
        text = "".join(out)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r" +([.,?!:;])", r"\1", text)
        return text.strip()
