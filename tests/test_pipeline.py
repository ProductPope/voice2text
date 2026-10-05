from dictaitor.composer import Composer
from dictaitor.config import Config
from dictaitor.gate import Action, Gate
from dictaitor.learning import LearnedStore, apply_replacements
from dictaitor.script import parse_script
from dictaitor.session import Session


def cfg(**override):
    return Config.from_dict(override)


def run(script, config=None, **kw):
    """Feed a script through a session; returns (sent texts, session)."""
    config = config or cfg()
    sent = []
    session = Session(config, kw.pop("store", LearnedStore()), sink=lambda t: sent.append(t) or "ok", **kw)
    for words in parse_script(script, config["pauses"]["split_silence"]):
        session.feed(words)
    return sent, session


def compose(script, config=None):
    config = config or cfg()
    c = Composer(config)
    for words in parse_script(script, config["pauses"]["split_silence"]):
        c.add_words(words)
    return c.render()


# --------------------------------------------------------------------- gate


def test_nothing_is_sent_without_safe_phrase():
    sent, session = run("To jest długa wiadomość [3.0] i jeszcze jedna [5.0] i koniec")
    assert sent == []
    assert "wiadomość" in session.draft()


def test_safe_phrase_sends_and_is_stripped():
    sent, _ = run("Cześć Ania [1.0] wyślij teraz")
    assert sent == ["Cześć Ania."]


def test_safe_phrase_mid_sentence_does_not_send():
    sent, session = run("Powiedz mu wyślij teraz ten raport [1.0] dzięki")
    assert sent == []
    assert "wyślij teraz ten raport" in session.draft()


def test_safe_phrase_tolerates_whisper_typos():
    sent, _ = run("Test [1.0] Wyślij, teraz.")
    assert sent == ["Test."]
    sent, _ = run("Test [1.0] wyslij terаz")
    assert sent == ["Test."]


def test_cut_chunk_does_not_trust_safe_phrase():
    gate = Gate(cfg())
    words = parse_script("tekst wyślij teraz", 0.6)[0]
    assert gate.check(words, followed_by_pause=False).action is Action.CONTINUE
    assert gate.check(words, followed_by_pause=True).action is Action.SEND


def test_cancel_phrase_clears_draft():
    sent, session = run("Tajne rzeczy [1.0] anuluj wszystko [1.0] Nowe [1.0] wyślij teraz")
    assert sent == ["Nowe."]


def test_custom_safe_phrase():
    sent, _ = run("Hej [1.0] wyślij teraz [1.0] zatwierdzam bez zmian", cfg(gate={"send_phrase": "zatwierdzam bez zmian"}))
    assert sent == ["Hej, wyślij teraz."]


# ----------------------------------------------------------------- composer


def test_thinking_pause_after_conjunction_is_not_a_sentence_end():
    assert compose("Zrobimy to w [2.0] poniedziałek") == "Zrobimy to w poniedziałek."


def test_long_pause_ends_sentence_and_capitalises():
    assert compose("Pierwsze zdanie [2.0] drugie zdanie") == "Pierwsze zdanie. Drugie zdanie."


def test_medium_pause_is_comma_but_not_before_i():
    assert compose("Pozdrawiam [1.0] Marcin") == "Pozdrawiam, marcin."
    assert compose("W środę [1.0] i w czwartek") == "W środę i w czwartek."


def test_whisper_period_at_chunk_edge_is_dropped_on_short_pause():
    # Whisper ends every chunk with "." - a short pause must not end the sentence.
    assert compose("Mam pomysł. [0.8] Zróbmy demo.") == "Mam pomysł, zróbmy demo."
    assert compose("Spotkanie jest. [0.8] W czwartek.") == "Spotkanie jest w czwartek."
    assert compose("Czy przyjdziesz? [0.8] Daj znać.") == "Czy przyjdziesz? Daj znać."


def test_whisper_punctuation_inside_continuous_speech_is_kept():
    assert compose("Tak, oczywiście. Do jutra.") == "Tak, oczywiście. Do jutra."


def test_fillers_are_removed():
    assert compose("Yyy [0.8] no więc eee robimy to") == "No więc robimy to."


def test_voice_commands():
    assert compose("Lista zakupów dwukropek mleko przecinek chleb kropka nowa linia Dzięki") == (
        "Lista zakupów: mleko, chleb.\nDzięki."
    )


