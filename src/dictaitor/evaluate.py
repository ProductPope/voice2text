"""`dictaitor eval`: run recordings through the real pipeline and score them.

An evaluation set is a folder of recordings, each with a text file of the
same name holding what *should* have been sent:

    zakupy.wav   zakupy.txt   ->  "Kup mleko, chleb i masło."

Several sends in one recording are separated by a line with `---`; a text
file containing only `#nosend` means nothing may be sent (e.g. you said the
safe phrase in the middle of a sentence). Recordings stay on your disk.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import zip_longest
from pathlib import Path

from .audio import chunker_for, frames_of
from .config import Config
from .i18n import t
from .learning import LearnedStore
from .metrics import PunctuationScore, punctuation_score, word_error_rate
from .pipeline import Pipeline
from .session import Session

AUDIO_SUFFIXES = {".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus", ".webm"}
NO_SEND = "#nosend"


@dataclass
class FileResult:
    name: str
    expected: list[str]
    sent: list[str]
    wer: float
    punctuation: PunctuationScore
    audio_seconds: float
    transcribe_seconds: float
    send_latency: float  # transcription time of the chunk holding the safe phrase

    @property
    def false_sends(self) -> int:
        return max(0, len(self.sent) - len(self.expected))

    @property
    def missed_sends(self) -> int:
        return max(0, len(self.expected) - len(self.sent))


@dataclass
class Report:
    model: str
    files: list[FileResult] = field(default_factory=list)

    @property
    def wer(self) -> float:
        scored = [f for f in self.files if f.expected]
        return sum(f.wer for f in scored) / len(scored) if scored else 0.0

    @property
    def punctuation_f1(self) -> float:
        total = PunctuationScore()
        for f in self.files:
            total = total + f.punctuation
        return total.f1

    @property
    def false_sends(self) -> int:
        return sum(f.false_sends for f in self.files)

    @property
    def missed_sends(self) -> int:
        return sum(f.missed_sends for f in self.files)

    @property
    def real_time_factor(self) -> float:
        audio = sum(f.audio_seconds for f in self.files)
        return sum(f.transcribe_seconds for f in self.files) / audio if audio else 0.0

    @property
    def max_send_latency(self) -> float:
        return max((f.send_latency for f in self.files if f.sent), default=0.0)


def load_expected(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8").strip()
    if text == NO_SEND:
        return []
    return [part.strip() for part in text.split("\n---\n") if part.strip()]


def find_recordings(folder: Path) -> list[tuple[Path, Path]]:
    pairs = []
    for audio in sorted(folder.iterdir()):
        if audio.suffix.lower() in AUDIO_SUFFIXES and audio.with_suffix(".txt").exists():
            pairs.append((audio, audio.with_suffix(".txt")))
    return pairs


def evaluate_audio(name: str, audio, expected: list[str], config: Config, transcriber, scorer=None) -> FileResult:
    sent: list[str] = []
    latencies: list[float] = []
    # A fresh, empty rule store: the eval measures the defaults plus config.toml,
    # and must not learn from (or write to) your real data.
    session = Session(config, LearnedStore(), sink=lambda t: sent.append(t) or "eval")
    pipe = Pipeline(session, transcriber, chunker_for(config, scorer))
    for frame in frames_of(audio):
        before = len(sent)
        pipe.push(frame)
        if len(sent) > before:
            latencies.append(pipe.timing.last_chunk_seconds)
    before = len(sent)
    pipe.flush()
    if len(sent) > before:
        latencies.append(pipe.timing.last_chunk_seconds)

    reference, hypothesis = "\n".join(expected), "\n".join(sent)
    return FileResult(
        name=name,
        expected=expected,
        sent=sent,
        wer=word_error_rate(reference, hypothesis) if expected else 0.0,
        punctuation=punctuation_score(reference, hypothesis) if expected and sent else PunctuationScore(),
        audio_seconds=len(audio) / 16000,
        transcribe_seconds=pipe.timing.transcribe_seconds,
        send_latency=max(latencies, default=0.0),
    )


def evaluate_folder(folder: Path, config: Config, transcriber, model_name: str) -> Report:
    from faster_whisper import decode_audio

    report = Report(model=model_name)
    for audio_path, text_path in find_recordings(folder):
        audio = decode_audio(str(audio_path), sampling_rate=16000)
        report.files.append(evaluate_audio(audio_path.stem, audio, load_expected(text_path), config, transcriber))
    return report


def format_report(report: Report) -> str:
    lines = [f"Model: {report.model}", ""]
    lines.append(
        t(
            f"{'nagranie':<24}{'WER':>7}{'interp.F1':>11}{'wysłane':>9}{'oczek.':>8}{'opóźn.':>9}",
            f"{'recording':<24}{'WER':>7}{'punct.F1':>11}{'sent':>9}{'expect.':>8}{'delay':>9}",
        )
    )
    for f in report.files:
        if f.false_sends:
            flag = t("  ⚠ FAŁSZYWA WYSYŁKA", "  ⚠ FALSE SEND")
        else:
            flag = t("  ⚠ pominięte hasło", "  ⚠ missed phrase") if f.missed_sends else ""
        lines.append(
            f"{f.name[:23]:<24}{f.wer:>7.1%}{f.punctuation.f1:>11.2f}{len(f.sent):>9}"
            f"{len(f.expected):>8}{f.send_latency:>8.2f}s{flag}"
        )
        if f.sent != f.expected:
            for exp, got in zip_longest(f.expected, f.sent, fillvalue="—"):
                lines.append(
                    t(f"    oczekiwano: {exp}\n    otrzymano:  {got}", f"    expected: {exp}\n    got:      {got}")
                )
    lines += [
        "",
        t(f"Średni WER:            {report.wer:.1%}", f"Average WER:           {report.wer:.1%}"),
        t(
            f"Interpunkcja (F1):     {report.punctuation_f1:.2f}",
            f"Punctuation (F1):      {report.punctuation_f1:.2f}",
        ),
        t(
            f"Fałszywe wysyłki:      {report.false_sends}   (cel: 0)",
            f"False sends:           {report.false_sends}   (goal: 0)",
        ),
        t(f"Pominięte hasła:       {report.missed_sends}", f"Missed phrases:        {report.missed_sends}"),
        t(
            f"Szybkość (RTF):        {report.real_time_factor:.2f}   (< 1 = szybciej niż mówisz)",
            f"Speed (RTF):           {report.real_time_factor:.2f}   (< 1 = faster than you speak)",
        ),
        t(
            f"Najdłuższe czekanie po haśle: {report.max_send_latency:.2f}s",
            f"Longest wait after the phrase: {report.max_send_latency:.2f}s",
        ),
    ]
    return "\n".join(lines)
