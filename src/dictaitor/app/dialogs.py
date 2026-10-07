"""Dialogs: correct last text, learned rules, settings, safe-phrase test."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import autostart, intent
from ..config import LANGUAGES as PRESETS
from ..config import Config, defaults_for, update_file
from ..i18n import t
from ..learning import LearnedStore
from ..phrase import PhraseCheck
from . import hotkeys


def open_path(path) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - opens with the user's default app
    else:
        subprocess.Popen(["xdg-open", str(path)])


def bring_to_front(dialog: QDialog) -> None:
    dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


class CorrectionDialog(QDialog):
    """Ctrl+Alt+K: edit the last sent text; the difference is what gets learned."""

    def __init__(self, text: str, on_save: Callable[[str, bool], None]):
        super().__init__()
        self.setWindowTitle(t("dictAItor – popraw ostatni tekst", "dictAItor – correct last text"))
        self.resize(560, 260)
        self.on_save = on_save
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                t(
                    "Popraw tekst tak, jak powinien wyglądać. dictAItor zapamięta różnice\n"
                    "(słowa, nazwy, interpunkcję po Twoich pauzach i Twój styl).",
                    "Fix the text the way it should look. dictAItor remembers the differences\n"
                    "(words, names, punctuation after your pauses and your style).",
                )
            )
        )
        self.edit = QPlainTextEdit(text)
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox()
        self.save = buttons.addButton(t("Zapamiętaj", "Remember"), QDialogButtonBox.AcceptRole)
        self.save_copy = buttons.addButton(t("Zapamiętaj i skopiuj", "Remember and copy"), QDialogButtonBox.AcceptRole)
        buttons.addButton(t("Anuluj", "Cancel"), QDialogButtonBox.RejectRole)
        self.save.clicked.connect(lambda: self._done(False))
        self.save_copy.clicked.connect(lambda: self._done(True))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.edit.setFocus()

    def _done(self, copy: bool) -> None:
        self.on_save(self.edit.toPlainText(), copy)
        self.accept()


class RulesDialog(QDialog):
    """What dictAItor has learned, with delete, export and import."""

    def __init__(self, store: LearnedStore, config: Config):
        super().__init__()
        self.store, self.config = store, config
        self.setWindowTitle(t("dictAItor – czego się nauczyłem", "dictAItor – what I have learned"))
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [
                t("Whisper słyszy", "Whisper hears"),
                t("Zamieniam na", "Replaced with"),
                t("Ile razy poprawiłeś", "Times you corrected it"),
            ]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for label, slot in (
            (t("Usuń zaznaczone", "Delete selected"), self._delete),
            (t("Eksportuj…", "Export…"), self._export),
            (t("Importuj…", "Import…"), self._import),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch()
        close = QPushButton(t("Zamknij", "Close"))
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        need = self.config["learning"]["min_occurrences"]
        rows = [(w, r, c) for w, opts in sorted(self.store.replacements.items()) for r, c in opts.items()]
        self.table.setRowCount(len(rows))
        for i, (wrong, right, count) in enumerate(rows):
            for j, value in enumerate(
                (
                    wrong,
                    right,
                    f"{count}" + ("" if count >= need else t(f" (aktywne od {need})", f" (active from {need})")),
                )
            ):
                self.table.setItem(i, j, QTableWidgetItem(value))
        comma, sentence = self.store.thresholds(self.config)
        self.summary.setText(
            t(
                f"Pauzy: przecinek od {comma:.2f} s, koniec zdania od {sentence:.2f} s "
                f"(nauczone z {len(self.store.pause_samples)} Twoich pauz). "
                f"Przykłady Twojego stylu: {len(self.store.examples)}.",
                f"Pauses: comma from {comma:.2f} s, end of sentence from {sentence:.2f} s "
                f"(learned from {len(self.store.pause_samples)} of your pauses). "
                f"Examples of your style: {len(self.store.examples)}.",
            )
        )

    def _delete(self) -> None:
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.store.remove_replacement(self.table.item(index, 0).text())
        self.store.save()
        self.refresh()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            t("Eksportuj reguły", "Export rules"),
            t("dictaitor-reguly.json", "dictaitor-rules.json"),
            "JSON (*.json)",
        )
        if path:
            Path(path).write_text(json.dumps(self.store.export_rules(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, t("Importuj reguły", "Import rules"), "", "JSON (*.json)")
        if not path:
            return
        try:
            n = self.store.import_rules(json.loads(Path(path).read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "dictAItor", t(f"Nie udało się zaimportować: {exc}", f"Import failed: {exc}"))
            return
        self.store.save()
        self.refresh()
        QMessageBox.information(self, "dictAItor", t(f"Zaimportowano {n} reguł.", f"Imported {n} rules."))


# Option lists are functions so they follow the interface language chosen at startup.
def models() -> list[tuple[str, str]]:
    return [
        ("auto", t("Automatycznie (zalecane)", "Automatic (recommended)")),
        ("small", t("small – szybki", "small – fast")),
        ("medium", t("medium – dokładniejszy", "medium – more accurate")),
        (
            "large-v3-turbo",
            t(
                "large-v3-turbo – najdokładniejszy (karta graficzna lub mocny procesor)",
                "large-v3-turbo – most accurate (graphics card or a strong processor)",
            ),
        ),
    ]


def intent_modes() -> list[tuple[str, str]]:
    return [
        ("off", t("Wyłączone", "Off")),
        ("local", t("Model na tym komputerze (Ollama, LM Studio)", "A model on this computer (Ollama, LM Studio)")),
        ("claude", t("Claude – chmura (tekst opuszcza komputer)", "Claude – cloud (the text leaves your computer)")),
    ]


def claude_models() -> list[tuple[str, str]]:
    return [
        ("claude-opus-5-5", t("Claude Opus 5.5 – najlepsza jakość", "Claude Opus 5.5 – best quality")),
        ("claude-haiku-4-5", t("Claude Haiku 4.5 – najszybszy, najtańszy", "Claude Haiku 4.5 – fastest, cheapest")),
    ]


def cloud_consent() -> str:
    return t(
        "Po włączeniu Claude każdy wysyłany tekst (nie dźwięk) trafi do Anthropic przez internet, "
        "żeby go uporządkować. Dźwięk i rozpoznawanie mowy nadal zostają na Twoim komputerze.\n\n"
        "Kółko w zasobniku dostanie białą obwódkę, dopóki ta opcja jest włączona.\n\nWłączyć?",
        "With Claude on, every text you send (not the audio) goes to Anthropic over the internet "
        "to be tidied up. Audio and speech recognition still stay on your computer.\n\n"
        "The tray dot gets a white ring while this option is on.\n\nTurn it on?",
    )


LANGUAGES = [
    ("pl", "polski (z angielskimi wtrąceniami)"),
    ("en", "English"),
]


def delivery_options() -> list[tuple[str, str]]:
    return [
        ("auto", t("Wpisuj w okno (wielowierszowe – wklejaj)", "Type into the window (paste multi-line text)")),
        ("paste", t("Zawsze wklejaj", "Always paste")),
        ("clipboard", t("Tylko do schowka", "Clipboard only")),
    ]


class SettingsDialog(QDialog):
    def __init__(
        self, config: Config, config_path: Path, on_test_phrase: Callable[[str], None], on_saved: Callable[[], None]
    ):
        super().__init__()
        self.config, self.path = config, config_path
        self.on_test_phrase, self.on_saved = on_test_phrase, on_saved
        self.setWindowTitle(t("dictAItor – ustawienia", "dictAItor – settings"))
        self.resize(560, 360)
        form = QFormLayout()
        g, a = config["gate"], config["app"]
        self.language = self._combo(LANGUAGES, config["general"]["language"])
        self.language.currentIndexChanged.connect(self._language_changed)
        form.addRow(t("Język dyktowania:", "Dictation language:"), self.language)
        self.send_phrase = QLineEdit(g["send_phrase"])
        test = QPushButton(t("Sprawdź hasło…", "Test the phrase…"))
        test.clicked.connect(lambda: self.on_test_phrase(self.send_phrase.text().strip()))
        phrase_row = QHBoxLayout()
        phrase_row.addWidget(self.send_phrase)
        phrase_row.addWidget(test)
        form.addRow(t("Hasło wysyłki:", "Send phrase:"), phrase_row)
        self.cancel_phrase = QLineEdit(g["cancel_phrase"])
        form.addRow(t("Hasło anulowania:", "Cancel phrase:"), self.cancel_phrase)
        self.hotkey = QLineEdit(a["hotkey"])
        form.addRow(t("Skrót dyktowania:", "Dictation hotkey:"), self.hotkey)
        self.correct_hotkey = QLineEdit(a["correct_hotkey"])
        form.addRow(t("Skrót „popraw ostatni”:", "“Correct last” hotkey:"), self.correct_hotkey)
        self.abort = QDoubleSpinBox(minimum=0.0, maximum=5.0, singleStep=0.1, decimals=1, suffix=" s")
        self.abort.setValue(float(a["abort_seconds"]))
        form.addRow(t("Czas na Esc po haśle:", "Time to press Esc after the phrase:"), self.abort)
        self.delivery = self._combo(delivery_options(), a["delivery"])
        form.addRow(t("Dostarczanie tekstu:", "Text delivery:"), self.delivery)
        self.model = self._combo(models(), config["general"]["model"])
        form.addRow(t("Model mowy:", "Speech model:"), self.model)
        self.autostart = QCheckBox(t("Uruchamiaj razem z Windows", "Start with Windows"))
        self.autostart.setEnabled(os.name == "nt")
        self.autostart.setChecked(autostart.is_enabled())
        form.addRow("", self.autostart)

        i = config["intent"]
        form.addRow(
            QLabel(
                t(
                    "<b>Porządkowanie przez AI</b> (np. „w poniedziałek… nie, we wtorek” → „we wtorek”)",
                    "<b>AI clean-up</b> (e.g. “on Monday… no, on Tuesday” → “on Tuesday”)",
                )
            )
        )
        self.intent_mode = self._combo(intent_modes(), i["mode"])
        self.intent_mode.currentIndexChanged.connect(self._mode_changed)
        form.addRow(t("Tryb:", "Mode:"), self.intent_mode)
        self.instructions = QLineEdit(i["instructions"])
        self.instructions.setPlaceholderText(
            t("np. Pisz zwięźle. Bez wykrzykników.", "e.g. Be concise. No exclamation marks.")
        )
        form.addRow(t("Twoje zasady stylu:", "Your style rules:"), self.instructions)
        self.local_model = QLineEdit(i["local_model"])
        form.addRow(t("Model lokalny:", "Local model:"), self.local_model)
        self.claude_model = self._combo(claude_models(), i["claude_model"])
        form.addRow(t("Model Claude:", "Claude model:"), self.claude_model)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        has_key = bool(intent.get_api_key())
        self.api_key.setPlaceholderText(
            t("zapisany – wpisz nowy, żeby zmienić", "saved – type a new one to change it")
            if has_key
            else t("sk-ant-… (z console.anthropic.com)", "sk-ant-… (from console.anthropic.com)")
        )
        form.addRow(t("Klucz API Claude:", "Claude API key:"), self.api_key)
        self._mode_changed()

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(
            QLabel(
                t(
                    "Skróty wpisuj jak: ctrl+alt+d, f9, ctrl+shift+space.",
                    "Write hotkeys like: ctrl+alt+d, f9, ctrl+shift+space.",
                )
            )
        )
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        advanced = buttons.addButton(t("Zaawansowane (Notatnik)", "Advanced (Notepad)"), QDialogButtonBox.ResetRole)
        advanced.clicked.connect(self._advanced)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _combo(options, current) -> QComboBox:
        box = QComboBox()
        for value, label in options:
            box.addItem(label, value)
        index = box.findData(current)
        if index < 0:
            box.addItem(current, current)
            index = box.count() - 1
        box.setCurrentIndex(index)
        return box

    def _language_changed(self) -> None:
        # Swap the safe phrases to the new language's defaults, unless you chose your own.
        new = defaults_for(self.language.currentData())["gate"]
        for box, key in ((self.send_phrase, "send_phrase"), (self.cancel_phrase, "cancel_phrase")):
            if box.text().strip() in {p["gate"][key] for p in PRESETS.values()}:
                box.setText(new[key])

    def _mode_changed(self) -> None:
        mode = self.intent_mode.currentData()
        self.local_model.setEnabled(mode == "local")
        self.claude_model.setEnabled(mode == "claude")
        self.api_key.setEnabled(mode == "claude")
        self.instructions.setEnabled(mode != "off")

    def _advanced(self) -> None:
        if not self.path.exists():
            update_file(self.path, {})
        open_path(self.path)

    def _save(self) -> None:
        for field, spec in (
            (t("Skrót dyktowania", "Dictation hotkey"), self.hotkey.text()),
            (t("Skrót „popraw ostatni”", "“Correct last” hotkey"), self.correct_hotkey.text()),
        ):
            try:
                hotkeys.parse(spec)
            except hotkeys.HotkeyError as exc:
                QMessageBox.warning(self, "dictAItor", f"{field}: {exc}")
                return
        if not self.send_phrase.text().strip():
            QMessageBox.warning(
                self, "dictAItor", t("Hasło wysyłki nie może być puste.", "The send phrase can't be empty.")
            )
            return
        mode = self.intent_mode.currentData()
        if mode == "claude" and self.config["intent"]["mode"] != "claude":
            if (
                QMessageBox.question(self, t("dictAItor – chmura", "dictAItor – cloud"), cloud_consent())
                != QMessageBox.Yes
            ):
                return
        if mode == "claude" and self.api_key.text().strip():
            intent.set_api_key(self.api_key.text().strip())
        elif mode == "claude" and not intent.get_api_key():
            QMessageBox.warning(
                self,
                "dictAItor",
                t(
                    "Podaj klucz API Claude (console.anthropic.com → API Keys).",
                    "Enter a Claude API key (console.anthropic.com → API Keys).",
                ),
            )
            return
        update_file(
            self.path,
            {
                "gate": {
                    "send_phrase": self.send_phrase.text().strip(),
                    "cancel_phrase": self.cancel_phrase.text().strip(),
                },
                "app": {
                    "hotkey": self.hotkey.text().strip().lower(),
                    "correct_hotkey": self.correct_hotkey.text().strip().lower(),
                    "abort_seconds": round(self.abort.value(), 1),
                    "delivery": self.delivery.currentData(),
                },
                "general": {"model": self.model.currentData(), "language": self.language.currentData()},
                "intent": {
                    "mode": mode,
                    "instructions": self.instructions.text().strip(),
                    "local_model": self.local_model.text().strip() or "qwen2.5:7b",
                    "claude_model": self.claude_model.currentData(),
                },
            },
        )
        if os.name == "nt" and self.autostart.isChecked() != autostart.is_enabled():
            autostart.set_enabled(self.autostart.isChecked())
        self.accept()
        self.on_saved()


class PhraseTestDialog(QDialog):
    """Say the phrase three times; show what Whisper heard each time."""

    def __init__(self, phrase: str, times: int = 3):
        super().__init__()
        self.setWindowTitle(t("dictAItor – test hasła", "dictAItor – phrase test"))
        self.resize(480, 260)
        self.phrase, self.times = phrase, times
        layout = QVBoxLayout(self)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setTextFormat(Qt.RichText)
        layout.addWidget(self.label)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.heard: list[str] = []
        self._update()

    def add_heard(self, text: str) -> None:
        self.heard.append(text)
        self._update()

    def _update(self) -> None:
        lines = [
            t(
                f"Powiedz <b>„{self.phrase}”</b> {self.times} razy, z krótką przerwą po każdym.",
                f"Say <b>“{self.phrase}”</b> {self.times} times, with a short pause after each.",
            )
        ]
        lines += [t(f"{i + 1}. słyszę: „{h}”", f"{i + 1}. I hear: “{h}”") for i, h in enumerate(self.heard)]
        if len(self.heard) < self.times:
            lines.append(
                t(
                    f"<i>Słucham… ({len(self.heard) + 1}/{self.times})</i>",
                    f"<i>Listening… ({len(self.heard) + 1}/{self.times})</i>",
                )
            )
        self.label.setText("<br>".join(lines))

    def show_result(self, result: PhraseCheck) -> None:
        marks = [f"{'✔' if ok else '✖'} “{h}”" for h, ok in result.heard]
        good, warn = t("<b>Hasło jest dobre.</b>", "<b>The phrase is good.</b>"), t("<b>Uwaga:</b>", "<b>Note:</b>")
        verdict = good if result.ok else warn + "<br>" + "<br>".join(result.problems)
        self.label.setText("<br>".join(marks + ["", verdict]))
