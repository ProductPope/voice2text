# Changelog

## 1.0.0 – 2026-10-08

First stable release. Everything below was built and tested during the 0.9 beta.

- Never sends without your safe phrase (or the "Send" button): zero false sends in every
  measurement, in Polish and English.
- Windows installer (`dictaitor-setup-1.0.0.exe`): per-user, no administrator rights, no Python.
- Synthetic evaluation sets (`scripts/make_synthetic_set.py`) and measurements in
  `docs/PLAN.md` (Polish and English, `small` and `large-v3-turbo`).
- Known limits: the installer is not code-signed yet (Windows shows "unknown publisher");
  self-corrections ("Monday, no, Tuesday") need the optional AI step.

### Added during the beta

- English dictation: `general.language = "en"` (or Settings → language) switches the safe
  phrases ("send it now"), voice commands ("period", "new line", "scratch that"), filler and
  pause words, and the AI guard's self-correction markers (", no, …", "I mean").
- English interface: menus, overlay, settings and messages follow the dictation language
  (`app.ui_language` = `auto` | `pl` | `en`). The `dictaitor` command line follows it too.
- Windows tray app: `Ctrl+Alt+D` dictation, live overlay with "Wyślij" (send) and
  "Anuluj" (cancel) buttons, Esc countdown, typing into the window you started in (paste for multi-line, clipboard when unsafe).
- `Ctrl+Alt+K` "correct last": learns words, names, pause rhythm and style.
- Settings window, safe-phrase test, start with Windows, learned-rules window with
  export/import.
- Optional AI clean-up: local OpenAI-compatible server or Claude (opt-in), with a guard
  against added content.
- Silero VAD, live preview, Whisper hallucination filter, automatic model choice,
  `dictaitor record` / `dictaitor eval`.
