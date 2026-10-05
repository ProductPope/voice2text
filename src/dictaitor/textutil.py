"""Small text helpers shared by the composer, gate and learner."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Punctuation Whisper glues onto words ("teraz." / "Cześć,").
_TRAILING_PUNCT = re.compile(r"([.,!?;:…]+)$")
_LEADING_PUNCT = re.compile(r"^[\"'„“”(\[]+")
_WORD_RE = re.compile(r"[\w'’-]+", re.UNICODE)


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # "ł" has no combining form, handle it explicitly.
    return stripped.replace("ł", "l").replace("Ł", "L")


def norm(text: str) -> str:
    """Lowercase, accent-free, punctuation-free form used for matching."""
    text = strip_accents(text.lower())
    return " ".join(_WORD_RE.findall(text))


def split_punct(token: str) -> tuple[str, str]:
    """Split "teraz." into ("teraz", ".")."""
    token = _LEADING_PUNCT.sub("", token.strip())
    m = _TRAILING_PUNCT.search(token)
    if not m:
        return token, ""
    return token[: m.start()], m.group(1)


def words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def matches_phrase(spoken: list[str], phrase: str, threshold: float) -> bool:
    """Fuzzy-compare a list of spoken words with a configured phrase."""
    if not spoken:
        return False
    return SequenceMatcher(None, norm(" ".join(spoken)), norm(phrase)).ratio() >= threshold


def capitalize_first(text: str) -> str:
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1 :]
    return text


def decapitalize_first(text: str) -> str:
    # Keep acronyms ("API", "PKO") untouched.
    if len(text) > 1 and text.isupper():
        return text
    return text[:1].lower() + text[1:]
