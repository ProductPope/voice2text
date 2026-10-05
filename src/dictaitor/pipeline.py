"""Audio frames -> chunks -> words -> session. Shared by `listen` and `eval`."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from .audio import FRAME_SECONDS, SAMPLE_RATE, Chunk, Chunker
from .session import Event, Session

MIN_PREVIEW_SECONDS = 0.8


@dataclass
class Timing:
    audio_seconds: float = 0.0
    transcribe_seconds: float = 0.0
    last_chunk_seconds: float = 0.0  # what you wait for after the safe phrase
    chunks: int = 0
    per_chunk: list[float] = field(default_factory=list)


class Pipeline:
    def __init__(self, session: Session, transcriber, chunker: Chunker, preview_interval: float = 0.0):
        self.session = session
        self.transcriber = transcriber
        self.chunker = chunker
        self.preview_frames = round(preview_interval / FRAME_SECONDS) if preview_interval > 0 else 0
        self._since_preview = 0
        self.timing = Timing()
        self.on_words = None  # optional debug hook

    def push(self, frame: np.ndarray) -> Event | None:
        self.timing.audio_seconds += FRAME_SECONDS
        chunk = self.chunker.push(frame)
        if chunk is not None:
            self._since_preview = 0
            return self._process(chunk)
        if self.chunker.in_speech:
            self._since_preview += 1
        return None

    def flush(self) -> Event | None:
        chunk = self.chunker.flush()
        return self._process(chunk) if chunk is not None else None

    def preview_due(self) -> bool:
        return bool(self.preview_frames) and self._since_preview >= self.preview_frames

    def preview(self) -> str:
        """Rough text of the chunk being spoken right now (not part of the draft yet)."""
        self._since_preview = 0
        current = self.chunker.current()
        if current is None or len(current[0]) < MIN_PREVIEW_SECONDS * SAMPLE_RATE:
            return ""
        audio, _ = current
        return self.transcriber.preview(audio)

    def _process(self, chunk: Chunk) -> Event:
        start = time.perf_counter()
        words = self.transcriber.transcribe(chunk.audio, chunk.offset)
        took = time.perf_counter() - start
        t = self.timing
        t.transcribe_seconds += took
        t.last_chunk_seconds = took
        t.chunks += 1
        t.per_chunk.append(took)
        if self.on_words:
            self.on_words(words)
        return self.session.feed(words, chunk.followed_by_pause)
