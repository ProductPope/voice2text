import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace

import pytest

from dictaitor import intent
from dictaitor.config import Config
from dictaitor.learning import LearnedStore
from dictaitor.script import parse_script
from dictaitor.session import Session

DRAFT = "Spotkanie w poniedziałek, nie, we wtorek o dziesiątej."
CLEAN = "Spotkanie we wtorek o dziesiątej."


def cfg(**intent_cfg):
    return Config.from_dict({"intent": intent_cfg})


# ------------------------------------------------------------------ guard


def test_guard_accepts_faithful_cleanup():
    assert intent.suspicious(DRAFT, CLEAN) == ""


@pytest.mark.parametrize(
    "result,reason",
    [
        ("", "pusty"),
        (CLEAN + " Daj znać, czy pasuje, chętnie przygotuję agendę i salę na to spotkanie.", "dopisał"),
        ("Zebranie zaplanowano na środę rano w biurze.", "zmienił"),
    ],
)
def test_guard_rejects_invented_content(result, reason):
    assert reason in intent.suspicious(DRAFT, result)


# ----------------------------------------------------------------- prompt


def test_prompt_contains_style_profile_and_examples():
    config = Config.from_dict({"intent": {"instructions": "Bez wykrzykników."}, "profiles": {"Slack": "Luźno."}})
    system, user = intent.build_prompt(
        DRAFT, "Bez wykrzykników.\n" + intent.profile_for("general | Slack", config["profiles"]), [("a b", "A, b.")]
    )
    assert "Bez wykrzykników." in system and "Luźno." in system and "<draft>a b</draft>" in system
    assert user == f"<draft>{DRAFT}</draft>"
    assert intent.profile_for("Notatnik", config["profiles"]) == ""


# ------------------------------------------------------------ local model


