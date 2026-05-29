"""Issue #448 — hermes env/secrets reconcile invariant.

`lifecycle.start_agent` for hermes probes the on-host `.env`'s
`API_SERVER_KEY` before starting the daemon. If it disagrees with
`secrets.json[<key_id>:hermes:<name>].HERMES_API_SERVER_KEY`, we
reconfigure first — `secrets.json` is the authoritative source.

The probe is intentionally non-fatal: on any failure (host
unreachable, malformed line, etc.) it returns ``(True, error)`` so we
do not synthesize a configure loop on transient issues.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from clawrium.core.lifecycle import _hermes_env_token_matches_secrets


def _ssh_returning(stdout_bytes: bytes):
    """Build a paramiko.SSHClient mock whose exec_command yields the
    given bytes on stdout. MagicMock's default 3-tuple unpacking is
    unreliable; construct the tuple explicitly."""
    client = MagicMock()
    stdout = MagicMock()
    stdout.read.return_value = stdout_bytes
    client.exec_command.return_value = (MagicMock(), stdout, MagicMock())
    ssh_cls = MagicMock(return_value=client)
    return ssh_cls


def _host():
    return {
        "hostname": "wolf.example",
        "key_id": "wolf-key",
        "port": 22,
        "user": "xclm",
        "os_family": "linux",
    }


def test_probe_returns_match_when_values_agree():
    with (
        patch(
            "clawrium.core.lifecycle.get_instance_secrets",
            return_value={"HERMES_API_SERVER_KEY": {"value": "abc123"}},
        ),
        patch(
            "clawrium.core.lifecycle.get_host_private_key",
            return_value="/tmp/key",
        ),
        patch(
            "clawrium.core.lifecycle.paramiko.SSHClient",
            _ssh_returning(b"API_SERVER_KEY='abc123'\n"),
        ),
    ):
        matches, error = _hermes_env_token_matches_secrets(_host(), "maurice")
    assert matches is True
    assert error is None


def test_probe_returns_mismatch_when_values_differ():
    """The maurice/wolf-i breakage: .env has the bearer rendered from a
    previous hostname-keyed entry; secrets.json now holds the new key_id
    entry. Mismatch → reconfigure."""
    with (
        patch(
            "clawrium.core.lifecycle.get_instance_secrets",
            return_value={"HERMES_API_SERVER_KEY": {"value": "new-token"}},
        ),
        patch(
            "clawrium.core.lifecycle.get_host_private_key",
            return_value="/tmp/key",
        ),
        patch(
            "clawrium.core.lifecycle.paramiko.SSHClient",
            _ssh_returning(b"API_SERVER_KEY='stale-token'\n"),
        ),
    ):
        matches, error = _hermes_env_token_matches_secrets(_host(), "maurice")
    assert matches is False
    assert error is None


def test_probe_is_non_fatal_on_ssh_failure():
    with (
        patch(
            "clawrium.core.lifecycle.get_host_private_key",
            return_value="/tmp/key",
        ),
        patch(
            "clawrium.core.lifecycle.paramiko.SSHClient",
            side_effect=RuntimeError("no route to host"),
        ),
    ):
        matches, error = _hermes_env_token_matches_secrets(_host(), "maurice")
    # Transient failure must not trigger a reconfigure storm.
    assert matches is True
    assert error is not None
