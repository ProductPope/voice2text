"""Interface language. Messages are written as t("polski", "English") pairs so both
versions sit next to each other in the code and can't drift apart."""

from __future__ import annotations

SUPPORTED = ("pl", "en")
_language = "pl"


def set_language(language: str) -> str:
    global _language
    _language = language if language in SUPPORTED else "en"
    return _language


def language() -> str:
    return _language


def ui_language(config) -> str:
    """app.ui_language, where "auto" follows the dictation language."""
    chosen = config["app"]["ui_language"]
    return chosen if chosen != "auto" else config["general"]["language"]


def t(pl: str, en: str) -> str:
    return en if _language == "en" else pl
