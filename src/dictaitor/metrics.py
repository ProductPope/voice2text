"""Quality metrics for `dictaitor eval`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .textutil import norm

_TOKEN = re.compile(r"([\w'’-]+)([^\w\s]*)(\s*)", re.UNICODE)


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Levenshtein distance over normalised words, divided by reference length."""
    ref, hyp = norm(reference).split(), norm(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


def _labelled(text: str) -> tuple[list[str], list[str]]:
    """Words plus the punctuation class after each: "S" sentence end, "C" comma, "" none."""
    words, labels = [], []
    for m in _TOKEN.finditer(text):
        punct, space = m.group(2), m.group(3)
        if any(c in punct for c in ".?!…") or "\n" in space:
            label = "S"
        elif any(c in punct for c in ",;:–"):
            label = "C"
        else:
            label = ""
        words.append(norm(m.group(1)))
        labels.append(label)
    return words, labels


@dataclass
class PunctuationScore:
    correct: int = 0
    predicted: int = 0
    expected: int = 0

    def __add__(self, other: "PunctuationScore") -> "PunctuationScore":
        return PunctuationScore(
            self.correct + other.correct, self.predicted + other.predicted, self.expected + other.expected
        )

    @property
    def f1(self) -> float:
        if not self.predicted and not self.expected:
            return 1.0
        p = self.correct / self.predicted if self.predicted else 0.0
        r = self.correct / self.expected if self.expected else 0.0
        return 2 * p * r / (p + r) if p + r else 0.0


def punctuation_score(reference: str, hypothesis: str) -> PunctuationScore:
    """Compare punctuation after words both texts share (ignores the final mark)."""
    rw, rl = _labelled(reference)
    hw, hl = _labelled(hypothesis)
    score = PunctuationScore()
    for block in SequenceMatcher(None, rw, hw, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            i, j = block.a + k, block.b + k
            if i == len(rw) - 1 or j == len(hw) - 1:
                continue
            score.expected += bool(rl[i])
            score.predicted += bool(hl[j])
            score.correct += bool(rl[i]) and rl[i] == hl[j]
    return score
