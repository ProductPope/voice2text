# dictAItor

*You dictate. It waits for your word.*

[Polski opis → README.pl.md](README.pl.md) · [Windows: step-by-step (PL)](docs/START-WINDOWS.md)

Local dictation for people who think while they talk:

- **Nothing is sent until you say your safe phrase** (default: "send it now" in English,
  "wyślij teraz" in Polish), followed
  by a pause. Saying it mid-sentence does nothing; a short countdown lets you press Esc.
- **Understands pauses.** A pause after "and", "that", "in"… is thinking, not a full stop.
  Longer pauses become commas, long ones end the sentence.
- **Learns your rules.** Fix the last text with `Ctrl+Alt+K` and dictAItor learns the
  word, the name, your punctuation rhythm and your style.
- **Private by default.** Speech recognition (Whisper via faster-whisper) runs on your
  machine. No account, no telemetry, audio only in RAM. An optional AI clean-up step runs
  on a local model, or — only if you opt in — on Claude.
- **Types where you were.** `Ctrl+Alt+D` in any window (Slack, mail, Claude Code), speak,
  say the phrase — the text is typed into that window. Multi-line text is pasted so a
  newline never sends a chat message half-way. Never presses Enter for you.

Dictation languages: **English** and **Polish** (with English tech terms mixed in) come with
their own safe phrases, voice commands ("period", "new line", "scratch that"…) and pause
words — pick one in Settings or set `general.language = "en"`. Other Whisper languages
work too; set the phrases and commands yourself in `config.toml`. The app's menus and
messages follow the dictation language (English for anything but Polish); set
`app.ui_language` to choose them separately.

## Install

**Windows:** download `dictaitor-setup-<version>.exe` from the
[latest release](https://github.com/ProductPope/voice2text/releases/latest) and run it — no
Python and no administrator rights needed. Windows may warn about an unknown publisher (the
installer isn't code-signed yet): *More info → Run anyway*. To run from source with
double-click scripts, see [docs/START-WINDOWS.md](docs/START-WINDOWS.md) (Polish).

**From source (any OS):**

```bash
pip install -e ".[app]"     # tray app (Windows: typing + hotkeys; elsewhere: clipboard)
dictaitor app
dictaitor listen            # terminal mode, sends to the clipboard
```

## Measure it on your voice

```bash
dictaitor record samples msg1   # record a message (with the safe phrase), type what should be sent
dictaitor eval samples          # WER, punctuation F1, false sends (target: 0), latency
```

## How it works

```
mic → Silero VAD → faster-whisper (local) → safe-phrase gate → pause rules & voice commands
    → your learned rules → optional AI clean-up (local LLM / Claude, with a content guard)
    → typed into the window you started in (or the clipboard when that is not safe)
```

See [docs/PLAN.md](docs/PLAN.md) for the design and roadmap, [SECURITY.md](SECURITY.md)
for the privacy model, and [CONTRIBUTING.md](CONTRIBUTING.md) to help.

## License

MIT
