"""Configuration: defaults, user overrides from TOML, storage locations."""

from __future__ import annotations

import copy
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Polish defaults; every list/map can be overridden in config.toml.
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
    "i", "a", "oraz", "albo", "lub", "ale", "lecz", "bo", "że", "żeby", "aby",
    "który", "która", "które", "którzy", "gdy", "kiedy", "jeśli", "jeżeli",
    "w", "we", "na", "do", "z", "ze", "o", "od", "po", "przy", "dla", "za",
    "pod", "nad", "przez", "u", "to", "jest", "są", "czy", "jak", "niż",
    "the", "and", "or", "but", "to", "of", "in", "on", "for", "with", "that",
]

DEFAULTS: dict[str, Any] = {
    "general": {
        "language": "pl",
        "model": "small",
        "device": "auto",
        "compute_type": "int8",
    },
    "gate": {
        "send_phrase": "wyślij teraz",
        "cancel_phrase": "anuluj wszystko",
        "match_threshold": 0.8,
        # The send phrase only counts when followed by a pause, so saying it
        # in the middle of a sentence never sends anything.
        "require_pause": True,
    },
    "pauses": {
        "comma_gap": 0.7,
        "sentence_gap": 1.5,
        "split_silence": 0.6,
        "learn": True,
    },
    "commands": DEFAULT_COMMANDS,
    "text": {
        "fillers": DEFAULT_FILLERS,
        "continuations": DEFAULT_CONTINUATIONS,
        # Pausing before these never adds a comma ("w środę … i w czwartek").
        "no_comma_before": ["i", "oraz", "lub", "albo", "czy", "ani", "ni", "and", "or", "nor"],
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
    "polish": {
        "enabled": False,
        "url": "http://localhost:11434",
        "model": "llama3.1",
        "instructions": "",
        "allow_remote": False,
    },
    "learning": {
        "min_occurrences": 2,
        "min_pause_samples": 12,
    },
    "audio": {
        "sample_rate": 16000,
        "energy_threshold": 0.0,
        "max_chunk_seconds": 25.0,
    },
}


def home_dir() -> Path:
    env = os.environ.get("DICTAITOR_HOME")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "dictaitor"


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

    def __getitem__(self, section: str) -> dict[str, Any]:
        return self.data[section]

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or home_dir() / "config.toml"
        if not path.exists():
            return cls(path=path)
        with path.open("rb") as fh:
            user = tomllib.load(fh)
        commands = user.pop("commands", None)
        data = _merge(DEFAULTS, user)
        if commands is not None:
            # Commands merge key-by-key; an empty string disables a default command.
            merged = dict(DEFAULT_COMMANDS)
            merged.update(commands)
            data["commands"] = {k: v for k, v in merged.items() if v != ""}
        return cls(data=data, path=path)

    @classmethod
    def from_dict(cls, override: dict[str, Any]) -> "Config":
        return cls(data=_merge(DEFAULTS, override))
