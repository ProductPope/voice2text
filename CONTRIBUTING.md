# Contributing

Thanks for helping! dictAItor is small on purpose — please keep changes focused.

## Setup

```bash
pip install -e ".[app,dev]"
pytest                      # Linux needs QT_QPA_PLATFORM=offscreen for the Qt tests
ruff check src tests packaging && ruff format src tests packaging
```

Work on a branch and open a pull request to `main`; GitHub Actions runs lint and the
full test suite on Linux and Windows (Python 3.11 and 3.12) and builds the Windows
installer when the app changes. Merge when everything is green.

Everything except the Windows typing/hotkey layer is testable on any OS:

- `src/dictaitor/` — core: audio/VAD, transcription, safe-phrase gate, pause rules,
  learning, AI clean-up. Pure Python, unit-tested.
- `src/dictaitor/app/controller.py` — app logic with no GUI code; test it with
  `FakePlatform` (see `tests/test_app.py`).
- `src/dictaitor/app/win32.py` — Windows API via ctypes; its tests run on Windows only
  (`pytest` on a Windows machine, or the manual `tests` workflow in GitHub Actions).

`dictaitor simulate "text [1.2] more text [1.0] wyślij teraz"` replays a script with
pauses through the pipeline without a microphone — handy for pause/command changes.

## Rules of thumb

- **No false sends.** Any change near the gate or delivery needs a test proving nothing
  is sent or typed when it shouldn't be.
- **Nothing leaves the machine by default.** New network calls must be opt-in and
  documented in SECURITY.md.
- Language presets (safe phrases, voice commands, pause words) live in `LANGUAGES` in
  `src/dictaitor/config.py`; adding a language starts there.
- Every message a user can see is written as `t("polski", "English")` (`dictaitor.i18n`),
  so both versions change together.
- Run `pytest` (and `dictaitor eval` on your samples if you touched recognition or pauses)
  before opening a pull request.

## Code of conduct

Be kind and constructive – see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
(Contributor Covenant 2.1).
