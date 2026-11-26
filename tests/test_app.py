import pytest

from powerlog import __version__
from powerlog.app import main


def test_version_exits_before_starting_gui(monkeypatch, capsys):
    def unexpected_gui(*args):
        pytest.fail("--version must not start the GUI")

    monkeypatch.setattr("powerlog.app.QApplication", unexpected_gui)
    with pytest.raises(SystemExit) as result:
        main(["--version"])
    assert result.value.code == 0
    assert capsys.readouterr().out == f"Powerlog {__version__}\n"
