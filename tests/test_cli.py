from dictaitor import cli, i18n


def run(capsys, *argv):
    try:
        assert cli.main(list(argv)) == 0
        return capsys.readouterr().out
    finally:
        i18n.set_language("pl")


def test_cli_speaks_the_configured_language(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("DICTAITOR_HOME", str(tmp_path))
    out = run(capsys, "simulate", "Cześć Ania [1.0] wyślij teraz", "--output", "stdout")
    assert "Cześć Ania." in out and "WYSŁANO" in out

    config = tmp_path / "en.toml"
    config.write_text('[general]\nlanguage = "en"\n', encoding="utf-8")
    out = run(capsys, "--config", str(config), "simulate", "Hi Anna [1.0] send it now", "--output", "stdout")
    assert "Hi Anna." in out and "SENT (printed to stdout)" in out
    out = run(capsys, "--config", str(config), "rules")
    assert "Send phrase: “send it now”" in out and "Voice commands:" in out
