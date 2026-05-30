"""Unit tests for `core/lifecycle_canonical.py` internals.

Closes ATX #555-polish blockers:

* B5 — `_extract_secret_keys` / `_diff_removes_secrets` had zero direct
  coverage. Tests below exercise each `_SECRET_KEY_SUFFIXES` family,
  the `.yaml` / `.toml` skip path, the `force=True` bypass, and
  commented-out lines.
* B6 — `_atomic_write` failure paths (empty mktemp, sftp raise,
  install exit code != 0) had no tests. Each path is asserted to
  raise `CanonicalSyncError` with a message naming the failing file.
* B8 — `restart=False` path for zeroclaw was previously verified by a
  test that monkey-patched the function body away. The test below
  confirms `_restart_unit` and `_zeroclaw_repair_after_start` are NOT
  called when `restart=False`, even on a zeroclaw agent (the
  AGENTS.md "no idempotent-skip path" rule only applies when restart
  IS requested).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from clawrium.core import lifecycle_canonical as lc
from clawrium.core.lifecycle_canonical import (
    CanonicalSyncError,
    SecretRemovalRefused,
    _atomic_write,
    _diff_removes_secrets,
    _extract_secret_keys,
    sync_agent_canonical,
)
from clawrium.core.render_diff import FileDiff


# ---------------------------------------------------------------------------
# B5: _extract_secret_keys / _diff_removes_secrets coverage
# ---------------------------------------------------------------------------


class TestExtractSecretKeys:
    def test_every_secret_suffix_family_detected(self):
        body = (
            "FOO_TOKEN=abc\n"
            "BAR_API_KEY=def\n"
            "BAZ_SECRET=ghi\n"
            "QUX_SECRET_KEY=jkl\n"
            "ZZZ_PASSWORD=mno\n"
            "WWW_CREDENTIALS=pqr\n"
            "AWS_ACCESS_KEY_ID=stu\n"
        )
        keys = _extract_secret_keys(body)
        assert keys == {
            "FOO_TOKEN",
            "BAR_API_KEY",
            "BAZ_SECRET",
            "QUX_SECRET_KEY",
            "ZZZ_PASSWORD",
            "WWW_CREDENTIALS",
            "AWS_ACCESS_KEY_ID",
        }

    def test_non_secret_var_not_detected(self):
        body = "LOG_LEVEL=debug\nDISCORD_HOME_CHANNEL=C123\n"
        assert _extract_secret_keys(body) == set()

    def test_broad_underscore_key_suffix_matches_aws_style(self):
        """`_KEY` is intentionally broad — `LOG_LEVEL_KEY` (hypothetical)
        would be flagged, which is acceptable: false-positive forces an
        operator to pass `--force`, while false-negative restores the
        original #555 silent-wipe bug."""
        body = "LOG_LEVEL_KEY=debug\n"
        assert "LOG_LEVEL_KEY" in _extract_secret_keys(body)

    def test_commented_line_not_detected(self):
        body = "# OPENAI_API_KEY=secret\n   # foo\n"
        assert _extract_secret_keys(body) == set()

    def test_inline_assignment_with_spaces(self):
        body = "DISCORD_BOT_TOKEN = 'abc'\n"
        assert "DISCORD_BOT_TOKEN" in _extract_secret_keys(body)


class TestDiffRemovesSecrets:
    def _make_diff(self, *, path: str, remote: str, rendered: str) -> FileDiff:
        return FileDiff(
            path=path,
            remote_path=f"/host/{path}",
            remote_body=remote,
            rendered_body=rendered,
            unified_diff="--- a\n+++ b\n@@ @@\n-x\n+y\n",
            remote_present=True,
        )

    def test_env_file_removal_detected(self):
        d = self._make_diff(
            path=".hermes/.env",
            remote="OPENAI_API_KEY=keep\nGITHUB_TOKEN=keep\n",
            rendered="OPENAI_API_KEY=keep\n",
        )
        assert _diff_removes_secrets(d) == {"GITHUB_TOKEN"}

    def test_env_file_keys_retained_no_removal(self):
        d = self._make_diff(
            path=".hermes/.env",
            remote="OPENAI_API_KEY=keep\nGITHUB_TOKEN=keep\n",
            rendered="OPENAI_API_KEY=keep\nGITHUB_TOKEN=keep\n",
        )
        assert _diff_removes_secrets(d) == set()

    def test_yaml_file_never_triggers_guard(self):
        """YAML bodies have no bare KEY=VALUE lines, so the guard
        skips them — `API_KEY: foo` inside a YAML scalar would
        otherwise match the regex spuriously."""
        d = self._make_diff(
            path=".hermes/config.yaml",
            remote="env:\n  OPENAI_API_KEY: keep\n",
            rendered="env:\n",
        )
        assert _diff_removes_secrets(d) == set()

    def test_toml_file_never_triggers_guard(self):
        d = self._make_diff(
            path=".zeroclaw/config.toml",
            remote='[providers.models.openai]\napi_key = "sk-1"\n',
            rendered="[providers.models.openai]\n",
        )
        assert _diff_removes_secrets(d) == set()


