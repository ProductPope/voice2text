import json
import os

import pytest

from dictaitor import autostart
from dictaitor.config import Config, update_file
from dictaitor.learning import LearnedStore
from dictaitor.phrase import check_phrase
from dictaitor.script import parse_script
from dictaitor.session import Session

# ----------------------------------------------------------- config file


def test_update_file_keeps_comments_and_adds_missing(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        '# moje ustawienia\n[gate]\nsend_phrase = "wyślij teraz"   # hasło\n\n[pauses]\ncomma_gap = 0.7\n',
        encoding="utf-8",
    )
    update_file(path, {"gate": {"send_phrase": 'zatwierdzam "to"', "match_threshold": 0.85}, "app": {"abort_seconds": 1.5}})
    text = path.read_text(encoding="utf-8")
    assert "# moje ustawienia" in text and "# hasło" in text
    cfg = Config.load(path)
    assert cfg["gate"]["send_phrase"] == 'zatwierdzam "to"'
    assert cfg["gate"]["match_threshold"] == 0.85
    assert cfg["app"]["abort_seconds"] == 1.5
    assert cfg["pauses"]["comma_gap"] == 0.7
    assert cfg.warnings == []


def test_update_file_creates_file(tmp_path):
    path = tmp_path / "new" / "config.toml"
    update_file(path, {"app": {"delivery": "paste"}})
    assert Config.load(path)["app"]["delivery"] == "paste"


# ---------------------------------------------------------------- phrase


def test_good_phrase_heard_every_time():
    r = check_phrase("zatwierdzam bez zmian", ["Zatwierdzam bez zmian.", "zatwierdzam bez zmian", "Zatwierdzam, bez zmian!"], 0.8)
    assert r.ok and all(ok for _, ok in r.heard)


def test_short_and_common_phrases_are_flagged():
    assert not check_phrase("ok", [], 0.8).ok
    assert "częstych" in check_phrase("dobra wyślij", [], 0.8).problems[0]


def test_misheard_phrase_is_flagged():
    r = check_phrase("zatwierdzam bez zmian", ["zatwierdzam bez zmian", "a twierdza mi się zmian", "zatwierdzam bez zmian"], 0.8)
    assert not r.ok and "1 z 3" in r.problems[0]


def test_phrase_too_similar_to_cancel():
    r = check_phrase("anuluj teraz", [], 0.8, cancel_phrase="anuluj wszystko")
    assert any("anulowania" in p for p in r.problems)


# ------------------------------------------------------- correct last sent


def send(session, script):
    for words in parse_script(script, 0.6):
        session.feed(words)


def test_correction_after_sending_teaches_words_and_examples(tmp_path):
    store = LearnedStore(path=tmp_path / "learned.json")
    config = Config.from_dict({"learning": {"min_occurrences": 2}})
    session = Session(config, store, sink=lambda t: "ok")
    for _ in range(2):
        send(session, "Baza to postgres [1.0] wyślij teraz")
        assert session.learn_correction("Baza to PostgreSQL.") == [("postgres", "PostgreSQL")]
    sent = []
    session.sink = lambda t: sent.append(t) or "ok"
    send(session, "Baza to postgres [1.0] wyślij teraz")
    assert sent == ["Baza to PostgreSQL."]
    saved = json.loads((tmp_path / "learned.json").read_text(encoding="utf-8"))
    assert saved["examples"][-1] == ["Baza to postgres.", "Baza to PostgreSQL."]


def test_correction_without_change_or_before_sending_does_nothing():
    session = Session(Config(), LearnedStore(), sink=lambda t: "ok")
    assert session.learn_correction("cokolwiek") == []
    send(session, "Tekst [1.0] wyślij teraz")
    assert session.learn_correction("Tekst.") == []


# -------------------------------------------------------- export / import


def test_export_import_roundtrip():
    a = LearnedStore()
    a.add_replacement("ajfon", "iPhone", weight=2)
    a.add_example("draft", "final")
    b = LearnedStore()
    b.add_replacement("ajfon", "iPhone")
    assert b.import_rules(json.loads(json.dumps(a.export_rules()))) == 1
    assert b.replacements == {"ajfon": {"iPhone": 3}}
    assert b.examples == [("draft", "final")]
    with pytest.raises(ValueError):
        b.import_rules({"cos": 1})


def test_remove_replacement():
    s = LearnedStore()
    s.add_replacement("a", "b")
    assert s.remove_replacement("a") and not s.remove_replacement("a")


# --------------------------------------------------------------- autostart


@pytest.mark.skipif(os.name != "nt", reason="Windows registry")
def test_autostart_roundtrip():
    was = autostart.is_enabled()
    try:
        autostart.set_enabled(True)
        assert autostart.is_enabled()
        autostart.set_enabled(False)
        assert not autostart.is_enabled()
    finally:
        autostart.set_enabled(was)


def test_autostart_command_runs_the_app():
    assert autostart.command().endswith("-m dictaitor.app")