class _Handler(BaseHTTPRequestHandler):
    reply = CLEAN
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        _Handler.seen.append((self.path, body))
        out = json.dumps({"choices": [{"message": {"content": _Handler.reply}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _Handler.seen.clear()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_local_backend_roundtrip(local_server):
    config = cfg(mode="local", local_url=local_server, local_model="test-model")
    r = intent.refine(DRAFT, config, [])
    assert (r.text, r.used, r.note) == (CLEAN, "local", "")
    path, body = _Handler.seen[0]
    assert path == "/v1/chat/completions" and body["model"] == "test-model" and body["temperature"] == 0


def test_local_backend_guard_keeps_draft(local_server):
    _Handler.reply = "Zupełnie inny tekst, który model sobie wymyślił od zera, bez sensu i bez związku."
    try:
        r = intent.refine(DRAFT, cfg(mode="local", local_url=local_server), [])
    finally:
        _Handler.reply = CLEAN
    assert r.text == DRAFT and "odrzucony" in r.note


def test_local_backend_refuses_remote_url():
    r = intent.refine(DRAFT, cfg(mode="local", local_url="https://api.example.com"), [])
    assert r.text == DRAFT and "zablokowano" in r.note


def test_local_backend_down_keeps_draft():
    r = intent.refine(DRAFT, cfg(mode="local", local_url="http://127.0.0.1:9", timeout=1.0), [])
    assert r.text == DRAFT and "nie odpowiada" in r.note


# ----------------------------------------------------------------- Claude


class FakeClaude:
    def __init__(self, text=CLEAN, stop_reason="end_turn"):
        self.calls = []
        self.text, self.stop_reason = text, stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=self.text)])


def test_claude_request_shape():
    pytest.importorskip("anthropic")
    client = FakeClaude()
    cfg_ = cfg(mode="claude")["intent"]
    assert intent.call_claude("sys", "<draft>x</draft>", cfg_, client) == CLEAN
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"] == {"effort": "low"}
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "thinking" not in call and "temperature" not in call


def test_claude_haiku_gets_plain_request():
    pytest.importorskip("anthropic")
    client = FakeClaude()
    intent.call_claude("sys", "u", cfg(mode="claude", claude_model="claude-haiku-4-5")["intent"], client)
    assert not {"output_config", "fallbacks", "betas"} & set(client.calls[0])


def test_claude_refusal_keeps_draft(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.setitem(
        intent.BACKENDS, "claude", lambda s, u, c: intent.call_claude(s, u, c, FakeClaude("", "refusal"))
    )
    r = intent.refine(DRAFT, cfg(mode="claude"), [])
    assert r.text == DRAFT and "odmówił" in r.note


def test_claude_without_key_keeps_draft(monkeypatch):
    pytest.importorskip("anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(intent, "get_api_key", lambda: None)
    r = intent.refine(DRAFT, cfg(mode="claude"), [])
    assert r.text == DRAFT and "klucza" in r.note


# ---------------------------------------------------------------- session


def test_session_sends_refined_text_with_profile(monkeypatch):
    seen = {}

    def fake_backend(system, user, c):
        seen["system"] = system
        return "Raport gotowy."

    monkeypatch.setitem(intent.BACKENDS, "local", fake_backend)
    config = Config.from_dict({"intent": {"mode": "local"}, "profiles": {"Slack": "Luźno."}})
    sent = []
    session = Session(config, LearnedStore(), sink=lambda t: sent.append(t) or "ok")
    session.context = "#general - Slack"
    for words in parse_script("Raport raport gotowy [1.0] wyślij teraz", 0.6):
        session.feed(words)
    assert sent == ["Raport gotowy."] and "Luźno." in seen["system"]


def test_guard_rejects_invented_word_but_accepts_fixes():
    # Real outputs of a local 7B model on Whisper drafts (measured).
    assert "dopisał" in intent.suspicious(
        "Zrobimy to wy. Poniedziałek rano.", "Zrobimy to wyciągnemy to poniedziałek rano."
    )
    assert intent.suspicious("Zrobimy to wy. Poniedziałek rano.", "Zrobimy to w poniedziałek rano.") == ""
    assert (
        intent.suspicious(
            "Wyślę ci raport, to znaczy, wyślę ci prezentację jutro rano.", "Wyślę ci prezentację jutro rano."
        )
        == ""
    )
    assert intent.suspicious("Zrób deploy na stegingu i i odpal testy.", "Zrób deploy na stagingu i odpal testy.") == ""


def test_warm_up_hits_local_server(local_server):
    intent.warm_up(cfg(mode="local", local_url=local_server))
    assert _Handler.seen and _Handler.seen[-1][0] == "/v1/chat/completions"
    intent.warm_up(cfg(mode="off"))  # no-op


def test_guard_protects_self_corrections():
    draft = "Spotkanie w poniedziałek, nie we wtorek o 10."
    assert intent.corrected_words(draft) == ["wtorek"]
    # measured: a local 7B model kept the wrong day
    assert "poprawkę" in intent.suspicious(draft, "Spotkanie w poniedziałek o 10.")
    assert intent.suspicious(draft, "Spotkanie we wtorek o 10.") == ""
    assert intent.corrected_words("Nie wiem, czy zdążę.") == []
    assert intent.corrected_words("Wyślę ci raport, to znaczy, prezentację.") == ["prezentacje"]


def test_guard_knows_english_self_corrections():
    draft = "Let's meet on Monday, no, on Tuesday at ten."
    assert intent.corrected_words(draft, "en") == ["tuesday"]
    assert intent.suspicious(draft, "Let's meet on Monday at ten.", "en") != ""
    assert intent.suspicious(draft, "Let's meet on Tuesday at ten.", "en") == ""
    assert intent.corrected_words("I mean it, not later.", "en") == ["later"]
    assert intent.corrected_words("No problem at all.", "en") == []
    # Polish markers don't fire on English text and vice versa
    assert intent.corrected_words("Spotkanie w poniedziałek, no dobra.", "pl") == []
