"""Learning the user's rules from their own corrections.

Two things are learned, both stored locally in learned.json:

* word replacements - when you correct the same misheard word the same way
  enough times, it is fixed automatically from then on;
* pause thresholds - every corrected draft tells us which of your pauses
  were sentence ends, which were commas and which were just thinking, and
  the thresholds are re-fitted to your own rhythm of speech.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .composer import Boundary
from .config import Config

_FINAL_TOKEN = re.compile(r"([\w'’-]+)([^\w\s]*)(\s*)", re.UNICODE)
MIN_PAUSE = 0.3  # shorter gaps are plain word spacing, Whisper's grammar decides there
MAX_SAMPLES = 600


@dataclass
class LearnedStore:
    path: Path | None = None
    replacements: dict[str, dict[str, int]] = field(default_factory=dict)
    pause_samples: list[tuple[float, int]] = field(default_factory=list)

    # ------------------------------------------------------------ persistence

    @classmethod
    def load(cls, path: Path) -> "LearnedStore":
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            path=path,
            replacements=raw.get("replacements", {}),
            pause_samples=[tuple(s) for s in raw.get("pause_samples", [])],
        )

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"replacements": self.replacements, "pause_samples": self.pause_samples}
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    # ----------------------------------------------------------- replacements

    def add_replacement(self, wrong: str, right: str, weight: int = 1) -> None:
        wrong, right = wrong.strip(), right.strip()
        if not wrong or wrong == right:
            return
        # A correction in the opposite direction weakens the old rule.
        back = self.replacements.get(right, {})
        if wrong in back:
            back[wrong] -= weight
            if back[wrong] <= 0:
                del back[wrong]
            if not back:
                self.replacements.pop(right, None)
        self.replacements.setdefault(wrong, {})
        self.replacements[wrong][right] = self.replacements[wrong].get(right, 0) + weight

    def active_replacements(self, min_occurrences: int) -> dict[str, str]:
        out = {}
        for wrong, options in self.replacements.items():
            right, count = max(options.items(), key=lambda kv: kv[1])
            if count >= min_occurrences:
                out[wrong] = right
        return out

    # ----------------------------------------------------------------- pauses

    def thresholds(self, config: Config) -> tuple[float, float]:
        comma = config["pauses"]["comma_gap"]
        sentence = config["pauses"]["sentence_gap"]
        if not config["pauses"]["learn"]:
            return comma, sentence
        need = config["learning"]["min_pause_samples"]
        samples = [s for s in self.pause_samples if s[0] >= MIN_PAUSE]
        if len(samples) < need:
            return comma, sentence
        fitted_comma = _fit_threshold([(g, lbl >= 1) for g, lbl in samples])
        fitted_sentence = _fit_threshold([(g, lbl == 2) for g, lbl in samples])
        if fitted_comma is not None:
            comma = max(0.25, fitted_comma)
        if fitted_sentence is not None:
            sentence = fitted_sentence
        return comma, max(sentence, comma + 0.2)

    # ---------------------------------------------------------------- editing

    def learn_words(self, draft: str, final: str) -> list[tuple[str, str]]:
        """Remember word-level corrections between what was shown and what was sent."""
        a = [m.group(1) for m in _FINAL_TOKEN.finditer(draft)]
        b_matches = list(_FINAL_TOKEN.finditer(final))
        b = [m.group(1) for m in b_matches]
        learned = []
        for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if op != "replace" or i2 - i1 > 3 or j2 - j1 > 4:
                continue
            wrong, right = " ".join(a[i1:i2]), " ".join(b[j1:j2])
            if _only_initial_case_differs(wrong, right):
                # "marcin" -> "Marcin" mid-sentence is a name worth remembering;
                # anything at a sentence start is just capitalisation.
                before = final[: b_matches[j1].start()].rstrip()
                if right[:1].islower() or not before or before[-1] in ".?!:":
                    continue
            self.add_replacement(wrong, right)
            learned.append((wrong, right))
        return learned

    def learn_pauses(self, final: str, boundaries: list[Boundary]) -> None:
        """Label each measured pause with the punctuation the user kept there."""
        tokens = list(_FINAL_TOKEN.finditer(final))
        final_words = [m.group(1).lower() for m in tokens]
        labels = []
        for m in tokens:
            punct, space = m.group(2), m.group(3)
            if any(c in punct for c in ".?!…") or "\n" in space:
                labels.append(2)
            elif any(c in punct for c in ",;:–-"):
                labels.append(1)
            else:
                labels.append(0)
        draft_words = [b.word.lower() for b in boundaries]
        sm = SequenceMatcher(None, draft_words, final_words, autojunk=False)
        for block in sm.get_matching_blocks():
            for k in range(block.size):
                i, j = block.a + k, block.b + k
                b = boundaries[i]
                if j == len(final_words) - 1 or b.after_continuation or b.gap > 30:
                    continue
                self.pause_samples.append((round(b.gap, 3), labels[j]))
        self.pause_samples = self.pause_samples[-MAX_SAMPLES:]


def _only_initial_case_differs(a: str, b: str) -> bool:
    return a != b and a.lower() == b.lower() and a[1:] == b[1:]


def _fit_threshold(samples: list[tuple[float, bool]]) -> float | None:
    """Gap threshold that best separates positive from negative samples."""
    pos = sum(1 for _, y in samples if y)
    if pos < 3 or len(samples) - pos < 3:
        return None
    gaps = sorted({g for g, _ in samples})
    candidates = [(a + b) / 2 for a, b in zip(gaps, gaps[1:])] or gaps
    best, best_err = None, None
    for t in candidates:
        err = sum(1 for g, y in samples if (g >= t) != y)
        if best_err is None or err < best_err:
            best, best_err = t, err
    return round(best, 3) if best is not None else None


def apply_replacements(text: str, rules: dict[str, str]) -> str:
    # Longest source first so multi-word rules win over single words.
    for wrong in sorted(rules, key=len, reverse=True):
        right = rules[wrong]
        flags = re.IGNORECASE if wrong == wrong.lower() else 0
        pattern = re.compile(r"(?<!\w)" + re.escape(wrong) + r"(?!\w)", flags)

        def repl(m: re.Match, right=right) -> str:
            # Keep sentence-start capitalisation when the rule is lowercase.
            if m.group(0)[:1].isupper() and right[:1].islower():
                return right[:1].upper() + right[1:]
            return right

        text = pattern.sub(repl, text)
    return text
