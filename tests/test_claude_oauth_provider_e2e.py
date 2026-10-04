"""Safe regression contracts for the real Claude OAuth E2E harness (#1015)."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


_SCRIPT_PATH = Path(__file__).parents[1] / "scripts/e2e/claude_provider_e2e.py"
_SPEC = importlib.util.spec_from_file_location(
    "claude_oauth_provider_e2e", _SCRIPT_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_e2e = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _e2e
_SPEC.loader.exec_module(_e2e)


def test_safe_environment_removes_all_claude_credential_sources(monkeypatch) -> None:
    for key in _e2e._CREDENTIAL_SOURCE_ENVIRONMENT:
        monkeypatch.setenv(key, "test-only-credential")

    environment = _e2e._safe_environment()

    assert all(key not in environment for key in _e2e._CREDENTIAL_SOURCE_ENVIRONMENT)


def test_normal_attachment_uses_provider_cli_and_preserves_safe_category(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    audited: list[tuple[str, str, str]] = []
    runner = object.__new__(_e2e.ClaudeOAuthProviderE2E)
    runner._audit = lambda action, result, notes: audited.append(
        (action, result, notes)
    )

    def fake_run_cli(arguments: list[str], *, expected_returncode: int | None = 0):
        calls.append(arguments)
        assert expected_returncode is None
        return SimpleNamespace(
            returncode=1,
            stdout="Error: local Claude OAuth source unavailable (category=credentials_artifact_unavailable)",
            stderr="",
        )

    monkeypatch.setattr(_e2e, "_run_cli", fake_run_cli)

    with pytest.raises(_e2e.LocalOAuthReaderFailure) as error:
        runner._attach_provider()

    assert error.value.category == "credentials_artifact_unavailable"
    assert calls == [
        [
            "agent",
            "provider",
            "attach",
            _e2e.OAUTH_PROVIDER,
            "--agent",
            _e2e.OAUTH_AGENT,
        ]
    ]
    assert audited == [
        (
            f"clawctl agent provider attach {_e2e.OAUTH_PROVIDER} --agent {_e2e.OAUTH_AGENT}",
            "failure",
            "Issue #1015 local OAuth reader failure",
        )
    ]


def test_successful_run_exercises_normal_provider_flow_and_cleanup(monkeypatch) -> None:
    """Pin the secret-free orchestration order behind the real-host proof."""
    host = {"hostname": "wolf-i.example", "agents": {}}
    provider: dict[str, str] | None = None
    secret_scope_present = False
    calls: list[list[str]] = []
    remote_assertions: list[str] = []

    runner = object.__new__(_e2e.ClaudeOAuthProviderE2E)
    runner.host_alias = "wolf-i"
    runner.audit_session = "test-session"
    runner.agent_created = False
    runner.provider_created = False
    runner._audit = lambda *_args: None
    runner._remote_assert = remote_assertions.append

    def local_secret_scope_present() -> bool:
        return secret_scope_present

    runner._local_secret_scope_present = local_secret_scope_present
    monkeypatch.setattr(_e2e, "get_host", lambda _alias: host)
    monkeypatch.setattr(_e2e, "get_provider", lambda _name: provider)

    def fake_run_cli(arguments: list[str], *, expected_returncode: int | None = 0):
        nonlocal provider, secret_scope_present
        calls.append(arguments)
        if arguments[:2] == ["agent", "create"]:
            host["agents"][_e2e.OAUTH_AGENT] = {
                "type": "claude",
                "status": "installed",
                "config": {},
            }
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if arguments[:2] == ["agent", "open"]:
            assert expected_returncode == 1
            return SimpleNamespace(returncode=1, stdout="", stderr="has no web UI")
        if arguments[:3] == ["provider", "registry", "create"]:
            provider = {
                "name": _e2e.OAUTH_PROVIDER,
                "type": "claude-oauth",
            }
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if arguments[:3] == ["agent", "provider", "attach"]:
            host["agents"][_e2e.OAUTH_AGENT]["providers"] = [_e2e.OAUTH_PROVIDER]
            secret_scope_present = True
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if arguments[:3] == ["agent", "secret", "get"]:
            return SimpleNamespace(
                returncode=0, stdout="CLAUDE_CODE_OAUTH_TOKEN\n", stderr=""
            )
        if arguments[:2] == ["agent", "sync"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if arguments[:2] == ["agent", "shell"]:
            return SimpleNamespace(
                returncode=0,
                stdout="OAUTH_ENVIRONMENT_NONEMPTY=true\nANTHROPIC_API_KEY_EMPTY=true\n",
                stderr="",
            )
        if arguments[:2] == ["agent", "delete"]:
            host["agents"].pop(_e2e.OAUTH_AGENT)
            secret_scope_present = False
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        if arguments[:3] == ["provider", "registry", "delete"]:
            provider = None
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        pytest.fail(f"unexpected E2E CLI command: {arguments!r}")

    monkeypatch.setattr(_e2e, "_run_cli", fake_run_cli)

    result = runner.run()

    assert result.passed
    assert not host["agents"]
    assert provider is None
    assert not secret_scope_present
    assert calls == [
        [
            "agent",
            "create",
            _e2e.OAUTH_AGENT,
            "--type",
            "claude",
            "--host",
            "wolf-i",
        ],
        ["agent", "open", _e2e.OAUTH_AGENT],
        [
            "provider",
            "registry",
            "create",
            _e2e.OAUTH_PROVIDER,
            "--type",
            "claude-oauth",
        ],
        [
            "agent",
            "provider",
            "attach",
            _e2e.OAUTH_PROVIDER,
            "--agent",
            _e2e.OAUTH_AGENT,
        ],
        ["agent", "secret", "get", "--agent", _e2e.OAUTH_AGENT],
        ["agent", "sync", _e2e.OAUTH_AGENT],
        [
            "agent",
            "shell",
            _e2e.OAUTH_AGENT,
            "--",
            (
                'test -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" '
                '&& test -z "${ANTHROPIC_API_KEY:-}" '
                "&& printf 'OAUTH_ENVIRONMENT_NONEMPTY=true\\n' "
                "&& printf 'ANTHROPIC_API_KEY_EMPTY=true\\n'"
            ),
        ],
        ["agent", "delete", "--yes", _e2e.OAUTH_AGENT],
        ["provider", "registry", "delete", "--yes", _e2e.OAUTH_PROVIDER],
    ]
    assert len(remote_assertions) == 4
    evidence = _e2e._render_evidence("wolf-i", result)
    assert "**PASS**" in evidence
    assert "Owned-resource cleanup: **PASS**" in evidence


def test_control_plane_scan_recognizes_credential_field_names() -> None:
    assert _e2e._contains_forbidden_credential_field(
        {"CLAUDE_CODE_OAUTH_TOKEN": "test-only-credential"}
    )
    assert _e2e._contains_forbidden_credential_field(
        {"ANTHROPIC_API_KEY": "test-only-credential"}
    )


def test_evidence_is_fixed_redacted_text() -> None:
    evidence = _e2e._render_evidence("wolf-i", _e2e.OAuthEvidence(completed_at="now"))

    assert "CLAUDE_CODE_OAUTH_TOKEN=" not in evidence
    assert "ANTHROPIC_API_KEY=" not in evidence
    assert "test-only-credential" not in evidence
    assert "`ANTHROPIC_API_KEY` empty" in evidence


def test_credential_assignment_output_is_rejected() -> None:
    with pytest.raises(_e2e.E2EFailure, match="credential assignment"):
        _e2e._assert_output_has_no_credential_assignment(
            "export CLAUDE_CODE_OAUTH_TOKEN=test-only-credential"
        )

    # Keep the test process clean for plugins that inspect its environment.
    for key in _e2e._CREDENTIAL_SOURCE_ENVIRONMENT:
        os.environ.pop(key, None)
