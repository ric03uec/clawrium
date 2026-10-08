"""Tests for the `clawctl service` group."""

import os
from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


class TestServiceInit:
    def test_creates_config_dir(self, isolated_config: Path) -> None:
        """`clawctl service init` creates `~/.config/clawrium/` (same as `clawctl init`)."""
        assert not isolated_config.exists()
        result = runner.invoke(app, ["service", "init"], env=os.environ)
        assert result.exit_code == 0
        assert isolated_config.exists()
        assert isolated_config.is_dir()

    def test_emits_success_line(self, isolated_config: Path) -> None:
        result = runner.invoke(app, ["service", "init"], env=os.environ)
        assert result.exit_code == 0
        assert (
            "initialized" in result.output.lower() or "created" in result.output.lower()
        )

    def test_reports_config_security_error_without_traceback(self, monkeypatch) -> None:
        """Fail-closed config validation should produce actionable CLI output."""
        monkeypatch.setattr(
            "clawrium.cli.init.init_config_dir",
            lambda: (_ for _ in ()).throw(PermissionError("unsafe config")),
        )

        result = runner.invoke(app, ["service", "init"])

        assert result.exit_code == 1
        assert "Unable to initialize the Clawrium config directory" in result.output
        assert "XDG_CONFIG_HOME" in result.output
        assert "Traceback" not in result.output

    def test_reports_parent_component_config_path_error(
        self, monkeypatch, tmp_path
    ) -> None:
        """CLI reports lexical-parent rejection without a traceback."""
        from clawrium.core import config as config_module

        monkeypatch.setattr(
            config_module,
            "get_config_dir",
            lambda: tmp_path / "private" / ".." / "public" / "clawrium",
        )

        result = runner.invoke(app, ["service", "init"])

        assert result.exit_code == 1
        assert "XDG_CONFIG_HOME" in result.output
        assert "Traceback" not in result.output

    def test_sanitizes_bidi_dependency_metadata(self, monkeypatch) -> None:
        """Dependency metadata cannot inject terminal controls into the table."""
        monkeypatch.setattr("clawrium.cli.init.init_config_dir", lambda: Path("/tmp/config"))
        monkeypatch.setattr(
            "clawrium.cli.init.check_all_dependencies",
            lambda: [
                SimpleNamespace(
                    name="[bold]name\u202e[/bold]",
                    found=True,
                    version="[italic]v\u202ex[/italic]",
                    path=None,
                    install_hint="ignored",
                ),
                SimpleNamespace(
                    name="missing",
                    found=False,
                    version=None,
                    path="[u]/x\u202ey[/u]",
                    install_hint="[red]i\u202ez[/red]",
                ),
            ],
        )

        result = runner.invoke(app, ["service", "init"])

        assert result.exit_code == 1
        assert "\u202e" not in result.output
        assert "[bold]name[/bold]" in result.output
        assert "[italic]vx[/italic]" in result.output
        assert "[u]/xy[/u]" in result.output
        assert "[red]iz[/red]" in result.output

    def test_sanitizes_bidi_config_directory_output(self, monkeypatch) -> None:
        """An XDG-derived config path cannot spoof terminal output."""
        dangerous_path = Path("/tmp/[bold]config-\u202e-hidden[/bold]")
        monkeypatch.setattr("clawrium.cli.init.init_config_dir", lambda: dangerous_path)
        monkeypatch.setattr("clawrium.cli.init.check_all_dependencies", lambda: [])

        result = runner.invoke(app, ["service", "init"])

        assert result.exit_code == 0
        assert "\u202e" not in result.output
        assert str(dangerous_path).replace("\u202e", "") in result.output


class TestServiceStubs:
    def test_start_stub(self) -> None:
        result = runner.invoke(app, ["service", "start"])
        assert result.exit_code == 0
        assert result.output.strip() == "Not implemented: service start"

    def test_stop_stub(self) -> None:
        result = runner.invoke(app, ["service", "stop"])
        assert result.exit_code == 0
        assert result.output.strip() == "Not implemented: service stop"

    def test_snapshot_stub(self) -> None:
        result = runner.invoke(app, ["service", "snapshot"])
        assert result.exit_code == 0
        assert result.output.strip() == "Not implemented: service snapshot"

    def test_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["service", "--help"])
        assert result.exit_code == 0
        for verb in ("init", "start", "stop", "snapshot"):
            assert verb in result.output
