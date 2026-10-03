#!/usr/bin/env python3
"""Run redaction-safe provider E2E checks for the daemonless Claude agent.

This harness intentionally has no credential-file fallback. OAuth may be
imported only from an explicitly exported ``CLAUDE_CODE_OAUTH_TOKEN``; it
never reads ``~/.claude``, a browser profile, a keychain, or a database.

The API-key phase generates a one-time dummy value, passes it only through
``clawctl agent secret create --value-stdin``, and never invokes Claude or an
external API. Command output is intentionally not persisted: the evidence
contains only pass/fail assertions and command shapes, so a future redaction
regression cannot write a credential to the repository.

Run from a prepared worktree:

    uv run python scripts/e2e/claude_provider_e2e.py \
      --phase oauth --host wolf-i --evidence .itx/1003/02_E2E_OAUTH.md
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shlex
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from clawrium.core.claude_credentials import import_claude_oauth_from_environment
from clawrium.core.hosts import get_host
from clawrium.core.keys import get_host_private_key
from clawrium.core.secrets import get_instance_key, get_instance_secrets


OAUTH_AGENT = "claude-oauth-e2e"
API_KEY_AGENT = "claude-api-key-e2e"
_CLI_ENTRYPOINT = "from clawrium.cli import app; app()"
_NO_SECRETS_ENV = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")


class E2EFailure(RuntimeError):
    """A failed E2E assertion whose detail is safe to record."""


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _fail(message: str) -> NoReturn:
    raise E2EFailure(message)


def _safe_environment() -> dict[str, str]:
    """Keep caller credential sources out of every spawned CLI process."""
    environment = os.environ.copy()
    for key in _NO_SECRETS_ENV:
        environment.pop(key, None)
    return environment


def _assert_output_redacted(output: str, sensitive_values: tuple[str, ...]) -> None:
    """Fail closed without returning any captured output to the caller."""
    if any(value and value in output for value in sensitive_values):
        _fail("a command output surface exposed the test credential")


def _run(
    command: list[str],
    *,
    expected_returncode: int = 0,
    input_text: str | None = None,
    sensitive_values: tuple[str, ...] = (),
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command without ever emitting its stdout or stderr."""
    result = subprocess.run(
        command,
        check=False,
        input=input_text,
        text=True,
        capture_output=True,
        env=environment,
    )
    _assert_output_redacted(result.stdout + result.stderr, sensitive_values)
    if result.returncode != expected_returncode:
        _fail(f"command returned {result.returncode}, expected {expected_returncode}")
    return result


