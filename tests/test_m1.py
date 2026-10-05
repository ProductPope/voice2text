import numpy as np
import pytest

from dictaitor.audio import FRAME_SAMPLES, Chunker, EnergyScorer, frames_of
from dictaitor.composer import Word
from dictaitor.config import Config, unknown_keys
from dictaitor.evaluate import evaluate_audio, format_report, load_expected, Report
from dictaitor.learning import LearnedStore
from dictaitor.metrics import punctuation_score, word_error_rate
from dictaitor.transcriber import choose_model, is_hallucination

SR = 16000
rng = np.random.default_rng(0)


def noise(seconds, amp):
    return rng.normal(0, amp, int(seconds * SR)).astype(np.float32)


def stream(*parts):
    return np.concatenate([noise(s, a) for s, a in parts])


# ------------------------------------------------------------------ chunker


def chunks_of(audio, split=0.6, max_chunk=25.0):
    c = Chunker(EnergyScorer(), split, max_chunk)
    out = [ch for f in frames_of(audio) if (ch := c.push(f)) is not None]
    if (last := c.flush()) is not None:
        out.append(last)
    return out


def test_chunker_splits_on_silence_with_offsets():
    audio = stream((1.2, 0.001), (1.0, 0.2), (1.0, 0.001), (0.5, 0.2), (1.0, 0.001))
    chunks = chunks_of(audio)
    assert len(chunks) == 2
    assert all(c.followed_by_pause for c in chunks)
    assert 0.8 < chunks[0].offset < 1.3
    assert 2.85 < chunks[1].offset < 3.2  # 3.2 s minus 0.3 s pre-roll


def test_short_click_is_ignored():
    audio = stream((1.2, 0.001), (0.05, 0.3), (1.0, 0.001))
    assert chunks_of(audio) == []


def test_length_cut_is_not_followed_by_pause():
    audio = stream((1.2, 0.001), (3.0, 0.2), (1.0, 0.001))
    chunks = chunks_of(audio, max_chunk=2.0)
    assert [c.followed_by_pause for c in chunks] == [False, True]


def test_silero_scorer_is_quiet_on_silence():
    pytest.importorskip("faster_whisper")
    pytest.importorskip("onnxruntime")
    from dictaitor.audio import SileroScorer

    s = SileroScorer()
    probs = [s(f) for f in frames_of(noise(1.0, 0.0005))]
    assert max(probs) < 0.5


# ------------------------------------------------------------- transcriber


def test_model_choice_by_hardware():
    assert choose_model(1, 4).model == "large-v3-turbo"
    assert choose_model(1, 4).device == "cuda"
    assert choose_model(0, 16).model == "large-v3-turbo"
    assert choose_model(0, 4).model == "small"


@pytest.mark.parametrize(
    "text,nsp,logprob,ratio,expected",
    [
        ("Dziękuję za uwagę.", 0.4, -0.5, 1.2, True),
        ("Napisy stworzone przez społeczność Amara.org", 0.0, -0.3, 1.2, True),
        ("tak tak tak tak tak tak tak tak tak tak", 0.0, -0.3, 3.1, True),
        ("coś", 0.9, -1.5, 1.0, True),
        ("Dziękuję za uwagę.", 0.01, -0.2, 1.2, False),  # said on purpose, clearly
        ("Zrób deploy na stagingu.", 0.05, -0.3, 1.1, False),
    ],
)
def test_hallucination_filter(text, nsp, logprob, ratio, expected):
    assert is_hallucination(text, nsp, logprob, ratio) is expected


# ----------------------------------------------------------------- config


def test_unknown_keys_are_reported_but_free_form_sections_are_not():
    user = {
        "gate": {"send_phrse": "x"},
        "nonsense": {},
        "commands": {"cokolwiek": "."},
        "rules": {"replacements": {"a": "b"}, "vocabulary": []},
    }
    assert sorted(unknown_keys(user)) == ["gate.send_phrse", "nonsense"]


def test_config_load_collects_warnings(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[gate]\nsend_phrse = "x"\n', encoding="utf-8")
    assert Config.load(path).warnings == ["nieznane ustawienie w config.toml: gate.send_phrse"]


def test_learned_vocabulary_keeps_names_only():
    store = LearnedStore()
    store.add_replacement("postgres", "PostgreSQL", weight=2)
    store.add_replacement("lubie", "lubię", weight=2)
    assert store.vocabulary(2) == ["PostgreSQL"]


# ---------------------------------------------------------------- metrics


def test_word_error_rate():
    assert word_error_rate("Ala ma kota.", "ala ma kota") == 0.0
    assert word_error_rate("Ala ma kota", "Ala ma psa") == pytest.approx(1 / 3)
    assert word_error_rate("Ala ma kota", "Ala kota") == pytest.approx(1 / 3)


def test_punctuation_score():
    perfect = punctuation_score("Jabłka, gruszki. Śliwki.", "Jabłka, gruszki. Śliwki.")
    assert perfect.f1 == 1.0
    wrong = punctuation_score("Jabłka, gruszki. Śliwki.", "Jabłka. Gruszki, śliwki.")
    assert wrong.f1 == 0.0


def test_load_expected(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("#nosend\n", encoding="utf-8")
    assert load_expected(p) == []
    p.write_text("Pierwsza.\n---\nDruga.\n", encoding="utf-8")
    assert load_expected(p) == ["Pierwsza.", "Druga."]


# ------------------------------------------------------------------- eval


class ScriptedTranscriber:
    """Stands in for Whisper: returns prepared words for each chunk in turn."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def transcribe(self, audio, offset):
        texts = self.chunks.pop(0).split()
        step = len(audio) / SR / max(len(texts), 1)
        words = [Word(t, offset + i * step, offset + (i + 0.8) * step) for i, t in enumerate(texts)]
        words[0].chunk_start = words[-1].chunk_end = True
        return words


def test_eval_counts_sends_and_scores():
    audio = stream((1.2, 0.001), (1.5, 0.2), (2.0, 0.001), (0.8, 0.2), (1.0, 0.001))
    t = ScriptedTranscriber(["Kup mleko i chleb.", "Wyślij teraz."])
    config = Config.from_dict({"audio": {"vad": "energy"}})
    result = evaluate_audio("zakupy", audio, ["Kup mleko i chleb."], config, t, scorer=EnergyScorer())
    assert result.sent == ["Kup mleko i chleb."]
    assert result.wer == 0.0
    assert result.false_sends == result.missed_sends == 0
    assert "Fałszywe wysyłki:      0" in format_report(Report("fake", [result]))


def test_eval_flags_false_send():
    audio = stream((1.2, 0.001), (1.5, 0.2), (1.0, 0.001))
    t = ScriptedTranscriber(["Test wyślij teraz"])
    result = evaluate_audio("x", audio, [], Config(), t, scorer=EnergyScorer())
    assert result.false_sends == 1
    assert "FAŁSZYWA WYSYŁKA" in format_report(Report("fake", [result]))
