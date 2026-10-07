"""Configuration: defaults, user overrides from TOML, storage locations."""

from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Language presets (general.language picks one); every list/map can be overridden
# in config.toml. Polish is the default.
DEFAULT_COMMANDS: dict[str, str] = {
    "kropka": ".",
    "przecinek": ",",
    "znak zapytania": "?",
    "wykrzyknik": "!",
    "dwukropek": ":",
    "średnik": ";",
    "myślnik": " –",
    "nowa linia": "\n",
    "nowy akapit": "\n\n",
    "cofnij": "@undo",
    "skreśl to": "@undo",
    "wyczyść wszystko": "@clear",
}

DEFAULT_FILLERS = ["yyy", "yy", "eee", "ee", "mmm", "hmm", "hm", "eh", "um", "uh", "uhm"]

# A pause right after one of these words is a "thinking" pause, never a sentence end.
DEFAULT_CONTINUATIONS = [
    "i",
    "a",
    "oraz",
    "albo",
    "lub",
    "ale",
    "lecz",
    "bo",
    "że",
    "żeby",
    "aby",
    "który",
    "która",
    "które",
    "którzy",
    "gdy",
    "kiedy",
    "jeśli",
    "jeżeli",
    "w",
    "we",
    "na",
    "do",
    "z",
    "ze",
    "o",
    "od",
    "po",
    "przy",
    "dla",
    "za",
    "pod",
    "nad",
    "przez",
    "u",
    "to",
    "jest",
    "są",
    "czy",
    "jak",
    "niż",
    "the",
    "and",
    "or",
    "but",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "that",
]

EN_COMMANDS: dict[str, str] = {
    "period": ".",
    "full stop": ".",
    "comma": ",",
    "question mark": "?",
    "exclamation mark": "!",
    "colon": ":",
    "semicolon": ";",
    "dash": " –",
    "new line": "\n",
    "new paragraph": "\n\n",
    "scratch that": "@undo",
    "undo that": "@undo",
    "clear everything": "@clear",
}

EN_CONTINUATIONS = [
    "and",
    "or",
    "but",
    "because",
    "so",
    "that",
    "which",
    "who",
    "when",
    "if",
    "than",
    "to",
    "of",
    "in",
    "on",
    "at",
    "for",
    "with",
    "from",
    "by",
    "about",
    "into",
    "the",
    "a",
    "an",
    "is",
    "are",
    "my",
    "your",
]

# English words that keep their capital even where dictAItor lowers Whisper's
# chunk-start capital ("on [pause] Friday").
EN_KEEP_CASE = ["I", "I'm", "I'll", "I've", "I'd"] + (
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April June July "
    "August September October November December"
).split()

# What changes with general.language. Anything set in config.toml still wins.
LANGUAGES: dict[str, dict[str, Any]] = {
    "pl": {
        "gate": {"send_phrase": "wyślij teraz", "cancel_phrase": "anuluj wszystko"},
        "commands": DEFAULT_COMMANDS,
        "text": {
            "fillers": DEFAULT_FILLERS,
            "continuations": DEFAULT_CONTINUATIONS,
            # Pausing before these never adds a comma ("w środę … i w czwartek").
            "no_comma_before": ["i", "oraz", "lub", "albo", "czy", "ani", "ni", "and", "or", "nor"],
        },
    },
    "en": {
        "gate": {"send_phrase": "send it now", "cancel_phrase": "cancel everything"},
        "commands": EN_COMMANDS,
        "text": {
            "fillers": ["um", "uh", "uhm", "erm", "er", "hmm", "hm", "mmm", "ah"],
            "continuations": EN_CONTINUATIONS,
            "no_comma_before": ["and", "or", "nor"],
            "keep_case": EN_KEEP_CASE,
        },
    },
}

DEFAULTS: dict[str, Any] = {
    "general": {
        "language": "pl",
        # "auto" picks by hardware: large-v3-turbo on an NVIDIA GPU or 8+ cores, else small.
        "model": "auto",
        "device": "auto",
        "compute_type": "auto",
        # Optional Whisper initial prompt. Empty is best for most people (measured).
        "prompt": "",
    },
    "gate": {
        "send_phrase": LANGUAGES["pl"]["gate"]["send_phrase"],
        "cancel_phrase": LANGUAGES["pl"]["gate"]["cancel_phrase"],
        "match_threshold": 0.8,
        # The send phrase only counts when followed by a pause, so saying it
        # in the middle of a sentence never sends anything.
        "require_pause": True,
    },
    "pauses": {
        "comma_gap": 0.7,
        "sentence_gap": 1.5,
        "split_silence": 0.6,
        # Re-read the chunk before a thinking pause together with the next one.
        # Off by default: on Polish test speech with the "small" model it did not help.
        "rejoin": False,
        "learn": True,
    },
    "commands": DEFAULT_COMMANDS,
    "text": {
        **LANGUAGES["pl"]["text"],
        "keep_case": [],
    },
    "rules": {
        "replacements": {},
        "vocabulary": [],
    },
    "output": {
        "mode": "clipboard",
        "file": "",
        "command": "",
    },
    "review": {
        "enabled": False,
    },
    "intent": {
        # off | local (Ollama, LM Studio, llama.cpp on this computer) | claude (cloud, opt-in)
        "mode": "off",
        "instructions": "",
        "local_url": "http://localhost:11434",
        "local_model": "qwen2.5:7b",
        "claude_model": "claude-opus-5-5",
        "timeout": 8.0,
        "examples": 6,  # how many of your recent corrections to show the model
        "allow_remote": False,
    },
    # Window title fragment -> extra style rules, e.g. "Slack" = "luźno, bez kropki na końcu"
    "profiles": {},
    "learning": {
        "min_occurrences": 2,
        "min_pause_samples": 12,
    },
    "app": {
        "hotkey": "ctrl+alt+d",
        "correct_hotkey": "ctrl+alt+k",
        # Seconds between the safe phrase and typing; Esc cancels. 0 = no wait.
        "abort_seconds": 0.8,
        "delivery": "auto",  # auto | type | paste | clipboard
        "paste_over_chars": 300,
    },
    "audio": {
        "vad": "auto",  # auto | silero | energy
        "energy_threshold": 0.0,
        "max_chunk_seconds": 25.0,
        # Seconds between live previews of the chunk being spoken; 0 = off.
        "preview_interval": 1.0,
    },
}


