"""Microphone capture split into utterance chunks by voice activity.

A chunk ends when you are silent for `pauses.split_silence` seconds. Ending a
chunk only triggers transcription - it never sends anything. Audio is kept
in memory only and is never written to disk.

Voice activity comes from Silero VAD (shipped with faster-whisper) when it is
available, otherwise from an adaptive energy threshold.
"""

from __future__ import annotations

import queue
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np

from .config import Config

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512  # what Silero expects at 16 kHz
FRAME_SECONDS = FRAME_SAMPLES / SAMPLE_RATE
PRE_ROLL_SECONDS = 0.3
MIN_SPEECH_SECONDS = 0.2  # shorter bursts (clicks, a cough) are dropped

Scorer = Callable[[np.ndarray], float]


@dataclass
class Chunk:
    audio: np.ndarray
    offset: float  # seconds since the stream started
    followed_by_pause: bool


class EnergyScorer:
    """Speech probability 0/1 from loudness relative to the learned noise floor."""

    CALIBRATION_SECONDS = 1.0

    def __init__(self, threshold: float = 0.0):
        self.fixed = threshold
        self.noise: list[float] = []
        self.frames = 0

    @property
    def threshold(self) -> float:
        if self.fixed > 0:
            return self.fixed
        floor = float(np.median(self.noise)) if self.noise else 0.005
        return max(floor * 3.0, 0.004)

    def __call__(self, frame: np.ndarray) -> float:
        self.frames += 1
        rms = float(np.sqrt(np.mean(frame**2)))
        if self.frames * FRAME_SECONDS < self.CALIBRATION_SECONDS:
            self.noise.append(rms)
            return 0.0
        speech = rms >= self.threshold
        if not speech:
            self.noise = (self.noise + [rms])[-300:]
        return 1.0 if speech else 0.0


class SileroScorer:
    """Streaming Silero VAD: carries the recurrent state between 32 ms frames."""

    CONTEXT = 64

    def __init__(self):
        from faster_whisper.vad import get_vad_model

        self.session = get_vad_model().session
        self.reset()

    def reset(self) -> None:
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.context = np.zeros(self.CONTEXT, dtype=np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.context, frame.astype(np.float32)])[None, :]
        out, self.h, self.c = self.session.run(None, {"input": x, "h": self.h, "c": self.c})
        self.context = frame[-self.CONTEXT :].astype(np.float32)
        return float(np.asarray(out).reshape(-1)[-1])


def make_scorer(config: Config) -> Scorer:
    a = config["audio"]
    if a["vad"] in ("auto", "silero"):
        try:
            return SileroScorer()
        except Exception:
            if a["vad"] == "silero":
                raise
    return EnergyScorer(a["energy_threshold"])


class Chunker:
    """Turns a stream of 512-sample frames into speech chunks."""

    def __init__(
        self,
        scorer: Scorer,
        split_silence: float,
        max_chunk: float,
        start_threshold: float = 0.5,
        stop_threshold: float = 0.35,
    ):
        self.scorer = scorer
        self.split_frames = max(1, round(split_silence / FRAME_SECONDS))
        self.max_frames = round(max_chunk / FRAME_SECONDS)
        self.pre_roll = round(PRE_ROLL_SECONDS / FRAME_SECONDS)
        self.min_speech = round(MIN_SPEECH_SECONDS / FRAME_SECONDS)
        # Hysteresis: harder to start speech than to keep it going.
        self.start_threshold = start_threshold
        self.stop_threshold = stop_threshold
        self.history: list[np.ndarray] = []
        self.speech: list[np.ndarray] = []
        self.speech_frames = 0
        self.silent_run = 0
        self.frames_seen = 0
        self.chunk_start_frame = 0

    @property
    def in_speech(self) -> bool:
        return bool(self.speech)

    def current(self) -> tuple[np.ndarray, float] | None:
        """Audio of the chunk still being spoken, for live previews."""
        if not self.speech:
            return None
        return np.concatenate(self.speech), self.chunk_start_frame * FRAME_SECONDS

    def push(self, frame: np.ndarray) -> Chunk | None:
        self.frames_seen += 1
        p = self.scorer(frame)

        if not self.speech:
            self.history = (self.history + [frame])[-self.pre_roll :]
            if p >= self.start_threshold:
                self.speech = list(self.history)
                self.chunk_start_frame = self.frames_seen - len(self.speech)
                self.speech_frames = 1
                self.silent_run = 0
            return None

        self.speech.append(frame)
        if p >= self.stop_threshold:
            self.silent_run = 0
            self.speech_frames += 1
        else:
            self.silent_run += 1
        if self.silent_run >= self.split_frames:
            return self._emit(followed_by_pause=True)
        if len(self.speech) >= self.max_frames:
            return self._emit(followed_by_pause=False)
        return None

    def flush(self) -> Chunk | None:
        """End of stream: whatever is left counts as followed by a pause."""
        return self._emit(followed_by_pause=True) if self.speech else None

    def _emit(self, followed_by_pause: bool) -> Chunk | None:
        audio = np.concatenate(self.speech).astype(np.float32)
        offset = self.chunk_start_frame * FRAME_SECONDS
        enough = self.speech_frames >= self.min_speech
        self.speech, self.history, self.silent_run, self.speech_frames = [], [], 0, 0
        return Chunk(audio, offset, followed_by_pause) if enough else None


def frames_of(audio: np.ndarray) -> Iterator[np.ndarray]:
    for i in range(0, len(audio) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
        yield audio[i : i + FRAME_SAMPLES]


def chunker_for(config: Config, scorer: Scorer | None = None) -> Chunker:
    return Chunker(
        scorer or make_scorer(config),
        config["pauses"]["split_silence"],
        config["audio"]["max_chunk_seconds"],
    )


def microphone_frames() -> Iterator[np.ndarray]:
    import sounddevice as sd  # optional dependency, only for live use

    frames: queue.Queue[np.ndarray] = queue.Queue()

    def callback(indata, _frames, _time, _status):
        frames.put(indata[:, 0].copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=FRAME_SAMPLES, callback=callback
    ):
        while True:
            yield frames.get()
