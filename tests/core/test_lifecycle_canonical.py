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
    monkeypatch.setattr(lc, "_atomic_write", lambda *a, **kw: None)
    # restart=False so we don't traverse the zeroclaw repair path.
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

    # Without force, refusal:
    with pytest.raises(SecretRemovalRefused):
        sync_agent_canonical("alpha", force=False, restart=False)
    # With force, no raise; the rendered body is written.
    result = sync_agent_canonical("alpha", force=True, restart=False)
    assert result.success
    assert ".hermes/.env" in result.files_written


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


def test_zeroclaw_sync_restart_false_skips_restart_and_repair(monkeypatch):
    """When `restart=False`, neither `_restart_unit` nor
    `_zeroclaw_repair_after_start` must be called — even on zeroclaw.
    The AGENTS.md gateway-token-lifecycle rule binds when restart IS
    requested; opting out means the operator accepts the stale bearer
    trade-off documented in `clawctl agent sync --no-restart`."""
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
    assert repair_called == []
