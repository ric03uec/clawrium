"""Tests for clm init command."""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli.main import app

runner = CliRunner()


class TestCliInit:
    """Tests for the init command."""

    def test_no_args_shows_help(self) -> None:
        """Running clm with --help should show help."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output or "usage:" in result.output.lower()
        assert "init" in result.output

    def test_init_creates_config_dir(self, isolated_config: Path) -> None:
        """clm init should create the config directory."""
        assert not isolated_config.exists()

        result = runner.invoke(app, ["init"], env=os.environ)

        assert result.exit_code == 0
        assert isolated_config.exists()
        assert isolated_config.is_dir()

    def test_init_outputs_config_path(self, isolated_config: Path) -> None:
        """clm init should output the config directory path."""
        result = runner.invoke(app, ["init"], env=os.environ)

        assert str(isolated_config) in result.output

    def test_init_shows_success_message(self, isolated_config: Path) -> None:
        """clm init should show a success message."""
        result = runner.invoke(app, ["init"], env=os.environ)

        assert (
            "initialized" in result.output.lower() or "created" in result.output.lower()
        )

    def test_init_idempotent(self, isolated_config: Path) -> None:
        """clm init should work even if directory exists."""
        # First run
        runner.invoke(app, ["init"], env=os.environ)
        assert isolated_config.exists()

        # Second run should not fail
        result = runner.invoke(app, ["init"], env=os.environ)
        assert result.exit_code == 0

    def test_init_shows_dependency_table(self, isolated_config: Path) -> None:
        """clm init should show dependency status table."""
        result = runner.invoke(app, ["init"])

        assert "Dependency Status" in result.output
        assert "python" in result.output.lower()
        assert "ansible" in result.output.lower()

    def test_init_shows_ok_for_found_deps(self, isolated_config: Path) -> None:
        """clm init should show OK for found dependencies."""
        result = runner.invoke(app, ["init"])

        # Python and ansible-runner should always be found (project deps)
        assert "OK" in result.output

    def test_init_exits_1_when_deps_missing(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """clm init should exit 1 if any dependency is missing."""
        from clawrium.core import deps

        # Mock ansible as missing
        original_check = deps.check_ansible

        def mock_check_ansible():
            return deps.DependencyStatus(
                name="ansible",
                found=False,
                version=None,
                path=None,
                install_hint="Install via: pipx install ansible",
            )

        monkeypatch.setattr(deps, "check_ansible", mock_check_ansible)

        result = runner.invoke(app, ["init"])

        assert result.exit_code == 1
        assert "MISSING" in result.output

    def test_init_shows_install_hint_for_missing(
        self, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """clm init should show install instructions for missing deps."""
        from clawrium.core import deps

        def mock_check_ansible():
            return deps.DependencyStatus(
                name="ansible",
                found=False,
                version=None,
                path=None,
                install_hint="Install via: pipx install ansible",
            )

        monkeypatch.setattr(deps, "check_ansible", mock_check_ansible)

        result = runner.invoke(app, ["init"])

        # Table may wrap text, so check for parts separately
        assert "pipx" in result.output
        assert "install ansible" in result.output
