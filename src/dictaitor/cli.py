"""Command line: listen, simulate, eval, record, learn, forget, rules, init."""

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
    from .audio import chunker_for, microphone_frames
    from .pipeline import Pipeline
    from .transcriber import Transcriber, resolve_model

    store = _store()
    choice = resolve_model(config)
    print(f"Ładuję model {choice.model} ({choice.device}, {choice.compute_type}) – lokalnie…", flush=True)
    transcriber = Transcriber(config, store.vocabulary(config["learning"]["min_occurrences"]))
    if transcriber.warning:
        print(transcriber.warning)
    session = Session(config, store)
    pipe = Pipeline(session, transcriber, chunker_for(config), config["audio"]["preview_interval"])
    if args.debug:
        pipe.on_words = lambda words: print(
            "  [whisper]", " ".join(f"{w.text}@{w.start:.2f}-{w.end:.2f}" for w in words)
        )
    g = config["gate"]
    print(f"Słucham. Wyślij: „{g['send_phrase']}”. Anuluj: „{g['cancel_phrase']}”. Ctrl+C kończy.", flush=True)
    try:
        for frame in microphone_frames():
            event = pipe.push(frame)
            if event is not None:
                _report(event, live=True)
            elif pipe.preview_due():
                text = pipe.preview()
                if text:
                    print(f"  … {text}", flush=True)
    except KeyboardInterrupt:
        if not session.composer.empty:
            print("\nPrzerwano. Niewysłany szkic (NIE został nigdzie wysłany):\n" + session.draft())
    return 0


def cmd_prepare(args, config: Config) -> int:
    """Download the model and check the hardware once, with clear messages."""
    from .transcriber import Transcriber, resolve_model

    choice = resolve_model(config)
    print(f"Wybrany model: {choice.model} ({'karta graficzna' if choice.device == 'cuda' else 'procesor'}).")
    print("Pobieram i sprawdzam model – za pierwszym razem może to potrwać kilka minut…", flush=True)
    t = Transcriber(config)
    if t.warning:
        print(t.warning)
    print(f"Gotowe: {t.choice.model} działa na {'karcie graficznej' if t.choice.device == 'cuda' else 'procesorze'}.")
    try:
        import sounddevice as sd

        mic = sd.query_devices(kind="input")
        print(f"Mikrofon: {mic['name']}")
    except Exception as exc:
        print(f"Uwaga: nie widzę mikrofonu ({exc}). Sprawdź, czy jest podłączony i dozwolony w Ustawieniach prywatności.")
        return 1
    return 0


def cmd_eval(args, config: Config) -> int:
    from .evaluate import evaluate_folder, find_recordings, format_report
    from .transcriber import Transcriber, resolve_model

    folder = Path(args.folder)
    if not find_recordings(folder):
        print(f"Brak nagrań z plikami .txt w {folder}. Nagraj je: dictaitor record {folder} NAZWA")
        return 1
    for model in args.model or [config["general"]["model"]]:
        config["general"]["model"] = model
        choice = resolve_model(config)
        print(f"\n=== {choice.model} ({choice.device}, {choice.compute_type}) ===", flush=True)
        report = evaluate_folder(folder, config, Transcriber(config), choice.model)
        print(format_report(report))
    return 0


def cmd_record(args, config: Config) -> int:
    import threading
    import wave

    import numpy as np

    from .audio import SAMPLE_RATE, microphone_frames

    folder = Path(args.folder)
    folder.mkdir(parents=True, exist_ok=True)
    wav_path = folder / f"{args.name}.wav"
    print(
        "Nagrywam do pliku (to jedyna komenda, która zapisuje dźwięk na dysk).\n"
        "Dyktuj naturalnie, razem z hasłem. Enter kończy nagranie.",
        flush=True,
    )
    stop = threading.Event()
    threading.Thread(target=lambda: (input(), stop.set()), daemon=True).start()
    frames = []
    for frame in microphone_frames():
        frames.append(frame)
        if stop.is_set():
            break
    audio = np.clip(np.concatenate(frames), -1, 1)
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes((audio * 32767).astype("<i2").tobytes())
    print(f"Zapisano {wav_path} ({len(audio) / SAMPLE_RATE:.1f} s).")
    expected = input("Co powinno zostać wysłane? (puste = nic nie powinno zostać wysłane)\n> ").strip()
    wav_path.with_suffix(".txt").write_text((expected or "#nosend") + "\n", encoding="utf-8")
    print(f"Zapisano {wav_path.with_suffix('.txt')}. Popraw go w edytorze, jeśli trzeba (np. nowe linie).")
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
    with resources.as_file(resources.files("dictaitor") / "config.example.toml") as src:
        shutil.copy(src, target)
    print(f"Utworzono {target}. Ustaw tam swoje hasło i reguły.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dictaitor", description="Lokalne dyktowanie z hasłem wysyłki.")
    parser.add_argument("--config", type=Path, help="ścieżka do config.toml")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("listen", help="słuchaj mikrofonu")
    p.add_argument("--debug", action="store_true", help="pokaż surowy wynik Whispera")
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser("app", help="aplikacja w zasobniku (skrót klawiszowy, wpisywanie w okno)")
    p.set_defaults(func=lambda args, config: __import__("dictaitor.app.ui", fromlist=["main"]).main())

    p = sub.add_parser("prepare", help="pobierz model i sprawdź sprzęt oraz mikrofon")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("eval", help="zmierz jakość na własnych nagraniach")
    p.add_argument("folder", help="folder z parami nagranie + .txt")
    p.add_argument("--model", action="append", help="porównaj modele (można podać kilka razy)")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("record", help="nagraj próbkę do zestawu ewaluacyjnego")
    p.add_argument("folder")
    p.add_argument("name")
    p.set_defaults(func=cmd_record)

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
    config = Config.load(args.config)
    for warning in config.warnings:
        print(f"Uwaga: {warning}", file=sys.stderr)
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
