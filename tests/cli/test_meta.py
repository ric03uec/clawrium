"""Tests for `clawctl version`, `clawctl --version`, and `clawctl completion`."""

from typer.testing import CliRunner

from clawrium import __git_sha__, __version__
from clawrium.cli import app

runner = CliRunner()


class TestVersion:
    def test_flag_and_subcommand_match(self) -> None:
        flag = runner.invoke(app, ["--version"])
        sub = runner.invoke(app, ["version"])
        assert flag.exit_code == 0
        assert sub.exit_code == 0
        assert (
            flag.output.strip()
            == sub.output.strip()
            == f"clawctl {__version__} (git: {__git_sha__})"
        )

    def test_git_sha_in_output(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert f"git: {__git_sha__}" in result.output


class TestCompletion:
    def test_bash(self) -> None:
        result = runner.invoke(app, ["completion", "bash"])
        assert result.exit_code == 0
        # Click's bash completion script defines a `_<APP>_completion` shell fn.
        assert "_clawctl_completion" in result.output or "complete -" in result.output

    def test_zsh(self) -> None:
        result = runner.invoke(app, ["completion", "zsh"])
        assert result.exit_code == 0
        assert "_clawctl_completion" in result.output or "compdef" in result.output

    def test_fish(self) -> None:
        result = runner.invoke(app, ["completion", "fish"])
        assert result.exit_code == 0
        assert "complete --no-files" in result.output or "complete -" in result.output

    def test_rejects_unknown_shell(self) -> None:
        result = runner.invoke(app, ["completion", "powershell"])
        assert result.exit_code != 0
