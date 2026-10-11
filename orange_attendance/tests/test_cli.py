from typer.testing import CliRunner

from orange_attendance_tools.cli import app


def test_help_lists_attendance_commands() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "day" in result.stdout
    assert "grid" in result.stdout
    assert "stat" in result.stdout
