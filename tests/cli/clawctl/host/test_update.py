"""Tests for `clawctl host edit --hostname` (IP address / hostname update)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.core.hosts import get_host

runner = CliRunner()


def test_edit_hostname_success(fleet_dir) -> None:
    """--hostname updates hostname and the primary addresses entry."""
    result = runner.invoke(app, ["host", "edit", "wolf-i", "--hostname", "10.0.0.99"])
    assert result.exit_code == 0, result.output
    assert "updated" in result.output

    host = get_host("wolf-i")
    assert host is not None
    assert host["hostname"] == "10.0.0.99"
    # Primary address entry must be updated too
    primaries = [a for a in host.get("addresses", []) if a.get("is_primary")]
    assert len(primaries) == 1
    assert primaries[0]["address"] == "10.0.0.99"
    # key_id must be unchanged
    assert host["key_id"] == "10.0.0.1"


def test_edit_hostname_prints_key_id_note(fleet_dir) -> None:
    """A note about the unchanged SSH key is printed after hostname update."""
    result = runner.invoke(app, ["host", "edit", "wolf-i", "--hostname", "10.0.0.99"])
    assert result.exit_code == 0, result.output
    assert "key_id: 10.0.0.1" in result.output
    assert "authorized_keys" in result.output


def test_edit_hostname_no_change(fleet_dir) -> None:
    """Passing the same hostname as current produces no key_id note."""
    result = runner.invoke(app, ["host", "edit", "wolf-i", "--hostname", "10.0.0.1"])
    assert result.exit_code == 0, result.output
    # Same IP: record is "updated" (no-op on value) but no key note
    assert "authorized_keys" not in result.output


def test_edit_hostname_conflict(fleet_dir) -> None:
    """--hostname rejects a value already in use by another host."""
    result = runner.invoke(app, ["host", "edit", "wolf-i", "--hostname", "10.0.0.2"])
    assert result.exit_code != 0
    assert "already in use" in result.output


def test_edit_hostname_empty_rejected(fleet_dir) -> None:
    """Passing an empty string to --hostname is rejected before touching state."""
    result = runner.invoke(app, ["host", "edit", "wolf-i", "--hostname", ""])
    assert result.exit_code != 0
    assert "cannot be empty" in result.output


def test_edit_no_args_error(fleet_dir) -> None:
    """Calling edit with no flags exits non-zero with a helpful message."""
    result = runner.invoke(app, ["host", "edit", "wolf-i"])
    assert result.exit_code != 0
    assert "--hostname" in result.output


def test_edit_hostname_combined_with_alias(fleet_dir) -> None:
    """--hostname and --alias can be combined in a single call."""
    result = runner.invoke(
        app,
        ["host", "edit", "wolf-i", "--hostname", "10.0.0.50", "--alias", "wolf-new"],
    )
    assert result.exit_code == 0, result.output
    assert "updated" in result.output

    host = get_host("wolf-new")
    assert host is not None
    assert host["hostname"] == "10.0.0.50"
    assert host["alias"] == "wolf-new"
    primaries = [a for a in host.get("addresses", []) if a.get("is_primary")]
    assert len(primaries) == 1
    assert primaries[0]["address"] == "10.0.0.50"


def test_edit_hostname_invalid_format_rejected(fleet_dir) -> None:
    """--hostname rejects values that fail address format validation."""
    # Shell metacharacter — rejected by _validate_address
    result = runner.invoke(app, ["host", "edit", "wolf-i", "--hostname", "10.0.0.1;rm"])
    assert result.exit_code != 0

    # CIDR notation — not a bare address
    result2 = runner.invoke(app, ["host", "edit", "wolf-i", "--hostname", "10.0.0.0/24"])
    assert result2.exit_code != 0

    # host record must be unchanged
    host = get_host("wolf-i")
    assert host is not None
    assert host["hostname"] == "10.0.0.1"


def test_edit_hostname_describe_reflects_update(fleet_dir) -> None:
    """describe -o json reports the new hostname after edit --hostname."""
    runner.invoke(app, ["host", "edit", "wolf-i", "--hostname", "10.0.0.77"])
    describe = runner.invoke(app, ["host", "describe", "wolf-i", "-o", "json"])
    assert describe.exit_code == 0, describe.output
    data = json.loads(describe.output)[0]
    assert data["hostname"] == "10.0.0.77"
    primary = next(a for a in data["addresses"] if a["is_primary"])
    assert primary["address"] == "10.0.0.77"
