"""Local speech-to-text with faster-whisper. Audio never leaves the machine."""

from __future__ import annotations

import os
from dataclasses import dataclass

from .composer import Word
from .config import Config
from .textutil import norm, similarity

# Phrases Whisper is known to invent on silence or noise (it was trained on
# subtitled video). Dropped only when a whole segment is just that phrase.
HALLUCINATIONS = [
    "dziękuję za uwagę",
    "dziękuję za obejrzenie",
    "dziękuję za oglądanie",
    "dzięki za obejrzenie",
    "zapraszam na kolejny odcinek",
    "subskrybuj kanał",
    "do zobaczenia w następnym odcinku",
    "napisy stworzone przez społeczność amara org",
    "napisy wykonane przez",
    "thank you for watching",
    "thanks for watching",
    "please subscribe",
    "subtitles by the amara org community",
]
_HALLUCINATIONS = [norm(h) for h in HALLUCINATIONS]



@dataclass
class ModelChoice:
    model: str
    device: str
    compute_type: str


def choose_model(cuda_devices: int, cpu_count: int) -> ModelChoice:
    """Pick the best model the hardware can run close to real time."""
    if cuda_devices > 0:
        return ModelChoice("large-v3-turbo", "cuda", "float16")
    if cpu_count >= 8:
        return ModelChoice("large-v3-turbo", "cpu", "int8")
    # Measured on 4 cores: small ~0.26x real time, large-v3-turbo ~0.64x.
    return ModelChoice("small", "cpu", "int8")


def resolve_model(config: Config, allow_gpu: bool = True) -> ModelChoice:
    g = config["general"]
    cuda = 0
    if allow_gpu and g["device"] in ("auto", "cuda"):
        try:
            import ctranslate2

            cuda = ctranslate2.get_cuda_device_count()
        except Exception:
            cuda = 0
    auto = choose_model(cuda, os.cpu_count() or 1)
    device = auto.device if g["device"] == "auto" or not allow_gpu else g["device"]
    model = auto.model if g["model"] == "auto" else g["model"]
    compute = g["compute_type"]
    if compute == "auto":
        compute = "float16" if device == "cuda" else "int8"
    return ModelChoice(model, device, compute)


def is_hallucination(text: str, no_speech_prob: float, avg_logprob: float, compression_ratio: float) -> bool:
    if compression_ratio > 2.4:  # "tak tak tak tak tak ..." loops
        return True
    if no_speech_prob > 0.6 and avg_logprob < -1.0:
        return True
    n = norm(text)
    if not n:
        return True
    if "amara org" in n:
        return True
    return any(similarity(n, h) >= 0.85 for h in _HALLUCINATIONS) and no_speech_prob > 0.1


class Transcriber:
    def __init__(self, config: Config, extra_vocabulary: list[str] | None = None):
        from faster_whisper import WhisperModel  # heavy import, only when listening

        self.language = config["general"]["language"]
        self.prompt_text = config["general"]["prompt"]
        self.warning = ""
        self.choice = resolve_model(config)
        try:
            self.model = self._load(WhisperModel, self.choice)
        except Exception as exc:
            if self.choice.device != "cuda":
                raise
            # An NVIDIA card without the CUDA libraries (cuBLAS/cuDNN) is common
            # on Windows; it only fails once the model actually runs.
            self.warning = f"Karta graficzna niedostępna ({exc.__class__.__name__}: {exc}); używam procesora."
            self.choice = resolve_model(config, allow_gpu=False)
            self.model = self._load(WhisperModel, self.choice)
        self.set_vocabulary(list(config["rules"]["vocabulary"]) + list(extra_vocabulary or []))

    def _load(self, whisper_model, choice: ModelChoice):
        import numpy as np

        model = whisper_model(choice.model, device=choice.device, compute_type=choice.compute_type)
        segments, _ = model.transcribe(np.zeros(16000, dtype=np.float32), language=self.language)
        list(segments)  # run it once so a broken GPU setup fails here, not mid-dictation
        return model

    def set_vocabulary(self, vocabulary: list[str]) -> None:
        vocab = list(dict.fromkeys(v for v in vocabulary if v.strip()))
        # Hotwords bias decoding towards your names and jargon; the prompt also
        # tells Whisper the text is Polish with English terms mixed in.
        self.hotwords = ", ".join(vocab) or None
        # Off by default: measured on Polish speech, a generic style prompt made
        # Whisper drop first syllables ("Spotkanie" -> "Potkanie").
        self.prompt = self.prompt_text or None

    def transcribe(self, audio, offset: float) -> list[Word]:
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            word_timestamps=True,
            initial_prompt=self.prompt,
            hotwords=self.hotwords,
            condition_on_previous_text=False,
            vad_filter=False,
            beam_size=5,
        )
        words = [
            Word(w.word.strip(), offset + w.start, offset + w.end)
            for seg in segments
            if not is_hallucination(seg.text, seg.no_speech_prob, seg.avg_logprob, seg.compression_ratio)
            for w in (seg.words or [])
            if w.word.strip()
        ]
        if words:
            words[0].chunk_start = True
            words[-1].chunk_end = True
        return words

    def preview(self, audio) -> str:
        """Fast, rough text of a chunk still being spoken (shown greyed out)."""
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            initial_prompt=self.prompt,
            hotwords=self.hotwords,
            condition_on_previous_text=False,
            vad_filter=False,
            beam_size=1,
            without_timestamps=True,
        )
        return " ".join(
            s.text.strip()
            for s in segments
            if not is_hallucination(s.text, s.no_speech_prob, s.avg_logprob, s.compression_ratio)
        )
