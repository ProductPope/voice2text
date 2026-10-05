"""Command line: `v2t listen`, `v2t simulate`, `v2t learn`, `v2t rules`, `v2t init`."""

from __future__ import annotations

import argparse
import shutil
import sys
from importlib import resources
from pathlib import Path

from .config import Config, home_dir
from .gate import Action
from .learning import LearnedStore
from .script import parse_script
from .session import Event, Session


def _store() -> LearnedStore:
    return LearnedStore.load(home_dir() / "learned.json")


def _report(event: Event, live: bool) -> None:
    if event.action is Action.CONTINUE:
        if live:
            print("\n── szkic (powiedz hasło, żeby wysłać) ──\n" + (event.draft or "…"), flush=True)
        if event.info:
            print(f"[{event.info}]")
    elif event.action is Action.SEND:
        print(f"\n✔ WYSŁANO ({event.info})")
        if live:
            print(event.sent)
    else:
        print(f"\n✖ {event.info}")


def cmd_listen(args, config: Config) -> int:
    from .audio import microphone_chunks
    from .transcriber import Transcriber

    print(f"Ładuję model '{config['general']['model']}' (lokalnie)…", flush=True)
    transcriber = Transcriber(config)
    session = Session(config, _store())
    g = config["gate"]
    print(
        f"Słucham. Wyślij: „{g['send_phrase']}”. Anuluj: „{g['cancel_phrase']}”. Ctrl+C kończy.\n"
        "Kalibruję szum przez 1 s – nic nie mów…",
        flush=True,
    )
    try:
        for chunk in microphone_chunks(config):
            words = transcriber.transcribe(chunk.audio, chunk.offset)
            if args.debug:
                print("  [whisper]", " ".join(f"{w.text}@{w.start:.2f}-{w.end:.2f}" for w in words))
            _report(session.feed(words, chunk.followed_by_pause), live=True)
    except KeyboardInterrupt:
        if not session.composer.empty:
            print("\nPrzerwano. Niewysłany szkic (NIE został nigdzie wysłany):\n" + session.draft())
    return 0


def cmd_simulate(args, config: Config) -> int:
    text = args.script if args.script != "-" else sys.stdin.read()
    if args.output:
        config["output"]["mode"] = args.output
    store = _store() if args.persist else LearnedStore()
    session = Session(config, store)
    for words in parse_script(text, config["pauses"]["split_silence"]):
        event = session.feed(words)
        if args.verbose or event.action is not Action.CONTINUE:
            _report(event, live=args.verbose)
    if not session.composer.empty:
        print("── niewysłany szkic ──\n" + session.draft())
    return 0


def cmd_learn(args, config: Config) -> int:
    store = _store()
    store.add_replacement(args.wrong, args.right, weight=config["learning"]["min_occurrences"])
    store.save()
    print(f"Zapamiętano: {args.wrong} → {args.right}")
    return 0


def cmd_forget(args, config: Config) -> int:
    store = _store()
    if store.replacements.pop(args.wrong, None) is None:
        print(f"Brak reguły dla: {args.wrong}")
        return 1
    store.save()
    print(f"Zapomniano: {args.wrong}")
    return 0


def cmd_rules(args, config: Config) -> int:
    store = _store()
    comma, sentence = store.thresholds(config)
    g = config["gate"]
    print(f"Konfiguracja: {config.path}  (istnieje: {bool(config.path and config.path.exists())})")
    print(f"Hasło wysłania: „{g['send_phrase']}”   anulowania: „{g['cancel_phrase']}”")
    print(f"Pauzy: przecinek ≥ {comma:.2f}s, koniec zdania ≥ {sentence:.2f}s "
          f"(próbek z Twoich poprawek: {len(store.pause_samples)})")
    print("\nKomendy głosowe:")
    for phrase, action in config["commands"].items():
        print(f"  „{phrase}” → {action!r}")
    print("\nTwoje reguły (config.toml):")
    for a, b in config["rules"]["replacements"].items():
        print(f"  {a} → {b}")
    print("\nNauczone zamiany (aktywne od "
          f"{config['learning']['min_occurrences']} powtórzeń):")
    for wrong, options in store.replacements.items():
        for right, count in options.items():
            print(f"  {wrong} → {right}   ×{count}")
    return 0


def cmd_init(args, config: Config) -> int:
    target = home_dir() / "config.toml"
    if target.exists() and not args.force:
        print(f"{target} już istnieje (użyj --force, żeby nadpisać).")
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    with resources.as_file(resources.files("voice2text") / "config.example.toml") as src:
        shutil.copy(src, target)
    print(f"Utworzono {target}. Ustaw tam swoje hasło i reguły.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2t", description="Lokalne dyktowanie z hasłem wysyłki.")
    parser.add_argument("--config", type=Path, help="ścieżka do config.toml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("listen", help="słuchaj mikrofonu")
    p.add_argument("--debug", action="store_true", help="pokaż surowy wynik Whispera")
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser("simulate", help="przetwórz skrypt tekstowy zamiast mikrofonu")
    p.add_argument("script", help="tekst z pauzami [1.2] albo '-' dla stdin")
    p.add_argument("--output", help="nadpisz output.mode (np. stdout)")
    p.add_argument("--persist", action="store_true", help="używaj i zapisuj nauczone reguły")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("learn", help="dodaj zamianę od razu aktywną")
    p.add_argument("wrong")
    p.add_argument("right")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("forget", help="usuń nauczoną zamianę")
    p.add_argument("wrong")
    p.set_defaults(func=cmd_forget)

    p = sub.add_parser("rules", help="pokaż reguły, progi pauz i nauczone zamiany")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("init", help="utwórz config.toml z przykładu")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    args = parser.parse_args(argv)
    return args.func(args, Config.load(args.config))


if __name__ == "__main__":
    sys.exit(main())
