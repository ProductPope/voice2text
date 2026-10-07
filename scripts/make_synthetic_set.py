"""Build a synthetic evaluation set with the Piper speech synthesizer.

    pip install piper-tts
    # voices: https://huggingface.co/rhasspy/piper-voices
    #   pl: pl/pl_PL/gosia/medium/pl_PL-gosia-medium.onnx (+ .onnx.json)
    #   en: en/en_US/lessac/medium/en_US-lessac-medium.onnx (+ .onnx.json)
    python scripts/make_synthetic_set.py pl pl_PL-gosia-medium.onnx synthetic-pl
    dictaitor eval synthetic-pl

Numbers in a case are pauses in seconds. Synthetic voices garble some sounds, so this
set checks the pipeline (pauses, commands, the safe phrase); real recordings
(`dictaitor record`) are what measure recognition quality.
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

SR = 16000
NOSEND = "#nosend"

CASES = {
    "pl": {
        "01_myslenie_po_w": (
            ["Zrobimy to w", 1.8, "poniedziałek rano.", 1.0, "Wyślij teraz."],
            "Zrobimy to w poniedziałek rano.",
        ),
        "02_dwa_zdania": (
            ["Raport jest gotowy.", 2.0, "Wyślę go jutro.", 1.2, "Wyślij teraz."],
            "Raport jest gotowy. Wyślę go jutro.",
        ),
        "03_angielskie_wtracenia": (
            ["Zrób deploy na stagingu", 1.0, "i odpal testy.", 1.0, "Wyślij teraz."],
            "Zrób deploy na stagingu i odpal testy.",
        ),
        "04_haslo_w_srodku": (["Powiedz mu, wyślij teraz ten raport do klienta.", 1.0, "Dzięki."], NOSEND),
        "05_anulowanie": (
            ["To jest tajna wiadomość.", 1.0, "Anuluj wszystko.", 1.2, "Nowa wiadomość.", 1.0, "Wyślij teraz."],
            "Nowa wiadomość.",
        ),
        "06_komendy": (
            ["Lista zakupów dwukropek mleko przecinek chleb kropka", 1.0, "Wyślij teraz."],
            "Lista zakupów: mleko, chleb.",
        ),
        "07_nowa_linia": (
            ["Cześć.", 0.8, "Nowa linia.", 0.8, "Dzięki za pomoc.", 1.0, "Wyślij teraz."],
            "Cześć\nDzięki za pomoc.",
        ),
        "08_cofnij": (
            ["Spotkajmy się", 0.9, "w poniedziałek.", 0.9, "Cofnij.", 0.9, "we wtorek.", 1.0, "Wyślij teraz."],
            "Spotkajmy się we wtorek.",
        ),
        "09_autopoprawka": (
            ["Spotkanie w poniedziałek, nie, we wtorek o dziesiątej.", 1.0, "Wyślij teraz."],
            "Spotkanie we wtorek o dziesiątej.",
        ),
        "10_pytanie": (
            [
                "Czy możesz sprawdzić logi z produkcji,",
                1.2,
                "bo coś się sypie od rana?",
                2.0,
                "Daj znać, co znalazłeś.",
                1.0,
                "Wyślij teraz.",
            ],
            "Czy możesz sprawdzić logi z produkcji, bo coś się sypie od rana? Daj znać, co znalazłeś.",
        ),
        "11_bez_hasla": (["To tylko notatka dla siebie, nic nie wysyłaj."], NOSEND),
        "12_dlugie_pauzy_myslenia": (
            ["Myślę, że", 1.6, "najlepiej będzie", 1.4, "przenieść to na przyszły tydzień.", 1.0, "Wyślij teraz."],
            "Myślę, że najlepiej będzie przenieść to na przyszły tydzień.",
        ),
    },
    "en": {
        "01_thinking_after_on": (
            ["We ship it on", 1.8, "Monday morning.", 1.0, "Send it now."],
            "We ship it on Monday morning.",
        ),
        "02_two_sentences": (
            ["The report is ready.", 2.0, "I will send it tomorrow.", 1.2, "Send it now."],
            "The report is ready. I will send it tomorrow.",
        ),
        "03_tech_terms": (
            ["Deploy the build to staging", 1.0, "and run the tests.", 1.0, "Send it now."],
            "Deploy the build to staging and run the tests.",
        ),
        "04_phrase_mid_sentence": (["Tell him to send it now to the client.", 1.0, "Thanks."], NOSEND),
        "05_cancel": (
            ["This is a secret message.", 1.0, "Cancel everything.", 1.2, "New message.", 1.0, "Send it now."],
            "New message.",
        ),
        "06_commands": (["Groceries colon milk comma bread period", 1.0, "Send it now."], "Groceries: milk, bread."),
        "07_new_line": (
            ["Hi.", 0.8, "New line.", 0.8, "Thanks for your help.", 1.0, "Send it now."],
            "Hi\nThanks for your help.",
        ),
        "08_scratch_that": (
            ["Let's meet", 0.9, "on Monday.", 0.9, "Scratch that.", 0.9, "on Tuesday.", 1.0, "Send it now."],
            "Let's meet on Tuesday.",
        ),
        "09_self_correction": (
            ["The meeting is on Monday, no, on Tuesday at ten.", 1.0, "Send it now."],
            "The meeting is on Tuesday at ten.",
        ),
        "10_question": (
            [
                "Can you check the production logs,",
                1.2,
                "because something has been failing since morning?",
                2.0,
                "Let me know what you find.",
                1.0,
                "Send it now.",
            ],
            "Can you check the production logs, because something has been failing since morning? "
            "Let me know what you find.",
        ),
        "11_no_phrase": (["This is just a note to myself, do not send anything."], NOSEND),
        "12_long_thinking_pauses": (
            ["I think that", 1.6, "the best option is", 1.4, "to move it to next week.", 1.0, "Send it now."],
            "I think that the best option is to move it to next week.",
        ),
    },
}


def main(language: str, voice_path: str, out_dir: str) -> int:
    from piper import PiperVoice

    voice = PiperVoice.load(voice_path)

    def say(text: str) -> np.ndarray:
        audio = np.concatenate([chunk.audio_float_array for chunk in voice.synthesize(text)])
        x = np.linspace(0, len(audio) - 1, int(len(audio) * SR / voice.config.sample_rate))
        return np.interp(x, np.arange(len(audio)), audio).astype(np.float32)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, (parts, expected) in CASES[language].items():
        pieces = [np.zeros(int(0.5 * SR), np.float32)]
        pieces += [np.zeros(int(p * SR), np.float32) if isinstance(p, (int, float)) else say(p) for p in parts]
        pieces.append(np.zeros(int(1.5 * SR), np.float32))
        audio = np.clip(np.concatenate(pieces), -1, 1)
        with wave.open(str(out / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes((audio * 32767).astype("<i2").tobytes())
        (out / f"{name}.txt").write_text(expected + "\n", encoding="utf-8")
    print(f"{len(CASES[language])} recordings in {out}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in CASES:
        sys.exit(__doc__)
    sys.exit(main(*sys.argv[1:]))