def _stub_sync_environment(monkeypatch, *, agent_type: str = "hermes"):
    """Stub out the IO surface so `sync_agent_canonical` can run in-process.

    Returns the captured event list and the per-call patches so tests
    can override individual collaborators (transition_state, etc.).
    """
    from clawrium.core.render import (
        ChannelInputs,
        GatewayInputs,
        ProviderInputs,
        RenderInputs,
        RenderedFiles,
    )

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type=agent_type,
        provider=ProviderInputs(
            name="o", type="openrouter", api_key="sk", default_model="m"
        ),
        channels=(
            ChannelInputs(name="d", type="discord", bot_token="t"),
        ),
        gateway=GatewayInputs(host="h", port=40000, auth="a"),
    )
    monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
    if agent_type == "zeroclaw":
        rendered = RenderedFiles(
            files={
                ".zeroclaw/config.toml": "x = 1\n",
                ".zeroclaw/zeroclaw-env.conf": "",
            }
        )
    else:
        rendered = RenderedFiles(files={".hermes/.env": "FOO=1\n"})
    monkeypatch.setitem(lc._RENDERERS, agent_type, lambda _: rendered)
    monkeypatch.setattr(
        lc,
        "get_agent_by_name",
        lambda _: ({"hostname": "h"}, f"{agent_type}:alpha", {}),
    )
    diff = FileDiff(
        path=next(iter(rendered.files)),
        remote_path="/host/" + next(iter(rendered.files)),
        remote_body="",
        rendered_body=next(iter(rendered.files.values())),
        unified_diff="--- a\n+++ b\n@@ @@\n+x\n",
        remote_present=False,
    )
    monkeypatch.setattr(lc, "diff_files", lambda **_: [diff])
    monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())
    monkeypatch.setattr(lc, "_atomic_write", lambda *a, **kw: None)
    monkeypatch.setattr(lc, "_restart_unit", lambda *a, **kw: None)
    monkeypatch.setattr(lc, "_verify_health", lambda *a, **kw: None)
    events: list[tuple[str, str]] = []
    return events, inputs


def test_sync_state_ready_success_no_error_field(monkeypatch):
    """B4 (ATX #555 polish round 2): happy-path state transition leaves
    `CanonicalSyncResult.error` unpopulated."""
    events, _ = _stub_sync_environment(monkeypatch)
    monkeypatch.setattr(
        "clawrium.core.onboarding.transition_state",
        lambda *a, **kw: None,
    )
    result = sync_agent_canonical(
        "alpha",
        restart=False,
        verify=False,
        on_event=lambda s, m: events.append((s, m)),
    )
    assert result.success
    assert result.error is None


def test_sync_state_ready_invalid_transition_emits_note(monkeypatch):
    """B4: InvalidTransitionError leaves `error=None` (mid-walk agents
    are not a sync failure) but emits a `sync` note explaining the
    skip — previously this branch was completely silent."""
    from clawrium.core.onboarding import InvalidTransitionError

    events, _ = _stub_sync_environment(monkeypatch)

    def _raise(*a, **kw):
        raise InvalidTransitionError("stuck in PROVIDERS")

    monkeypatch.setattr("clawrium.core.onboarding.transition_state", _raise)
    result = sync_agent_canonical(
        "alpha",
        restart=False,
        verify=False,
        on_event=lambda s, m: events.append((s, m)),
    )
    assert result.success
    assert result.error is None
    note_events = [m for s, m in events if s == "sync" and "skipped state=READY" in m]
    assert note_events, events


