# Changelog

## 0.9.0-beta (unreleased)

- English dictation: `general.language = "en"` (or Settings → language) switches the safe
  phrases ("send it now"), voice commands ("period", "new line", "scratch that"), filler and
  pause words, and the AI guard's self-correction markers (", no, …", "I mean").
- English interface: menus, overlay, settings and messages follow the dictation language
  (`app.ui_language` = `auto` | `pl` | `en`). The `dictaitor` command line follows it too.

- Windows tray app: `Ctrl+Alt+D` dictation, live overlay with "Wyślij" (send) and "Anuluj" (cancel) buttons, Esc countdown, typing into the
  window you started in (paste for multi-line, clipboard when unsafe).
- `Ctrl+Alt+K` "correct last": learns words, names, pause rhythm and style.
- Settings window, safe-phrase test, start with Windows, learned-rules window with
  export/import.
- Optional AI clean-up: local OpenAI-compatible server or Claude (opt-in), with a guard
  against added content.
- Silero VAD, live preview, Whisper hallucination filter, automatic model choice,
  `dictaitor record` / `dictaitor eval`.
