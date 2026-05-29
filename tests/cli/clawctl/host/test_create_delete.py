"""Tests for `clawctl host create` and `clawctl host delete`.

These exercise:
  - The non-interactive contract (stdin-not-tty + missing flag fails;
    stdin-not-tty + --yes proceeds for delete).
  - The `--user xclm` requirement.
  - The two-phase create flow: first run generates a keypair and prints
    manual setup commands when xclm SSH fails; re-run after manual setup
    succeeds and persists the host record.
  - `os_family` detection: persisted from `uname -s` on successful
    verification (regression guard for the macOS dispatcher in #469).
  - Rich markup safety: hostname / pubkey markup metacharacters are
    escaped before they reach `console.print`.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


@pytest.fixture
def mock_ssh_fail(monkeypatch):
    """Force `clawctl host create` to see xclm SSH verification fail."""
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.test_ssh_connection",
        lambda **_kw: (False, "Authentication failed - check SSH keys"),
    )


@pytest.fixture
def mock_ssh_ok_linux(monkeypatch):
    """xclm SSH succeeds; uname -s returns Linux."""
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.test_ssh_connection",
        lambda **_kw: (True, "Connection successful"),
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create._detect_os_family",
        lambda *_a, **_kw: "linux",
    )


@pytest.fixture
def mock_ssh_ok_darwin(monkeypatch):
    """xclm SSH succeeds; uname -s returns Darwin."""
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.test_ssh_connection",
        lambda **_kw: (True, "Connection successful"),
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create._detect_os_family",
        lambda *_a, **_kw: "darwin",
    )


def test_create_requires_user_on_non_tty(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["host", "create", "192.168.1.100"])
    assert result.exit_code != 0
    assert "Error: missing required flag --user" in result.output


def test_create_rejects_non_xclm_user(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "carol", "--alias", "newbox"],
    )
    assert result.exit_code != 0
    assert "must be 'xclm'" in result.output


def test_create_first_run_generates_keypair_and_prints_manual_setup(
    fleet_dir, stdin_not_tty, mock_ssh_fail
) -> None:
    result = runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"],
    )
    assert result.exit_code == 1, result.output
    # Keypair was generated under the XDG config dir.
    key_dir: Path = fleet_dir / "keys" / "192.168.1.100"
    assert (key_dir / "xclm_ed25519").exists()
    assert (key_dir / "xclm_ed25519.pub").exists()
    # Both OS blocks are present, with the macOS-only access_ssh hint.
    assert "## Linux" in result.output
    assert "## macOS" in result.output
    assert "com.apple.access_ssh" in result.output
    assert "ssh-ed25519" in result.output
    # Host record was NOT persisted on this run.
    list_result = runner.invoke(app, ["host", "get", "-o", "json"])
    parsed = json.loads(list_result.output)
    assert all(row["name"] != "newbox" for row in parsed)


def test_create_rerun_after_manual_setup_succeeds(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    # Run 1: SSH fails → keypair generated, manual setup printed, exit 1.
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.test_ssh_connection",
        lambda **_kw: (False, "Authentication failed"),
    )
    first = runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"],
    )
    assert first.exit_code == 1

    # Run 2: operator pasted the commands; SSH succeeds, uname -s returns
    # Linux. monkeypatch.setattr cleans up automatically at test exit so
    # state does not leak into other tests.
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.test_ssh_connection",
        lambda **_kw: (True, "Connection successful"),
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create._detect_os_family",
        lambda *_a, **_kw: "linux",
    )

    second = runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"],
    )
    assert second.exit_code == 0, second.output

    list_result = runner.invoke(app, ["host", "get", "-o", "json"])
    parsed = json.loads(list_result.output)
    names = {row["name"] for row in parsed}
    assert "newbox" in names


def test_create_persists_os_family_linux(
    fleet_dir, stdin_not_tty, mock_ssh_ok_linux
) -> None:
    result = runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "linbox"],
    )
    assert result.exit_code == 0, result.output

    from clawrium.core.hosts import get_host

    record = get_host("192.168.1.100")
    assert record is not None
    assert record["os_family"] == "linux"


def test_create_persists_os_family_darwin(
    fleet_dir, stdin_not_tty, mock_ssh_ok_darwin
) -> None:
    """Regression guard for #547 / #469 — a fresh Mac must land as darwin,
    not the linux default that _apply_legacy_defaults backfills."""
    result = runner.invoke(
        app,
        ["host", "create", "10.0.0.99", "--user", "xclm", "--alias", "macbox"],
    )
    assert result.exit_code == 0, result.output

    from clawrium.core.hosts import get_host

    record = get_host("10.0.0.99")
    assert record is not None
    assert record["os_family"] == "darwin"


def test_create_idempotent_when_record_already_matches(
    fleet_dir, stdin_not_tty, mock_ssh_ok_linux, monkeypatch
) -> None:
    """SSH verification is run on every invocation. Idempotency is at the
    record-write layer, not the verify layer."""
    calls = {"count": 0}

    def _counting_verify(**_kw):
        calls["count"] += 1
        return (True, "Connection successful")

    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.test_ssh_connection", _counting_verify
    )

    runner.invoke(
        app, ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"]
    )
    result = runner.invoke(
        app, ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"]
    )
    assert result.exit_code == 0
    assert "already exists" in result.output
    # First call did the write; second short-circuits before the verify.
    assert calls["count"] == 1


def test_create_first_run_with_unknown_host_key_prompts_user(
    fleet_dir, stdin_not_tty, monkeypatch
) -> None:
    """`HostKeyVerificationRequired` from paramiko is surfaced with the
    one-shot `ssh xclm@...` instruction rather than silently swallowed."""
    from clawrium.core.ssh_connection import HostKeyVerificationRequired

    def _raise(**_kw):
        raise HostKeyVerificationRequired(
            hostname="192.168.1.100",
            key_type="ssh-ed25519",
            fingerprint="SHA256:abc123",
        )

    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.test_ssh_connection", _raise
    )

    result = runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"],
    )
    assert result.exit_code == 1
    assert "Host key prompt required" in result.output
    assert "SHA256:abc123" in result.output
    assert "ssh -p 22 xclm@192.168.1.100" in result.output


def test_create_rerun_reuses_existing_keypair(
    fleet_dir, stdin_not_tty, mock_ssh_fail
) -> None:
    """Regression guard against clobbering a previously-generated key on
    re-run. The deleted `host_macos` suite covered this contract; we
    re-assert it here for the new flow."""
    runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"],
    )
    key_path: Path = fleet_dir / "keys" / "192.168.1.100" / "xclm_ed25519"
    first_content = key_path.read_bytes()

    runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"],
    )
    assert key_path.read_bytes() == first_content


def test_create_escapes_rich_markup_in_hostname(
    fleet_dir, stdin_not_tty, mock_ssh_fail
) -> None:
    """A hostname containing `[bold]` etc. must not be parsed as Rich
    markup when surfaced in the keygen / manual-setup output."""
    malicious = "host.[red]boom[/red].example"
    result = runner.invoke(
        app,
        ["host", "create", malicious, "--user", "xclm", "--alias", "mhost"],
    )
    # Rich markup tags would normally be stripped from output; the literal
    # bracketed text must appear instead.
    assert "[red]boom[/red]" in result.output


def test_create_escapes_shell_metachars_in_pubkey(
    fleet_dir, stdin_not_tty, mock_ssh_fail, monkeypatch
) -> None:
    """The pubkey is inlined into the printed `echo … | sudo tee` block.
    A pubkey comment containing backticks or `$()` must be quoted so that
    pasting the block does not execute arbitrary commands on the host."""
    poisoned = "ssh-ed25519 AAAAC3Nz `rm -rf /` $(id) clawrium"
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.read_public_key",
        lambda _h: poisoned,
    )
    result = runner.invoke(
        app,
        ["host", "create", "192.168.1.100", "--user", "xclm", "--alias", "newbox"],
    )
    # shlex.quote wraps the whole pubkey in single quotes so the backtick
    # and $() cannot be evaluated by the receiving shell.
    assert "'ssh-ed25519 AAAAC3Nz `rm -rf /` $(id) clawrium'" in result.output


def test_delete_non_tty_without_yes_fails(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["host", "delete", "kevin"])
    assert result.exit_code != 0
    assert "Error:" in result.output
    assert "--yes" in result.output


def test_delete_non_tty_with_yes_succeeds(fleet_dir, stdin_not_tty) -> None:
    result = runner.invoke(app, ["host", "delete", "kevin", "--yes"])
    assert result.exit_code == 0
    list_result = runner.invoke(app, ["host", "get", "-o", "name"])
    assert "host/kevin" not in list_result.output


def test_detect_os_family_returns_darwin_for_uname_output(monkeypatch) -> None:
    """Direct unit test of `_detect_os_family`. The shipping dispatcher
    consumes the return value verbatim, so the Linux/Darwin string mapping
    must be exact."""
    from clawrium.cli.clawctl.host import create as create_mod

    fake_stdout = MagicMock()
    fake_stdout.read.return_value = b"Darwin\n"

    fake_client = MagicMock()
    fake_client.exec_command.return_value = (MagicMock(), fake_stdout, MagicMock())
    monkeypatch.setattr(
        create_mod.paramiko, "SSHClient", lambda: fake_client
    )

    assert (
        create_mod._detect_os_family("10.0.0.1", 22, "/tmp/key") == "darwin"
    )
