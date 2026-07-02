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

import re
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


@pytest.fixture(autouse=True)
def _default_probe_present(request, monkeypatch):
    """#811: every sync test that doesn't explicitly exercise the
    validate-phase probe gets a "both artifacts present" stub so the
    new SSH round-trip in `sync_agent_canonical` is invisible.

    Tests that want to exercise the real probe declare
    `@pytest.mark.no_probe_stub` (ATX iter-1 B4 — marker-based opt-
    out instead of a class-name string literal that would silently
    decay if the class is renamed).
    """
    if request.node.get_closest_marker("no_probe_stub") is not None:
        return
    monkeypatch.setattr(
        lc,
        "probe_host_install",
        lambda *_a, **_kw: lc.HostInstallProbe(
            unit_present=True,
            home_present=True,
            unit_path="/etc/systemd/system/x.service",
            home_path="/home/x/.x",
        ),
    )


def _catalog_pattern_containing(needle: str) -> str:
    """Look up a `_KNOWN_UNIT_FATAL_PATTERNS` regex by content
    instead of positional index — ATX iter-4 S2. Inserting a new
    catalog entry before an existing one no longer silently shifts
    the index out from under the test."""
    for pattern, _scope, _summary, _remediation in lc._KNOWN_UNIT_FATAL_PATTERNS:
        if needle in pattern:
            return pattern
    raise AssertionError(
        f"no catalog entry contains {needle!r}; check needle or catalog"
    )


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
    # #811: stub the validate-phase host probe to "install intact" so
    # the new validate-phase short-circuit doesn't fire on tests that
    # exercise downstream sync behavior. Tests that want to exercise
    # the missing-install path override this explicitly.
    monkeypatch.setattr(
        lc,
        "probe_host_install",
        lambda *_a, **_kw: lc.HostInstallProbe(
            unit_present=True,
            home_present=True,
            unit_path="/etc/systemd/system/x.service",
            home_path="/home/alpha/.x",
        ),
    )
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
    monkeypatch.setattr(
        lc,
        "probe_host_install",
        lambda *_a, **_kw: lc.HostInstallProbe(
            unit_present=True,
            home_present=True,
            unit_path="/etc/systemd/system/zeroclaw-zc.service",
            home_path="/home/zc/.zeroclaw",
        ),
    )

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
    monkeypatch.setattr(
        lc,
        "probe_host_install",
        lambda *_a, **_kw: lc.HostInstallProbe(
            unit_present=True,
            home_present=True,
            unit_path="/etc/systemd/system/hermes-alpha.service",
            home_path="/home/alpha/.hermes",
        ),
    )
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

    @pytest.mark.parametrize(
        "journal_line",
        [
            # Rust-shaped phrasing — "is empty" branch.
            b"zeroclaw: configuration error: field 'gateway.host' is "
            b"empty in /home/zeroclaw-x/.zeroclaw/config.toml\n",
            # Canonical phrasing — "must not be empty" branch (ATX
            # iter-2 W3: previously unexercised).
            b"zeroclaw[1234]: validation: gateway.host must not be "
            b"empty\n",
        ],
    )
    def test_zeroclaw_broadened_gateway_host_token(self, journal_line):
        """ATX B3 + iter-2 W3: the broadened regex matches both
        post-v0.7.5 phrasings, so a future zeroclaw rewrite changing
        wording does not silently turn this entry into a dead letter."""
        client = _FakeSSHClient(
            [("journalctl", 0, journal_line)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="zeroclaw-x.service", agent_type="zeroclaw"
        )
        assert diag is not None
        assert "gateway.host" in diag
        # ATX iter-2 W1: pin the remediation body so a truncated
        # remediation string fails this test loudly.
        assert "clawctl agent sync" in diag
        assert "#576" in diag

    @pytest.mark.parametrize(
        "journal_line",
        [
            # ATX iter-2 B1: a benign startup log mentioning the
            # `(required)` annotation alongside `gateway.host` must
            # NOT fire the diagnostic — that was the over-match the
            # original `|required` alternation produced.
            b"zeroclaw[1234]: Config field gateway.host (required): "
            b"set this to 0.0.0.0\n",
            b"zeroclaw[1234]: checking gateway.host... required for "
            b"daemon init\n",
            # ATX iter-3 S3: also pin the exact `is required` /
            # `required` phrasings that the dropped `|required` branch
            # would have over-matched. These exercise the specific
            # word boundary that distinguishes a startup annotation
            # from a fault state.
            b"zeroclaw[1234]: schema: gateway.host is required\n",
            b"zeroclaw[1234]: gateway.host required\n",
        ],
    )
    def test_zeroclaw_required_annotation_does_not_over_match(
        self, journal_line
    ):
        """ATX iter-2 B1 + iter-3 S3: dropping `|required` from the
        alternation means startup logs mentioning `(required)`,
        `is required`, or bare `required` alongside `gateway.host` no
        longer over-fire the diagnostic. The actual crash cases
        ("must not be empty", "is empty") are unchanged and still
        match (covered by `test_zeroclaw_broadened_gateway_host_token`).
        """
        client = _FakeSSHClient(
            [("journalctl", 0, journal_line)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="zeroclaw-x.service", agent_type="zeroclaw"
        )
        assert diag is None

    def test_zeroclaw_branch1_alone_matches_canonical_token(self):
        """ATX iter-3 W-NEW-2: pin that branch1
        (`required_field_empty.*gateway.host`) fires on a journal
        line that does NOT carry any suffix branch2 would also
        accept. Without this case, deleting branch1 from the
        production regex would still pass every other test —
        because every other positive test happens to carry both
        a `required_field_empty` token AND a `must not be empty` /
        `is empty` phrase, so branch2 alone covers them. A
        mutation-test would flag the missing exclusive coverage."""
        # No `must not be empty` / `is empty` suffix — only branch1
        # can match this line.
        journal = (
            b"zeroclaw[1234]: [required_field_empty] gateway.host "
            b"\xe2\x80\x94 field was blank\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="zeroclaw-x.service", agent_type="zeroclaw"
        )
        assert diag is not None
        assert "gateway.host" in diag
        # Sanity check: branch2 alone (without `required_field_empty`)
        # would NOT have matched this body. The diagnostic firing
        # therefore proves branch1 carries its own weight.
        pattern = _catalog_pattern_containing("required_field_empty")
        branch2_only = r"gateway\.host.*(?:must not be empty|is empty)"
        assert re.search(pattern, journal.decode())
        assert not re.search(branch2_only, journal.decode())

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
        # ATX iter-2 W2: also pin the remediation body to match the
        # rigor of the first-branch test.
        assert "clawctl agent configure" in diag

    @pytest.mark.parametrize(
        "journal_line",
        [
            # ATX iter-2 B2: the greedy `.*` over-match cases that
            # the tightened pattern must reject. Each line contains
            # the key name and the phrase "not set" but in a
            # state-snapshot / migration context where the key IS
            # present at boot.
            b"hermes[1234]: OPENROUTER_API_KEY was not set on previous "
            b"boot, now present\n",
            b"hermes[1234]: OPENROUTER_API_KEY was not set, now using "
            b"fallback\n",
            # ATX iter-4 S3: bracket-form stale-env case that the
            # iter-2 comment narrated but no test previously
            # covered. Bracket separator is not in the `[\t :=]+`
            # class, so the diagnostic must NOT fire.
            b"hermes[1234]: OPENROUTER_API_KEY [was not set, "
            b"using fallback]\n",
            # ATX iter-4 S4: a case that would fire under a naive
            # `.*` pattern but NOT under the tightened
            # `[\t :=]+(?:is\s+)?not\s+set\b` — the key name and
            # "previously not set" phrase are 4 words apart, so
            # only `.*` could bridge them.
            b"hermes[1234]: OPENROUTER_API_KEY environment variable "
            b"was previously not set\n",
            # ATX iter-4 W1: cross-line case — key at end of one
            # journal line, "not set" at start of next. With a
            # newline-including separator class the diagnostic
            # would over-fire on the multi-line blob; with
            # `[\t :=]+` the newline breaks adjacency and the
            # diagnostic stays silent.
            b"agent[1234]: env dump OPENROUTER_API_KEY\n"
            b"agent[1234]: not set, using ollama fallback\n",
            # ATX iter-4 W3 fix in place: leading `\b` now rejects
            # substring prefixes. `MY_OPENROUTER_API_KEY` is NOT the
            # OpenRouter key clawctl plumbs, and the leading word
            # boundary on `\bOPENROUTER_API_KEY` correctly suppresses
            # the substring match. This case pins that behavior as a
            # regression guard.
            b"hermes[1234]: MY_OPENROUTER_API_KEY is not set\n",
            # ATX iter-5 W1-RESIDUAL (#575): cross-line case inside
            # the suffix — `KEY:` on one line, `is\nnot set`
            # straddling newline between `is` and `not set`. With
            # the iter-4 suffix `(?:is\s+)?not\s+set` (where `\s`
            # includes `\n`), this would have over-fired on a
            # `journalctl -o cat` blob that drops per-line
            # timestamp prefixes. The iter-5 production fix
            # tightened the suffix to `[\t ]+` everywhere; this
            # negative pins the change.
            b"agent[1234]: OPENROUTER_API_KEY: is\nnot set\n",
            # ATX iter-6 S3 (#575): the symmetric newline case
            # between `not` and `set`. The iter-5 fix tightened
            # both `is[\t ]+` and `not[\t ]+set`; this pins the
            # second tightening.
            b"agent[1234]: OPENROUTER_API_KEY: not\nset\n",
        ],
    )
    def test_provider_key_pattern_does_not_over_match_stale_env_logs(
        self, journal_line
    ):
        """ATX iter-2 B2: tightening to
        `\\bOPENROUTER_API_KEY[\\t :=]+(?:is[\\t ]+)?not[\\t ]+set\\b`
        means a stale-env snapshot or migration log that mentions
        the key + a non-adjacent "not set" phrase no longer
        over-fires the diagnostic. ATX iter-5: the horizontal-only
        whitespace classes also reject newline-straddling matches
        in the suffix."""
        client = _FakeSSHClient(
            [("journalctl", 0, journal_line)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        assert diag is None

    @pytest.mark.parametrize(
        "journal_line",
        [
            # ATX iter-3 W-NEW-1: the colon-separator case the
            # iter-2 pattern silently missed.
            b"hermes[1234]: OPENROUTER_API_KEY: is not set in "
            b"environment\n",
            b"hermes[1234]: OPENROUTER_API_KEY: not set\n",
            # `KEY=` style — covered by the same `[\\t :=]+` class.
            b"hermes[1234]: OPENROUTER_API_KEY=not set\n",
            # ATX iter-3 S6: uppercase variant — `(?i)` flag means
            # this matches even though the prefix is uppercase but
            # the phrase is too.
            b"hermes[1234]: OPENROUTER_API_KEY IS NOT SET\n",
            # ATX iter-4 W2: lowercase env-var name — some agents
            # emit env dumps in lowercase. The `(?i)` flag applies
            # to the whole pattern (acknowledged in production
            # comment); this is an intentional match, pinned here
            # so a future scope-tightening of `(?i)` to the suffix
            # only would fail this test rather than silently regress.
            b"agent[1234]: openrouter_api_key not set\n",
            # ATX iter-6 W3 (#575): tab in the `is`-to-`not`
            # position. The `[\t ]+` class admits tabs but no
            # prior positive case exercised them; without this,
            # a future narrowing of the suffix to `[ ]+` (space
            # only) would silently pass tests because the optional
            # `(?:is[\t ]+)?` group lets the engine skip the
            # `is` arm entirely.
            b"hermes[1234]: OPENROUTER_API_KEY: is\tnot set\n",
        ],
    )
    def test_provider_key_pattern_matches_canonical_separators(
        self, journal_line
    ):
        """ATX iter-3 W-NEW-1 + S6: the `[\\t :=]+` separator class
        (horizontal whitespace + colon + equals) plus the `(?i)`
        flag means colon, equals, and case-shifted variants all
        surface the diagnostic. Without these, the pattern was
        silently missing a common log shape."""
        client = _FakeSSHClient(
            [("journalctl", 0, journal_line)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="hermes-x.service", agent_type="hermes"
        )
        assert diag is not None
        assert "Provider credentials missing" in diag
        assert "clawctl agent configure" in diag

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

    def test_zeroclaw_pattern_does_not_fire_on_openclaw(self):
        """ATX iter-2 W4: third-type isolation. The journal body
        here DOES match the zeroclaw regex content-wise — what
        suppresses the diagnostic is the `agent_types` scope filter,
        not the regex itself. A future accidental widening of
        `frozenset({'zeroclaw'})` to include `openclaw` would
        immediately surface a TOML-edit remediation against an agent
        type that has no `~/.openclaw/config.toml` file. ATX iter-3
        S1: make the dual nature explicit — the regex matches, the
        scope filter blocks."""
        journal = (
            b"openclaw[1234]: [required_field_empty] gateway.host must "
            b"not be empty\n"
        )
        # Make the test intent explicit: the regex would match this
        # body. The scope filter is what suppresses the diagnostic.
        zeroclaw_pattern = _catalog_pattern_containing("required_field_empty")
        assert re.search(zeroclaw_pattern, journal.decode())
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="openclaw-x.service", agent_type="openclaw"
        )
        assert diag is None

    def test_discord_pattern_does_not_fire_on_openclaw(self):
        """ATX iter-2 W4: third-type isolation for the hermes-scoped
        Discord entry. An openclaw journal containing the Discord
        substring must NOT receive hermes architectural blame."""
        journal = (
            b"openclaw[1234]: external integration: "
            b"discord.errors.LoginFailure: token rejected\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="openclaw-x.service", agent_type="openclaw"
        )
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
        """ATX W5 (iter-3 S5: corrected tag — this is W5, not W4):
        pin the tuple-order contract — when a journal
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

    def test_first_pattern_wins_zeroclaw_over_provider(self):
        """ATX iter-2 W5: pin first-match-wins for the zeroclaw entry
        beating the cross-agent provider entry. Earlier test covered
        entries 1 vs 3 (Discord vs provider); this covers 2 vs 3."""
        journal = (
            b"zeroclaw[1234]: Error: [required_field_empty] gateway.host "
            b"must not be empty (gateway.host)\n"
            b"zeroclaw[1234]: also OPENROUTER_API_KEY is not set\n"
        )
        client = _FakeSSHClient(
            [("journalctl", 0, journal)],
        )
        diag = lc._diagnose_unit_failure(
            client, unit="zeroclaw-x.service", agent_type="zeroclaw"
        )
        assert diag is not None
        # Zeroclaw gateway.host entry (#2) wins over provider key (#3).
        assert "gateway.host" in diag
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

    def test_active_unit_skips_journalctl_and_requires_gateway_port(self):
        # ATX iter-3 W4: renamed from `test_active_unit_no_diagnosis_no_raise`
        # — that name says the opposite of what now happens. Post-#812
        # pins two invariants: (1) `is-active=active` skips the
        # journalctl diagnostic round trip, (2) `gateway_port=None`
        # on Linux raises for install-incompleteness (parity with macOS).
        scripted = [("is-active", 0, b"active\n")]
        client = _FakeSSHClient(scripted)
        with pytest.raises(
            CanonicalSyncError,
            match=r"no gateway port persisted",
        ):
            lc._verify_health(client, agent_type="hermes", agent_name="x")
        # No second `journalctl` call — happy-path is one round trip.
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


# ---------------------------------------------------------------------------
# #812: _verify_health Linux gateway-port probe (parity with macOS).
# ---------------------------------------------------------------------------


class _LinuxProbeStream:
    """Separate-stderr stub for `_verify_gateway_listening_linux`. The
    probe command ends with `2>&1` so in production bash's stderr is
    merged into stdout and `err.read()` is empty; tests that want to
    drive the missing-bash / disabled-/dev/tcp diagnostic shapes
    populate the `stderr_bytes` slot of `_LinuxProbeClient` script
    entries — the diagnostic helper's `combined = stderr_text +
    stdout_text` covers both stream layouts.

    ATX iter-3 W1: `_Ch.close()` is a no-op so the production
    `try: channel.close(); except Exception: pass` cleanup path is
    actually exercised by tests rather than silently swallowing an
    `AttributeError`.
    """

    def __init__(self, payload: bytes, exit_status: int) -> None:
        self._payload = payload

        class _Ch:
            def __init__(self, rc):
                self._rc = rc

            def recv_exit_status(self):
                return self._rc

            def close(self):
                pass

        self.channel = _Ch(exit_status)

    def read(self) -> bytes:
        return self._payload


class _LinuxProbeClient:
    """Fake paramiko SSHClient. Each entry in `script` is
    (substring, exit_status, stdout_bytes, stderr_bytes). First match
    is consumed. Unmatched commands raise so a typo fails loudly.

    `raise_for` (cmd-substring → exception) lets a test inject a
    paramiko / OSError raise at `exec_command` time without scripting
    a stream — exercises the B1 SSH-channel-error wrap.

    `assert_all_consumed()` lets a test verify it didn't over-script
    (e.g. a "this entry should fire on the second poll" that never
    actually did) — silent over-scripting was the W5 dead-code bug.
    """

    def __init__(
        self,
        script: list[tuple[str, int, bytes, bytes]] | None = None,
        raise_for: dict[str, BaseException] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self._script = list(script or [])
        self._raise_for = dict(raise_for or {})

    def exec_command(self, cmd: str, timeout: int | None = None):
        self.calls.append(cmd)
        for needle, exc in self._raise_for.items():
            if needle in cmd:
                raise exc
        for i, (needle, rc, out, err) in enumerate(self._script):
            if needle in cmd:
                self._script.pop(i)
                return (
                    None,
                    _LinuxProbeStream(out, rc),
                    _LinuxProbeStream(err, rc),
                )
        raise AssertionError(f"_LinuxProbeClient: unscripted command: {cmd!r}")

    def assert_all_consumed(self) -> None:
        if self._script:
            raise AssertionError(
                f"_LinuxProbeClient: {len(self._script)} scripted "
                f"entries never consumed: {self._script!r}"
            )


def _stub_monotonic_linux(monkeypatch, ticks: list[float]) -> None:
    """Mirror of the macOS dispatch test helper. Pop one tick per call
    to `time.monotonic`; sleep is a no-op. Tests that under-feed ticks
    raise loudly rather than silently fall through wall-clock."""
    import time as time_mod

    feed = list(ticks)

    def _next_tick() -> float:
        if not feed:
            raise AssertionError(
                "test under-fed monotonic ticks — extend the list"
            )
        return feed.pop(0)

    monkeypatch.setattr(time_mod, "monotonic", _next_tick)
    monkeypatch.setattr(time_mod, "sleep", lambda _s: None)


class TestVerifyHealthLinuxGatewayProbe:
    """#812: post-`is-active` probe of the gateway port. The Linux
    systemd unit shape we ship (`Type=simple`) reports `active` as soon
    as the daemon process is spawned — before it has bound the gateway
    port and (for a crashlooping daemon) potentially between restart
    cycles. Bringing the Linux verify path to parity with the macOS
    `nc -z` probe stops sync from printing `synced (drift=0)` when the
    daemon is not actually serving requests."""

    def test_probe_returns_immediately_on_first_poll(self, monkeypatch):
        # ATX iter-2 S5: stub monotonic for consistency with the other
        # tests in this class (and so a future regression that turned
        # this loop into a 15s wall-clock wait fails fast in CI).
        _stub_monotonic_linux(monkeypatch, [0.0, 1.0])
        client = _LinuxProbeClient(
            [
                ("systemctl is-active", 0, b"active\n", b""),
                ("/dev/tcp/127.0.0.1/40198", 0, b"", b""),
            ]
        )
        lc._verify_health(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            gateway_port=40198,
        )
        client.assert_all_consumed()
        # Exactly one probe — happy path is one round trip.
        assert sum(1 for c in client.calls if "/dev/tcp" in c) == 1
        # The probe shape MUST invoke `bash` explicitly — `/dev/tcp` is
        # a bash builtin, not a real device. A regression that dropped
        # to `sh -c …` would silently fail on dash-shipping distros.
        probe_calls = [c for c in client.calls if "/dev/tcp" in c]
        assert all(c.startswith("bash -c ") for c in probe_calls)

    def test_delayed_success_exercises_polling_loop(self, monkeypatch):
        """A regression that short-circuited on the first non-zero rc
        would pass the happy-path test but break here. Two failed
        connects then a success; assert the loop kept polling."""
        client = _LinuxProbeClient(
            [
                ("systemctl is-active", 0, b"active\n", b""),
                ("/dev/tcp/127.0.0.1/40198", 1, b"", b""),
                ("/dev/tcp/127.0.0.1/40198", 1, b"", b""),
                ("/dev/tcp/127.0.0.1/40198", 0, b"", b""),
            ]
        )
        # Feed: initial deadline calc + 3 loop-head checks well under
        # deadline. We never miss the deadline before the connect
        # returns 0.
        _stub_monotonic_linux(monkeypatch, [0.0, 1.0, 2.0, 3.0])

        lc._verify_health(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            gateway_port=40198,
            timeout=30,
        )
        client.assert_all_consumed()
        probe_calls = [c for c in client.calls if "/dev/tcp" in c]
        assert len(probe_calls) == 3, probe_calls

    def test_timeout_raises_with_port_in_message(self, monkeypatch):
        """Port never opens → operator gets a precise error naming the
        port and the agent. Sync MUST NOT print `synced (drift=0)`
        in this case — that's the whole point of #812.

        ATX iter-2 W5: ticks `[0.0, 0.5, 999.0]` so the probe actually
        fires once (loop enters at 0.5 < deadline=1.0) before the
        deadline expires on the next check. The previous `[0.0, 999.0]`
        skipped the loop body entirely; the scripted probe entry was
        dead code (over-scripting is now caught by `assert_all_consumed`).
        """
        client = _LinuxProbeClient(
            [
                ("systemctl is-active", 0, b"active\n", b""),
                ("/dev/tcp/127.0.0.1/40198", 1, b"", b""),
            ]
        )
        _stub_monotonic_linux(monkeypatch, [0.0, 0.5, 999.0])

        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"gateway port 40198 not accepting connections",
        ) as exc:
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                gateway_port=40198,
                timeout=1,
            )
        client.assert_all_consumed()
        # The probe MUST have actually fired before the timeout — a
        # regression that left it as dead code is exactly what W5
        # iter-2 caught the first time around.
        assert sum(1 for c in client.calls if "/dev/tcp" in c) == 1
        # The error MUST also point operators at the journal for the
        # actual root-cause — anything weaker just relocates the
        # "now what?" problem. The unit name MUST include the agent
        # *type* (`openclaw-alpha.service`, not bare `alpha.service`)
        # so the suggested `journalctl -u …` command is copy-pasteable
        # — surfaced live on wolf-i during #812 UAT round 1.
        msg = str(exc.value)
        assert "journalctl -u openclaw-alpha.service" in msg

    @pytest.mark.parametrize(
        "stderr_text",
        [
            # dash / sh shape — `\bbash\b … \bnot found\b` arm
            b"sh: 1: bash: not found\n",
            # bash-from-PATH-shape — `\bbash\b … \bnot found\b` arm
            b"bash: command not found\n",
            # Alpine / busybox shape — `\bnot found\b … \bbash\b` arm
            # (the second alternation in `_BASH_MISSING_RE`). Without
            # a test that matches this arm only, a regression that
            # tightens the regex to a single direction goes silent
            # on Alpine images (ATX iter-2 W6).
            b"sh: command not found: bash\n",
        ],
    )
    def test_bash_missing_breaks_early_with_diagnostic(
        self, monkeypatch, stderr_text
    ):
        """If `bash` is not on PATH the probe surfaces as rc=127 with
        a "not found"-shaped error. The helper must break early with a
        diagnostic pointing at the missing tool — not chase the 15s
        deadline and misdirect operators at the daemon."""
        client = _LinuxProbeClient(
            [
                ("systemctl is-active", 0, b"active\n", b""),
                (
                    "/dev/tcp/127.0.0.1/40198",
                    127,
                    b"",
                    stderr_text,
                ),
            ]
        )
        _stub_monotonic_linux(monkeypatch, [0.0, 0.5])

        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"`bash` is not available",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                gateway_port=40198,
                timeout=30,
            )
        client.assert_all_consumed()
        # MUST break on the first probe — not retry until the deadline.
        assert sum(1 for c in client.calls if "/dev/tcp" in c) == 1

    def test_gateway_port_none_raises_for_install_incompleteness(self):
        """ATX iter-2 W1: parity with `verify_health_macos`. A persisted
        `gateway.port` of `None` for a Linux agent that declares one in
        its manifest means install.py never allocated one — silent
        success here would write `state=READY` for a never-verified
        daemon and reintroduce the silent-green failure mode #812
        closes."""
        client = _LinuxProbeClient(
            [("systemctl is-active", 0, b"active\n", b"")]
        )
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"no gateway port persisted.*install\.py never allocated",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                gateway_port=None,
            )
        # No probe attempted.
        assert not any("/dev/tcp" in c for c in client.calls)

    @pytest.mark.parametrize(
        "invalid_port",
        [
            "40198",  # string-typed (hand-edited hosts.json)
            0,        # zero — POSIX reserved
            -1,       # negative
            65536,    # exact upper-bound off-by-one
            3.14,     # float
            True,     # bool (subclass of int)
            False,    # also a bool
        ],
    )
    def test_invalid_port_rejected_before_probe(self, invalid_port):
        """Refuse to interpolate hand-edited junk into the shell probe.
        Mirrors the macOS dispatch invariant."""
        client = _LinuxProbeClient(
            [("systemctl is-active", 0, b"active\n", b"")]
        )
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"invalid gateway_port",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                gateway_port=invalid_port,  # type: ignore[arg-type]
            )
        # No probe attempted — we raise before any SSH probe.
        assert not any("/dev/tcp" in c for c in client.calls)

    def test_unit_not_active_raises_before_probe(self):
        """When `is-active` already failed the diagnostic path runs and
        raises — the port probe must NOT also fire (would only
        compound the noise and waste a round trip)."""
        client = _LinuxProbeClient(
            [
                ("systemctl is-active", 3, b"activating\n", b""),
                ("journalctl", 0, b"", b""),
            ]
        )
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"not active after restart",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                gateway_port=40198,
            )
        assert not any("/dev/tcp" in c for c in client.calls)

    @pytest.mark.parametrize("valid_port", [1, 1024, 40198, 65535])
    def test_valid_port_boundary_values_accepted(self, monkeypatch, valid_port):
        """ATX iter-2 W7: the highest legal port (65535) and lowest
        legal port (1) must succeed through the validator. Combined
        with the 65536 / 0 / -1 invalid cases above, this pins the
        exact `0 < port < 65536` invariant — a regression that
        tightened the guard to `< 65535` or `> 1024` would silently
        misclassify legitimate operator-chosen ports as invalid."""
        _stub_monotonic_linux(monkeypatch, [0.0, 1.0])
        client = _LinuxProbeClient(
            [
                ("systemctl is-active", 0, b"active\n", b""),
                (f"/dev/tcp/127.0.0.1/{valid_port}", 0, b"", b""),
            ]
        )
        lc._verify_health(
            client,
            agent_type="openclaw",
            agent_name="alpha",
            gateway_port=valid_port,
        )
        assert any(f"/dev/tcp/127.0.0.1/{valid_port}" in c for c in client.calls)

    def test_dev_tcp_disabled_breaks_early_with_diagnostic(self, monkeypatch):
        """ATX iter-2 W3: a bash compiled `--disable-net-redirections`
        emits `bash: connect: /dev/tcp/127.0.0.1/N: No such file or
        directory` with rc=1. Without a dedicated branch the operator
        chases the 15s "port not accepting" red herring against a
        perfectly healthy daemon."""
        stderr = b"bash: /dev/tcp/127.0.0.1/40198: No such file or directory\n"
        # ATX iter-3 W6: trimmed from `[0.0, 0.5, 0.6]` to `[0.0, 0.5]`
        # — the early-break path consumes exactly two ticks (deadline
        # calc + one loop-head check) before raising.
        _stub_monotonic_linux(monkeypatch, [0.0, 0.5])
        client = _LinuxProbeClient(
            [
                ("systemctl is-active", 0, b"active\n", b""),
                ("/dev/tcp/127.0.0.1/40198", 1, b"", stderr),
            ]
        )
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"bash on the agent host was built without `/dev/tcp`",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                gateway_port=40198,
                timeout=30,
            )
        client.assert_all_consumed()
        # MUST break on the first probe — not retry until the deadline.
        assert sum(1 for c in client.calls if "/dev/tcp" in c) == 1

    @pytest.mark.parametrize(
        "exc",
        [
            # paramiko-shape channel error
            pytest.param(
                __import__("paramiko").SSHException("channel reset by peer"),
                id="SSHException",
            ),
            # plain OSError shape (e.g. transport-level socket error)
            pytest.param(
                OSError("Connection reset by peer"),
                id="OSError",
            ),
            # ATX iter-3 S1: paramiko raises bare EOFError on abrupt
            # teardown; NOT a subclass of SSHException or OSError, so
            # a regression that dropped it from the except tuple would
            # propagate raw without this parametrize arm.
            pytest.param(EOFError("transport closed"), id="EOFError"),
        ],
    )
    def test_ssh_channel_error_wrapped_as_canonical_error(
        self, monkeypatch, exc
    ):
        """ATX iter-2 B1 + ATX iter-3 W3/S1: every exception type
        paramiko can raise mid-poll MUST surface as
        `CanonicalSyncError`, not propagate raw through
        `sync_agent_canonical`. Parametrized across SSHException,
        OSError, and EOFError so a regression dropping any one arm
        from the except tuple is caught."""
        _stub_monotonic_linux(monkeypatch, [0.0, 0.5])
        client = _LinuxProbeClient(
            script=[("systemctl is-active", 0, b"active\n", b"")],
            raise_for={"/dev/tcp/127.0.0.1/40198": exc},
        )
        with pytest.raises(
            lc.CanonicalSyncError,
            match=r"SSH channel error while probing gateway port 40198",
        ):
            lc._verify_health(
                client,
                agent_type="openclaw",
                agent_name="alpha",
                gateway_port=40198,
                timeout=30,
            )
        client.assert_all_consumed()


# ---------------------------------------------------------------------------
# Brave (#734) — openclaw version preflight.
# ---------------------------------------------------------------------------


class TestOpenclawBraveVersionPreflight:
    """`sync_agent_canonical` must refuse to write `.openclaw/env` with a
    brave block when the host openclaw is older than the plugin's
    `minHostVersion`. Without the preflight the plugin would install
    against a host it doesn't support and surface as a daemon-side
    error that's much harder to diagnose."""

    def _setup(self, monkeypatch, host_version: tuple[int, int, int] | None):
        from clawrium.core.render import (
            GatewayInputs,
            IntegrationInputs,
            ProviderInputs,
            RenderInputs,
            RenderedFiles,
        )

        inputs = RenderInputs(
            agent_name="oc",
            agent_type="openclaw",
            provider=ProviderInputs(
                name="or",
                type="openrouter",
                api_key="sk",
                default_model="m",
            ),
            gateway=GatewayInputs(host="h", port=40000, auth="a"),
            integrations=(
                IntegrationInputs(
                    name="my-brave",
                    type="brave",
                    credentials=(("BRAVE_API_KEY", "bsk-1"),),
                ),
            ),
        )
        monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
        rendered = RenderedFiles(
            files={
                ".openclaw/env": "BRAVE_API_KEY='bsk-1'\n",
                ".openclaw/openclaw.json": "{}",
            }
        )
        monkeypatch.setitem(lc._RENDERERS, "openclaw", lambda _: rendered)
        monkeypatch.setattr(
            lc,
            "get_agent_by_name",
            lambda _: ({"hostname": "h"}, "openclaw:oc", {}),
        )
        monkeypatch.setattr(lc, "diff_files", lambda **_: [])
        monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())
        monkeypatch.setattr(
            lc,
            "_get_host_openclaw_version",
            lambda *_a, **_kw: (host_version, ""),
        )
        # #755: stub the new plugin-install helper — this test class
        # targets the preflight specifically; install behavior has its
        # own coverage in TestOpenclawInstallPlugins.
        monkeypatch.setattr(
            lc, "_openclaw_install_plugins", lambda *_a, **_kw: ((), ())
        )

    def test_below_min_version_raises(self, monkeypatch):
        self._setup(monkeypatch, (2026, 3, 13))
        with pytest.raises(
            CanonicalSyncError,
            match=r"openclaw on 'h' is 2026\.3\.13; brave plugin requires >= 2026\.6\.9",
        ):
            sync_agent_canonical("oc", restart=False, verify=False)

    def test_one_below_floor_raises(self, monkeypatch):
        """Off-by-one boundary: pin-floor minus one must be rejected. The
        far-below case wouldn't catch a comparator regression that treated
        the floor as `< min` instead of `<= min`. (W3 ATX iter 2)"""
        self._setup(monkeypatch, (2026, 6, 8))
        with pytest.raises(
            CanonicalSyncError,
            match=r"openclaw on 'h' is 2026\.6\.8; brave plugin requires >= 2026\.6\.9",
        ):
            sync_agent_canonical("oc", restart=False, verify=False)

    def test_exact_min_version_passes(self, monkeypatch):
        self._setup(monkeypatch, (2026, 6, 9))
        # Should not raise on the preflight; diffs are empty so the rest
        # of the pipeline is a no-op.
        sync_agent_canonical("oc", restart=False, verify=False)

    def test_newer_than_min_version_passes(self, monkeypatch):
        self._setup(monkeypatch, (2026, 6, 10))
        sync_agent_canonical("oc", restart=False, verify=False)

    def test_unknown_version_raises(self, monkeypatch):
        """Unknown version (binary missing / unparseable output) is a
        hard fail — never let the brave plugin install land on an
        unknown host where the plugin's minHostVersion contract cannot
        be evaluated."""
        self._setup(monkeypatch, None)
        with pytest.raises(
            CanonicalSyncError, match=r"openclaw on 'h' is <unknown>"
        ):
            sync_agent_canonical("oc", restart=False, verify=False)

    def test_unknown_version_includes_probe_stderr(self, monkeypatch):
        """W5 ATX iter 2: when the probe returns `None`, the captured
        stderr (sudo failure, unsafe-path rejection, etc.) is appended
        to the error so the operator has a starting diagnostic instead
        of a bare `<unknown>`."""
        self._setup(monkeypatch, None)  # base wiring
        # Override the probe to return None+a real stderr tail.
        monkeypatch.setattr(
            lc,
            "_get_host_openclaw_version",
            lambda *_a, **_kw: (None, "sudo: a password is required"),
        )
        with pytest.raises(
            CanonicalSyncError,
            match=r"stderr: sudo: a password is required",
        ):
            sync_agent_canonical("oc", restart=False, verify=False)

    def test_macos_host_routes_to_macos_resolver(self, monkeypatch):
        """The dispatcher must pass `os_family` from the host record
        through to `_get_host_openclaw_version` — otherwise a Darwin
        host falls back to the Linux variant and the macOS home-path
        fork is dead code."""
        self._setup(monkeypatch, (2026, 6, 9))
        monkeypatch.setattr(
            lc,
            "get_agent_by_name",
            lambda _: (
                {"hostname": "h", "os_family": "darwin"},
                "openclaw:oc",
                {},
            ),
        )
        captured: dict = {}

        def _spy(_client, _agent_name, *, os_family, timeout=10):
            captured["os_family"] = os_family
            return (2026, 6, 9), ""

        monkeypatch.setattr(lc, "_get_host_openclaw_version", _spy)
        sync_agent_canonical("oc", restart=False, verify=False)
        assert captured.get("os_family") == "darwin"

    def test_preflight_skipped_when_no_brave_integration(self, monkeypatch):
        """The preflight has a measurable cost (one SSH exec). When no
        brave integration is attached we MUST NOT invoke it — otherwise
        every openclaw sync pays for a feature that's not in use."""
        from clawrium.core.render import (
            GatewayInputs,
            ProviderInputs,
            RenderInputs,
            RenderedFiles,
        )

        inputs = RenderInputs(
            agent_name="oc",
            agent_type="openclaw",
            provider=ProviderInputs(
                name="or",
                type="openrouter",
                api_key="sk",
                default_model="m",
            ),
            gateway=GatewayInputs(host="h", port=40000, auth="a"),
        )
        monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
        rendered = RenderedFiles(
            files={".openclaw/env": "", ".openclaw/openclaw.json": "{}"}
        )
        monkeypatch.setitem(lc._RENDERERS, "openclaw", lambda _: rendered)
        monkeypatch.setattr(
            lc,
            "get_agent_by_name",
            lambda _: ({"hostname": "h"}, "openclaw:oc", {}),
        )
        monkeypatch.setattr(lc, "diff_files", lambda **_: [])
        monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())

        # Sentinel that fails the test if invoked.
        called = []

        def _should_not_be_called(*_a, **_kw):
            called.append(True)
            return (2026, 5, 28), ""

        monkeypatch.setattr(
            lc, "_get_host_openclaw_version", _should_not_be_called
        )
        # ATX iter-2 W5: stub `_openclaw_install_plugins` so this test
        # does not implicitly exercise it (and the disk-bound
        # `_load_openclaw_plugins` it would call) — the test targets
        # ONLY the version preflight skip.
        monkeypatch.setattr(
            lc, "_openclaw_install_plugins", lambda *_a, **_kw: ((), ())
        )
        sync_agent_canonical("oc", restart=False, verify=False)
        assert called == [], "_get_host_openclaw_version was invoked"


# ---------------------------------------------------------------------------
# Brave (#734) — semver parsing + SSH probe (ATX iter 1 B3).
# ---------------------------------------------------------------------------


class TestParseSemverTuple:
    """`_parse_semver_tuple` is the security-relevant gate that decides
    whether the brave plugin install proceeds. Direct tests rather than
    going through the SSH-mocked happy path so a parser regression
    surfaces on its own."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026.5.28", (2026, 5, 28)),
            ("openclaw 2026.4.10", (2026, 4, 10)),
            ("openclaw version 2026.5.28\nbuilt 2026-05-28", (2026, 5, 28)),
            ("openclaw 1.2.3", (1, 2, 3)),
            ("  2026.4.10  \n", (2026, 4, 10)),
        ],
    )
    def test_parses_realistic_version_strings(self, raw, expected):
        assert lc._parse_semver_tuple(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "not a version",
            "openclaw",
            "12.34",  # only two components
            "version unavailable",
        ],
    )
    def test_returns_none_for_unparseable_input(self, raw):
        assert lc._parse_semver_tuple(raw) is None

    def test_picks_first_line_only(self):
        """If a future build prints a Node/Rust runtime version after
        the openclaw version, we want the openclaw line, not the
        runtime line. (W8 ATX iter 1)"""
        raw = "openclaw 2026.5.28\nnode v22.1.0\n"
        assert lc._parse_semver_tuple(raw) == (2026, 5, 28)


class _ProbeMockClient:
    """Helper that records the SSH commands issued and returns a
    canned (stdout, stderr, exit_status) per invocation. The probe
    issues exactly one `exec_command` per call, so a single entry is
    enough."""

    def __init__(self, stdout: str = "", stderr: str = "", exit_status: int = 0):
        self.commands: list[str] = []
        self._stdout = stdout
        self._stderr = stderr
        self._exit_status = exit_status

    def as_client(self) -> MagicMock:
        client = MagicMock()

        def _exec_command(cmd, **_kw):
            self.commands.append(cmd)
            channel = MagicMock()
            channel.recv_exit_status.return_value = self._exit_status
            out = MagicMock()
            out.read.return_value = self._stdout.encode("utf-8")
            out.channel = channel
            err = MagicMock()
            err.read.return_value = self._stderr.encode("utf-8")
            return MagicMock(), out, err

        client.exec_command.side_effect = _exec_command
        return client


class TestGetHostOpenclawVersionLinux:
    """Linux variant: per-agent binary under `/home/<agent>/`, PATH
    fallback safelist `/usr/local/bin`, `/usr/bin`, `/home/`.
    (B1/B2 ATX iter 2 — completely forked from macOS variant.)"""

    def test_command_shape_includes_linux_per_agent_path_and_safelist(self):
        """Pin the exact shell construction so a regression that
        dropped the per-agent branch (or the safelist check) would
        fail the test rather than survive on generic substring
        matches."""
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        version, _ = lc._get_host_openclaw_version_linux(
            probe.as_client(), "wolf-i"
        )
        assert version == (2026, 6, 8)
        cmd = probe.commands[0]
        # Per-agent path is Linux-rooted.
        assert "/home/wolf-i/.openclaw/bin/openclaw" in cmd
        # Size>0 gate (W1).
        assert (
            "[ -x /home/wolf-i/.openclaw/bin/openclaw ] && "
            "[ -s /home/wolf-i/.openclaw/bin/openclaw ]" in cmd
        )
        # PATH fallback present.
        assert "resolved=$(command -v openclaw" in cmd
        # Safelist contains Linux prefixes.
        assert "/usr/local/bin/" in cmd
        assert "/usr/bin/" in cmd
        assert "/home/" in cmd
        # And NOT macOS prefixes.
        assert "/Users/" not in cmd
        assert "/opt/homebrew/bin/" not in cmd
        # Login shell + sudo + agent-name quoting.
        assert "sudo -n -u wolf-i bash -lc " in cmd
        # Explicit exit 1 branch (binary missing / no PATH match).
        assert "else exit 1; fi" in cmd

    def test_path_fallback_safelist_reject_exits_two_with_stderr(self):
        """If `command -v openclaw` resolves to an unsafelisted path
        (e.g. `/tmp/openclaw`), the probe exits 2 and emits stderr
        naming the path. This is the W2 defense-in-depth fix."""
        probe = _ProbeMockClient(
            "", "openclaw on PATH is at unsafe path: /tmp/openclaw\n", 2
        )
        version, stderr = lc._get_host_openclaw_version_linux(
            probe.as_client(), "wolf-i"
        )
        assert version is None
        assert "unsafe path: /tmp/openclaw" in stderr

    def test_nonzero_exit_returns_none_with_stderr_tail(self):
        """W5 ATX iter 2: stderr is captured and surfaced even when
        the probe fails. Operator now sees sudo / pam errors instead
        of an opaque `<unknown>`."""
        probe = _ProbeMockClient(
            "", "sudo: a password is required\n", 1
        )
        version, stderr = lc._get_host_openclaw_version_linux(
            probe.as_client(), "wolf-i"
        )
        assert version is None
        assert "sudo: a password is required" in stderr

    def test_unparseable_output_returns_none(self):
        probe = _ProbeMockClient("garbage output\n", "", 0)
        version, _ = lc._get_host_openclaw_version_linux(
            probe.as_client(), "wolf-i"
        )
        assert version is None

    def test_agent_name_is_shell_quoted(self):
        """Hostile agent name (e.g. `; rm -rf` injected via a
        misconfigured hosts.json) must not break out of the sudo
        shell. Both the agent-name position (`sudo -n -u`) and the
        per-agent path (which contains `agent_name`) flow through
        `shlex.quote` before reaching bash."""
        probe = _ProbeMockClient("0.0.0\n", "", 0)
        lc._get_host_openclaw_version_linux(probe.as_client(), "a;rm -rf /")
        cmd = probe.commands[0]
        # The agent-name position is single-quoted at the sudo level.
        assert cmd.startswith("sudo -n -u 'a;rm -rf /' bash -lc '")
        # The entire `bash -lc` body is single-quoted, so the `;rm`
        # cannot escape into a top-level shell command separator —
        # any inner single quotes are escaped by shlex.quote's
        # standard `'\''` pattern. (Sanity check: no unescaped
        # top-level `;` would appear after the closing wrapper quote
        # other than as part of a balanced `'\''` sequence.)
        assert cmd.endswith("'")


class TestGetHostOpenclawVersionMacos:
    """macOS (arm64) variant: per-agent binary under `/Users/<agent>/`,
    PATH fallback safelist `/opt/homebrew/bin`, `/usr/local/bin`,
    `/usr/bin`, `/Users/`. Completely forked from the Linux variant —
    when macOS x86_64 support is added, dispatch should fork further
    rather than retrofitting an arch branch into either function.
    (B1/B2 ATX iter 2)"""

    def test_command_shape_includes_macos_per_agent_path_and_safelist(self):
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        version, _ = lc._get_host_openclaw_version_macos(
            probe.as_client(), "wolf-m"
        )
        assert version == (2026, 6, 8)
        cmd = probe.commands[0]
        # Per-agent path is macOS-rooted.
        assert "/Users/wolf-m/.openclaw/bin/openclaw" in cmd
        # Size>0 gate (W1).
        assert (
            "[ -x /Users/wolf-m/.openclaw/bin/openclaw ] && "
            "[ -s /Users/wolf-m/.openclaw/bin/openclaw ]" in cmd
        )
        # PATH fallback present.
        assert "resolved=$(command -v openclaw" in cmd
        # Safelist contains macOS prefixes (Homebrew first).
        assert "/opt/homebrew/bin/" in cmd
        assert "/Users/" in cmd
        # And NOT Linux-only prefix.
        assert "/home/" not in cmd

    def test_path_fallback_safelist_reject_returns_none(self):
        probe = _ProbeMockClient(
            "", "openclaw on PATH is at unsafe path: /tmp/openclaw\n", 2
        )
        version, stderr = lc._get_host_openclaw_version_macos(
            probe.as_client(), "wolf-m"
        )
        assert version is None
        assert "unsafe path: /tmp/openclaw" in stderr

    def test_per_agent_branch_uses_users_prefix(self):
        """Regression guard: the macOS variant must NOT use `/home/`.
        If anyone retrofits `if os_family ==` branching back into the
        Linux variant, this assertion fails immediately."""
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        lc._get_host_openclaw_version_macos(probe.as_client(), "wolf-m")
        assert "/home/wolf-m" not in probe.commands[0]


class TestGetHostOpenclawVersionDispatcher:
    """The public `_get_host_openclaw_version(...)` is a thin dispatcher
    that routes to the Linux or macOS variant based on `os_family`. The
    dispatcher is the only place that knows about both — matches the
    dispatcher-only-OS-fork convention (AGENTS.md)."""

    def test_darwin_routes_to_macos_variant(self):
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        version, _ = lc._get_host_openclaw_version(
            probe.as_client(), "wolf-m", os_family="darwin"
        )
        assert version == (2026, 6, 8)
        assert "/Users/wolf-m/.openclaw/bin/openclaw" in probe.commands[0]
        assert "/home/" not in probe.commands[0]

    def test_linux_routes_to_linux_variant(self):
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        version, _ = lc._get_host_openclaw_version(
            probe.as_client(), "wolf-i", os_family="linux"
        )
        assert version == (2026, 6, 8)
        assert "/home/wolf-i/.openclaw/bin/openclaw" in probe.commands[0]
        assert "/Users/" not in probe.commands[0]

    def test_empty_os_family_defaults_to_linux(self):
        """Older hosts.json records may pre-date os_family persistence;
        treat missing/empty as Linux to match the install.yaml default."""
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        lc._get_host_openclaw_version(
            probe.as_client(), "wolf-i", os_family=""
        )
        assert "/home/wolf-i/.openclaw/bin/openclaw" in probe.commands[0]

    def test_capitalized_darwin_routes_to_macos(self):
        """S4 ATX iter 2: `Darwin` (capitalized) must route to the
        macOS variant. Without lowercase normalization in the
        dispatcher, a host record persisted with `Darwin` would
        silently fall back to Linux and the macOS fork would be
        dead code for that host."""
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        lc._get_host_openclaw_version(
            probe.as_client(), "wolf-m", os_family="Darwin"
        )
        assert "/Users/wolf-m/.openclaw/bin/openclaw" in probe.commands[0]


class TestGetHostOpenclawVersionHomeRootSeam:
    """Issue #752: the OS→home-root mapping must come from the single
    `core.playbook_resolver.home_root_for` seam, NOT from a hardcoded
    `/home` or `/Users` literal in this module. These tests pin the
    integration so a future change to `home_root_for` (e.g., adding
    bsd or moving macOS to `/private/var/users`) propagates into the
    openclaw version probe automatically — and conversely, that
    nobody re-introduces the OS literal here as a shortcut.
    """

    def test_linux_variant_uses_home_root_for_linux(self, monkeypatch):
        """Patch `home_root_for` to return a sentinel root and confirm
        the Linux variant assembles the probe under that root.

        The `raise ValueError` (instead of `assert`) inside the fake
        survives `python -O` and produces a clearly labeled error
        distinguishable from a test assertion failure (ATX iter 1 S1).
        """

        def _fake_home_root_for(os_family: str) -> str:
            if os_family != "linux":
                raise ValueError(
                    f"expected linux, got {os_family!r}"
                )
            return "/SENTINEL-LINUX"

        monkeypatch.setattr(lc, "home_root_for", _fake_home_root_for)
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        lc._get_host_openclaw_version_linux(probe.as_client(), "wolf-i")
        cmd = probe.commands[0]
        assert "/SENTINEL-LINUX/wolf-i/.openclaw/bin/openclaw" in cmd
        # And NOT the historical Linux literal — proves the variant
        # is sourcing the root from the seam, not a duplicate literal.
        assert "/home/wolf-i/.openclaw/bin/openclaw" not in cmd

    def test_macos_variant_uses_home_root_for_darwin(self, monkeypatch):
        """Symmetric pin for the macOS variant."""

        def _fake_home_root_for(os_family: str) -> str:
            if os_family != "darwin":
                raise ValueError(
                    f"expected darwin, got {os_family!r}"
                )
            return "/SENTINEL-DARWIN"

        monkeypatch.setattr(lc, "home_root_for", _fake_home_root_for)
        probe = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        lc._get_host_openclaw_version_macos(probe.as_client(), "wolf-m")
        cmd = probe.commands[0]
        assert "/SENTINEL-DARWIN/wolf-m/.openclaw/bin/openclaw" in cmd
        assert "/Users/wolf-m/.openclaw/bin/openclaw" not in cmd

    def test_resolver_currently_maps_to_expected_roots(self):
        """End-to-end pin: assert the variants produce `/home/...` on
        Linux and `/Users/...` on macOS *today*, using literal strings
        as the expected values (NOT the resolver output — that would
        be tautological and pass even against a hardcoded-literal
        revert, ATX iter 1 B1).

        Together with the sentinel monkeypatch tests above:
        - The monkeypatch pair proves the variants *call* the seam.
        - This test proves the seam *currently* maps to the values
          historically expected by the playbooks (Linux `/home`,
          macOS `/Users`).
        """
        probe_l = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        lc._get_host_openclaw_version_linux(probe_l.as_client(), "wolf-i")
        assert (
            "/home/wolf-i/.openclaw/bin/openclaw" in probe_l.commands[0]
        )

        probe_m = _ProbeMockClient("openclaw 2026.6.8\n", "", 0)
        lc._get_host_openclaw_version_macos(probe_m.as_client(), "wolf-m")
        assert (
            "/Users/wolf-m/.openclaw/bin/openclaw" in probe_m.commands[0]
        )


class TestGetHostOpenclawVersionMacosInjection:
    """S6 ATX iter 2: mirror the Linux shell-injection guard on the
    macOS variant so a regression that drops `shlex.quote` from the
    macOS path is caught symmetrically."""

    def test_agent_name_is_shell_quoted_on_macos(self):
        probe = _ProbeMockClient("0.0.0\n", "", 0)
        lc._get_host_openclaw_version_macos(probe.as_client(), "a;rm -rf /")
        cmd = probe.commands[0]
        assert cmd.startswith("sudo -n -u 'a;rm -rf /' bash -lc '")
        assert cmd.endswith("'")


class TestRunOpenclawVersionProbeStderr:
    """S7 ATX iter 2: pin the 512-byte cap on `stderr_tail` so a
    regression flipping `[-512:]` to `[:512]` or dropping the slice
    surfaces immediately. The cap exists to bound log size when a
    runaway openclaw binary spews stderr."""

    def test_stderr_tail_capped_at_512_bytes(self):
        long_stderr = "ABCDEFGHIJ" * 200  # 2000 bytes
        probe = _ProbeMockClient("", long_stderr, 1)
        _, stderr_tail = lc._get_host_openclaw_version_linux(
            probe.as_client(), "wolf-i"
        )
        assert len(stderr_tail) <= 512
        # And it's the TAIL, not the head — last 512 chars (post-strip).
        assert stderr_tail == long_stderr[-512:].strip()


class TestOpenclawVersionProbeShellSemantics:
    """B4 ATX iter 2: the safelist enforcement must be verified
    against a real bash, not mocked SSH output. The previous
    `' || '.join(case ...)` shape passed every substring assertion
    while only enforcing the first safelist prefix at runtime
    because `case` always exits 0. This class runs the inner script
    via `subprocess.run(['bash', '-c', ...])` against fixture
    binaries to pin the actual shell semantics."""

    def _make_fake_openclaw(self, path):
        """Write a minimal executable shim that prints the canonical
        version line + a marker echoing the resolved path so tests
        can confirm which binary actually ran."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "#!/bin/bash\n"
            'echo "openclaw 2026.6.8"\n'
        )
        path.chmod(0o755)

    def _run(self, inner_script, *, path_dirs):
        import shutil
        import subprocess

        bash = shutil.which("bash") or "/bin/bash"
        # Restrict PATH inside the script to ONLY the test-fixture
        # dirs so `command -v openclaw` returns the fixture we set
        # up — never the test runner's actual openclaw if one exists.
        # `bash` itself is invoked by absolute path so it doesn't
        # need PATH to start.
        env = {"PATH": ":".join(str(p) for p in path_dirs)}
        return subprocess.run(
            [bash, "-c", inner_script],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_per_agent_binary_takes_precedence_over_path(self, tmp_path):
        agent_home = tmp_path / "agents"
        per_agent = agent_home / "x" / ".openclaw" / "bin" / "openclaw"
        self._make_fake_openclaw(per_agent)

        # PATH points elsewhere with a DIFFERENT version string so
        # we can tell which binary ran.
        path_bin = tmp_path / "path-fallback"
        path_bin.mkdir()
        (path_bin / "openclaw").write_text(
            "#!/bin/bash\necho 'openclaw 1.0.0'\n"
        )
        (path_bin / "openclaw").chmod(0o755)

        script = lc._build_openclaw_version_inner_script(
            "x", home_root=str(agent_home), path_safelist=(str(path_bin) + "/",)
        )
        result = self._run(script, path_dirs=[path_bin])
        assert result.returncode == 0, result.stderr
        assert "2026.6.8" in result.stdout
        assert "1.0.0" not in result.stdout

    def test_path_fallback_accepts_first_safelisted_prefix(self, tmp_path):
        """Single-prefix safelist with PATH binary inside it — must accept."""
        safelist_dir = tmp_path / "good"
        self._make_fake_openclaw(safelist_dir / "openclaw")

        script = lc._build_openclaw_version_inner_script(
            "x",
            home_root=str(tmp_path / "missing"),
            path_safelist=(str(safelist_dir) + "/",),
        )
        result = self._run(script, path_dirs=[safelist_dir])
        assert result.returncode == 0, result.stderr
        assert "2026.6.8" in result.stdout

    def test_path_fallback_accepts_every_safelist_prefix(self, tmp_path):
        """B4 regression catcher: a 3-prefix safelist with the
        binary under the *third* prefix MUST be accepted. The
        previous `||`-chained `case` shape would short-circuit on
        the first `case` (always exits 0) and reject the binary as
        unsafelisted even though the third prefix covers it."""
        prefix_a = tmp_path / "a"
        prefix_b = tmp_path / "b"
        prefix_c = tmp_path / "c"
        for p in (prefix_a, prefix_b, prefix_c):
            p.mkdir()
        self._make_fake_openclaw(prefix_c / "openclaw")

        script = lc._build_openclaw_version_inner_script(
            "x",
            home_root=str(tmp_path / "missing"),
            path_safelist=(
                str(prefix_a) + "/",
                str(prefix_b) + "/",
                str(prefix_c) + "/",
            ),
        )
        result = self._run(script, path_dirs=[prefix_c])
        assert result.returncode == 0, (
            f"3rd-prefix binary was rejected — case-chain regression "
            f"(stderr: {result.stderr!r})"
        )
        assert "2026.6.8" in result.stdout

    def test_path_fallback_rejects_unsafelisted_prefix(self, tmp_path):
        """Binary outside the safelist → exit 2, stderr names the path."""
        outside_dir = tmp_path / "outside"
        self._make_fake_openclaw(outside_dir / "openclaw")

        safelist_dir = tmp_path / "safe"
        safelist_dir.mkdir()  # exists, but binary is NOT here

        script = lc._build_openclaw_version_inner_script(
            "x",
            home_root=str(tmp_path / "missing"),
            path_safelist=(str(safelist_dir) + "/",),
        )
        result = self._run(script, path_dirs=[outside_dir])
        assert result.returncode == 2
        assert "unsafe path" in result.stderr
        assert str(outside_dir / "openclaw") in result.stderr

    def test_no_binary_anywhere_exits_one(self, tmp_path):
        """No per-agent binary, nothing on PATH → exit 1."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        script = lc._build_openclaw_version_inner_script(
            "x",
            home_root=str(tmp_path / "missing"),
            path_safelist=(str(empty_dir) + "/",),
        )
        result = self._run(script, path_dirs=[empty_dir])
        assert result.returncode == 1

    def test_zero_byte_per_agent_binary_falls_through_to_path(self, tmp_path):
        """W1 ATX iter 1: a 0-byte executable file in the per-agent
        slot must NOT be used. With `[ -x ] && [ -s ]` the gate
        fails (size==0) and we fall through to the PATH fallback,
        which here finds a valid binary."""
        agent_home = tmp_path / "agents"
        per_agent = agent_home / "x" / ".openclaw" / "bin" / "openclaw"
        per_agent.parent.mkdir(parents=True)
        per_agent.touch()  # zero bytes
        per_agent.chmod(0o755)

        path_dir = tmp_path / "good"
        self._make_fake_openclaw(path_dir / "openclaw")

        script = lc._build_openclaw_version_inner_script(
            "x",
            home_root=str(agent_home),
            path_safelist=(str(path_dir) + "/",),
        )
        result = self._run(script, path_dirs=[path_dir])
        assert result.returncode == 0, result.stderr
        assert "2026.6.8" in result.stdout


class TestLoadOpenclawBravePin:
    """`_load_openclaw_brave_pin` is the single source of truth for the
    plugin pin (npm package, version, min host version). Both
    `lifecycle.configure_agent` and `lifecycle_canonical.sync_agent_canonical`
    consume it; a manifest drift would silently desync the playbook
    install version from the preflight floor. (W2 + W3 ATX iter 1)"""

    def test_loads_pin_from_manifest(self):
        pin = lc._load_openclaw_brave_pin()
        assert pin["npm_package"] == "@openclaw/brave-plugin"
        assert pin["version"] == "2026.6.9"
        assert pin["min_host_version"] == (2026, 6, 9)

    def test_raises_when_pin_block_missing(self, monkeypatch):
        """Manifest with no `plugins.brave` block → hard fail. Never
        let `npm install @openclaw/brave-plugin@` run with an empty
        version under `no_log: true` masking. (W3)"""
        import yaml

        monkeypatch.setattr(
            yaml,
            "safe_load",
            lambda _txt: {"agent": {"type": "openclaw"}},
        )
        with pytest.raises(
            CanonicalSyncError,
            match=r"openclaw manifest is missing plugins\.brave",
        ):
            lc._load_openclaw_brave_pin()

    def test_raises_when_min_host_version_is_invalid(self, monkeypatch):
        """A typo in the manifest (`min_host_version: "not-a-version"`)
        must hard fail, not silently fall back to (0, 0, 0)."""
        import yaml

        monkeypatch.setattr(
            yaml,
            "safe_load",
            lambda _txt: {
                "plugins": {
                    "brave": {
                        "npm_package": "@openclaw/brave-plugin",
                        "version": "2026.6.8",
                        "min_host_version": "not-a-version",
                    }
                }
            },
        )
        with pytest.raises(
            CanonicalSyncError, match=r"not a valid X\.Y\.Z version"
        ):
            lc._load_openclaw_brave_pin()


# ---------------------------------------------------------------------------
# Brave (#734) — playbook dispatch routing (ATX iter 1 B4).
# ---------------------------------------------------------------------------


class TestOpenclawConfigureDispatch:
    """The macOS sibling `configure_macos.yaml` MUST be the file
    selected by `resolve_agent_playbook` for `os_family="darwin"`.
    Without this test a regression renaming the file (or breaking the
    `_macos` suffix convention) would only surface on a real Mac
    host."""

    def test_darwin_routes_to_configure_macos(self):
        from clawrium.core.playbook_resolver import resolve_agent_playbook

        path = resolve_agent_playbook("openclaw", "configure", "darwin")
        assert path.name == "configure_macos.yaml"
        assert path.exists()

    def test_linux_routes_to_configure(self):
        from clawrium.core.playbook_resolver import resolve_agent_playbook

        path = resolve_agent_playbook("openclaw", "configure", "linux")
        assert path.name == "configure.yaml"
        assert path.exists()

    def test_neither_configure_playbook_contains_brave_install_task(self):
        """#755 (T7): brave plugin install was lifted out of both
        configure playbooks into `lifecycle_canonical._openclaw_install_plugins`.
        Configure stays scoped to onboarding stages (providers /
        identity / channels). A regression that reintroduces the
        playbook install would double-install on every configure-then-
        sync cycle and re-create the "sync doesn't install plugins"
        UX gap #755 fixed."""
        from clawrium.core.playbook_resolver import resolve_agent_playbook

        linux = resolve_agent_playbook("openclaw", "configure", "linux")
        darwin = resolve_agent_playbook("openclaw", "configure", "darwin")
        for path in (linux, darwin):
            body = path.read_text()
            assert "openclaw_brave_plugin_package" not in body, path
            assert "openclaw_brave_plugin_version" not in body, path
            assert "brave-plugin-installed" not in body, path
            assert "@openclaw/brave-plugin" not in body, path
            # No Darwin-conditional inside either file (dispatcher-only
            # OS fork — #734 invariant; #755 keeps it).
            assert "ansible_os_family == 'Darwin'" not in body, path
            assert 'ansible_os_family == "Darwin"' not in body, path


# ---------------------------------------------------------------------------
# Openclaw plugin install on sync (#755).
# ---------------------------------------------------------------------------


class _FakeChannel:
    """Minimal stand-in for paramiko's channel object — only the bits
    `_openclaw_install_plugins` reads."""

    def __init__(self, exit_status: int):
        self._exit_status = exit_status

    def recv_exit_status(self) -> int:
        return self._exit_status


class _FakeStream:
    def __init__(self, body: bytes = b"", exit_status: int = 0):
        self._body = body
        self.channel = _FakeChannel(exit_status)

    def read(self) -> bytes:
        return self._body


class _ScriptedSSHClient:
    """Records every `exec_command` call and replays a scripted set of
    `(stdout_body, stderr_body, exit_status)` triples in order. Tests
    that don't care about ordering can rely on the captured `calls`
    list.

    ATX iter-2 W4: both stdout and stderr share the same `_FakeChannel`
    so a future code change that reads `stderr.channel.recv_exit_status()`
    instead of `stdout.channel.recv_exit_status()` does not spuriously
    pass at rc=0. Real paramiko returns a single shared channel for
    both streams."""

    def __init__(self, script: list[tuple[bytes, bytes, int]]):
        self._script = list(script)
        self.calls: list[str] = []

    def exec_command(self, cmd: str, timeout: int | None = None):
        self.calls.append(cmd)
        if not self._script:
            raise AssertionError(
                f"unexpected extra exec_command: {cmd!r}"
            )
        stdout_body, stderr_body, rc = self._script.pop(0)
        shared_channel = _FakeChannel(rc)
        stdout = _FakeStream(stdout_body, rc)
        stderr = _FakeStream(stderr_body, rc)
        stdout.channel = shared_channel
        stderr.channel = shared_channel
        return _FakeStream(), stdout, stderr


def _inputs_with_integrations(types: list[str]):
    """Build a minimal `RenderInputs`-like object — only `.integrations`
    is read by `_openclaw_install_plugins`."""
    from clawrium.core.render import IntegrationInputs

    integrations = tuple(
        IntegrationInputs(name=f"my-{t}", type=t) for t in types
    )
    inputs = MagicMock()
    inputs.integrations = integrations
    return inputs


class TestOpenclawInstallPlugins:
    """#755 T1-T6: lifted plugin install. Drives off the openclaw
    manifest's `plugins:` block; sentinel-gated for idempotency; raises
    `CanonicalSyncError` on any per-host failure so the caller can
    short-circuit before restart."""

    _PIN = {
        "brave": {
            "npm_package": "@openclaw/brave-plugin",
            "version": "2026.6.9",
            "min_host_version": "2026.6.9",
        }
    }

    def _patch_pin(self, monkeypatch, plugins=None):
        monkeypatch.setattr(
            lc,
            "_load_openclaw_plugins",
            lambda: plugins if plugins is not None else self._PIN,
        )

    def test_t1_installs_when_attached_and_missing(self, monkeypatch):
        """T1: brave attached, sentinel absent → `openclaw plugins
        install` is invoked AND sentinel is stamped, in order. The
        install command must use openclaw's own CLI (not raw `npm
        install`) because a raw npm install into `~<agent>/.openclaw/
        node_modules/` is NOT discovered by `openclaw plugins list` —
        UAT on esper-mac-oc proved this is the failure mode that masked
        the pre-#755 playbook approach for the entire #734 lifetime."""
        self._patch_pin(monkeypatch)
        client = _ScriptedSSHClient(
            [
                (b"", b"", 1),  # sentinel probe: absent (test -f exit 1)
                (b"installed", b"", 0),  # openclaw plugins install
                (b"", b"", 0),  # sentinel stamp
            ]
        )
        inputs = _inputs_with_integrations(["brave"])
        installed, skipped = lc._openclaw_install_plugins(
            client,
            "wolf-i",
            os_family="linux",
            inputs=inputs,
        )
        assert installed == ("brave",)
        assert skipped == ()
        install_cmd = client.calls[1]
        # Must use openclaw's own CLI, NOT raw `npm install --prefix`.
        assert "openclaw plugins install" in install_cmd
        assert "npm install --prefix" not in install_cmd
        # --force lets a pin bump overwrite a prior install; --pin
        # records the resolved name@version exactly so a transitive
        # upgrade cannot smuggle in a new floor.
        assert "--force" in install_cmd
        assert "--pin" in install_cmd
        assert "@openclaw/brave-plugin@2026.6.9" in install_cmd
        assert "/home/wolf-i/.openclaw/bin/openclaw" in install_cmd
        # Sentinel path encodes the version so a pin bump auto-fires.
        stamp_cmd = client.calls[2]
        assert ".brave-plugin-installed.2026.6.9" in stamp_cmd

    def test_t2_skips_install_when_sentinel_present(self, monkeypatch):
        """T2: pin matches what's already installed → sentinel probe
        succeeds → no install runs, no further commands."""
        self._patch_pin(monkeypatch)
        client = _ScriptedSSHClient([(b"", b"", 0)])  # sentinel probe: ok
        inputs = _inputs_with_integrations(["brave"])
        installed, skipped = lc._openclaw_install_plugins(
            client,
            "wolf-i",
            os_family="linux",
            inputs=inputs,
        )
        assert installed == ()
        assert skipped == ("brave",)
        # Only the sentinel probe ran — no install, no stamp.
        assert len(client.calls) == 1
        assert "test -f" in client.calls[0]
        assert ".brave-plugin-installed.2026.6.9" in client.calls[0]

    def test_t3_reinstalls_when_pin_version_differs(self, monkeypatch):
        """T3: a pin bump changes the sentinel filename (which encodes
        the version), so the prior-version sentinel no longer matches.
        Probe returns absent → install fires at the new pinned version."""
        self._patch_pin(
            monkeypatch,
            plugins={
                "brave": {
                    "npm_package": "@openclaw/brave-plugin",
                    "version": "2027.1.0",
                    "min_host_version": "2027.1.0",
                }
            },
        )
        client = _ScriptedSSHClient(
            [
                (b"", b"", 1),  # sentinel for 2027.1.0 absent
                (b"installed", b"", 0),  # openclaw plugins install
                (b"", b"", 0),  # sentinel stamp
            ]
        )
        inputs = _inputs_with_integrations(["brave"])
        installed, _ = lc._openclaw_install_plugins(
            client,
            "wolf-i",
            os_family="linux",
            inputs=inputs,
        )
        assert installed == ("brave",)
        install_cmd = client.calls[1]
        assert "@openclaw/brave-plugin@2027.1.0" in install_cmd
        assert "openclaw plugins install" in install_cmd

    def test_t4_does_not_install_when_brave_not_attached(self, monkeypatch):
        """T4: no brave integration → no per-plugin SSH commands fire.
        The helper still consults the manifest but exits with empty
        installed + the manifest key in skipped (the "not attached"
        bucket)."""
        self._patch_pin(monkeypatch)
        client = _ScriptedSSHClient([])  # zero commands expected
        inputs = _inputs_with_integrations([])
        installed, skipped = lc._openclaw_install_plugins(
            client,
            "wolf-i",
            os_family="linux",
            inputs=inputs,
        )
        assert installed == ()
        assert skipped == ("brave",)
        assert client.calls == []

    def test_t5_install_runs_before_restart_via_sync(self, monkeypatch):
        """T5 (ATX iter-2 B1): the install helper MUST run before
        `_restart_unit` inside `sync_agent_canonical`. Iter-1 had a
        vacuous variant that called both functions directly from the
        test body — that proved Python executes consecutive statements
        in order but said nothing about the wiring inside
        `sync_agent_canonical`. This rewrite drives the whole pipeline
        and asserts ordering via spies on the IO surface, so a future
        edit that moves `_openclaw_install_plugins` below
        `_restart_unit` actually fails."""
        from clawrium.core.render import (
            GatewayInputs,
            IntegrationInputs,
            ProviderInputs,
            RenderInputs,
            RenderedFiles,
        )

        order: list[str] = []

        def spy_install(*_a, **_kw):
            order.append("install_plugins")
            return ((), ())

        def spy_restart(*_a, **_kw):
            order.append("restart_unit")

        inputs = RenderInputs(
            agent_name="wolf-i",
            agent_type="openclaw",
            provider=ProviderInputs(
                name="or",
                type="openrouter",
                api_key="sk",
                default_model="m",
            ),
            gateway=GatewayInputs(host="h", port=40000, auth="a"),
            integrations=(
                IntegrationInputs(
                    name="my-brave",
                    type="brave",
                    credentials=(("BRAVE_API_KEY", "bsk"),),
                ),
            ),
        )
        rendered = RenderedFiles(
            files={
                ".openclaw/env": "BRAVE_API_KEY='bsk'\n",
                ".openclaw/openclaw.json": "{}",
            }
        )

        # Force a non-empty write path so `_restart_unit` is reached
        # (sync only restarts when files were written or zeroclaw).
        fake_diff = MagicMock()
        fake_diff.unified_diff = "+x"
        fake_diff.path = ".openclaw/env"
        fake_diff.remote_path = "/home/wolf-i/.openclaw/env"
        fake_diff.rendered_body = "BRAVE_API_KEY='bsk'\n"
        fake_diff.remote_body = ""

        monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
        monkeypatch.setitem(lc._RENDERERS, "openclaw", lambda _: rendered)
        monkeypatch.setattr(
            lc,
            "get_agent_by_name",
            lambda _: ({"hostname": "h"}, "openclaw:wolf-i", {}),
        )
        monkeypatch.setattr(lc, "diff_files", lambda **_: [fake_diff])
        monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())
        monkeypatch.setattr(
            lc,
            "_get_host_openclaw_version",
            lambda *_a, **_kw: ((2026, 6, 9), ""),
        )
        monkeypatch.setattr(
            lc, "_diff_removes_secrets", lambda _d: set()
        )
        monkeypatch.setattr(lc, "_atomic_write", lambda *_a, **_kw: None)
        monkeypatch.setattr(lc, "_openclaw_install_plugins", spy_install)
        monkeypatch.setattr(lc, "_restart_unit", spy_restart)
        monkeypatch.setattr(lc, "_verify_health", lambda **_: None)
        # workspace_sync push: stub at import site
        monkeypatch.setattr(
            "clawrium.core.workspace_sync.push_workspace_phase",
            lambda **_kw: MagicMock(
                success=True, files_pushed=(), files_excluded=(), error=None
            ),
        )

        sync_agent_canonical("wolf-i", verify=False)
        assert order == ["install_plugins", "restart_unit"]

    def test_install_failure_short_circuits_before_restart(
        self, monkeypatch
    ):
        """Companion to T5: when `_openclaw_install_plugins` raises,
        `_restart_unit` MUST NOT run. The agent is never restarted on
        a half-installed plugin set — mirrors the workspace-overlay
        contract."""
        from clawrium.core.render import (
            GatewayInputs,
            IntegrationInputs,
            ProviderInputs,
            RenderInputs,
            RenderedFiles,
        )

        restart_called: list[bool] = []

        def boom_install(*_a, **_kw):
            raise CanonicalSyncError("plugin install boom")

        def spy_restart(*_a, **_kw):
            restart_called.append(True)

        inputs = RenderInputs(
            agent_name="wolf-i",
            agent_type="openclaw",
            provider=ProviderInputs(
                name="or",
                type="openrouter",
                api_key="sk",
                default_model="m",
            ),
            gateway=GatewayInputs(host="h", port=40000, auth="a"),
            integrations=(
                IntegrationInputs(
                    name="my-brave",
                    type="brave",
                    credentials=(("BRAVE_API_KEY", "bsk"),),
                ),
            ),
        )
        rendered = RenderedFiles(
            files={".openclaw/env": "BRAVE_API_KEY='bsk'\n"}
        )

        monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
        monkeypatch.setitem(lc._RENDERERS, "openclaw", lambda _: rendered)
        monkeypatch.setattr(
            lc,
            "get_agent_by_name",
            lambda _: ({"hostname": "h"}, "openclaw:wolf-i", {}),
        )
        monkeypatch.setattr(lc, "diff_files", lambda **_: [])
        monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())
        monkeypatch.setattr(
            lc,
            "_get_host_openclaw_version",
            lambda *_a, **_kw: ((2026, 6, 9), ""),
        )
        monkeypatch.setattr(lc, "_openclaw_install_plugins", boom_install)
        monkeypatch.setattr(lc, "_restart_unit", spy_restart)

        with pytest.raises(CanonicalSyncError, match=r"plugin install boom"):
            sync_agent_canonical("wolf-i", verify=False)
        assert restart_called == []

    def test_stamp_failure_after_successful_install_raises(
        self, monkeypatch
    ):
        """ATX iter-2 B2: the sentinel-stamp failure branch had zero
        coverage in iter-1. Distinct from install-failure: at this
        point the plugin IS installed; the only fallout is that a
        future sync will re-install. Surfacing as
        `CanonicalSyncError` (vs swallow + warn) is deliberate so the
        operator investigates the FS / perms regression immediately
        rather than seeing silent re-installs forever."""
        self._patch_pin(monkeypatch)
        client = _ScriptedSSHClient(
            [
                (b"", b"", 1),  # sentinel probe: absent
                (b"installed", b"", 0),  # openclaw install OK
                (
                    b"",
                    b"touch: EACCES /home/wolf-i/.openclaw",
                    1,
                ),  # stamp fails
            ]
        )
        inputs = _inputs_with_integrations(["brave"])
        with pytest.raises(CanonicalSyncError) as excinfo:
            lc._openclaw_install_plugins(
                client,
                "wolf-i",
                os_family="linux",
                inputs=inputs,
            )
        msg = str(excinfo.value)
        assert "sentinel stamp" in msg
        assert ".brave-plugin-installed.2026.6.9" in msg
        assert "EACCES" in msg
        # The plugin was installed, so the install command did run
        # before the stamp step.
        assert "openclaw plugins install" in client.calls[1]

    def test_t6_propagates_install_failure_with_pkg_and_stderr(
        self, monkeypatch
    ):
        """T6: a non-zero install raises CanonicalSyncError whose
        message names both the npm package and the captured stderr —
        the operator's actionable signal."""
        self._patch_pin(monkeypatch)
        client = _ScriptedSSHClient(
            [
                (b"", b"", 1),  # sentinel absent
                (b"", b"E403 forbidden", 1),  # openclaw install failure
            ]
        )
        inputs = _inputs_with_integrations(["brave"])
        with pytest.raises(CanonicalSyncError) as excinfo:
            lc._openclaw_install_plugins(
                client,
                "wolf-i",
                os_family="linux",
                inputs=inputs,
            )
        msg = str(excinfo.value)
        assert "@openclaw/brave-plugin@2026.6.9" in msg
        assert "E403 forbidden" in msg

    def test_macos_uses_users_home_root(self, monkeypatch):
        """OS-family dispatch: darwin → `/Users/<n>/.openclaw`. The
        mapping flows through `home_root_for` so the no-OS-literal
        invariant (#770) holds inside this helper."""
        self._patch_pin(monkeypatch)
        client = _ScriptedSSHClient(
            [
                (b"", b"", 1),  # sentinel absent
                (b"installed", b"", 0),  # openclaw install
                (b"", b"", 0),  # sentinel stamp
            ]
        )
        inputs = _inputs_with_integrations(["brave"])
        lc._openclaw_install_plugins(
            client,
            "wolf-i",
            os_family="darwin",
            inputs=inputs,
        )
        joined = " ".join(client.calls)
        assert "/Users/wolf-i/.openclaw/bin/openclaw" in joined
        assert "/home/wolf-i/.openclaw" not in joined

    def test_manifest_missing_npm_package_raises(self, monkeypatch):
        """Defensive: a malformed plugin spec must hard fail at the
        Python boundary, not silently invoke `npm install @<empty>@<v>`
        on the host."""
        self._patch_pin(
            monkeypatch,
            plugins={"brave": {"version": "2026.6.9"}},
        )
        client = _ScriptedSSHClient([])
        inputs = _inputs_with_integrations(["brave"])
        with pytest.raises(
            CanonicalSyncError,
            match=r"missing npm_package or version",
        ):
            lc._openclaw_install_plugins(
                client,
                "wolf-i",
                os_family="linux",
                inputs=inputs,
            )


class TestLoadOpenclawPlugins:
    """#755: the full-block loader is the manifest seam for the generic
    install helper. Mirrors `_load_openclaw_brave_pin`'s hard-fail
    discipline."""

    def test_loads_full_block(self):
        plugins = lc._load_openclaw_plugins()
        assert "brave" in plugins
        assert plugins["brave"]["npm_package"] == "@openclaw/brave-plugin"

    def test_empty_block_returns_empty_dict(self, monkeypatch):
        import yaml

        monkeypatch.setattr(yaml, "safe_load", lambda _txt: {})
        assert lc._load_openclaw_plugins() == {}

    def test_malformed_block_raises(self, monkeypatch):
        import yaml

        monkeypatch.setattr(
            yaml, "safe_load", lambda _txt: {"plugins": "not-a-mapping"}
        )
        with pytest.raises(
            CanonicalSyncError, match=r"not a mapping"
        ):
            lc._load_openclaw_plugins()


# ---------------------------------------------------------------------------
# #811: probe_host_install + AgentInstallMissingError + sync validate-phase
# ---------------------------------------------------------------------------


class _FakeSSHExec:
    """A minimal paramiko-shaped stand-in that records the last exec_command
    call and returns a stdout body the probe can parse."""

    def __init__(self, body: str):
        self._body = body
        self.last_cmd: str | None = None

    def exec_command(self, cmd, timeout=None):  # noqa: D401
        self.last_cmd = cmd

        class _C:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body.encode("utf-8")

        return None, _C(self._body), _C("")


@pytest.mark.no_probe_stub
class TestProbeHostInstall:
    def test_both_present_linux(self):
        client = _FakeSSHExec("unit:1\nhome:1\n")
        host = {"hostname": "h", "os_family": "linux"}
        from clawrium.core.lifecycle_canonical import probe_host_install as _probe
        result = _probe(
            client,
            agent_type="zeroclaw",
            agent_name="alpha",
            host=host,
        )
        assert result.ok is True
        assert result.unit_present is True
        assert result.home_present is True
        assert result.unit_path == "/etc/systemd/system/zeroclaw-alpha.service"
        assert result.home_path == "/home/alpha/.zeroclaw"
        assert result.missing_summary() == ""
        # The probe used the dispatcher-resolved paths, not hard-coded literals.
        assert "/etc/systemd/system/zeroclaw-alpha.service" in client.last_cmd
        assert "/home/alpha/.zeroclaw" in client.last_cmd

    def test_unit_missing_only(self):
        client = _FakeSSHExec("unit:0\nhome:1\n")
        from clawrium.core.lifecycle_canonical import probe_host_install as _probe
        result = _probe(
            client,
            agent_type="zeroclaw",
            agent_name="alpha",
            host={"hostname": "h", "os_family": "linux"},
        )
        assert result.ok is False
        assert result.unit_present is False
        assert result.home_present is True
        assert "service unit" in result.missing_summary()
        assert "agent home" not in result.missing_summary()

    def test_home_missing_only(self):
        client = _FakeSSHExec("unit:1\nhome:0\n")
        from clawrium.core.lifecycle_canonical import probe_host_install as _probe
        result = _probe(
            client,
            agent_type="hermes",
            agent_name="alpha",
            host={"hostname": "h", "os_family": "linux"},
        )
        assert result.ok is False
        assert "agent home" in result.missing_summary()
        assert "service unit" not in result.missing_summary()

    def test_both_missing_lists_both(self):
        client = _FakeSSHExec("unit:0\nhome:0\n")
        from clawrium.core.lifecycle_canonical import probe_host_install as _probe
        result = _probe(
            client,
            agent_type="zeroclaw",
            agent_name="alpha",
            host={"hostname": "h", "os_family": "linux"},
        )
        assert result.ok is False
        summary = result.missing_summary()
        assert "service unit" in summary
        assert "agent home" in summary

    def test_macos_uses_plist_path(self):
        client = _FakeSSHExec("unit:1\nhome:1\n")
        from clawrium.core.lifecycle_canonical import probe_host_install as _probe
        result = _probe(
            client,
            agent_type="hermes",
            agent_name="alpha",
            host={"hostname": "h", "os_family": "darwin"},
        )
        assert result.unit_path.startswith("/Library/LaunchDaemons/")
        assert result.unit_path.endswith(".plist")
        assert result.home_path == "/Users/alpha/.hermes"
        # Probe command actually referenced the plist + Users home.
        assert "/Library/LaunchDaemons/" in client.last_cmd
        assert "/Users/alpha/.hermes" in client.last_cmd

    def test_malformed_output_raises_canonical_sync_error(self):
        """ATX iter-1 B1: an unparseable response MUST raise
        `CanonicalSyncError` rather than fabricate "both missing"
        (which would fire `AgentInstallMissingError` against a
        healthy host whose probe transiently blipped). See the
        `TestProbeHostInstallFailureModes` block below for the
        full failure-mode matrix."""
        from clawrium.core.lifecycle_canonical import (
            CanonicalSyncError,
            probe_host_install as _probe,
        )

        client = _FakeSSHExec("garbage\nnotaprobeoutput\n")
        with pytest.raises(CanonicalSyncError, match="unparseable output"):
            _probe(
                client,
                agent_type="zeroclaw",
                agent_name="alpha",
                host={"hostname": "h", "os_family": "linux"},
            )


class TestSyncValidatePhaseProbe:
    def _make_probe(self, *, unit: bool, home: bool, agent_type: str = "zeroclaw"):
        # Pre-resolve paths so the stub returns the same shape the real
        # helper would.
        from clawrium.core.playbook_resolver import home_root_for, unit_path_for

        return lc.HostInstallProbe(
            unit_present=unit,
            home_present=home,
            unit_path=unit_path_for("linux", agent_type, "alpha"),
            home_path=f"{home_root_for('linux')}/alpha/.{agent_type}",
        )

    def test_probe_failure_short_circuits_before_render(self, monkeypatch):
        events, _ = _stub_sync_environment(monkeypatch, agent_type="zeroclaw")
        # Force probe failure: unit missing.
        monkeypatch.setattr(
            lc,
            "probe_host_install",
            lambda *_a, **_kw: self._make_probe(unit=False, home=True),
        )
        # Sentinel: renderer must NEVER be called.
        renderer_called = {"count": 0}

        def _sentinel_renderer(_inputs):
            renderer_called["count"] += 1
            raise AssertionError("renderer must not run when probe fails")

        monkeypatch.setitem(lc._RENDERERS, "zeroclaw", _sentinel_renderer)
        # diff_files must also not run.
        diff_called = {"count": 0}

        def _sentinel_diff(**_kw):
            diff_called["count"] += 1
            raise AssertionError("diff_files must not run when probe fails")

        monkeypatch.setattr(lc, "diff_files", _sentinel_diff)
        with pytest.raises(lc.AgentInstallMissingError) as excinfo:
            sync_agent_canonical(
                "alpha",
                restart=False,
                verify=False,
                on_event=lambda s, m: events.append((s, m)),
            )
        msg = str(excinfo.value)
        assert "zeroclaw-alpha.service" in msg
        # ATX iter-5 B1: there is no `clawctl agent install` verb;
        # the repair hint points at `delete` + `create` (the real
        # reinstall flow) and `doctor` (for diagnosis).
        assert "clawctl agent delete alpha" in msg
        assert "clawctl agent create alpha" in msg
        assert "clawctl agent doctor alpha" in msg
        # Regression guard against the iter-5 B1 bug.
        assert "clawctl agent install" not in msg
        # The validate emit fired.
        assert any(
            s == "validate" and "checking host install" in m for s, m in events
        )
        assert renderer_called["count"] == 0
        assert diff_called["count"] == 0

    def test_probe_failure_with_home_missing_names_home(self, monkeypatch):
        events, _ = _stub_sync_environment(monkeypatch, agent_type="zeroclaw")
        monkeypatch.setattr(
            lc,
            "probe_host_install",
            lambda *_a, **_kw: self._make_probe(unit=True, home=False),
        )
        with pytest.raises(lc.AgentInstallMissingError) as excinfo:
            sync_agent_canonical("alpha", restart=False, verify=False,
                                 on_event=lambda s, m: events.append((s, m)))
        assert "/home/alpha/.zeroclaw" in str(excinfo.value)

    def test_probe_failure_lists_both_missing_artifacts(self, monkeypatch):
        events, _ = _stub_sync_environment(monkeypatch, agent_type="zeroclaw")
        monkeypatch.setattr(
            lc,
            "probe_host_install",
            lambda *_a, **_kw: self._make_probe(unit=False, home=False),
        )
        with pytest.raises(lc.AgentInstallMissingError) as excinfo:
            sync_agent_canonical("alpha", restart=False, verify=False,
                                 on_event=lambda s, m: events.append((s, m)))
        msg = str(excinfo.value)
        assert "zeroclaw-alpha.service" in msg
        assert "/home/alpha/.zeroclaw" in msg

    def test_probe_failure_blocks_workspace_only_sync(self, monkeypatch):
        """A `--workspace-only` sync must also short-circuit before the
        overlay push and before the zeroclaw bearer rotation."""
        events, _ = _stub_sync_environment(monkeypatch, agent_type="zeroclaw")
        monkeypatch.setattr(
            lc,
            "probe_host_install",
            lambda *_a, **_kw: self._make_probe(unit=False, home=True),
        )
        # Sentinels: neither overlay push nor zeroclaw repair may run.
        from clawrium.core import workspace_sync, lifecycle

        def _sentinel_push(**_kw):
            raise AssertionError("overlay push must not run when probe fails")

        def _sentinel_repair(*_a, **_kw):
            raise AssertionError("zeroclaw repair must not run when probe fails")

        monkeypatch.setattr(
            workspace_sync, "push_workspace_phase", _sentinel_push
        )
        monkeypatch.setattr(
            lifecycle, "_zeroclaw_repair_after_start", _sentinel_repair
        )
        with pytest.raises(lc.AgentInstallMissingError):
            sync_agent_canonical(
                "alpha",
                restart=False,
                verify=False,
                workspace_only=True,
                on_event=lambda s, m: events.append((s, m)),
            )

    def test_probe_pass_proceeds_normally(self, monkeypatch):
        """When the probe reports both artifacts present, sync must
        continue through render/diff/write/restart as it did before
        the validate-phase was introduced. Guards against the probe
        becoming a regression on the happy path."""
        events, _ = _stub_sync_environment(monkeypatch, agent_type="hermes")
        monkeypatch.setattr(
            "clawrium.core.onboarding.transition_state",
            lambda *a, **kw: None,
        )
        result = sync_agent_canonical(
            "alpha",
            restart=True,
            verify=False,
            on_event=lambda s, m: events.append((s, m)),
        )
        assert result.success
        # `write` stage fired — proves we got past validate.
        assert any(s == "write" for s, _ in events)


# ---------------------------------------------------------------------------
# #811 ATX iter-1 follow-ups: B1/B2/B3 + W5 + S4/S8 coverage on the probe.
# ---------------------------------------------------------------------------


@pytest.mark.no_probe_stub
class TestProbeHostInstallFailureModes:
    """Failure-mode discipline — every non-happy code path."""

    def test_unparseable_output_raises_canonical_sync_error(self):
        """ATX iter-1 B1: empty / garbage stdout MUST raise
        `CanonicalSyncError` rather than silently report "both
        missing" (which would fire `AgentInstallMissingError`
        against a healthy host)."""
        from clawrium.core.lifecycle_canonical import (
            CanonicalSyncError,
            probe_host_install,
        )

        client = _FakeSSHExec("totally not the probe output\n")
        with pytest.raises(
            CanonicalSyncError, match="unparseable output"
        ):
            probe_host_install(
                client,
                agent_type="zeroclaw",
                agent_name="alpha",
                host={"hostname": "h", "os_family": "linux"},
            )

    def test_sshexception_wrapped_in_canonical_sync_error(self):
        """ATX iter-1 B2: paramiko `SSHException` from `exec_command`
        is wrapped in `CanonicalSyncError`, not propagated raw."""
        import paramiko

        from clawrium.core.lifecycle_canonical import (
            CanonicalSyncError,
            probe_host_install,
        )

        class _Boom:
            def exec_command(self, _cmd, timeout=None):
                raise paramiko.SSHException("session lost")

        with pytest.raises(
            CanonicalSyncError, match="transport failure"
        ):
            probe_host_install(
                _Boom(),
                agent_type="zeroclaw",
                agent_name="alpha",
                host={"hostname": "h", "os_family": "linux"},
            )

    def test_oserror_wrapped_in_canonical_sync_error(self):
        """ATX iter-1 B2: `OSError` (network reset, broken pipe) wraps too."""
        from clawrium.core.lifecycle_canonical import (
            CanonicalSyncError,
            probe_host_install,
        )

        class _Broken:
            def exec_command(self, _cmd, timeout=None):
                raise OSError("connection reset by peer")

        with pytest.raises(
            CanonicalSyncError, match="transport failure"
        ):
            probe_host_install(
                _Broken(),
                agent_type="zeroclaw",
                agent_name="alpha",
                host={"hostname": "h", "os_family": "linux"},
            )

    def test_zeroclaw_on_darwin_raises_canonical_sync_error(self):
        """ATX iter-1 B3: `unit_path_for("darwin", "zeroclaw", ...)` raises
        `ValueError` (no plist convention). The probe wraps it in
        `CanonicalSyncError` so a malformed hosts.json row gets an
        operator-readable error instead of an opaque traceback."""
        from clawrium.core.lifecycle_canonical import (
            CanonicalSyncError,
            probe_host_install,
        )

        client = _FakeSSHExec("ignored")
        with pytest.raises(
            CanonicalSyncError, match="no service-manager artifact convention"
        ):
            probe_host_install(
                client,
                agent_type="zeroclaw",
                agent_name="alpha",
                host={"hostname": "h", "os_family": "darwin"},
            )

    def test_sudo_refusal_raises_distinct_canonical_sync_error(self):
        """ATX iter-1 W1: sudo -n stderr matches a refusal pattern
        AND home_present=False → distinct CanonicalSyncError
        (not AgentInstallMissingError, not a silent mis-flag)."""
        from clawrium.core.lifecycle_canonical import (
            CanonicalSyncError,
            probe_host_install,
        )

        class _SudoDenied:
            def exec_command(self, _cmd, timeout=None):
                class _C:
                    def __init__(self, body):
                        self._body = body

                    def read(self):
                        return self._body.encode("utf-8")

                # Unit present, home failed because sudo refused.
                return (
                    None,
                    _C("unit:1\nhome:0\n"),
                    _C(
                        "sudo: a password is required\n"
                    ),
                )

        with pytest.raises(CanonicalSyncError, match="sudo refused"):
            probe_host_install(
                _SudoDenied(),
                agent_type="zeroclaw",
                agent_name="alpha",
                host={"hostname": "h", "os_family": "linux"},
            )

    def test_probe_command_uses_sudo_n_for_home(self):
        """ATX iter-1 S4: regression guard — without `sudo -n` the
        probe falsely reports the home dir missing on every healthy
        Linux agent (the bug found during wolf-i UAT)."""
        from clawrium.core.lifecycle_canonical import probe_host_install

        client = _FakeSSHExec("unit:1\nhome:1\n")
        probe_host_install(
            client,
            agent_type="zeroclaw",
            agent_name="alpha",
            host={"hostname": "h", "os_family": "linux"},
        )
        assert "sudo -n test -d" in client.last_cmd

    def test_probe_openclaw_linux_path(self):
        """ATX iter-1 S8: openclaw was previously unexercised at the
        probe level. Cover both that the dispatcher resolves the
        right unit path and that the probe shells the right home
        dir for openclaw."""
        from clawrium.core.lifecycle_canonical import probe_host_install

        client = _FakeSSHExec("unit:1\nhome:1\n")
        r = probe_host_install(
            client,
            agent_type="openclaw",
            agent_name="oc1",
            host={"hostname": "h", "os_family": "linux"},
        )
        assert r.unit_path == "/etc/systemd/system/openclaw-oc1.service"
        assert r.home_path == "/home/oc1/.openclaw"
        assert "/etc/systemd/system/openclaw-oc1.service" in client.last_cmd
        assert "/home/oc1/.openclaw" in client.last_cmd

    def test_probe_openclaw_darwin_uses_plist(self):
        """ATX iter-1 W7: openclaw-on-darwin should resolve through
        the launchd plist convention, not raise."""
        from clawrium.core.lifecycle_canonical import probe_host_install

        client = _FakeSSHExec("unit:1\nhome:1\n")
        r = probe_host_install(
            client,
            agent_type="openclaw",
            agent_name="oc1",
            host={"hostname": "h", "os_family": "darwin"},
        )
        assert r.unit_path.startswith("/Library/LaunchDaemons/")
        assert r.unit_path.endswith(".plist")
        assert r.home_path == "/Users/oc1/.openclaw"


def test_sync_dry_run_with_probe_failure_still_short_circuits(monkeypatch):
    """ATX iter-1 W5: dry-run must pay the probe cost — a dry-run
    that "would change N files" against a missing daemon is
    misleading. Probe failure short-circuits even on dry-run."""
    events, _ = _stub_sync_environment(monkeypatch, agent_type="zeroclaw")
    monkeypatch.setattr(
        lc,
        "probe_host_install",
        lambda *_a, **_kw: lc.HostInstallProbe(
            unit_present=False,
            home_present=True,
            unit_path="/etc/systemd/system/zeroclaw-alpha.service",
            home_path="/home/alpha/.zeroclaw",
        ),
    )
    with pytest.raises(lc.AgentInstallMissingError):
        sync_agent_canonical(
            "alpha",
            restart=False,
            verify=False,
            dry_run=True,
            on_event=lambda s, m: events.append((s, m)),
        )


class TestParseProbeOutput:
    """Direct coverage on the shared parser (ATX iter-1 S1)."""

    def test_recognizes_both_keys(self):
        from clawrium.core.lifecycle_canonical import _parse_probe_output

        parsed, unit, home = _parse_probe_output("unit:1\nhome:0\n")
        assert parsed is True
        assert unit is True
        assert home is False

    def test_partial_input_still_parsed(self):
        """Only the `unit` key present — parsed=True, home defaults False."""
        from clawrium.core.lifecycle_canonical import _parse_probe_output

        parsed, unit, home = _parse_probe_output("unit:1\n")
        assert parsed is True
        assert unit is True
        assert home is False

    def test_empty_body_parsed_false(self):
        from clawrium.core.lifecycle_canonical import _parse_probe_output

        parsed, unit, home = _parse_probe_output("")
        assert parsed is False
        assert unit is False
        assert home is False

    def test_garbage_parsed_false(self):
        from clawrium.core.lifecycle_canonical import _parse_probe_output

        parsed, _u, _h = _parse_probe_output("nope\nnothing\n")
        assert parsed is False


# ---------------------------------------------------------------------------
# #811 ATX iter-2: pattern + helper direct coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stderr",
    [
        "sudo: a password is required",
        # ATX iter-3 W6: isolated coverage for the bare "password
        # is required" pattern; the entry above doubles up with
        # "a password is required" so the parametrize matrix
        # previously left this entry only transitively exercised.
        "sudo: password is required to access this resource",
        "Sorry, user xclm is not allowed to execute '/usr/bin/test' as root on h.",
        "Sorry, xclm is not allowed to run sudo on h.",
        "xclm is not in the sudoers file. This incident will be reported.",
        # ATX iter-4 B1: isolated coverage for the "incident will
        # be reported" pattern — the entry above doubles up with
        # "not in the sudoers" so removing pattern 7 from the
        # tuple would otherwise still leave the matrix green.
        "sudo: this incident will be reported to the administrator.",
        "xclm may not run sudo on h.",
        "sudo: no tty present and no askpass program specified",
        "sudo: a terminal is required to read the password",
        # ATX iter-4 W7: sudo binary missing entirely.
        "bash: sudo: command not found",
    ],
)
def test_looks_like_sudo_refusal_matches_each_pattern(stderr):
    """ATX iter-2 W4: every documented pattern in
    `_SUDO_REFUSAL_PATTERNS` must be detected. Without this
    parametrized guard, a regression that drops a pattern goes
    undetected by the existing single-sample test."""
    from clawrium.core.lifecycle_canonical import _looks_like_sudo_refusal

    assert _looks_like_sudo_refusal(stderr), stderr


def test_looks_like_sudo_refusal_does_not_match_benign_stderr():
    """The pattern list MUST NOT match arbitrary stderr — e.g.
    a probe whose stderr contains shell traces, SSH MOTD, or
    unrelated warnings should not trip the sudo-refusal branch."""
    from clawrium.core.lifecycle_canonical import _looks_like_sudo_refusal

    assert not _looks_like_sudo_refusal("warning: unrelated noise")
    assert not _looks_like_sudo_refusal("")
    assert not _looks_like_sudo_refusal(
        "ssh: connect to host x: connection refused"
    )


@pytest.mark.parametrize(
    "os_family,agent_type,agent_name,expected",
    [
        ("linux", "zeroclaw", "alpha", "/home/alpha/.zeroclaw"),
        ("linux", "hermes", "bob", "/home/bob/.hermes"),
        ("linux", "openclaw", "oc1", "/home/oc1/.openclaw"),
        ("darwin", "hermes", "mac1", "/Users/mac1/.hermes"),
        ("darwin", "openclaw", "mac2", "/Users/mac2/.openclaw"),
    ],
)
def test_agent_home_path_matrix(os_family, agent_type, agent_name, expected):
    """ATX iter-2 S4: direct coverage on the home-path helper.
    Previously only exercised transitively through probe tests."""
    from clawrium.core.lifecycle_canonical import _agent_home_path

    assert _agent_home_path(os_family, agent_type, agent_name) == expected


def test_build_probe_command_includes_lc_all_c():
    """ATX iter-2 W1: locale stability. `LC_ALL=C` must be exported
    so sudo's refusal banner stays in English regardless of host
    locale."""
    from clawrium.core.lifecycle_canonical import _build_probe_command

    cmd = _build_probe_command(
        "/etc/systemd/system/zeroclaw-a.service", "/home/a/.zeroclaw"
    )
    assert "LC_ALL=C" in cmd


class TestSyncRefusesIncompleteInstall:
    """Issue #810: `sync_agent_canonical` must short-circuit when the
    agent record reflects an incomplete `clawctl agent create` (status
    in {failed, installing}, or a status-bearing record without an
    `installed_at` timestamp). Without this guard the brave version-gate
    (and other downstream checks) run against a known-broken host and
    surface a misleading "Run `clawctl agent upgrade`" hint that itself
    trips the `clawctl_upgrade_strips_attachments` class — forcing
    operators to manually detach integrations to recover."""

    def _setup(self, monkeypatch, claw_record):
        from clawrium.core.render import (
            GatewayInputs,
            ProviderInputs,
            RenderInputs,
            RenderedFiles,
        )

        inputs = RenderInputs(
            agent_name="oc",
            agent_type="openclaw",
            provider=ProviderInputs(
                name="or",
                type="openrouter",
                api_key="sk",
                default_model="m",
            ),
            gateway=GatewayInputs(host="h", port=40000, auth="a"),
            integrations=(),
        )
        monkeypatch.setattr(lc, "build_render_inputs", lambda _: inputs)
        rendered = RenderedFiles(files={".openclaw/openclaw.json": "{}"})
        monkeypatch.setitem(lc._RENDERERS, "openclaw", lambda _: rendered)
        monkeypatch.setattr(
            lc,
            "get_agent_by_name",
            lambda _: ({"hostname": "h"}, "openclaw:oc", claw_record),
        )
        # If the guard does NOT short-circuit, these stubs let the
        # rest of the pipeline reach a clean exit so a regression
        # surfaces as "no raise" rather than as a SSH/diff KeyError.
        monkeypatch.setattr(lc, "diff_files", lambda **_: [])
        monkeypatch.setattr(lc, "_open_ssh", lambda _h, **__: MagicMock())
        monkeypatch.setattr(
            lc, "_openclaw_install_plugins", lambda *_a, **_kw: ((), ())
        )
        # ATX review W8: stub `push_workspace_phase` so the clean-record
        # path reaches a deterministic return value instead of bubbling
        # an unrelated workspace-sync failure that could mask the
        # negative-guard assertion.
        from clawrium.core import workspace_sync as _ws

        def _ok_phase(**_kw):
            return _ws.WorkspacePhaseResult(
                success=True,
                files_pushed=(),
                files_excluded=(),
            )

        monkeypatch.setattr(
            "clawrium.core.workspace_sync.push_workspace_phase",
            _ok_phase,
        )
        # ATX iter-2 W2: also stub the post-write state-transition
        # so the result reaches `success=True` deterministically.
        # `sync_agent_canonical` calls `transition_state(...,
        # OnboardingState.READY)` near the end; without a stub it
        # raises `AgentNotFoundError` against the empty fake
        # hosts.json and sets `success=False` (the "registration ...
        # Inspect hosts.json" error string).
        monkeypatch.setattr(
            "clawrium.core.onboarding.transition_state",
            lambda *_a, **_kw: True,
        )

    def test_status_failed_raises(self, monkeypatch):
        self._setup(
            monkeypatch,
            {"status": "failed", "installed_at": None},
        )
        with pytest.raises(
            CanonicalSyncError,
            match=r"incomplete installation.*clawctl agent create.*--cleanup-failed",
        ) as exc:
            sync_agent_canonical("oc", restart=False, verify=False)
        msg = str(exc.value)
        # The misleading `agent upgrade` hint MUST NOT appear — that's
        # the whole point of the guard.
        assert "upgrade" not in msg
        # Operator reassurance: attachments are preserved across the
        # refusal (we don't want them preemptively detaching).
        assert "attachments are preserved" in msg

    def test_status_installing_raises(self, monkeypatch):
        self._setup(
            monkeypatch,
            {"status": "installing", "installed_at": None},
        )
        with pytest.raises(
            CanonicalSyncError,
            match=r"status='installing'",
        ):
            sync_agent_canonical("oc", restart=False, verify=False)

    def test_status_installed_no_timestamp_raises(self, monkeypatch):
        """Mirrors the install.py:186 "corrupt state" branch: a record
        carries a status but never finished setting `installed_at`. Treat
        it as incomplete."""
        self._setup(
            monkeypatch,
            {"status": "installed", "installed_at": None},
        )
        with pytest.raises(CanonicalSyncError, match=r"incomplete installation"):
            sync_agent_canonical("oc", restart=False, verify=False)

    def test_clean_record_passes_guard(self, monkeypatch):
        """A complete install record must NOT trigger the new guard.
        ATX iter-2 W2: assert the pipeline returns a green result, not
        just "no incomplete-install error" — the negative-only form
        could pass silently on an unrelated downstream failure."""
        self._setup(
            monkeypatch,
            {"status": "installed", "installed_at": "2026-06-19T20:34:07Z"},
        )
        result = sync_agent_canonical("oc", restart=False, verify=False)
        assert result.success is True

    def test_empty_record_passes_guard(self, monkeypatch):
        """Regression guard: every existing test in this file uses an
        empty `_claw_record={}` mock. The new precondition MUST NOT fire
        on those — `status is None` short-circuits the second clause.
        Same iter-2 W2 stricture: assert success, don't just exclude
        the new error string."""
        self._setup(monkeypatch, {})
        result = sync_agent_canonical("oc", restart=False, verify=False)
        assert result.success is True

    def test_workspace_only_also_refused(self, monkeypatch):
        """`--workspace-only` is just another sync entry point and is
        bound by the same precondition. Writing operator overlay onto a
        half-installed daemon makes recovery harder, not easier."""
        self._setup(
            monkeypatch,
            {"status": "failed", "installed_at": None},
        )
        with pytest.raises(CanonicalSyncError, match=r"incomplete installation"):
            sync_agent_canonical(
                "oc", restart=False, verify=False, workspace_only=True
            )


# ---------------------------------------------------------------------------
# #834: Hermes Slack MCP install at sync time.
# ---------------------------------------------------------------------------


class TestHermesInstallSlackMCP:
    """`_hermes_install_slack_mcp` mirrors `_openclaw_install_plugins`:
    dedicated single-purpose runbook, invoked from the sync pipeline
    before the file-write loop, raises `CanonicalSyncError` on failure
    so the daemon never restarts on a half-installed integration.
    Contract lives in AGENTS.md §"Integration Binary Install"."""

    def _stub_playbook(self, monkeypatch, *, success=True, err=None):
        """Monkey-patch `_run_lifecycle_playbook` to capture the
        (agent_type, operation) tuple it was invoked with and return a
        canned success/failure pair — sidesteps ansible-runner and SSH."""
        calls: list[dict] = []

        def _fake(
            agent_type,
            agent_name,
            hostname,
            operation,
            host,
            timeout=60,
        ):
            calls.append(
                {
                    "agent_type": agent_type,
                    "agent_name": agent_name,
                    "hostname": hostname,
                    "operation": operation,
                    "host": host,
                    "timeout": timeout,
                }
            )
            return success, err

        monkeypatch.setattr(
            "clawrium.core.lifecycle._run_lifecycle_playbook", _fake
        )
        return calls

    def test_no_slack_integration_is_noop(self, monkeypatch):
        """Gate: helper must not touch ansible-runner (no SSH, no
        playbook spawn) when the agent has no slack integration
        attached. Fast path — every non-slack sync would otherwise pay
        the ansible-runner cold-start cost."""
        calls = self._stub_playbook(monkeypatch)
        inputs = _inputs_with_integrations(["github", "atlassian"])

        lc._hermes_install_slack_mcp(
            "maurice", "wolf-i", {"os_family": "linux"}, inputs
        )
        assert calls == []

    def test_slack_user_triggers_linux_runbook(self, monkeypatch):
        """slack-user attached on a linux host → the Linux runbook is
        picked (not the darwin sibling). Agent_type argument is
        `"hermes"` — the runbook lives under `hermes/playbooks/`."""
        calls = self._stub_playbook(monkeypatch)
        inputs = _inputs_with_integrations(["slack-user"])

        lc._hermes_install_slack_mcp(
            "maurice", "wolf-i", {"os_family": "linux"}, inputs
        )
        assert len(calls) == 1
        assert calls[0]["agent_type"] == "hermes"
        assert calls[0]["operation"] == "install_slack_mcp"
        assert calls[0]["agent_name"] == "maurice"
        assert calls[0]["hostname"] == "wolf-i"

    def test_slack_cookie_also_triggers_install(self, monkeypatch):
        """The gate covers BOTH slack-user and slack-cookie. A future
        refactor that only checked `slack-user` would silently skip
        cookie-mode installs."""
        calls = self._stub_playbook(monkeypatch)
        inputs = _inputs_with_integrations(["slack-cookie"])

        lc._hermes_install_slack_mcp(
            "maurice", "wolf-i", {"os_family": "linux"}, inputs
        )
        assert len(calls) == 1
        assert calls[0]["operation"] == "install_slack_mcp"

    def test_darwin_host_picks_macos_runbook(self, monkeypatch):
        """os_family='darwin' → dedicated `_macos` sibling. Names ≠
        Linux so the arch-map divergence (arm64/x86_64 vs
        aarch64/x86_64) does not silently mismatch."""
        calls = self._stub_playbook(monkeypatch)
        inputs = _inputs_with_integrations(["slack-user"])

        lc._hermes_install_slack_mcp(
            "mac-test", "mac-test", {"os_family": "darwin"}, inputs
        )
        assert calls[0]["operation"] == "install_slack_mcp_macos"

    def test_os_family_typo_normalized_to_darwin(self, monkeypatch):
        """Defense-in-depth: `macos`/`mac`/`osx`/`Darwin` all fold to
        `darwin` before dispatching. Without this, a legacy hosts.json
        record with `os_family="macos"` renders the Linux runbook on a
        Mac host and reopens the B1 class of bug (path mismatch)."""
        calls = self._stub_playbook(monkeypatch)
        inputs = _inputs_with_integrations(["slack-user"])

        for value in ("Darwin", "macos", "MacOS", "osx", "mac"):
            calls.clear()
            lc._hermes_install_slack_mcp(
                "mac-test", "mac-test", {"os_family": value}, inputs
            )
            assert calls[0]["operation"] == "install_slack_mcp_macos", value

    def test_missing_os_family_defaults_to_linux(self, monkeypatch):
        """Legacy hosts.json records may omit `os_family` entirely.
        Linux fleet default → picks the Linux runbook. Runbook itself
        also has an ansible_os_family guard at task-0 as belt-and-
        suspenders."""
        calls = self._stub_playbook(monkeypatch)
        inputs = _inputs_with_integrations(["slack-user"])

        lc._hermes_install_slack_mcp("maurice", "wolf-i", {}, inputs)
        assert calls[0]["operation"] == "install_slack_mcp"

    def test_playbook_failure_raises_canonical_sync_error(self, monkeypatch):
        """Playbook non-success MUST propagate as `CanonicalSyncError`
        so `sync_agent_canonical` short-circuits before `_restart_unit`.
        The daemon is never restarted on a half-installed binary set.
        Error message must name the agent so the operator has a
        starting point."""
        self._stub_playbook(
            monkeypatch,
            success=False,
            err="get_url: checksum mismatch",
        )
        inputs = _inputs_with_integrations(["slack-user"])

        with pytest.raises(CanonicalSyncError, match=r"maurice"):
            lc._hermes_install_slack_mcp(
                "maurice", "wolf-i", {"os_family": "linux"}, inputs
            )

    def test_emits_event_when_installing(self, monkeypatch):
        """`on_event` callback fires exactly once when the install
        proceeds — so `clawctl agent sync`'s progress stream surfaces
        the phase, matching the `_openclaw_install_plugins` pattern."""
        self._stub_playbook(monkeypatch)
        events: list[tuple[str, str]] = []

        inputs = _inputs_with_integrations(["slack-user"])
        lc._hermes_install_slack_mcp(
            "maurice",
            "wolf-i",
            {"os_family": "linux"},
            inputs,
            on_event=lambda stage, msg: events.append((stage, msg)),
        )
        assert len(events) == 1
        stage, msg = events[0]
        assert stage == "slack_mcp_install"
        assert "maurice" in msg
        assert "install_slack_mcp.yaml" in msg


class TestConfigurePlaybooksNoSlackInstall:
    """#834: the slack install lives in a dedicated runbook, NOT in
    configure.yaml. A regression that re-baked the install into
    configure would double-install on every configure-then-sync cycle
    AND recreate the "sync doesn't install binaries" UX gap that #755
    (openclaw) and #834 (hermes) both closed."""

    def test_neither_hermes_configure_playbook_contains_slack_install(self):
        """Slack install must not appear in configure.yaml or
        configure_macos.yaml. Mirrors the openclaw brave regression
        guard at `test_neither_configure_playbook_contains_brave_install_task`."""
        from pathlib import Path

        base = (
            Path(__file__).parent.parent.parent
            / "src"
            / "clawrium"
            / "platform"
            / "registry"
            / "hermes"
            / "playbooks"
        )
        for name in ("configure.yaml", "configure_macos.yaml"):
            body = (base / name).read_text()
            assert "mcp_slack_version" not in body, name
            assert "mcp_slack_arch_map" not in body, name
            assert "mcp_slack_sha256_map" not in body, name
            assert "slack_integration_assigned" not in body, name
            assert "slack-mcp-server" not in body, name
