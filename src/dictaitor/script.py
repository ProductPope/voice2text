"""Text scripts that stand in for the microphone (for `dictaitor simulate` and tests).

Words are spoken one after another; `[1.2]` inserts a 1.2 s pause. A pause
at least `split_silence` long ends a chunk, exactly as the live VAD would.

    Spotkanie jest w środę [0.9] i [1.0] w czwartek [2.0] wyślij teraz
"""

from __future__ import annotations

import re

from .composer import Word

WORD_SECONDS = 0.3
WORD_GAP = 0.08
_TOKEN = re.compile(r"\[(\d+(?:\.\d+)?)\]|(\S+)")


def parse_script(text: str, split_silence: float) -> list[list[Word]]:
    chunks: list[list[Word]] = [[]]
    t = 0.0
    pending_gap = 0.0
    for m in _TOKEN.finditer(text):
        if m.group(1):
            pending_gap += float(m.group(1))
            continue
        if chunks[-1] and pending_gap >= split_silence:
            chunks.append([])
        t += pending_gap or (WORD_GAP if chunks[-1] else 0.0)
        pending_gap = 0.0
        chunks[-1].append(Word(m.group(2), t, t + WORD_SECONDS))
        t += WORD_SECONDS
    chunks = [c for c in chunks if c]
    for c in chunks:
        c[0].chunk_start = True
        c[-1].chunk_end = True
    return chunks