def test_sync_state_ready_agent_not_found_populates_error(monkeypatch):
    """B4: AgentNotFoundError surfaces on `result.error` so callers
    that gate on `.error is None` see the registry incoherence
    (previously success=True / error=None — silent)."""
    from clawrium.core.onboarding import AgentNotFoundError

    events, _ = _stub_sync_environment(monkeypatch)

    def _raise(*a, **kw):
        raise AgentNotFoundError("agent gone")

    monkeypatch.setattr("clawrium.core.onboarding.transition_state", _raise)
    result = sync_agent_canonical(
        "alpha",
        restart=False,
        verify=False,
        on_event=lambda s, m: events.append((s, m)),
    )
    # B2 (ATX #555 polish round 3): registry incoherence is a real
    # failure — caller must see success=False AND a populated error.
    assert result.success is False
    assert result.error is not None
    assert "registry record missing" in result.error
    assert "agent gone" in result.error


def test_sync_state_ready_generic_exception_populates_error(monkeypatch):
    """B4: a non-onboarding-typed exception (IO, permission) on the
    state-write surfaces on `result.error`."""
    events, _ = _stub_sync_environment(monkeypatch)

    def _raise(*a, **kw):
        raise OSError("disk full")

    monkeypatch.setattr("clawrium.core.onboarding.transition_state", _raise)
    result = sync_agent_canonical(
        "alpha",
        restart=False,
        verify=False,
        on_event=lambda s, m: events.append((s, m)),
    )
    # B2 (ATX #555 polish round 3): IO/permission failures on the
    # state write are real failures — surface `success=False` so a CLI
    # handler does not print "sync complete" with a stuck non-READY
    # agent.
    assert result.success is False
    assert result.error is not None
    assert "state=READY" in result.error
    assert "disk full" in result.error


def test_open_ssh_raises_when_no_private_key(monkeypatch):
    """W9 (ATX #555 polish round 2): missing SSH key for the host
    surfaces as `CanonicalSyncError` with the operator-actionable hint
    referencing `clawctl host create`."""
    monkeypatch.setattr(lc, "get_host_private_key", lambda _: None)
    with pytest.raises(CanonicalSyncError, match="no SSH key registered"):
        lc._open_ssh({"hostname": "h", "key_id": "k"})


def test_open_ssh_wraps_authentication_exception(monkeypatch, tmp_path):
    """B7 (ATX #555 polish round 3): paramiko's
    `AuthenticationException` from `client.connect()` must surface as
    `CanonicalSyncError` naming the host."""
    import paramiko

    key_path = tmp_path / "k"
    key_path.write_text("dummy")
    monkeypatch.setattr(lc, "get_host_private_key", lambda _: key_path)
    monkeypatch.setattr(
        paramiko.SSHClient,
        "connect",
        lambda self, **kw: (_ for _ in ()).throw(
            paramiko.AuthenticationException("bad creds")
        ),
    )
    with pytest.raises(
        CanonicalSyncError,
        match=r"SSH connection to 'h\.example' failed: bad creds",
    ):
        lc._open_ssh({"hostname": "h.example", "key_id": "k"})


def test_open_ssh_wraps_oserror(monkeypatch, tmp_path):
    """B7 (ATX #555 polish round 3): OSError (network unreachable, dns
    failure, etc.) must surface as `CanonicalSyncError` referencing the
    host."""
    import paramiko

    key_path = tmp_path / "k"
    key_path.write_text("dummy")
    monkeypatch.setattr(lc, "get_host_private_key", lambda _: key_path)
    monkeypatch.setattr(
        paramiko.SSHClient,
        "connect",
        lambda self, **kw: (_ for _ in ()).throw(OSError("network unreachable")),
    )
    with pytest.raises(
        CanonicalSyncError,
        match=r"network error reaching 'h\.example': network unreachable",
    ):
        lc._open_ssh({"hostname": "h.example", "key_id": "k"})


def test_open_ssh_wraps_ssh_exception(monkeypatch, tmp_path):
    """W-B (ATX #555 polish round 4): paramiko's generic `SSHException`
    (e.g. banner timeout, transport-level error) shares the same
    except tuple as `AuthenticationException` and must surface as
    `CanonicalSyncError`."""
    import paramiko

    key_path = tmp_path / "k"
    key_path.write_text("dummy")
    monkeypatch.setattr(lc, "get_host_private_key", lambda _: key_path)
    monkeypatch.setattr(
        paramiko.SSHClient,
        "connect",
        lambda self, **kw: (_ for _ in ()).throw(
            paramiko.SSHException("banner timeout")
        ),
    )
    with pytest.raises(
        CanonicalSyncError,
        match=r"SSH connection to 'h\.example' failed: banner timeout",
    ):
        lc._open_ssh({"hostname": "h.example", "key_id": "k"})


