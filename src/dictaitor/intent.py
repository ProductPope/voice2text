"""Understanding intent: an LLM tidies the draft the way you meant it.

"w poniedziałek… nie, we wtorek" -> "we wtorek"; false starts and repeats go,
your style instructions and recent corrections are followed. Content is never
added: a guard compares the result with the draft and falls back to the
draft when the model wrote something you didn't say.

Backends:
* local - any OpenAI-compatible server on this machine (Ollama, LM Studio,
  llama.cpp). Refuses non-local URLs unless allow_remote = true.
* claude - the Claude API. Text leaves the computer, so it is opt-in, and the
  API key is kept in the Windows Credential Manager, never in config files.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

from .config import Config
from .i18n import t
from .textutil import norm, similarity

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
KEYRING_SERVICE = "dictaitor"
KEYRING_USER = "anthropic-api-key"

SYSTEM = """You clean up dictated text. The user spoke it aloud; a speech recogniser and \
pause rules produced the draft. Return the text the user meant to write.

Rules:
- Apply the speaker's self-corrections: "on Monday, no, on Tuesday" means "on Tuesday".
- Remove false starts, stutters, repeated words and abandoned half-sentences.
- Fix punctuation and capitalisation. Keep line breaks the speaker asked for.
- Keep the language, wording, tone and meaning. Do not summarise, do not answer \
questions in the text, do not add greetings, facts or anything the speaker did not say.
- Keep technical terms, names and words from other languages exactly as spoken.
- If the draft is already fine, return it unchanged.
Output only the final text, with no quotes or comments."""


class IntentError(RuntimeError):
    pass


@dataclass
class Refined:
    text: str
    note: str = ""  # shown to the user when something fell back
    used: str = ""  # backend that produced the text, "" when the draft was kept


def profile_for(window_title: str, profiles: dict[str, str]) -> str:
    """Style instructions for the window you dictate into ("Slack" -> "luźno")."""
    title = window_title.lower()
    for needle, instructions in profiles.items():
        if needle.lower() in title:
            return instructions
    return ""


def build_prompt(draft: str, instructions: str, examples: list[tuple[str, str]]) -> tuple[str, str]:
    system = SYSTEM
    if instructions.strip():
        system += f"\n\nThe speaker's own style rules (follow them):\n{instructions.strip()}"
    if examples:
        shots = "\n".join(f"<example>\n<draft>{d}</draft>\n<final>{f}</final>\n</example>" for d, f in examples)
        system += "\n\nRecent drafts the speaker corrected by hand - learn their preferences from them:\n" + shots
    return system, f"<draft>{draft}</draft>"


def suspicious(draft: str, result: str, language: str = "pl") -> str:
    """Why the result can't be trusted, or "" when it looks like a faithful clean-up."""
    if not result.strip():
        return t("model zwrócił pusty tekst", "the model returned empty text")
    d, r = norm(draft).split(), norm(result).split()
    if len(r) > len(d) * 1.25 + 4:
        return t("model dopisał treść", "the model added content")
    known = set(d)
    new = [w for w in r if w not in known]
    if len(new) > max(3, len(r) // 4):
        return t("model zmienił zbyt wiele słów", "the model changed too many words")
    # A legitimate fix turns a misheard word into a close variant ("wy" -> "w",
    # "stegingu" -> "stagingu"). A word with no look-alike in the draft was invented
    # (measured: a local model wrote "wyciągnemy" into a sentence that never had it).
    for word in new:
        if len(word) >= 4 and max((similarity(word, k) for k in known), default=0.0) < 0.65:
            return t(f"model dopisał słowo „{word}”", f"the model added the word “{word}”")
    # "w poniedziałek, nie, we wtorek": the words after the correction are what you
    # meant. A model that kept the old option instead (measured with a 7B local
    # model) would reverse your message, so its result is not used.
    kept = set(r)
    for meant in corrected_words(draft, language):
        if meant not in kept:
            return t(f"model pominął Twoją poprawkę („{meant}”)", f"the model dropped your correction (“{meant}”)")
    return ""


# Phrases that introduce a self-correction. "nie"/"no" count only after a comma
# (", nie we wtorek"), otherwise "nie wiem" would look like a correction.
_CORRECTION = {
    "pl": r",\s*nie\b|\bto znaczy\b|\bznaczy\b|\ba właściwie\b|\bprzepraszam\b|\balbo nie\b|\bsorry\b",
    "en": r",\s*no\b|\bi mean\b|\bor rather\b|\bsorry\b",
}
_NEGATIONS = {"nie", "not"}


def corrected_words(draft: str, language: str = "pl") -> list[str]:
    """First content word after each self-correction marker, normalised."""
    pattern = re.compile(f"(?:{_CORRECTION.get(language, _CORRECTION['pl'])})[\\s,.:;–-]*", re.IGNORECASE)
    out = []
    for m in pattern.finditer(draft):
        following = norm(draft[m.end() :]).split()
        content = [w for w in following if len(w) >= 3 and w not in _NEGATIONS]
        if content:
            out.append(content[0])
    return out


def _clean(text: str) -> str:
    text = text.strip()
    for tag in ("<final>", "</final>", "<draft>", "</draft>"):
        text = text.replace(tag, "")
    return text.strip().strip('"„”').strip()


# ----------------------------------------------------------------- backends


def call_local(system: str, user: str, cfg: dict) -> str:
    url = cfg["local_url"].rstrip("/")
    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS and not cfg["allow_remote"]:
        raise IntentError(
            t(
                f"intent.local_url wskazuje na {host!r}, a nie na ten komputer – zablokowano.",
                f"intent.local_url points to {host!r}, not to this computer – blocked.",
            )
        )
    body = json.dumps(
        {
            "model": cfg["local_model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "stream": False,
        }
    ).encode()
    req = urllib.request.Request(url + "/v1/chat/completions", data=body, headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # stay on this machine
    try:
        with opener.open(req, timeout=float(cfg["timeout"])) as resp:
            data = json.loads(resp.read())
    except OSError as exc:
        raise IntentError(
            t(
                f"lokalny model nie odpowiada ({exc}) – czy Ollama/LM Studio jest uruchomione?",
                f"the local model is not responding ({exc}) – is Ollama/LM Studio running?",
            )
        ) from exc
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise IntentError(
            t("nieoczekiwana odpowiedź lokalnego modelu", "unexpected reply from the local model")
        ) from exc


def get_api_key() -> str | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        return None


def set_api_key(key: str) -> None:
    import keyring

    if key:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception:
            pass


# Models that take effort and server-side refusal fallbacks.
_CURRENT_FAMILY = ("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")


def call_claude(system: str, user: str, cfg: dict, client=None) -> str:
    import anthropic

    if client is None:
        key = get_api_key()
        if not key:
            raise IntentError(
                t("brak klucza API Claude – dodaj go w Ustawieniach", "no Claude API key – add it in Settings")
            )
        client = anthropic.Anthropic(api_key=key, timeout=float(cfg["timeout"]), max_retries=1)
    model = cfg["claude_model"]
    kwargs = dict(
        model=model,
        max_tokens=4096,  # a cleaned-up dictation is never longer than this
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if model.startswith(_CURRENT_FAMILY):
        # Short clean-up work: lowest effort keeps latency down.
        kwargs["output_config"] = {"effort": "low"}
        kwargs["betas"] = ["server-side-fallback-2026-07-01"]
        kwargs["fallbacks"] = "default"
    try:
        response = client.beta.messages.create(**kwargs)
    except anthropic.AuthenticationError as exc:
        raise IntentError(t("klucz API Claude jest nieprawidłowy", "the Claude API key is invalid")) from exc
    except anthropic.RateLimitError as exc:
        raise IntentError(
            t("limit zapytań Claude – spróbuj za chwilę", "Claude rate limit – try again in a moment")
        ) from exc
    except anthropic.APIConnectionError as exc:
        raise IntentError(t("brak połączenia z Claude", "can't connect to Claude")) from exc
    except anthropic.APIStatusError as exc:
        raise IntentError(t(f"błąd Claude API ({exc.status_code})", f"Claude API error ({exc.status_code})")) from exc
    if response.stop_reason == "refusal":
        raise IntentError(t("Claude odmówił przetworzenia tego tekstu", "Claude declined to process this text"))
    return "".join(block.text for block in response.content if block.type == "text")


BACKENDS = {"local": call_local, "claude": call_claude}


def warm_up(config: Config) -> None:
    """Load the local model while you speak, so the first clean-up isn't slow.

    Measured on CPU: a cold 3-7B model needs 12-21 s to answer the first time,
    which would blow the timeout right after the safe phrase.
    """
    cfg = config["intent"]
    if cfg["mode"] != "local":
        return
    try:
        call_local("Reply with OK.", "OK", {**cfg, "timeout": 120})
    except Exception:
        pass  # the real request will report the problem


def refine(draft: str, config: Config, examples: list[tuple[str, str]], window_title: str = "") -> Refined:
    cfg = config["intent"]
    mode = cfg["mode"]
    if mode == "off" or not draft.strip():
        return Refined(draft)
    if mode not in BACKENDS:
        return Refined(draft, f"nieznany intent.mode = {mode!r}")
    instructions = "\n".join(
        x for x in (cfg["instructions"], profile_for(window_title, config["profiles"])) if x.strip()
    )
    system, user = build_prompt(draft, instructions, examples[-int(cfg["examples"]) :] if cfg["examples"] else [])
    try:
        result = _clean(BACKENDS[mode](system, user, cfg))
    except IntentError as exc:
        return Refined(draft, t(f"porządkowanie AI pominięte: {exc}", f"AI clean-up skipped: {exc}"))
    except Exception as exc:  # never lose the dictation because of the LLM step
        return Refined(
            draft,
            t(
                f"porządkowanie AI pominięte: {exc.__class__.__name__}: {exc}",
                f"AI clean-up skipped: {exc.__class__.__name__}: {exc}",
            ),
        )
    reason = suspicious(draft, result, config["general"]["language"])
    if reason:
        return Refined(
            draft,
            t(
                f"wynik AI odrzucony ({reason}) – wysłano tekst bez zmian",
                f"AI result rejected ({reason}) – the text was sent unchanged",
            ),
        )
    return Refined(result, used=mode)
