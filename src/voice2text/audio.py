"""Microphone capture split into utterance chunks by silence.

A chunk ends when you are silent for `pauses.split_silence` seconds. Ending a
chunk only triggers transcription - it never sends anything. Audio is kept
in memory only and is never written to disk.
"""

from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import Iterator

import numpy as np

from .config import Config

FRAME_SECONDS = 0.03
PRE_ROLL_SECONDS = 0.3
CALIBRATION_SECONDS = 1.0


@dataclass
class Chunk:
    audio: np.ndarray
    offset: float  # seconds since the session started
    followed_by_pause: bool


class EnergyChunker:
    """Splits a stream of frames into speech chunks. Separate from the mic for testing."""

    def __init__(self, sample_rate: int, split_silence: float, max_chunk: float, threshold: float = 0.0):
        self.sr = sample_rate
        self.frame = int(sample_rate * FRAME_SECONDS)
        self.split_frames = max(1, int(split_silence / FRAME_SECONDS))
        self.max_frames = int(max_chunk / FRAME_SECONDS)
        self.pre_roll = int(PRE_ROLL_SECONDS / FRAME_SECONDS)
        self.fixed_threshold = threshold
        self.noise: list[float] = []
        self.history: list[np.ndarray] = []
        self.speech: list[np.ndarray] = []
        self.silent_run = 0
        self.frames_seen = 0
        self.chunk_start_frame = 0

    @property
    def threshold(self) -> float:
        if self.fixed_threshold > 0:
            return self.fixed_threshold
        floor = float(np.median(self.noise)) if self.noise else 0.005
        return max(floor * 3.0, 0.004)

    def push(self, frame: np.ndarray) -> Chunk | None:
        self.frames_seen += 1
        rms = float(np.sqrt(np.mean(frame**2)))
        calibrating = self.frames_seen * FRAME_SECONDS < CALIBRATION_SECONDS
        if calibrating or (not self.speech and rms < self.threshold):
            self.noise = (self.noise + [rms])[-300:]
        if calibrating:
            return None

        if not self.speech:
            self.history = (self.history + [frame])[-self.pre_roll :]
            if rms >= self.threshold:
                self.speech = list(self.history)
                self.chunk_start_frame = self.frames_seen - len(self.speech)
                self.silent_run = 0
            return None

        self.speech.append(frame)
        self.silent_run = 0 if rms >= self.threshold else self.silent_run + 1
        if self.silent_run >= self.split_frames:
            return self._emit(followed_by_pause=True)
        if len(self.speech) >= self.max_frames:
            return self._emit(followed_by_pause=False)
        return None

    def _emit(self, followed_by_pause: bool) -> Chunk:
        audio = np.concatenate(self.speech).astype(np.float32)
        chunk = Chunk(audio, self.chunk_start_frame * FRAME_SECONDS, followed_by_pause)
        self.speech, self.history, self.silent_run = [], [], 0
        return chunk


def microphone_chunks(config: Config) -> Iterator[Chunk]:
    import sounddevice as sd  # optional dependency, only for live use

    a = config["audio"]
    chunker = EnergyChunker(
        a["sample_rate"], config["pauses"]["split_silence"], a["max_chunk_seconds"], a["energy_threshold"]
    )
    frames: queue.Queue[np.ndarray] = queue.Queue()

    def callback(indata, _frames, _time, _status):
        frames.put(indata[:, 0].copy())

    with sd.InputStream(
        samplerate=a["sample_rate"], channels=1, dtype="float32", blocksize=chunker.frame, callback=callback
    ):
        while True:
            chunk = chunker.push(frames.get())
            if chunk is not None:
                yield chunk