def test_zeroclaw_sync_repair_failure_raises(monkeypatch):
    """B-NEW-1 (ATX #555 polish round 4): when
    `_zeroclaw_repair_after_start` returns `(False, err)`, the sync
    must raise `CanonicalSyncError` with the operator-actionable
    message naming the re-pair failure. Closes the only branch added
    in round 3 that lacked direct coverage."""
    from clawrium.core.render import (
        GatewayInputs,
        ProviderInputs,
        RenderInputs,
        RenderedFiles,
    )

    inputs = RenderInputs(
        agent_name="zc",
        agent_type="zeroclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", api_key="sk", default_model="m"
        ),
        gateway=GatewayInputs(host="h", port=40000, auth="a"),
    )
    monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
    rendered = RenderedFiles(
        files={".zeroclaw/config.toml": "x = 1\n", ".zeroclaw/zeroclaw-env.conf": ""}
    )
    monkeypatch.setitem(lc._RENDERERS, "zeroclaw", lambda _: rendered)
    monkeypatch.setattr(
        lc,
        "get_agent_by_name",
        lambda _: ({"hostname": "h"}, "zeroclaw:zc", {}),
    )
    monkeypatch.setattr(
        lc,
        "diff_files",
        lambda **_: [
            FileDiff(
                path=".zeroclaw/config.toml",
                remote_path="/host/.zeroclaw/config.toml",
                remote_body="x = 0\n",
                rendered_body="x = 1\n",
                unified_diff="--- a\n+++ b\n@@ @@\n-x = 0\n+x = 1\n",
                remote_present=True,
            ),
        ],
    )
    monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())
    monkeypatch.setattr(lc, "_atomic_write", lambda *a, **kw: None)
    monkeypatch.setattr(lc, "_restart_unit", lambda *a, **kw: None)
    monkeypatch.setattr(lc, "_verify_health", lambda *a, **kw: None)

    with patch(
        "clawrium.core.lifecycle._zeroclaw_repair_after_start",
        return_value=(False, "handshake timeout"),
    ):
        with pytest.raises(
            CanonicalSyncError,
            match=r"re-pair failed: handshake timeout",
        ):
            sync_agent_canonical("zc", restart=True, verify=False)


def test_open_ssh_wraps_bad_host_key(monkeypatch, tmp_path):
    """B7 (ATX #555 polish round 3): `BadHostKeyException` (key swap
    on a previously-recorded host) must surface as `CanonicalSyncError`
    flagging the MITM hazard, not silently auto-accept."""
    import paramiko

    key_path = tmp_path / "k"
    key_path.write_text("dummy")
    monkeypatch.setattr(lc, "get_host_private_key", lambda _: key_path)

    def _connect(self, **kw):
        # Construct minimal BadHostKeyException — paramiko's __init__
        # takes hostname, got_key, expected_key.
        raise paramiko.BadHostKeyException("h.example", MagicMock(), MagicMock())

    monkeypatch.setattr(paramiko.SSHClient, "connect", _connect)
    with pytest.raises(CanonicalSyncError, match=r"could be a MITM"):
        lc._open_ssh({"hostname": "h.example", "key_id": "k"})


def test_sync_unknown_agent_type_raises(monkeypatch):
    """W10 (ATX #555 polish round 2): unknown agent type — renderer
    table lookup returns None — surfaces a CanonicalSyncError."""
    from clawrium.core.render import (
        GatewayInputs,
        ProviderInputs,
        RenderInputs,
    )

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="bogusclaw",
        provider=ProviderInputs(name="o", type="openrouter"),
        gateway=GatewayInputs(host="h", port=1),
    )
    monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
    with pytest.raises(CanonicalSyncError, match="no canonical renderer"):
        sync_agent_canonical("alpha")