def test_undo_removes_last_phrase():
    assert compose("Spotkajmy się [0.8] w poniedziałek [0.8] cofnij [0.8] we wtorek") == "Spotkajmy się, we wtorek."


def test_undo_within_one_chunk():
    config = cfg(pauses={"split_silence": 5.0})
    assert compose("Spotkajmy się [0.8] w poniedziałek rano [0.8] cofnij [0.8] we wtorek", config) == (
        "Spotkajmy się, we wtorek."
    )


def test_clear_command():
    assert compose("Coś złego [0.8] wyczyść wszystko [0.8] Dobre") == "Dobre."


def test_vocabulary_keeps_case():
    config = cfg(rules={"vocabulary": ["Marcin"]})
    assert compose("Pozdrawiam [1.0] Marcin", config) == "Pozdrawiam, Marcin."


# ----------------------------------------------------------------- learning


def test_replacements_from_config_apply_immediately():
    config = cfg(rules={"replacements": {"kubernetis": "Kubernetes"}})
    sent, _ = run("Deploy na kubernetis [1.0] wyślij teraz", config)
    assert sent == ["Deploy na Kubernetes."]


def test_learns_word_rule_after_repeated_review():
    store = LearnedStore()
    config = cfg(review={"enabled": True})
    fix = lambda t: t.replace("postgres", "PostgreSQL")
    for _ in range(2):
        run("Baza to postgres [1.0] wyślij teraz", config, store=store, reviewer=fix)
    # Third time the correction happens on its own.
    sent, _ = run("Baza to postgres [1.0] wyślij teraz", cfg(), store=store)
    assert sent == ["Baza to PostgreSQL."]


def test_learns_names_but_not_sentence_start_case():
    store = LearnedStore()
    store.learn_words("Pozdrawiam, marcin.", "Pozdrawiam, Marcin.")
    store.learn_words("Kot, pies.", "Kot. Pies.")
    assert store.replacements == {"marcin": {"Marcin": 1}}


def test_opposite_correction_weakens_rule():
    store = LearnedStore()
    store.add_replacement("api", "API", weight=2)
    store.add_replacement("API", "api", weight=2)
    assert "api" not in store.replacements


def test_learned_pause_thresholds_follow_the_user():
    """A slow speaker: 1.2 s pauses are commas for them, sentences only at 2.5 s."""
    store = LearnedStore()
    config = cfg(review={"enabled": True})
    script = "Jabłka [1.2] gruszki [1.2] śliwki [2.6] Potem [1.2] obiad [2.6] Koniec [1.0] wyślij teraz"
    want = "Jabłka, gruszki, śliwki. Potem, obiad. Koniec."
    for _ in range(4):
        run(script, config, store=store, reviewer=lambda t: want)
    comma, sentence = store.thresholds(config)
    assert comma < 1.2 < sentence < 2.6
    sent, _ = run(script, cfg(), store=store)
    assert sent == [want]


def test_apply_replacements_keeps_sentence_capital():
    assert apply_replacements("Postgres jest ok.", {"postgres": "postgreSQL"}) == "PostgreSQL jest ok."


def test_store_roundtrip(tmp_path):
    store = LearnedStore(path=tmp_path / "learned.json")
    store.add_replacement("a", "b")
    store.pause_samples.append((1.0, 2))
    store.save()
    loaded = LearnedStore.load(tmp_path / "learned.json")
    assert loaded.replacements == {"a": {"b": 1}}
    assert loaded.pause_samples == [(1.0, 2)]


# ---------------------------------------------------------------- privacy





def test_confirm_mode_waits_and_can_be_cancelled():
    sent = []
    config = cfg()
    session = Session(config, LearnedStore(), sink=lambda t: sent.append(t) or "ok", confirm=True)
    for words in parse_script("Raport gotowy [1.0] wyślij teraz", 0.6):
        event = session.feed(words)
    assert event.action is Action.PENDING and event.draft == "Raport gotowy."
    assert sent == []
    # Speech during the countdown is ignored.
    session.feed(parse_script("i jeszcze coś", 0.6)[0])
    session.cancel_pending()
    assert session.draft() == "Raport gotowy."
    for words in parse_script("[1.0] wyślij teraz", 0.6):
        session.feed(words)
    assert session.confirm_send().sent == "Raport gotowy."
    assert sent == ["Raport gotowy."]
