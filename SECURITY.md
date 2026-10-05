# Security and privacy

## What stays on your computer

- **Audio** is processed in memory and never written to disk. The only exception is the
  explicit `dictaitor record` command, which saves samples you choose to record.
- **Speech recognition** (faster-whisper) and **voice activity detection** (Silero) run
  locally. Models are downloaded once from Hugging Face; set `HF_HUB_OFFLINE=1` afterwards.
- **Learned rules and your corrections** live in `%APPDATA%\dictaitor\learned.json`
  (`~/.config/dictaitor` elsewhere) as plain JSON you can read, edit or delete.
- **No telemetry, no accounts, no update checks.**

## What can leave your computer — only if you enable it

- `intent.mode = "claude"`: the **text** of each message you send (never audio) goes to
  the Claude API to be cleaned up. The app asks for consent when you enable it and marks
  the tray icon with a white ring while it is on. The API key is stored in the Windows
  Credential Manager (or read from `ANTHROPIC_API_KEY`), never in config files.
- `intent.mode = "local"` talks only to `localhost` unless you explicitly set
  `allow_remote = true`.

## Safety of sending

- Text is delivered only after the safe phrase is recognised at the end of an utterance
  followed by a pause, then after a short Esc countdown.
- It is typed only into the window that was active when you started dictating; if the
  focus changed, the window runs as administrator, or typing fails, the text goes to the
  clipboard instead. dictAItor never presses Enter.
- Global hotkeys use `RegisterHotKey` (no keyboard hooks, no keylogging).

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's **Report a vulnerability** (Security tab →
Advisories) on this repository. We aim to answer within 7 days.