def _run_cli(
    arguments: list[str],
    *,
    expected_returncode: int = 0,
    input_text: str | None = None,
    sensitive_values: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    """Invoke the current worktree's Typer app, not an installed release."""
    return _run(
        [sys.executable, "-c", _CLI_ENTRYPOINT, *arguments],
        expected_returncode=expected_returncode,
        input_text=input_text,
        sensitive_values=sensitive_values,
        environment=_safe_environment(),
    )


def _agent_snapshot(host_alias: str) -> dict[str, tuple[str, str, str]]:
    """Return only non-secret fleet identity/state needed for preservation checks."""
    host = get_host(host_alias)
    return {
        name: (
            str(record.get("type", "")),
            str(record.get("agent_name", name)),
            str(record.get("status", "")),
        )
        for name, record in host.get("agents", {}).items()
        if isinstance(record, dict)
    }


def _agent_record(host_alias: str, agent_name: str) -> dict | None:
    host = get_host(host_alias)
    record = host.get("agents", {}).get(agent_name)
    return record if isinstance(record, dict) else None


@dataclass
class PhaseEvidence:
    name: str
    agent: str
    started_at: str
    install_only: bool = False
    source_available: bool | None = None
    source_detail: str | None = None
    credential_synced: bool = False
    remote_credential_mode: str | None = None
    redaction_checked: bool = False
    cleanup_verified: bool = False
    preexisting_agents_preserved: bool = False
    failures: list[str] = field(default_factory=list)
    completed_at: str | None = None

    @property
    def passed(self) -> bool:
        return not self.failures


class ClaudeProviderE2E:
    """Conservative real-host E2E runner with mandatory owned-resource cleanup."""

    def __init__(self, host_alias: str):
        self.host_alias = host_alias
        self.host = get_host(host_alias)
        self.hostname = str(self.host["hostname"])
        self.user = str(self.host.get("user", "xclm"))
        key_id = str(self.host.get("key_id") or self.hostname)
        private_key = get_host_private_key(key_id)
        if private_key is None:
            _fail("i-wolf SSH key is not available")
        self.private_key = private_key
        self.audit_session = self._new_audit_session()

    def _new_audit_session(self) -> str:
        result = _run_cli(["audit", "session", "new"])
        session = result.stdout.strip()
        if not session:
            _fail("could not create a clawctl audit session")
        return session

    def _audit(self, action: str, result: str, notes: str) -> None:
        _run_cli(
            [
                "audit",
                "log",
                action,
                "--result",
                result,
                "--session-id",
                self.audit_session,
                "--notes",
                notes,
            ]
        )

    def _mutate(
        self,
        arguments: list[str],
        *,
        action: str,
        notes: str,
        input_text: str | None = None,
        sensitive_values: tuple[str, ...] = (),
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = _run_cli(
                arguments,
                input_text=input_text,
                sensitive_values=sensitive_values,
            )
        except E2EFailure:
            self._audit(action, "failure", notes)
            raise
        self._audit(action, "success", notes)
        return result

    def _remote_assert(self, command: str) -> None:
        remote = "sudo -n bash -eu -o pipefail -c " + shlex.quote(command)
        _run(
            [
                "ssh",
                "-i",
                str(self.private_key),
                "-o",
                "IdentitiesOnly=yes",
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=20",
                f"{self.user}@{self.hostname}",
                remote,
            ]
        )

    def _instance_key(self, agent_name: str) -> str:
        key_id = str(self.host.get("key_id") or self.hostname)
        return get_instance_key(key_id, "claude", agent_name)

    def _assert_fresh(self, agent_name: str) -> None:
        if _agent_record(self.host_alias, agent_name) is not None:
            _fail(f"refusing to reuse existing agent {agent_name}")
        self._remote_assert(
            "\n".join(
                (
                    f"! getent passwd {shlex.quote(agent_name)} >/dev/null",
                    f"! test -e /home/{shlex.quote(agent_name)}",
                    f"! test -e /var/lib/clawrium/claude/{shlex.quote(agent_name)}.json",
                )
            )
        )
        if get_instance_secrets(self._instance_key(agent_name)):
            _fail(f"refusing to reuse local secret scope for {agent_name}")

    def _assert_install_only(self, agent_name: str) -> None:
        record = _agent_record(self.host_alias, agent_name)
        if record is None:
            _fail("install did not create a local agent record")
        if record.get("type") != "claude" or record.get("status") != "installed":
            _fail("install did not leave an installed Claude record")
        config = record.get("config", {})
        if not isinstance(config, dict):
            _fail("Claude install record configuration is not an object")
        forbidden_record_keys = {"gateway", "port", "dashboard", "auth"}
        if forbidden_record_keys.intersection(record) or forbidden_record_keys.intersection(config):
            _fail("install created gateway, port, UI, or credential record state")
        if get_instance_secrets(self._instance_key(agent_name)):
            _fail("install created local credentials")

        self._remote_assert(
            "\n".join(
                (
                    f"test -x /home/{agent_name}/.local/claude/bin/claude",
                    f"! test -e /home/{agent_name}/.claude",
                    f"! test -e /home/{agent_name}/.profile.d/clawrium-claude.sh",
                    f"! pgrep -u {agent_name} >/dev/null",
                    (
                        "! systemctl list-unit-files --all "
                        f"'claude-{agent_name}*' --no-legend | grep -q ."
                    ),
                    (
                        "! systemctl list-units --all "
                        f"'claude-{agent_name}*' --no-legend | grep -q ."
                    ),
                )
            )
        )

        no_ui = _run_cli(["agent", "open", agent_name], expected_returncode=1)
        if "has no web UI" not in no_ui.stderr:
            _fail("Claude agent open did not reject the absent native UI")

    def _assert_credential_activation(
        self,
        agent_name: str,
        *,
        active_key: str,
        inactive_key: str,
        expected_value: str | None,
    ) -> None:
        self._remote_assert(
            "\n".join(
                (
                    f"test -f /home/{agent_name}/.claude/clawrium-credentials.env",
                    (
                        f"test \"$(stat -c %a /home/{agent_name}/.claude/"
                        "clawrium-credentials.env)\" = 600"
                    ),
                    (
                        f"test \"$(stat -c %a /home/{agent_name}/.profile.d/"
                        "clawrium-claude.sh)\" = 600"
                    ),
                )
            )
        )

        checks = [
            f'test -n "${{{active_key}:-}}"',
            f'test -z "${{{inactive_key}:-}}"',
        ]
        if expected_value is not None:
            expected_digest = hashlib.sha256(expected_value.encode()).hexdigest()
            checks.append(
                f'test "$(printf %s "${{{active_key}}}" | sha256sum | '
                f"awk '{{print $1}}')\" = '{expected_digest}'"
            )
        checks.append("printf 'CREDENTIAL_ENVIRONMENT=exclusive\\n'")
        shell = _run_cli(
            ["agent", "shell", agent_name, "--", " && ".join(checks)],
            sensitive_values=(expected_value,) if expected_value is not None else (),
        )
        if shell.stdout.strip() != "CREDENTIAL_ENVIRONMENT=exclusive":
            _fail("remote shell did not confirm an exclusive credential environment")

    def _assert_cleanup(self, agent_name: str, before: dict[str, tuple[str, str, str]]) -> None:
        self._remote_assert(
            "\n".join(
                (
                    f"! getent passwd {agent_name} >/dev/null",
                    f"! test -e /home/{agent_name}",
                    f"! test -e /home/{agent_name}/.local/claude",
                    f"! test -e /home/{agent_name}/.claude",
                    f"! test -e /home/{agent_name}/.claude/clawrium-credentials.env",
                    f"! test -e /home/{agent_name}/.profile.d/clawrium-claude.sh",
                    f"! test -e /var/lib/clawrium/claude/{agent_name}.json",
                )
            )
        )
        if _agent_record(self.host_alias, agent_name) is not None:
            _fail("agent record remains after successful removal")
        if get_instance_secrets(self._instance_key(agent_name)):
            _fail("local instance secrets remain after successful removal")
        if _agent_snapshot(self.host_alias) != before:
            _fail("a pre-existing agent fleet record changed during E2E")

    def _delete_if_present(self, agent_name: str) -> None:
        if _agent_record(self.host_alias, agent_name) is None:
            return
        self._mutate(
            ["agent", "delete", "--yes", agent_name],
            action=f"clawctl agent delete {agent_name} --yes",
            notes="Issue #1003 owned-resource cleanup",
        )

    def run_oauth(self) -> PhaseEvidence:
        phase = PhaseEvidence("OAuth", OAUTH_AGENT, _utc_now())
        before = _agent_snapshot(self.host_alias)
        phase.source_available = bool(os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"))
        phase.source_detail = (
            "explicit CLAUDE_CODE_OAUTH_TOKEN environment source available"
            if phase.source_available
            else "blocked: explicit CLAUDE_CODE_OAUTH_TOKEN environment source absent; local ~/.claude was not inspected"
        )
        try:
            self._assert_fresh(phase.agent)
            self._mutate(
                ["agent", "create", phase.agent, "--type", "claude", "--host", self.host_alias],
                action=(
                    f"clawctl agent create {phase.agent} --type claude "
                    f"--host {self.host_alias}"
                ),
                notes="Issue #1003 OAuth install-only validation",
            )
            self._assert_install_only(phase.agent)
            phase.install_only = True

            if phase.source_available:
                # The public importer reads only the already-exported process value.
                # It has no keychain, browser, database, or ~/.claude fallback.
                import_claude_oauth_from_environment(phase.agent)
                self._audit(
                    f"Claude OAuth environment import for {phase.agent}",
                    "success",
                    "Issue #1003 explicit environment source only",
                )
                _run_cli(["agent", "secret", "get", "--agent", phase.agent])
                self._mutate(
                    ["agent", "sync", phase.agent],
                    action=f"clawctl agent sync {phase.agent}",
                    notes="Issue #1003 OAuth credential activation",
                )
                self._assert_credential_activation(
                    phase.agent,
                    active_key="CLAUDE_CODE_OAUTH_TOKEN",
                    inactive_key="ANTHROPIC_API_KEY",
                    expected_value=None,
                )
                phase.credential_synced = True
                phase.remote_credential_mode = "oauth-only"
                phase.redaction_checked = True
        except Exception as exc:  # Keep cleanup and the independent API phase running.
            phase.failures.append(f"{type(exc).__name__}: {str(exc)}")
        finally:
            try:
                self._delete_if_present(phase.agent)
                self._assert_cleanup(phase.agent, before)
                phase.cleanup_verified = True
                phase.preexisting_agents_preserved = True
            except Exception as exc:
                phase.failures.append(f"cleanup {type(exc).__name__}: {str(exc)}")
            phase.completed_at = _utc_now()
        return phase

    def run_api_key(self) -> PhaseEvidence:
        phase = PhaseEvidence("API key", API_KEY_AGENT, _utc_now())
        before = _agent_snapshot(self.host_alias)
        # This cannot authenticate with Anthropic. It is unique per run, passed on
        # stdin only, redaction-scanned, and never written to the evidence file.
        dummy_value = f"issue-1003-dummy-{uuid.uuid4().hex}"
        try:
            # The separate OAuth identity must still be completely gone before
            # this independent API-key case is permitted to start.
            self._assert_fresh(OAUTH_AGENT)
            self._assert_fresh(phase.agent)
            self._mutate(
                ["agent", "create", phase.agent, "--type", "claude", "--host", self.host_alias],
                action=(
                    f"clawctl agent create {phase.agent} --type claude "
                    f"--host {self.host_alias}"
                ),
                notes="Issue #1003 API-key install-only validation",
            )
            self._assert_install_only(phase.agent)
            phase.install_only = True

            self._mutate(
                [
                    "agent",
                    "secret",
                    "create",
                    "ANTHROPIC_API_KEY",
                    "--agent",
                    phase.agent,
                    "--value-stdin",
                    "--description",
                    "Issue #1003 dummy API-key transport test",
                    "--yes",
                ],
                action=(
                    "clawctl agent secret create ANTHROPIC_API_KEY "
                    f"--agent {phase.agent} --value-stdin"
                ),
                notes="Issue #1003 dummy credential only; value withheld",
                input_text=dummy_value + "\n",
                sensitive_values=(dummy_value,),
            )
            secrets = get_instance_secrets(self._instance_key(phase.agent))
            if set(secrets) != {"ANTHROPIC_API_KEY"}:
                _fail("API-key setup did not retain exactly one local credential mode")
            listed = _run_cli(
                ["agent", "secret", "get", "--agent", phase.agent],
                sensitive_values=(dummy_value,),
            )
            if "ANTHROPIC_API_KEY" not in listed.stdout:
                _fail("secret metadata did not report the intended credential key")
            self._mutate(
                ["agent", "sync", phase.agent],
                action=f"clawctl agent sync {phase.agent}",
                notes="Issue #1003 dummy API-key credential activation",
                sensitive_values=(dummy_value,),
            )
            self._assert_credential_activation(
                phase.agent,
                active_key="ANTHROPIC_API_KEY",
                inactive_key="CLAUDE_CODE_OAUTH_TOKEN",
                expected_value=dummy_value,
            )
            phase.credential_synced = True
            phase.remote_credential_mode = "api-key-only"
            phase.redaction_checked = True
        except Exception as exc:  # Keep cleanup mandatory after every partial phase.
            phase.failures.append(f"{type(exc).__name__}: {str(exc)}")
        finally:
            try:
                self._delete_if_present(phase.agent)
                self._assert_cleanup(phase.agent, before)
                phase.cleanup_verified = True
                phase.preexisting_agents_preserved = True
            except Exception as exc:
                phase.failures.append(f"cleanup {type(exc).__name__}: {str(exc)}")
            phase.completed_at = _utc_now()
        return phase


def _checkbox(value: bool) -> str:
    return "PASS" if value else "NOT RUN / BLOCKED"


def _render_evidence(host_alias: str, phases: list[PhaseEvidence]) -> str:
    lines = [
        "# Issue #1003 — Claude Provider E2E Evidence",
        "",
        f"**Host alias:** `{host_alias}` (i-wolf)",
        f"**Completed:** {_utc_now()}",
        "",
        "## Safety boundary",
        "",
        "- OAuth is accepted only from an explicitly exported `CLAUDE_CODE_OAUTH_TOKEN`; the harness never reads a keychain, browser profile, database, or local `~/.claude`.",
        "- The API-key phase creates a unique dummy value and supplies it only on stdin. It never invokes `claude` or an authenticated external API.",
        "- Captured command stdout/stderr is never persisted. The harness fails if its dummy value appears in a checked output surface.",
        "",
        "## Commands exercised",
        "",
        "- `clawctl agent create <fresh-name> --type claude --host wolf-i`",
        "- `clawctl agent secret create ANTHROPIC_API_KEY --agent <fresh-name> --value-stdin` (API-key case only)",
        "- `clawctl agent sync <fresh-name>`",
        "- `clawctl agent shell <fresh-name> -- <non-authenticating environment assertion>`",
        "- `clawctl agent delete --yes <fresh-name>`",
        "",
    ]
    for phase in phases:
        lines.extend(
            (
                f"## {phase.name}: `{phase.agent}`",
                "",
                f"- Install-only: **{_checkbox(phase.install_only)}** — package prefix exists; no Claude process, service, gateway/port/UI record, local credentials, remote `.claude`, or managed credential hook before sync.",
            )
        )
        if phase.source_available is not None:
            lines.append(f"- OAuth source: {phase.source_detail}")
        lines.extend(
            (
                f"- Credential activation: **{_checkbox(phase.credential_synced)}**"
                + (f" ({phase.remote_credential_mode})" if phase.remote_credential_mode else ""),
                f"- Redaction assertion: **{_checkbox(phase.redaction_checked)}**",
                f"- Owned-resource cleanup: **{_checkbox(phase.cleanup_verified)}** — account, home, prefix, complete `.claude`, credential file, startup hook, ownership marker, local instance secrets, and hosts record absent.",
                f"- Pre-existing fleet records preserved: **{_checkbox(phase.preexisting_agents_preserved)}**",
            )
        )
        if phase.failures:
            lines.extend(("- Result: **BLOCKED / FAILED**", *[f"  - {failure}" for failure in phase.failures]))
        elif phase.source_available is False:
            lines.append("- Result: **ENVIRONMENT BLOCKER** — install-only and cleanup completed; OAuth activation was not attempted.")
        else:
            lines.append("- Result: **PASS**")
        lines.append("")

    lines.extend(
        (
            "## Callout",
            "",
            "- The OAuth authenticated-command check is intentionally not run when the explicit environment source is unavailable. No fallback source was inspected.",
            "- Real Anthropic API authentication is deliberately deferred: the API-key assertion validates only exclusive remote environment transport with a generated dummy value.",
            "",
        )
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Configured i-wolf host alias.")
    parser.add_argument(
        "--phase",
        choices=("oauth", "api-key", "all"),
        default="all",
        help="Run one independent credential case (default: both, in order).",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Markdown evidence path (contains no command transcripts or values).",
    )
    args = parser.parse_args()

    runner = ClaudeProviderE2E(args.host)
    phases: list[PhaseEvidence]
    if args.phase == "oauth":
        phases = [runner.run_oauth()]
    elif args.phase == "api-key":
        phases = [runner.run_api_key()]
    else:
        oauth = runner.run_oauth()
        # The independent API-key agent may begin only after OAuth owned-resource
        # cleanup has completed, even when OAuth activation is environment-blocked.
        if oauth.cleanup_verified:
            phases = [oauth, runner.run_api_key()]
        else:
            phases = [
                oauth,
                PhaseEvidence(
                    "API key",
                    API_KEY_AGENT,
                    _utc_now(),
                    failures=["not run because OAuth owned-resource cleanup did not complete"],
                    completed_at=_utc_now(),
                ),
            ]
    evidence = _render_evidence(args.host, phases)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(evidence)

    # An unavailable explicit OAuth source is represented as a Callout in the
    # evidence, not as a phase failure. Any recorded failure is unexpected.
    unexpected_failures = [phase for phase in phases if phase.failures]
    return 1 if unexpected_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
