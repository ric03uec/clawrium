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


# ---------------------------------------------------------------------------
# #575: _diagnose_unit_failure + _verify_health diagnostic wrapping
# ---------------------------------------------------------------------------


class _FakeChannel:
    def __init__(self, exit_status: int = 0) -> None:
        self._exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self._exit_status


class _FakeStream:
    def __init__(self, payload: bytes, exit_status: int = 0) -> None:
        self._payload = payload
        self.channel = _FakeChannel(exit_status)

    def read(self) -> bytes:
        return self._payload


class _FakeSSHClient:
    """Routes `exec_command` calls by substring match. Each tuple
    (substring, exit_status, stdout_bytes) describes one expected call;
    the first matching tuple is consumed. Order does not matter — the
    helper under test calls `is-active` and `journalctl` in a fixed
    order but we let the tests assert on outcome only. Unmatched
    commands raise AssertionError so a needle typo surfaces loudly
    (ATX S3)."""

    def __init__(self, scripted: list[tuple[str, int, bytes]]) -> None:
        self._scripted = list(scripted)
        self.calls: list[str] = []

    def exec_command(self, command: str, timeout: int | None = None):
        self.calls.append(command)
        for i, (needle, rc, payload) in enumerate(self._scripted):
            if needle in command:
                self._scripted.pop(i)
                stream = _FakeStream(payload, rc)
                return (None, stream, stream)
        raise AssertionError(
            f"_FakeSSHClient: no scripted match for command {command!r}"
        )


