"""Command line: listen, simulate, eval, record, learn, forget, rules, init."""

from __future__ import annotations

import argparse
import shutil
import sys
from importlib import resources
from pathlib import Path

from .config import Config, home_dir
from .gate import Action
from .i18n import set_language, t, ui_language
from .learning import LearnedStore
from .script import parse_script
from .session import Event, Session


def _store() -> LearnedStore:
    return LearnedStore.load(home_dir() / "learned.json")


def _device(gpu: bool) -> str:
    return t("karta graficzna", "graphics card") if gpu else t("procesor", "processor")


def _report(event: Event, live: bool) -> None:
    if event.action is Action.CONTINUE:
        if live:
            print(
                t("\n── szkic (powiedz hasło, żeby wysłać) ──\n", "\n── draft (say the phrase to send) ──\n")
                + (event.draft or "…"),
                flush=True,
            )
        if event.info:
            print(f"[{event.info}]")
    elif event.action is Action.SEND:
        print(t(f"\n✔ WYSŁANO ({event.info})", f"\n✔ SENT ({event.info})"))
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
    print(
        t(
            f"Ładuję model {choice.model} ({choice.device}, {choice.compute_type}) – lokalnie…",
            f"Loading model {choice.model} ({choice.device}, {choice.compute_type}) – locally…",
        ),
        flush=True,
    )
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
    print(
        t(
            f"Słucham. Wyślij: „{g['send_phrase']}”. Anuluj: „{g['cancel_phrase']}”. Ctrl+C kończy.",
            f"Listening. Send: “{g['send_phrase']}”. Cancel: “{g['cancel_phrase']}”. Ctrl+C quits.",
        ),
        flush=True,
    )
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
            print(
                t(
                    "\nPrzerwano. Niewysłany szkic (NIE został nigdzie wysłany):\n",
                    "\nStopped. Unsent draft (NOT sent anywhere):\n",
                )
                + session.draft()
            )
    return 0


def cmd_prepare(args, config: Config) -> int:
    """Download the model and check the hardware once, with clear messages."""
    from .transcriber import Transcriber, resolve_model

    choice = resolve_model(config)
    gpu = choice.device == "cuda"
    print(t(f"Wybrany model: {choice.model}", f"Chosen model: {choice.model}") + f" ({_device(gpu)}).")
    print(
        t(
            "Pobieram i sprawdzam model – za pierwszym razem może to potrwać kilka minut…",
            "Downloading and checking the model – the first time this can take a few minutes…",
        ),
        flush=True,
    )
    model = Transcriber(config)
    if model.warning:
        print(model.warning)
    where = (
        t("karcie graficznej", "the graphics card")
        if model.choice.device == "cuda"
        else t("procesorze", "the processor")
    )
    print(t(f"Gotowe: {model.choice.model} działa na {where}.", f"Ready: {model.choice.model} runs on {where}."))
    try:
        import sounddevice as sd

        mic = sd.query_devices(kind="input")
        print(t(f"Mikrofon: {mic['name']}", f"Microphone: {mic['name']}"))
    except Exception as exc:
        print(
            t(
                f"Uwaga: nie widzę mikrofonu ({exc}). "
                "Sprawdź, czy jest podłączony i dozwolony w Ustawieniach prywatności.",
                f"Warning: no microphone found ({exc}). Check it is plugged in and allowed in Privacy settings.",
            )
        )
        return 1
    return 0


