"""Dialogs: correct last text, learned rules, settings, safe-phrase test."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

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

from .. import autostart
from ..config import Config, update_file
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
        self.setWindowTitle("dictAItor – popraw ostatni tekst")
        self.resize(560, 260)
        self.on_save = on_save
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Popraw tekst tak, jak powinien wyglądać. dictAItor zapamięta różnice\n"
                   "(słowa, nazwy, interpunkcję po Twoich pauzach i Twój styl).")
        )
        self.edit = QPlainTextEdit(text)
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox()
        self.save = buttons.addButton("Zapamiętaj", QDialogButtonBox.AcceptRole)
        self.save_copy = buttons.addButton("Zapamiętaj i skopiuj", QDialogButtonBox.AcceptRole)
        buttons.addButton("Anuluj", QDialogButtonBox.RejectRole)
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
        self.setWindowTitle("dictAItor – czego się nauczyłem")
        self.resize(620, 420)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Whisper słyszy", "Zamieniam na", "Ile razy poprawiłeś"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        for label, slot in (
            ("Usuń zaznaczone", self._delete),
            ("Eksportuj…", self._export),
            ("Importuj…", self._import),
        ):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch()
        close = QPushButton("Zamknij")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    def refresh(self) -> None:
        need = self.config["learning"]["min_occurrences"]
        rows = [(w, r, c) for w, opts in sorted(self.store.replacements.items()) for r, c in opts.items()]
        self.table.setRowCount(len(rows))
        for i, (wrong, right, count) in enumerate(rows):
            for j, value in enumerate((wrong, right, f"{count}" + ("" if count >= need else f" (aktywne od {need})"))):
                self.table.setItem(i, j, QTableWidgetItem(value))
        comma, sentence = self.store.thresholds(self.config)
        self.summary.setText(
            f"Pauzy: przecinek od {comma:.2f} s, koniec zdania od {sentence:.2f} s "
            f"(nauczone z {len(self.store.pause_samples)} Twoich pauz). "
            f"Przykłady Twojego stylu: {len(self.store.examples)}."
        )

    def _delete(self) -> None:
        for index in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.store.remove_replacement(self.table.item(index, 0).text())
        self.store.save()
        self.refresh()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Eksportuj reguły", "dictaitor-reguly.json", "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.store.export_rules(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Importuj reguły", "", "JSON (*.json)")
        if not path:
            return
        try:
            n = self.store.import_rules(json.loads(Path(path).read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "dictAItor", f"Nie udało się zaimportować: {exc}")
            return
        self.store.save()
        self.refresh()
        QMessageBox.information(self, "dictAItor", f"Zaimportowano {n} reguł.")


MODELS = [
    ("auto", "Automatycznie (zalecane)"),
    ("small", "small – szybki"),
    ("medium", "medium – dokładniejszy"),
    ("large-v3-turbo", "large-v3-turbo – najdokładniejszy (karta graficzna lub mocny procesor)"),
]
DELIVERY = [
    ("auto", "Wpisuj w okno (wielowierszowe – wklejaj)"),
    ("paste", "Zawsze wklejaj"),
    ("clipboard", "Tylko do schowka"),
]


class SettingsDialog(QDialog):
    def __init__(self, config: Config, config_path: Path, on_test_phrase: Callable[[str], None], on_saved: Callable[[], None]):
        super().__init__()
        self.config, self.path = config, config_path
        self.on_test_phrase, self.on_saved = on_test_phrase, on_saved
        self.setWindowTitle("dictAItor – ustawienia")
        self.resize(560, 360)
        form = QFormLayout()
        g, a = config["gate"], config["app"]
        self.send_phrase = QLineEdit(g["send_phrase"])
        test = QPushButton("Sprawdź hasło…")
        test.clicked.connect(lambda: self.on_test_phrase(self.send_phrase.text().strip()))
        phrase_row = QHBoxLayout()
        phrase_row.addWidget(self.send_phrase)
        phrase_row.addWidget(test)
        form.addRow("Hasło wysyłki:", phrase_row)
        self.cancel_phrase = QLineEdit(g["cancel_phrase"])
        form.addRow("Hasło anulowania:", self.cancel_phrase)
        self.hotkey = QLineEdit(a["hotkey"])
        form.addRow("Skrót dyktowania:", self.hotkey)
        self.correct_hotkey = QLineEdit(a["correct_hotkey"])
        form.addRow("Skrót „popraw ostatni”:", self.correct_hotkey)
        self.abort = QDoubleSpinBox(minimum=0.0, maximum=5.0, singleStep=0.1, decimals=1, suffix=" s")
        self.abort.setValue(float(a["abort_seconds"]))
        form.addRow("Czas na Esc po haśle:", self.abort)
        self.delivery = self._combo(DELIVERY, a["delivery"])
        form.addRow("Dostarczanie tekstu:", self.delivery)
        self.model = self._combo(MODELS, config["general"]["model"])
        form.addRow("Model mowy:", self.model)
        self.autostart = QCheckBox("Uruchamiaj razem z Windows")
        self.autostart.setEnabled(os.name == "nt")
        self.autostart.setChecked(autostart.is_enabled())
        form.addRow("", self.autostart)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel("Skróty wpisuj jak: ctrl+alt+d, f9, ctrl+shift+space."))
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        advanced = buttons.addButton("Zaawansowane (Notatnik)", QDialogButtonBox.ResetRole)
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

    def _advanced(self) -> None:
        if not self.path.exists():
            update_file(self.path, {})
        open_path(self.path)

    def _save(self) -> None:
        for field, spec in (("Skrót dyktowania", self.hotkey.text()), ("Skrót „popraw ostatni”", self.correct_hotkey.text())):
            try:
                hotkeys.parse(spec)
            except hotkeys.HotkeyError as exc:
                QMessageBox.warning(self, "dictAItor", f"{field}: {exc}")
                return
        if not self.send_phrase.text().strip():
            QMessageBox.warning(self, "dictAItor", "Hasło wysyłki nie może być puste.")
            return
        update_file(
            self.path,
            {
                "gate": {"send_phrase": self.send_phrase.text().strip(), "cancel_phrase": self.cancel_phrase.text().strip()},
                "app": {
                    "hotkey": self.hotkey.text().strip().lower(),
                    "correct_hotkey": self.correct_hotkey.text().strip().lower(),
                    "abort_seconds": round(self.abort.value(), 1),
                    "delivery": self.delivery.currentData(),
                },
                "general": {"model": self.model.currentData()},
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
        self.setWindowTitle("dictAItor – test hasła")
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
        lines = [f"Powiedz <b>„{self.phrase}”</b> {self.times} razy, z krótką przerwą po każdym."]
        lines += [f"{i + 1}. słyszę: „{h}”" for i, h in enumerate(self.heard)]
        if len(self.heard) < self.times:
            lines.append(f"<i>Słucham… ({len(self.heard) + 1}/{self.times})</i>")
        self.label.setText("<br>".join(lines))

    def show_result(self, result: PhraseCheck) -> None:
        marks = [f"{'✔' if ok else '✖'} „{h}”" for h, ok in result.heard]
        verdict = "<b>Hasło jest dobre.</b>" if result.ok else "<b>Uwaga:</b><br>" + "<br>".join(result.problems)
        self.label.setText("<br>".join(marks + ["", verdict]))
