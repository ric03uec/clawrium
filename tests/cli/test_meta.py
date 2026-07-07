"""Tests for `clawctl version`, `clawctl --version`, and `clawctl completion`.

B3: exercises the fallback path where ``clawrium._version`` is absent.
W7: includes an independent regex assertion that does not interpolate from
     the SUT's own imports.
S4: parametrized across both entrypoints and both SHA modes.
S6: ``test_git_sha_in_output`` replaced with regex-based assertion.
"""

from __future__ import annotations

import importlib
import re
import sys
from typing import Generator

import pytest
from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()

_VERSION_RE = re.compile(r"^clawctl .+(?: \(git: [0-9a-f]{4,40}\))?$")


class TestVersionOutput:
    """Happy-path version output tests."""

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["--version"], id="flag"),
            pytest.param(["version"], id="subcommand"),
        ],
    )
    def test_exit_code_zero(self, args: list[str]) -> None:
        result = runner.invoke(app, args)
        assert result.exit_code == 0

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["--version"], id="flag"),
            pytest.param(["version"], id="subcommand"),
        ],
    )
    def test_output_matches_regex(self, args: list[str]) -> None:
        """W7: independent regex assertion — does not depend on SUT imports."""
        result = runner.invoke(app, args)
        assert _VERSION_RE.match(result.output.strip()), (
            f"Output {result.output.strip()!r} does not match expected pattern"
        )

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["--version"], id="flag"),
            pytest.param(["version"], id="subcommand"),
        ],
    )
    def test_flag_and_subcommand_match(self, args: list[str]) -> None:
        """Both entrypoints must produce identical output."""
        flag_out = runner.invoke(app, ["--version"]).output.strip()
        sub_out = runner.invoke(app, ["version"]).output.strip()
        assert flag_out == sub_out


class TestFallback:
    """B3: verify the ``ImportError`` fallback path (editable install, no _version.py)."""

    @pytest.fixture(autouse=True)
    def _isolate_clawrium(self) -> Generator[None, None, None]:
        """Save and restore ``clawrium``-related modules in ``sys.modules``.

        Do NOT delete modules here — other tests hold references to the
        original module objects (e.g. ``from clawrium.core.hosts import
        load_hosts``). Deleting them forces fresh imports with new module
        objects, so ``monkeypatch.setattr("clawrium.core.hosts.foo", …)``
        patches a different object than the one the test's ``load_hosts``
        actually uses.  Saving and restoring the originals prevents this.
        """
        originals: dict[str, object] = {}
        for k, v in list(sys.modules.items()):
            if k == "clawrium" or (v is not None and k.startswith("clawrium.")):
                originals[k] = v
        yield
        for k, v in originals.items():
            sys.modules[k] = v

    @pytest.mark.parametrize(
        "args",
        [
            pytest.param(["--version"], id="flag"),
            pytest.param(["version"], id="subcommand"),
        ],
    )
    def test_fallback_unknown_sha(self, args: list[str]) -> None:
        """When ``clawrium._version`` is missing, output omits ``(git: …)``."""
        # Replace _version with a broken stub that lacks the expected
        # attributes — ``from clawrium._version import __git_sha__``
        # will raise ImportError, exercising the fallback branch.
        import types

        broken = types.ModuleType("clawrium._version")
        # Deliberately omit __version__ and __git_sha__.
        sys.modules["clawrium._version"] = broken

        # Reload clawrium so the except branch runs.
        import clawrium

        importlib.reload(clawrium)

        # Re-import cli so it picks up the reloaded clawrium.format_version.
        import clawrium.cli

        importlib.reload(clawrium.cli)

        from clawrium import __git_sha__

        assert __git_sha__ == "unknown", (
            f"Expected __git_sha__ == 'unknown' after breaking _version, got {__git_sha__!r}"
        )

        result = runner.invoke(clawrium.cli.app, args)
        assert result.exit_code == 0
        # W5: when SHA is "unknown", output should NOT contain "(git:"
        assert "(git:" not in result.output, (
            f"Expected no git suffix for unknown SHA, got: {result.output.strip()!r}"
        )
        assert result.output.strip().startswith("clawctl ")


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
