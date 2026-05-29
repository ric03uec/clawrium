"""Regression coverage for issue #448.

Re-running `clawctl host create` against an existing alias updates the
host's `hostname` / `port` / `addresses` without rotating its `key_id`.
The stable `key_id` is what `secrets.json` is keyed by — rotating it
on every IP/DNS change orphans every per-agent secret on the host.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.hosts import get_host

runner = CliRunner()


@pytest.fixture
def mock_ssh_ok_linux(monkeypatch):
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create.test_ssh_connection",
        lambda **_kw: (True, "Connection successful"),
    )
    monkeypatch.setattr(
        "clawrium.cli.clawctl.host.create._detect_os_family",
        lambda *_a, **_kw: "linux",
    )


def test_re_record_preserves_key_id_and_updates_hostname(
    fleet_dir: Path, stdin_not_tty, mock_ssh_ok_linux
) -> None:
    # First create: IP-only registration.
    first = runner.invoke(
        app,
        ["host", "create", "192.168.1.36", "--user", "xclm", "--alias", "maurice-host"],
    )
    assert first.exit_code == 0, first.output

    before = get_host("maurice-host")
    assert before is not None
    assert before["key_id"] == "192.168.1.36"
    assert before["hostname"] == "192.168.1.36"

    # Operator migrates the host to a Tailscale DNS name — same machine,
    # same alias. `clawctl host create <dns> --alias wolf-i` must
    # rewrite hostname/addresses and preserve key_id.
    second = runner.invoke(
        app,
        [
            "host", "create", "wolf.tailf7742d.ts.net",
            "--user", "xclm", "--alias", "maurice-host",
        ],
    )
    assert second.exit_code == 0, second.output
    assert "key_id preserved" in second.output

    after = get_host("maurice-host")
    assert after is not None
    assert after["key_id"] == "192.168.1.36"  # unchanged
    assert after["hostname"] == "wolf.tailf7742d.ts.net"
    primaries = [a for a in after["addresses"] if a.get("is_primary")]
    assert len(primaries) == 1
    assert primaries[0]["address"] == "wolf.tailf7742d.ts.net"


def test_re_record_rejected_when_user_would_change(
    fleet_dir: Path, stdin_not_tty, mock_ssh_ok_linux
) -> None:
    first = runner.invoke(
        app,
        ["host", "create", "192.168.1.36", "--user", "xclm", "--alias", "maurice-host"],
    )
    assert first.exit_code == 0
    # No way to actually change `user` since the CLI rejects non-xclm
    # values up front; this test asserts the existing error path still
    # fires (i.e. no regression where the re-record branch silently
    # accepted a different user).
    bogus = runner.invoke(
        app,
        ["host", "create", "192.168.1.37", "--user", "carol", "--alias", "maurice-host"],
    )
    assert bogus.exit_code != 0
    assert "must be 'xclm'" in bogus.output


def test_get_host_resolves_by_key_id(
    fleet_dir: Path, stdin_not_tty, mock_ssh_ok_linux
) -> None:
    """Issue #448: get_host must accept the immutable key_id so callers
    holding a stable identifier can resolve back to the host record after
    a hostname mutation."""
    runner.invoke(
        app,
        ["host", "create", "192.168.1.36", "--user", "xclm", "--alias", "maurice-host"],
    )
    runner.invoke(
        app,
        [
            "host", "create", "wolf.tailf7742d.ts.net",
            "--user", "xclm", "--alias", "maurice-host",
        ],
    )
    # `key_id` ("192.168.1.36") is no longer the hostname, but get_host
    # must still resolve it.
    record = get_host("192.168.1.36")
    assert record is not None
    assert record["hostname"] == "wolf.tailf7742d.ts.net"
