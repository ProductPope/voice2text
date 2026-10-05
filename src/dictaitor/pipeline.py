"""Audio frames -> chunks -> words -> session. Shared by `listen` and `eval`."""

from __future__ import annotations

import contextlib
import time
from dataclasses import dataclass, field

import numpy as np

from .audio import FRAME_SECONDS, SAMPLE_RATE, Chunk, Chunker
from .gate import Action
from .session import Event, Session

MIN_PREVIEW_SECONDS = 0.8
JOIN_SILENCE = 0.3  # silence kept between rejoined chunks
MAX_JOIN_SECONDS = 20.0
# Longer silences are a real break; shorter ones (even a long "hmm…") are rejoined -
# punctuation still comes from the real pause length, not from Whisper.
MAX_JOIN_GAP = 3.0
# Rejoining doubles the work; skip it when transcription is slower than this
# fraction of the audio, so a slow computer never falls behind your speech.
MAX_REJOIN_LOAD = 0.5


@dataclass
class _Joinable:
    segments: list[tuple[np.ndarray, float]]  # (audio, real start time) of each chunk
    marker: int
    last_end: float  # end time of its last word

    @property
    def seconds(self) -> float:
        return sum(len(a) for a, _ in self.segments) / SAMPLE_RATE


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
        # Guards session access when another thread (the app) also uses it.
        self.lock = contextlib.nullcontext()
        self.rejoin = session.config["pauses"]["rejoin"]
        self.sentence_gap = session.config["pauses"]["sentence_gap"]
        self._prev: _Joinable | None = None
        self.rejoins = 0

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
        with self.lock:
            event = self.session.feed(words, chunk.followed_by_pause)
            marker, had_command = self.session.last_marker, self.session.last_had_command
        if event.action is not Action.CONTINUE or had_command or not words:
            self._prev = None
            return event
        joined = self._try_rejoin(chunk, words, took)
        if joined is not None:
            return joined
        self._prev = _Joinable([(chunk.audio, chunk.offset)], marker, words[-1].end)
        return event

    def _try_rejoin(self, chunk: Chunk, words, took: float) -> Event | None:
        """After a thinking pause, re-read the previous chunk together with this one.

        A chunk that ends on "w" or "że" is hard for Whisper alone ("Zrobimy to w"
        came out as "Zrobimy to wy."); with the rest of the sentence it is not.
        """
        prev = self._prev
        if not self.rejoin or prev is None:
            return None
        duration = len(chunk.audio) / SAMPLE_RATE
        gap = words[0].start - prev.last_end
        too_long = prev.seconds + duration > MAX_JOIN_SECONDS
        if gap >= MAX_JOIN_GAP or too_long or took > duration * MAX_REJOIN_LOAD:
            return None
        segments = prev.segments + [(chunk.audio, chunk.offset)]
        silence = np.zeros(int(JOIN_SILENCE * SAMPLE_RATE), np.float32)
        parts, starts, pos = [], [], 0.0  # where each segment begins inside the joined audio
        for audio_part, _ in segments:
            starts.append(pos)
            parts += [audio_part, silence]
            pos += len(audio_part) / SAMPLE_RATE + JOIN_SILENCE
        start = time.perf_counter()
        merged = self.transcriber.transcribe(np.concatenate(parts[:-1]), 0.0)
        self.timing.transcribe_seconds += time.perf_counter() - start
        if not merged:
            return None
        for w in merged:  # map times back onto the real timeline, segment by segment
            k = max(i for i, s in enumerate(starts) if w.start >= s - JOIN_SILENCE / 2) if w.start >= 0 else 0
            shift = segments[k][1] - starts[k]
            w.start, w.end = w.start + shift, w.end + shift
        with self.lock:
            if self.session.pending is not None:
                return None
            event = self.session.replace_since(prev.marker, merged)
        self.rejoins += 1
        self._prev = _Joinable(segments, prev.marker, merged[-1].end)
        return event