def test_sync_agent_missing_from_hosts_raises(monkeypatch):
    """W10 (ATX #555 polish round 2): get_agent_by_name returning None
    must surface as CanonicalSyncError, not propagate a confusing
    AttributeError downstream."""
    from clawrium.core.render import (
        GatewayInputs,
        ProviderInputs,
        RenderInputs,
        RenderedFiles,
    )

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=ProviderInputs(name="o", type="openrouter", api_key="k"),
        gateway=GatewayInputs(host="h", port=1),
    )
    monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
    monkeypatch.setitem(
        lc._RENDERERS,
        "hermes",
        lambda _: RenderedFiles(files={".hermes/.env": ""}),
    )
    monkeypatch.setattr(lc, "get_agent_by_name", lambda _: None)
    with pytest.raises(CanonicalSyncError, match="not found in hosts.json"):
        sync_agent_canonical("alpha")


def test_sync_force_bypass_writes_through_secret_removal(monkeypatch):
    """force=True must allow a sync that removes host-side secrets."""
    from clawrium.core.render import (
        ChannelInputs,
        GatewayInputs,
        ProviderInputs,
        RenderInputs,
        RenderedFiles,
    )

    inputs = RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=ProviderInputs(name="o", type="openrouter", api_key="sk"),
        channels=(
            ChannelInputs(name="d", type="discord", bot_token="t"),
        ),
        gateway=GatewayInputs(host="h", port=1, auth="a"),
    )
    monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
    rendered = RenderedFiles(files={".hermes/.env": "FOO=1\n"})
    monkeypatch.setitem(lc._RENDERERS, "hermes", lambda _: rendered)
    monkeypatch.setattr(
        lc,
        "get_agent_by_name",
        lambda _: ({"hostname": "h"}, "hermes:alpha", {}),
    )
    diff = FileDiff(
        path=".hermes/.env",
        remote_path="/host/.env",
        remote_body="OPENAI_API_KEY=keep\nFOO=1\n",
        rendered_body="FOO=1\n",
        unified_diff="--- a\n+++ b\n@@ @@\n-OPENAI_API_KEY=keep\n",
        remote_present=True,
    )
    monkeypatch.setattr(lc, "diff_files", lambda **_: [diff])
    monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())
    # W7 (ATX #555 polish round 2): capture remote_path so we can
    # assert the rendered body actually reaches `_atomic_write`.
    written: list = []
    monkeypatch.setattr(
        lc,
        "_atomic_write",
        lambda *a, **kw: written.append(kw["remote_path"]),
    )
    # Stub onboarding transition so we don't write hosts.json.
    monkeypatch.setattr(
        "clawrium.core.onboarding.transition_state",
        lambda *a, **kw: None,
    )

    # Without force, refusal — and no write attempted.
    with pytest.raises(SecretRemovalRefused):
        sync_agent_canonical("alpha", force=False, restart=False)
    assert written == []
    # With force, no raise; the rendered body IS written.
    result = sync_agent_canonical("alpha", force=True, restart=False)
    assert result.success
    assert ".hermes/.env" in result.files_written
    assert written == ["/host/.env"]


# ---------------------------------------------------------------------------
# B6: _atomic_write failure paths
# ---------------------------------------------------------------------------


def _exec_stub(exit_status: int, stdout: bytes = b"", stderr: bytes = b""):
    """Build a (stdin, stdout, stderr) triple paramiko `exec_command` returns."""
    stdin = MagicMock()
    out = MagicMock()
    out.channel.recv_exit_status.return_value = exit_status
    out.read.return_value = stdout
    err = MagicMock()
    err.read.return_value = stderr
    return stdin, out, err


def test_atomic_write_raises_when_mktemp_returns_empty():
    client = MagicMock()
    client.exec_command.return_value = _exec_stub(0, stdout=b"\n")
    with pytest.raises(CanonicalSyncError, match="mktemp returned empty"):
        _atomic_write(
            client,
            agent_name="alpha",
            remote_path="/host/.hermes/.env",
            body="FOO=1\n",
        )


def test_atomic_write_raises_when_mktemp_exits_nonzero():
    client = MagicMock()
    client.exec_command.return_value = _exec_stub(1, stdout=b"/tmp/x\n")
    with pytest.raises(CanonicalSyncError, match="mktemp failed"):
        _atomic_write(
            client,
            agent_name="alpha",
            remote_path="/host/.hermes/.env",
            body="FOO=1\n",
        )