# Sections whose keys are free-form (user phrases), so unknown keys are fine there.
_FREE_FORM = {("commands",), ("rules", "replacements"), ("profiles",)}


def home_dir() -> Path:
    env = os.environ.get("DICTAITOR_HOME")
    if env:
        return Path(env).expanduser()
    if os.name == "nt" and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "dictaitor"
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "dictaitor"


def unknown_keys(user: dict[str, Any], defaults: dict[str, Any] = DEFAULTS, prefix: tuple = ()) -> list[str]:
    """Dotted names of settings that don't exist - almost always typos."""
    if prefix in _FREE_FORM:
        return []
    out = []
    for key, value in user.items():
        path = prefix + (key,)
        if key not in defaults:
            out.append(".".join(path))
        elif isinstance(value, dict) and isinstance(defaults[key], dict):
            out.extend(unknown_keys(value, defaults[key], path))
    return out


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict) and key != "commands":
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@dataclass
class Config:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    path: Path | None = None
    warnings: list[str] = field(default_factory=list)

    def __getitem__(self, section: str) -> dict[str, Any]:
        return self.data[section]

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        path = path or home_dir() / "config.toml"
        if not path.exists():
            return cls(path=path)
        with path.open("rb") as fh:
            user = tomllib.load(fh)
        warnings = [f"nieznane ustawienie w {path.name}: {k}" for k in unknown_keys(user)]
        language = user.get("general", {}).get("language", DEFAULTS["general"]["language"])
        if language not in LANGUAGES:
            warnings.append(f"general.language = {language!r}: hasła i komendy głosowe są tylko dla pl i en")
        return cls(data=_build(user), path=path, warnings=warnings)

    @classmethod
    def from_dict(cls, override: dict[str, Any]) -> Config:
        return cls(data=_build(copy.deepcopy(override)))


def defaults_for(language: str) -> dict[str, Any]:
    """DEFAULTS with the phrases, voice commands and word lists of one language."""
    preset = LANGUAGES.get(language)
    data = copy.deepcopy(DEFAULTS)
    data["general"]["language"] = language
    if preset:
        data["gate"].update(preset["gate"])
        data["commands"] = dict(preset["commands"])
        data["text"].update(copy.deepcopy(preset["text"]))
    return data


def _build(user: dict[str, Any]) -> dict[str, Any]:
    base = defaults_for(user.get("general", {}).get("language", DEFAULTS["general"]["language"]))
    commands = user.pop("commands", None)
    data = _merge(base, user)
    if commands is not None:
        # Commands merge key-by-key; an empty string disables a default command.
        merged = dict(base["commands"])
        merged.update(commands)
        data["commands"] = {k: v for k, v in merged.items() if v != ""}
    return data


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    raise TypeError(f"unsupported setting type: {type(value).__name__}")


def update_file(path: Path, changes: dict[str, dict[str, Any]]) -> None:
    """Change simple settings in config.toml in place, keeping the user's comments."""
    import re

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for section, values in changes.items():
        for key, value in values.items():
            line = f"{key} = {_toml_value(value)}"
            start = next((i for i, line_ in enumerate(lines) if line_.strip() == f"[{section}]"), None)
            if start is None:
                lines += ["", f"[{section}]", line]
                continue
            end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
            key_re = re.compile(rf"^\s*{re.escape(key)}\s*=")
            for i in range(start + 1, end):
                if key_re.match(lines[i]):
                    comment = re.search(r"\s+#.*$", lines[i].split("=", 1)[1])
                    keep = comment.group(0) if comment and lines[i].count('"') % 2 == 0 else ""
                    lines[i] = line + keep
                    break
            else:
                insert = end
                while insert > start + 1 and not lines[insert - 1].strip():
                    insert -= 1
                lines.insert(insert, line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
