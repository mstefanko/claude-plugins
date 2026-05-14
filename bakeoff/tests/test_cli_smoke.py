import pytest

from bakeoff.cli import main


def test_orientation_prints_user_surface(capsys):
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "bakeoff" in output
    assert "gather" in output
    assert "compare" in output
    assert "analyze" in output


def test_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])

    assert exc.value.code == 0
    assert "research" in capsys.readouterr().out
