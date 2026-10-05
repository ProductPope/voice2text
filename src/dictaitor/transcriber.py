"""Local speech-to-text with faster-whisper. Audio never leaves the machine."""

from __future__ import annotations

from .composer import Word
from .config import Config


class Transcriber:
    def __init__(self, config: Config):
        from faster_whisper import WhisperModel  # heavy import, only when listening

        g = config["general"]
        self.language = g["language"]
        self.model = WhisperModel(g["model"], device=g["device"], compute_type=g["compute_type"])
        vocab = config["rules"]["vocabulary"]
        # The initial prompt nudges Whisper towards your names and jargon.
        self.prompt = ("Słownictwo: " + ", ".join(vocab) + ".") if vocab else None

    def transcribe(self, audio, offset: float) -> list[Word]:
        segments, _ = self.model.transcribe(
            audio,
            language=self.language,
            word_timestamps=True,
            initial_prompt=self.prompt,
            condition_on_previous_text=False,
            vad_filter=False,
            beam_size=5,
        )
        words = [
            Word(w.word.strip(), offset + w.start, offset + w.end)
            for seg in segments
            for w in (seg.words or [])
            if w.word.strip()
        ]
        if words:
            words[0].chunk_start = True
            words[-1].chunk_end = True
        return words
