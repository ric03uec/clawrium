"""Tests for the `clawctl service` group."""

import os
from pathlib import Path

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