def cmd_eval(args, config: Config) -> int:
    from .evaluate import evaluate_folder, find_recordings, format_report
    from .transcriber import Transcriber, resolve_model

    folder = Path(args.folder)
    if not find_recordings(folder):
        print(
            t(
                f"Brak nagrań z plikami .txt w {folder}. Nagraj je: dictaitor record {folder} NAZWA",
                f"No recordings with .txt files in {folder}. Record some: dictaitor record {folder} NAME",
            )
        )
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
        t(
            "Nagrywam do pliku (to jedyna komenda, która zapisuje dźwięk na dysk).\n"
            "Dyktuj naturalnie, razem z hasłem. Enter kończy nagranie.",
            "Recording to a file (the only command that saves audio to disk).\n"
            "Dictate naturally, including the phrase. Enter stops the recording.",
        ),
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
    print(
        t(
            f"Zapisano {wav_path} ({len(audio) / SAMPLE_RATE:.1f} s).",
            f"Saved {wav_path} ({len(audio) / SAMPLE_RATE:.1f} s).",
        )
    )
    expected = input(
        t(
            "Co powinno zostać wysłane? (puste = nic nie powinno zostać wysłane)\n> ",
            "What should be sent? (empty = nothing should be sent)\n> ",
        )
    ).strip()
    wav_path.with_suffix(".txt").write_text((expected or "#nosend") + "\n", encoding="utf-8")
    print(
        t(
            f"Zapisano {wav_path.with_suffix('.txt')}. Popraw go w edytorze, jeśli trzeba (np. nowe linie).",
            f"Saved {wav_path.with_suffix('.txt')}. Fix it in an editor if needed (e.g. new lines).",
        )
    )
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
        print(t("── niewysłany szkic ──\n", "── unsent draft ──\n") + session.draft())
    return 0


def cmd_learn(args, config: Config) -> int:
    store = _store()
    store.add_replacement(args.wrong, args.right, weight=config["learning"]["min_occurrences"])
    store.save()
    print(t(f"Zapamiętano: {args.wrong} → {args.right}", f"Learned: {args.wrong} → {args.right}"))
    return 0


def cmd_forget(args, config: Config) -> int:
    store = _store()
    if store.replacements.pop(args.wrong, None) is None:
        print(t(f"Brak reguły dla: {args.wrong}", f"No rule for: {args.wrong}"))
        return 1
    store.save()
    print(t(f"Zapomniano: {args.wrong}", f"Forgot: {args.wrong}"))
    return 0


def cmd_rules(args, config: Config) -> int:
    store = _store()
    comma, sentence = store.thresholds(config)
    g = config["gate"]
    print(
        t(
            f"Konfiguracja: {config.path}  (istnieje: {bool(config.path and config.path.exists())})",
            f"Config: {config.path}  (exists: {bool(config.path and config.path.exists())})",
        )
    )
    print(
        t(
            f"Hasło wysłania: „{g['send_phrase']}”   anulowania: „{g['cancel_phrase']}”",
            f"Send phrase: “{g['send_phrase']}”   cancel: “{g['cancel_phrase']}”",
        )
    )
    print(
        t(
            f"Pauzy: przecinek ≥ {comma:.2f}s, koniec zdania ≥ {sentence:.2f}s "
            f"(próbek z Twoich poprawek: {len(store.pause_samples)})",
            f"Pauses: comma ≥ {comma:.2f}s, end of sentence ≥ {sentence:.2f}s "
            f"(samples from your corrections: {len(store.pause_samples)})",
        )
    )
    print(t("\nKomendy głosowe:", "\nVoice commands:"))
    for phrase, action in config["commands"].items():
        print(f"  „{phrase}” → {action!r}")
    print(t("\nTwoje reguły (config.toml):", "\nYour rules (config.toml):"))
    for a, b in config["rules"]["replacements"].items():
        print(f"  {a} → {b}")
    print(
        t(
            f"\nNauczone zamiany (aktywne od {config['learning']['min_occurrences']} powtórzeń):",
            f"\nLearned replacements (active after {config['learning']['min_occurrences']} repeats):",
        )
    )
    for wrong, options in store.replacements.items():
        for right, count in options.items():
            print(f"  {wrong} → {right}   ×{count}")
    return 0