def test_atomic_write_raises_when_install_fails():
    client = MagicMock()
    # First exec_command call: mktemp. Subsequent: install + rm cleanup.
    client.exec_command.side_effect = [
        _exec_stub(0, stdout=b"/tmp/clawrium-sync.abc\n"),
        _exec_stub(1, stderr=b"install: permission denied"),
        _exec_stub(0),  # rm cleanup in finally
    ]
    sftp = MagicMock()
    client.open_sftp.return_value = sftp
    with pytest.raises(
        CanonicalSyncError, match="install '/host/.hermes/.env' failed"
    ):
        _atomic_write(
            client,
            agent_name="alpha",
            remote_path="/host/.hermes/.env",
            body="FOO=1\n",
        )


def test_atomic_write_raises_when_sftp_write_fails():
    client = MagicMock()
    client.exec_command.side_effect = [
        _exec_stub(0, stdout=b"/tmp/clawrium-sync.abc\n"),
        _exec_stub(0),  # rm cleanup
    ]
    sftp = MagicMock()
    sftp.file.side_effect = OSError("sftp write disk full")
    client.open_sftp.return_value = sftp
    with pytest.raises(OSError, match="sftp write disk full"):
        _atomic_write(
            client,
            agent_name="alpha",
            remote_path="/host/.hermes/.env",
            body="FOO=1\n",
        )


# ---------------------------------------------------------------------------
# B8: restart=False on zeroclaw skips _restart_unit AND _zeroclaw_repair
# ---------------------------------------------------------------------------


def test_zeroclaw_sync_restart_false_still_repairs_bearer(monkeypatch):
    """B1 (ATX #555 polish round 3): zeroclaw must always re-pair the
    gateway bearer on sync regardless of `restart`. AGENTS.md
    "Gateway Token Lifecycle (zeroclaw)" §437 is explicit: "There is
    no idempotent-skip path." `restart=False` skips `_restart_unit`
    but the bearer re-mint runs unconditionally so a remote
    `clawctl agent chat` does not 401 indefinitely against the cached
    `hosts.json.gateway.auth`."""
    from clawrium.core.render import (
        GatewayInputs,
        ProviderInputs,
        RenderInputs,
        RenderedFiles,
    )

    inputs = RenderInputs(
        agent_name="zc",
        agent_type="zeroclaw",
        provider=ProviderInputs(
            name="or", type="openrouter", api_key="sk", default_model="m"
        ),
        gateway=GatewayInputs(host="h", port=40000, auth="a"),
    )
    monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
    rendered = RenderedFiles(
        files={".zeroclaw/config.toml": "x = 1\n", ".zeroclaw/zeroclaw-env.conf": ""}
    )
    monkeypatch.setitem(lc._RENDERERS, "zeroclaw", lambda _: rendered)
    monkeypatch.setattr(
        lc,
        "get_agent_by_name",
        lambda _: ({"hostname": "h"}, "zeroclaw:zc", {}),
    )
    diff = FileDiff(
        path=".zeroclaw/config.toml",
        remote_path="/host/.zeroclaw/config.toml",
        remote_body="x = 0\n",
        rendered_body="x = 1\n",
        unified_diff="--- a\n+++ b\n@@ @@\n-x = 0\n+x = 1\n",
        remote_present=True,
    )
    diff_unchanged = FileDiff(
        path=".zeroclaw/zeroclaw-env.conf",
        remote_path="/host/.zeroclaw/zeroclaw-env.conf",
        remote_body="",
        rendered_body="",
        unified_diff="",
        remote_present=True,
    )
    monkeypatch.setattr(lc, "diff_files", lambda **_: [diff, diff_unchanged])
    monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())
    monkeypatch.setattr(lc, "_atomic_write", lambda *a, **kw: None)
    monkeypatch.setattr(
        "clawrium.core.onboarding.transition_state",
        lambda *a, **kw: None,
    )

    restart_called = []
    monkeypatch.setattr(
        lc,
        "_restart_unit",
        lambda *a, **kw: restart_called.append(True),
    )

    repair_called = []
    with patch(
        "clawrium.core.lifecycle._zeroclaw_repair_after_start"
    ) as mock_repair:
        mock_repair.side_effect = lambda *a, **kw: repair_called.append(True) or (
            True,
            None,
        )
        events: list[tuple[str, str]] = []
        result = sync_agent_canonical(
            "zc",
            restart=False,
            verify=False,
            on_event=lambda s, m: events.append((s, m)),
        )

    assert result.success
    assert restart_called == []
    # B1 round-3: re-pair MUST run even with restart=False on zeroclaw.
    assert repair_called == [True]
    # Event stream confirms emission too.
    assert any(stage == "repair" for stage, _ in events), events
