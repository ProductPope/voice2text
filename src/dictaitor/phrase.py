"""Checking a safe phrase before trusting it: is it distinctive, does Whisper hear it?"""

from __future__ import annotations

from dataclasses import dataclass, field

from .textutil import matches_phrase, norm, similarity

# Words too common in normal speech to make a safe phrase on their own.
_COMMON = {"ok", "okej", "dobra", "tak", "nie", "wyślij", "wyslij", "send", "koniec", "dalej", "gotowe"}


@dataclass
class PhraseCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)
    heard: list[tuple[str, bool]] = field(default_factory=list)  # (what Whisper heard, matched?)


def check_phrase(phrase: str, heard: list[str], threshold: float, cancel_phrase: str = "") -> PhraseCheck:
    problems = []
    words = norm(phrase).split()
    if len(words) < 2 or len(norm(phrase)) < 8:
        problems.append("Hasło jest za krótkie – łatwo powiedzieć je przypadkiem. Użyj 2–3 słów.")
    elif all(w in _COMMON for w in words):
        problems.append("Hasło składa się z bardzo częstych słów. Dodaj coś nietypowego.")
    if cancel_phrase and (similarity(phrase, cancel_phrase) > 0.6 or set(words) & set(norm(cancel_phrase).split())):
        problems.append("Hasło wysyłki jest zbyt podobne do hasła anulowania.")
    results = [(h, matches_phrase(h.split(), phrase, threshold)) for h in heard]
    misses = sum(1 for _, ok in results if not ok)
    if misses:
        problems.append(
            f"Whisper nie rozpoznał hasła {misses} z {len(results)} razy. "
            "Wybierz wyraźniejsze słowa albo dodaj je do słownika."
        )
    return PhraseCheck(not problems, problems, results)