def cmd_init(args, config: Config) -> int:
    target = home_dir() / "config.toml"
    if target.exists() and not args.force:
        print(
            t(
                f"{target} już istnieje (użyj --force, żeby nadpisać).",
                f"{target} already exists (use --force to overwrite).",
            )
        )
        return 1
    target.parent.mkdir(parents=True, exist_ok=True)
    with resources.as_file(resources.files("dictaitor") / "config.example.toml") as src:
        shutil.copy(src, target)
    print(
        t(f"Utworzono {target}. Ustaw tam swoje hasło i reguły.", f"Created {target}. Set your phrase and rules there.")
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    # The language comes from config.toml, so read --config before building the help texts.
    early = argparse.ArgumentParser(add_help=False)
    early.add_argument("--config", type=Path)
    try:
        set_language(ui_language(Config.load(early.parse_known_args(argv)[0].config)))
    except Exception:  # a broken config is reported properly below
        pass
    parser = argparse.ArgumentParser(
        prog="dictaitor",
        description=t("Lokalne dyktowanie z hasłem wysyłki.", "Local dictation with a safe send phrase."),
    )
    parser.add_argument("--config", type=Path, help=t("ścieżka do config.toml", "path to config.toml"))
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("listen", help=t("słuchaj mikrofonu", "listen to the microphone"))
    p.add_argument("--debug", action="store_true", help=t("pokaż surowy wynik Whispera", "show raw Whisper output"))
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser(
        "app",
        help=t(
            "aplikacja w zasobniku (skrót klawiszowy, wpisywanie w okno)", "tray app (hotkey, types into the window)"
        ),
    )
    p.set_defaults(func=lambda args, config: __import__("dictaitor.app.ui", fromlist=["main"]).main())

    p = sub.add_parser(
        "prepare",
        help=t("pobierz model i sprawdź sprzęt oraz mikrofon", "download the model, check hardware and microphone"),
    )
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("eval", help=t("zmierz jakość na własnych nagraniach", "measure quality on your own recordings"))
    p.add_argument("folder", help=t("folder z parami nagranie + .txt", "folder with recording + .txt pairs"))
    p.add_argument(
        "--model",
        action="append",
        help=t("porównaj modele (można podać kilka razy)", "compare models (can be given several times)"),
    )
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser(
        "record", help=t("nagraj próbkę do zestawu ewaluacyjnego", "record a sample for the evaluation set")
    )
    p.add_argument("folder")
    p.add_argument("name")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser(
        "simulate",
        help=t("przetwórz skrypt tekstowy zamiast mikrofonu", "process a text script instead of the microphone"),
    )
    p.add_argument(
        "script", help=t("tekst z pauzami [1.2] albo '-' dla stdin", "text with pauses [1.2], or '-' for stdin")
    )
    p.add_argument("--output", help=t("nadpisz output.mode (np. stdout)", "override output.mode (e.g. stdout)"))
    p.add_argument(
        "--persist", action="store_true", help=t("używaj i zapisuj nauczone reguły", "use and save learned rules")
    )
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_simulate)

    p = sub.add_parser("learn", help=t("dodaj zamianę od razu aktywną", "add a replacement that is active right away"))
    p.add_argument("wrong")
    p.add_argument("right")
    p.set_defaults(func=cmd_learn)

    p = sub.add_parser("forget", help=t("usuń nauczoną zamianę", "remove a learned replacement"))
    p.add_argument("wrong")
    p.set_defaults(func=cmd_forget)

    p = sub.add_parser(
        "rules",
        help=t("pokaż reguły, progi pauz i nauczone zamiany", "show rules, pause thresholds and learned replacements"),
    )
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("init", help=t("utwórz config.toml z przykładu", "create config.toml from the example"))
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    for stream in (sys.stdout, sys.stderr):
        if stream and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(errors="replace")  # never crash on "ą" or "✔" in an old console
    args = parser.parse_args(argv)
    config = Config.load(args.config)
    for warning in config.warnings:
        print(t(f"Uwaga: {warning}", f"Warning: {warning}"), file=sys.stderr)
    return args.func(args, config)


if __name__ == "__main__":
    sys.exit(main())