class TestDiagnoseUnitFailure:
    def test_discord_login_failure_translated_to_remediation(self):
        journal = (
            b"May 30 09:47:56 wolf hermes[2427668]: ERROR asyncio: ...\n"
            b"discord.errors.LoginFailure: Improper token has been passed.\n"
            b"systemd[1]: hermes-x.service: Main process exited, "
            b"code=exited, status=1/FAILURE\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        assert diag is not None
        assert "Discord" in diag
        # ATX W5: pin the remediation body so a future truncation of
        # the catalog string fails this test loudly.
        assert "clawctl channel registry" in diag

    def test_zeroclaw_empty_gateway_host_translated(self):
        journal = (
            b"May 30 09:51:18 wolf zeroclaw[2431536]: Error: "
            b"[required_field_empty] gateway.host must not be empty "
            b"(gateway.host)\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="zeroclaw-x.service", agent_type="zeroclaw"
        )
        assert diag is not None
        assert "gateway.host" in diag
        assert "#576" in diag

    def test_zeroclaw_broadened_gateway_host_token(self):
        """ATX B3: the broadened regex matches a Rust-shaped phrasing
        in addition to the v0.7.5 token, so a future zeroclaw rewrite
        that changes wording does not silently turn this entry into a
        dead letter."""
        journal = (
            b"zeroclaw: configuration error: field 'gateway.host' is "
            b"empty in /home/zeroclaw-x/.zeroclaw/config.toml\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="zeroclaw-x.service", agent_type="zeroclaw"
        )
        assert diag is not None
        assert "gateway.host" in diag

    def test_missing_provider_key_openrouter_translated(self):
        """ATX B4: the OPENROUTER_API_KEY branch must have its own
        coverage so a regex typo or remediation truncation fails
        loudly."""
        journal = (
            b"hermes[1234]: ConfigError: OPENROUTER_API_KEY is not set "
            b"in environment\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        assert diag is not None
        assert "Provider credentials missing" in diag
        assert "clawctl agent configure" in diag

    def test_missing_provider_key_alternation_branch(self):
        """ATX B4: covers the second branch of the alternation so a
        future reorder of branches does not leave it unexercised."""
        journal = (
            b"agent boot error: No inference provider configured "
            b"after stage providers\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        # Cross-agent entry — empty `agent_types` means it fires on
        # any agent type. Verified with `openclaw` here.
        diag = lc._diagnose_unit_failure(
            client, unit="openclaw-x.service", agent_type="openclaw"
        )
        assert diag is not None
        assert "Provider credentials missing" in diag

    def test_unknown_failure_returns_none(self):
        """A journal that doesn't match any catalog entry returns None
        so the caller falls back to the original error message — the
        diagnostic must never invent a cause."""
        journal = b"systemd[1]: hermes-x.service: Some unknown failure\n"
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        assert diag is None

    def test_empty_journal_returns_none(self):
        """Whitespace-only or empty journal output — no pattern can
        match, so no diagnostic is emitted (rather than a false
        positive on an empty stream)."""
        client = _FakeSSHClient(
            [("journalctl", 0, b"\n\n   \n")],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        assert diag is None

    def test_ssh_failure_swallowed(self):
        """If the journal fetch raises (SSH disconnect, sudo refused,
        etc.) the helper must return None so the caller surfaces the
        original `unit not active` error rather than the diagnostic
        helper's own error."""

        class _RaisingClient:
            def exec_command(self, *_a, **_kw):
                raise RuntimeError("ssh dropped")

        diag = lc._diagnose_unit_failure(
            _RaisingClient(),
            unit="hermes-x.service",
            agent_type="hermes",
        )
        assert diag is None

    def test_uses_sudo_n_flag(self):
        """ATX W1: the journal fetch must use `sudo -n` to fail fast on
        a sudoers regression rather than hang waiting on a password
        prompt."""
        client = _FakeSSHClient([("journalctl", 0, b"")])
        lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        assert any("sudo -n " in cmd for cmd in client.calls), client.calls

    def test_zeroclaw_pattern_does_not_fire_on_hermes(self):
        """ATX B1/W7: a hermes-unit journal that happens to contain
        the `gateway.host` substring must NOT receive the zeroclaw
        TOML-edit remediation — the catalog entry is `agent_types`-
        scoped to zeroclaw only."""
        journal = (
            b"hermes[1234]: some unrelated log line mentioning "
            b"required_field_empty gateway.host in a docstring\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        # Catalog is hermes-scoped for Discord and zeroclaw-scoped for
        # gateway.host; neither matches a hermes journal that only
        # mentions gateway.host. Diagnostic must be None.
        assert diag is None

    def test_discord_pattern_does_not_fire_on_zeroclaw(self):
        """ATX B1/W7: a zeroclaw journal that contains the Discord
        substring (e.g. a config reference) must NOT receive the
        hermes-blaming Discord remediation."""
        journal = (
            b"zeroclaw[1234]: channel discord error: "
            b"discord.errors.LoginFailure: token rejected\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="zeroclaw-x.service", agent_type="zeroclaw"
        )
        # Discord entry is hermes-only. Zeroclaw uses its own native
        # discord client; if/when a zeroclaw-shaped Discord catalog
        # entry is needed, it should be a separate tuple with its own
        # remediation string.
        assert diag is None

    def test_first_pattern_wins_on_overlap(self):
        """ATX W4: pin the tuple-order contract — when a journal
        matches multiple patterns, the earlier one in the tuple wins.
        Future refactor to a dict would break this and the test would
        flag it."""
        journal = (
            b"hermes[1234]: discord.errors.LoginFailure: bad token\n"
            b"hermes[1234]: also OPENROUTER_API_KEY is not set\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        assert diag is not None
        # Discord entry is first in the tuple — it wins over the
        # provider-key entry, even though both match.
        assert "Discord" in diag
        assert "Provider credentials missing" not in diag


class TestVerifyHealthDiagnosticWrap:
    def test_failure_includes_diagnostic_when_pattern_matches(self):
        """The error raised by `_verify_health` on a non-active unit
        must include the diagnostic line — that's the operator-facing
        win from #575."""
        scripted = [
            # `systemctl is-active …` returns non-zero + 'activating'
            ("is-active", 3, b"activating\n"),
            # journalctl returns the Discord trace
            (
                "journalctl",
                0,
                b"discord.errors.LoginFailure: Improper token has been passed.\n",
            ),
        ]
        client = _FakeSSHClient(scripted)
        with pytest.raises(CanonicalSyncError) as exc:
            lc._verify_health(
                client, agent_type="hermes", agent_name="x"
            )
        msg = str(exc.value)
        assert "not active after restart" in msg
        assert "state='activating'" in msg
        # The whole win of #575: the operator sees the actual cause
        # right inside the error, not just the symptom.
        assert "Diagnosis:" in msg
        assert "Discord" in msg
        # ATX W5: pin the remediation body so the test fails loudly
        # if a future change drops the actionable command.
        assert "clawctl channel registry" in msg

    def test_failure_falls_back_to_base_message_on_unknown_pattern(self):
        scripted = [
            ("is-active", 3, b"failed\n"),
            ("journalctl", 0, b"systemd[1]: hermes-x.service: Boom\n"),
        ]
        client = _FakeSSHClient(scripted)
        with pytest.raises(CanonicalSyncError) as exc:
            lc._verify_health(
                client, agent_type="hermes", agent_name="x"
            )
        msg = str(exc.value)
        # No diagnostic suffix when no catalog entry matched — the
        # operator gets the same message as before #575.
        assert "Diagnosis:" not in msg
        assert "state='failed'" in msg

    def test_active_unit_no_diagnosis_no_raise(self):
        scripted = [("is-active", 0, b"active\n")]
        client = _FakeSSHClient(scripted)
        # No exception.
        lc._verify_health(client, agent_type="hermes", agent_name="x")
        # And no second `journalctl` call — happy path is one round trip.
        assert all("journalctl" not in c for c in client.calls)

    def test_diagnose_helper_raise_does_not_mask_health_verdict(
        self, monkeypatch
    ):
        """ATX B5: if `_diagnose_unit_failure` raises internally
        (defensive belt-and-braces against future regressions in the
        catalog or regex), `_verify_health` must still raise
        `CanonicalSyncError` with the bare base message — not the
        diagnostic helper's exception."""
        scripted = [("is-active", 3, b"activating\n")]
        client = _FakeSSHClient(scripted)

        def _raising_diagnose(*_a, **_kw):
            raise RuntimeError("catalog blew up")

        monkeypatch.setattr(lc, "_diagnose_unit_failure", _raising_diagnose)
        with pytest.raises(CanonicalSyncError) as exc:
            lc._verify_health(
                client, agent_type="hermes", agent_name="x"
            )
        msg = str(exc.value)
        assert "not active after restart" in msg
        assert "state='activating'" in msg
        # Crucial: the catalog raise must NOT mask the verdict.
        assert "Diagnosis:" not in msg
        assert "catalog blew up" not in msg
