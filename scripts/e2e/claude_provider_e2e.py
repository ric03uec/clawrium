#!/usr/bin/env python3
"""Run the real, redaction-safe Claude OAuth provider E2E on i-wolf.

This harness exercises only normal Clawrium UX: it creates a fresh Claude
agent, registers a selection-only ``claude-oauth`` provider, attaches it, and
syncs. The attachment is deliberately the only OAuth import operation; it
runs #1013's narrow local credential reader. The harness strips all caller
credential variables from every spawned Clawrium process and never prints,
copies, hashes, or persists the resulting token outside Clawrium's existing
per-instance secret flow.

Captured command output remains in memory only long enough to assert it has no
credential assignment. Evidence contains fixed assertion results and command
shapes, never transcripts or secret-derived values.

Run from a prepared worktree:

    uv run python scripts/e2e/claude_provider_e2e.py \
      --host wolf-i --evidence .itx/1015/02_E2E_OAUTH.md
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from clawrium.core.config import get_config_dir
from clawrium.core.hosts import get_host
from clawrium.core.keys import get_host_private_key
from clawrium.core.providers.storage import get_provider
from clawrium.core.secrets import SECRETS_FILE, get_instance_key


OAUTH_AGENT = "claude-oauth-e2e"
OAUTH_PROVIDER = "claude-oauth-e2e-provider"
_CLI_ENTRYPOINT = "from clawrium.cli import app; app()"
_CREDENTIAL_SOURCE_ENVIRONMENT = (
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?im)^\s*(?:export\s+)?(?:CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY)\s*=\s*\S+"
)
_FORBIDDEN_CREDENTIAL_FIELDS = frozenset(
    {
        "claude_code_oauth_token",
        "anthropic_api_key",
        "credential",
        "credentials",
        "token",
        "auth",
    }
)


class E2EFailure(RuntimeError):
    """A failed E2E assertion whose detail is safe to record."""


class LocalOAuthReaderFailure(E2EFailure):
    """The normal provider attachment could not import local OAuth."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _fail(message: str) -> NoReturn:
    raise E2EFailure(message)


def _safe_environment() -> dict[str, str]:
    """Prevent caller credentials from reaching the provider or its reader."""
    environment = os.environ.copy()
    for key in _CREDENTIAL_SOURCE_ENVIRONMENT:
        environment.pop(key, None)
    return environment


def _assert_output_has_no_credential_assignment(output: str) -> None:
    """Reject a credential-shaped CLI output without retaining a transcript."""
    if _CREDENTIAL_ASSIGNMENT.search(output):
        _fail("a CLI event or command output contained a credential assignment")


def _run(
    command: list[str],
    *,
    expected_returncode: int | None = 0,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run quietly; command output is not printed or persisted."""
    result = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        env=_safe_environment() if environment is None else environment,
    )
    _assert_output_has_no_credential_assignment(result.stdout + result.stderr)
    if expected_returncode is not None and result.returncode != expected_returncode:
        _fail(f"command returned {result.returncode}, expected {expected_returncode}")
    return result


def _run_cli(
    arguments: list[str], *, expected_returncode: int | None = 0
) -> subprocess.CompletedProcess[str]:
    """Invoke the current worktree's Clawrium CLI with no caller credential."""
    return _run(
        [sys.executable, "-c", _CLI_ENTRYPOINT, *arguments],
        expected_returncode=expected_returncode,
        environment=_safe_environment(),
    )


def _contains_forbidden_credential_field(value: object) -> bool:
    """Check control-plane metadata without inspecting any secret store."""
    if isinstance(value, dict):
        return any(
            str(key).lower() in _FORBIDDEN_CREDENTIAL_FIELDS
            or _contains_forbidden_credential_field(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_credential_field(child) for child in value)
    return False


def _agent_snapshot(host_alias: str) -> dict[str, tuple[str, str, str]]:
    """Return non-secret fleet identity/state for preservation assertions."""
    host = get_host(host_alias)
    return {
        name: (
            str(record.get("type", "")),
            str(record.get("agent_name", name)),
            str(record.get("status", "")),
        )
        for name, record in host.get("agents", {}).items()
        if isinstance(record, dict) and name != OAUTH_AGENT
    }


def _agent_record(host_alias: str, agent_name: str) -> dict | None:
    record = get_host(host_alias).get("agents", {}).get(agent_name)
    return record if isinstance(record, dict) else None


@dataclass
class OAuthEvidence:
    agent: str = OAUTH_AGENT
    provider: str = OAUTH_PROVIDER
    started_at: str = field(default_factory=_utc_now)
    install_only: bool = False
    provider_registered: bool = False
    provider_attached: bool = False
    local_oauth_reader_used: bool = False
    credential_synced: bool = False
    credential_file_private: bool = False
    oauth_nonempty: bool = False
    api_key_empty: bool = False
    state_redacted: bool = False
    cli_output_redacted: bool = False
    cleanup_verified: bool = False
    preexisting_agents_preserved: bool = False
    failures: list[str] = field(default_factory=list)
    completed_at: str | None = None

    @property
    def passed(self) -> bool:
        return not self.failures and all(
            (
                self.install_only,
                self.provider_registered,
                self.provider_attached,
                self.local_oauth_reader_used,
                self.credential_synced,
                self.credential_file_private,
                self.oauth_nonempty,
                self.api_key_empty,
                self.state_redacted,
                self.cli_output_redacted,
                self.cleanup_verified,
                self.preexisting_agents_preserved,
            )
        )


class ClaudeOAuthProviderE2E:
    """One fresh real-host OAuth case with mandatory resource cleanup."""

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
        self.instance_key = get_instance_key(key_id, "claude", OAUTH_AGENT)
        self.audit_session = self._new_audit_session()
        self.agent_created = False
        self.provider_created = False

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
        self, arguments: list[str], *, action: str, notes: str
    ) -> subprocess.CompletedProcess[str]:
        try:
            result = _run_cli(arguments)
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

    def _local_secret_scope_present(self) -> bool:
        """Test only the instance-key presence; never parse or copy secrets."""
        secrets_path = get_config_dir() / SECRETS_FILE
        if not secrets_path.exists():
            return False
        result = subprocess.run(
            ["grep", "-Fq", f'"{self.instance_key}"', str(secrets_path)],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_safe_environment(),
        )
        if result.returncode not in (0, 1):
            _fail("could not check local per-instance secret cleanup")
        return result.returncode == 0

    def _assert_fresh(self) -> None:
        if _agent_record(self.host_alias, OAUTH_AGENT) is not None:
            _fail(f"refusing to reuse existing agent {OAUTH_AGENT}")
        if get_provider(OAUTH_PROVIDER) is not None:
            _fail(f"refusing to reuse existing provider {OAUTH_PROVIDER}")
        if self._local_secret_scope_present():
            _fail("refusing to reuse a local OAuth secret scope")
        self._remote_assert(
            "\n".join(
                (
                    f"! getent passwd {shlex.quote(OAUTH_AGENT)} >/dev/null",
                    f"! test -e /home/{shlex.quote(OAUTH_AGENT)}",
                    (
                        "! test -e /var/lib/clawrium/claude/"
                        f"{shlex.quote(OAUTH_AGENT)}.json"
                    ),
                )
            )
        )

    def _assert_install_only(self) -> None:
        record = _agent_record(self.host_alias, OAUTH_AGENT)
        if record is None:
            _fail("install did not create a local agent record")
        if record.get("type") != "claude" or record.get("status") != "installed":
            _fail("install did not leave an installed Claude record")
        config = record.get("config", {})
        if not isinstance(config, dict):
            _fail("Claude install record configuration is not an object")
        forbidden_record_keys = {"gateway", "port", "dashboard", "auth"}
        if forbidden_record_keys.intersection(
            record
        ) or forbidden_record_keys.intersection(config):
            _fail("install created gateway, port, UI, or credential record state")
        if _contains_forbidden_credential_field(record):
            _fail("install record contains credential metadata")
        if self._local_secret_scope_present():
            _fail("install created a local credential")

        self._remote_assert(
            "\n".join(
                (
                    f"test -x /home/{OAUTH_AGENT}/.local/claude/bin/claude",
                    f"! test -e /home/{OAUTH_AGENT}/.claude",
                    f"! test -e /home/{OAUTH_AGENT}/.profile.d/clawrium-claude.sh",
                    f"! pgrep -u {OAUTH_AGENT} >/dev/null",
                    (
                        "! systemctl list-unit-files --all "
                        f"'claude-{OAUTH_AGENT}*' --no-legend | grep -q ."
                    ),
                    (
                        "! systemctl list-units --all "
                        f"'claude-{OAUTH_AGENT}*' --no-legend | grep -q ."
                    ),
                )
            )
        )

        no_ui = _run_cli(["agent", "open", OAUTH_AGENT], expected_returncode=1)
        if "has no web UI" not in no_ui.stderr:
            _fail("Claude agent open did not reject the absent native UI")

    def _assert_provider_registration(self) -> None:
        provider = get_provider(OAUTH_PROVIDER)
        if not isinstance(provider, dict):
            _fail("Claude OAuth provider registration is absent")
        if (
            provider.get("name") != OAUTH_PROVIDER
            or provider.get("type") != "claude-oauth"
        ):
            _fail("provider registration is not the expected Claude OAuth selection")
        allowed_fields = {"name", "type", "created_at", "updated_at"}
        if set(provider).difference(
            allowed_fields
        ) or _contains_forbidden_credential_field(provider):
            _fail("Claude OAuth provider registration contains credential state")

    def _attach_provider(self) -> None:
        action = f"clawctl agent provider attach {OAUTH_PROVIDER} --agent {OAUTH_AGENT}"
        try:
            result = _run_cli(
                ["agent", "provider", "attach", OAUTH_PROVIDER, "--agent", OAUTH_AGENT],
                expected_returncode=None,
            )
        except E2EFailure:
            self._audit(action, "failure", "Issue #1015 OAuth provider attachment")
            raise
        if result.returncode != 0:
            self._audit(action, "failure", "Issue #1015 local OAuth reader failure")
            category = re.search(r"category=([a-z_]+)", result.stdout + result.stderr)
            raise LocalOAuthReaderFailure(
                category.group(1) if category is not None else "unknown_reader_failure"
            )
        self._audit(action, "success", "Issue #1015 normal OAuth provider attachment")

    def _assert_attachment_and_local_secret_metadata(self) -> None:
        record = _agent_record(self.host_alias, OAUTH_AGENT)
        if record is None or record.get("providers") != [OAUTH_PROVIDER]:
            _fail("OAuth provider attachment was not recorded on the fresh agent")
        if _contains_forbidden_credential_field(
            {key: value for key, value in record.items() if key != "providers"}
        ):
            _fail("agent state contains credential metadata")
        listed = _run_cli(["agent", "secret", "get", "--agent", OAUTH_AGENT])
        if "CLAUDE_CODE_OAUTH_TOKEN" not in listed.stdout:
            _fail("OAuth attachment did not create the expected local secret metadata")
        if "ANTHROPIC_API_KEY" in listed.stdout:
            _fail("OAuth attachment retained the inactive API-key mode")

    def _assert_activation(self) -> None:
        credential_path = f"/home/{OAUTH_AGENT}/.claude/clawrium-credentials.env"
        startup_path = f"/home/{OAUTH_AGENT}/.profile.d/clawrium-claude.sh"
        settings_path = f"/home/{OAUTH_AGENT}/.claude/settings.json"
        self._remote_assert(
            "\n".join(
                (
                    f"test -f {shlex.quote(credential_path)}",
                    (
                        f"test \"$(stat -c '%U:%G:%a' {shlex.quote(credential_path)})\" "
                        f"= '{OAUTH_AGENT}:{OAUTH_AGENT}:600'"
                    ),
                    (
                        f"test \"$(stat -c '%U:%G:%a' {shlex.quote(startup_path)})\" "
                        f"= '{OAUTH_AGENT}:{OAUTH_AGENT}:600'"
                    ),
                    f"! grep -Fq 'CLAUDE_CODE_OAUTH_TOKEN' {shlex.quote(settings_path)}",
                    f"! grep -Fq 'ANTHROPIC_API_KEY' {shlex.quote(settings_path)}",
                )
            )
        )

        shell = _run_cli(
            [
                "agent",
                "shell",
                OAUTH_AGENT,
                "--",
                (
                    'test -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" '
                    '&& test -z "${ANTHROPIC_API_KEY:-}" '
                    "&& printf 'OAUTH_ENVIRONMENT_NONEMPTY=true\\n' "
                    "&& printf 'ANTHROPIC_API_KEY_EMPTY=true\\n'"
                ),
            ]
        )
        expected = "OAUTH_ENVIRONMENT_NONEMPTY=true\nANTHROPIC_API_KEY_EMPTY=true"
        if shell.stdout.strip() != expected:
            _fail(
                "agent shell did not return the expected redacted credential booleans"
            )

    def _assert_state_redacted(self) -> None:
        record = _agent_record(self.host_alias, OAUTH_AGENT)
        provider = get_provider(OAUTH_PROVIDER)
        if record is None or provider is None:
            _fail("control-plane state is missing during redaction validation")
        if _contains_forbidden_credential_field(
            {key: value for key, value in record.items() if key != "providers"}
        ) or _contains_forbidden_credential_field(provider):
            _fail("control-plane state contains a credential field")

    def _delete_agent_if_present(self) -> None:
        if _agent_record(self.host_alias, OAUTH_AGENT) is None:
            return
        self._mutate(
            ["agent", "delete", "--yes", OAUTH_AGENT],
            action=f"clawctl agent delete --yes {OAUTH_AGENT}",
            notes="Issue #1015 owned-resource cleanup",
        )

    def _delete_provider_if_present(self) -> None:
        if get_provider(OAUTH_PROVIDER) is None:
            return
        self._mutate(
            ["provider", "registry", "delete", "--yes", OAUTH_PROVIDER],
            action=f"clawctl provider registry delete --yes {OAUTH_PROVIDER}",
            notes="Issue #1015 selection-only provider cleanup",
        )

    def _assert_cleanup(self, before: dict[str, tuple[str, str, str]]) -> None:
        self._remote_assert(
            "\n".join(
                (
                    f"! getent passwd {OAUTH_AGENT} >/dev/null",
                    f"! test -e /home/{OAUTH_AGENT}",
                    f"! test -e /home/{OAUTH_AGENT}/.local/claude",
                    f"! test -e /home/{OAUTH_AGENT}/.claude",
                    f"! test -e /home/{OAUTH_AGENT}/.claude/clawrium-credentials.env",
                    f"! test -e /home/{OAUTH_AGENT}/.profile.d/clawrium-claude.sh",
                    f"! test -e /var/lib/clawrium/claude/{OAUTH_AGENT}.json",
                )
            )
        )
        if _agent_record(self.host_alias, OAUTH_AGENT) is not None:
            _fail("agent record remains after successful removal")
        if get_provider(OAUTH_PROVIDER) is not None:
            _fail("selection-only provider record remains after cleanup")
        if self._local_secret_scope_present():
            _fail("local per-instance secret scope remains after removal")
        if _agent_snapshot(self.host_alias) != before:
            _fail("a pre-existing agent fleet record changed during E2E")

    def run(self) -> OAuthEvidence:
        evidence = OAuthEvidence()
        before = _agent_snapshot(self.host_alias)
        stage = "preflight"
        try:
            self._assert_fresh()
            stage = "agent_create"
            self._mutate(
                [
                    "agent",
                    "create",
                    OAUTH_AGENT,
                    "--type",
                    "claude",
                    "--host",
                    self.host_alias,
                ],
                action=f"clawctl agent create {OAUTH_AGENT} --type claude --host {self.host_alias}",
                notes="Issue #1015 isolated install-only validation",
            )
            self.agent_created = True
            stage = "install_only"
            self._assert_install_only()
            evidence.install_only = True

            stage = "provider_create"
            self._mutate(
                [
                    "provider",
                    "registry",
                    "create",
                    OAUTH_PROVIDER,
                    "--type",
                    "claude-oauth",
                ],
                action=f"clawctl provider registry create {OAUTH_PROVIDER} --type claude-oauth",
                notes="Issue #1015 normal provider registration",
            )
            self.provider_created = True
            stage = "provider_registration"
            self._assert_provider_registration()
            evidence.provider_registered = True

            stage = "provider_attach"
            self._attach_provider()
            evidence.provider_attached = True
            evidence.local_oauth_reader_used = True
            stage = "local_secret_metadata"
            self._assert_attachment_and_local_secret_metadata()

            stage = "agent_sync"
            self._mutate(
                ["agent", "sync", OAUTH_AGENT],
                action=f"clawctl agent sync {OAUTH_AGENT}",
                notes="Issue #1015 OAuth credential activation",
            )
            evidence.credential_synced = True
            stage = "remote_activation"
            self._assert_activation()
            evidence.credential_file_private = True
            evidence.oauth_nonempty = True
            evidence.api_key_empty = True
            stage = "state_redaction"
            self._assert_state_redacted()
            evidence.state_redacted = True
            evidence.cli_output_redacted = True
        except LocalOAuthReaderFailure as exc:
            evidence.failures.append(f"LOCAL_OAUTH_{exc.category.upper()}")
        except E2EFailure:
            evidence.failures.append(f"E2E_ASSERTION_FAILURE_{stage.upper()}")
        except Exception:
            # Do not serialize arbitrary exception text: it could contain a
            # future dependency's unsafe command output.
            evidence.failures.append("UNEXPECTED_E2E_FAILURE")
        finally:
            try:
                self._delete_agent_if_present()
                self._delete_provider_if_present()
                self._assert_cleanup(before)
                evidence.cleanup_verified = True
                evidence.preexisting_agents_preserved = True
            except Exception:
                evidence.failures.append("CLEANUP_OR_PRESERVATION_FAILURE")
            evidence.completed_at = _utc_now()
        return evidence


def _checkbox(value: bool) -> str:
    return "PASS" if value else "FAIL"


def _render_evidence(host_alias: str, result: OAuthEvidence) -> str:
    """Render only fixed non-secret E2E facts; never command transcripts."""
    lines = [
        "# Issue #1015 — Real Claude OAuth Provider E2E Evidence",
        "",
        f"**Host alias:** `{host_alias}` (i-wolf)",
        f"**Completed:** {result.completed_at or _utc_now()}",
        "",
        "## Safety boundary",
        "",
        "- OAuth was imported only by normal `clawctl agent provider attach` selection; no direct secret command, dummy credential, or caller OAuth environment variable was used.",
        "- The attachment invokes #1013's narrow local credential reader. It accepts only the current user's validated Claude OAuth access-token field; this harness never prints, copies, hashes, or persists it outside Clawrium's existing per-instance secret flow.",
        "- The harness starts no Claude process: the only agent command is the existing finite `agent shell` environment assertion, which prints fixed booleans only.",
        "- CLI output is captured only in memory for assignment-shape redaction checks and is not included in this evidence.",
        "",
        "## Commands exercised",
        "",
        "- `clawctl agent create claude-oauth-e2e --type claude --host wolf-i`",
        "- `clawctl provider registry create claude-oauth-e2e-provider --type claude-oauth`",
        "- `clawctl agent provider attach claude-oauth-e2e-provider --agent claude-oauth-e2e`",
        "- `clawctl agent sync claude-oauth-e2e`",
        "- `clawctl agent shell claude-oauth-e2e -- <redacted boolean assertion>`",
        "- `clawctl agent delete --yes claude-oauth-e2e`",
        "- `clawctl provider registry delete --yes claude-oauth-e2e-provider`",
        "",
        "## Assertions",
        "",
        f"- Install-only: **{_checkbox(result.install_only)}** — no Claude process, service, gateway, port, UI state, local credential, remote `.claude`, or startup hook before OAuth sync.",
        f"- Selection-only provider registration: **{_checkbox(result.provider_registered)}**",
        f"- Normal OAuth attachment: **{_checkbox(result.provider_attached)}**",
        f"- Supported local reader path: **{_checkbox(result.local_oauth_reader_used)}**",
        f"- Sync activation: **{_checkbox(result.credential_synced)}**",
        f"- Credential file ownership and mode: **{_checkbox(result.credential_file_private)}** — agent-owned `0600`.",
        f"- Redacted agent-shell booleans: OAuth nonempty **{_checkbox(result.oauth_nonempty)}**; `ANTHROPIC_API_KEY` empty **{_checkbox(result.api_key_empty)}**.",
        f"- State/settings/CLI-event redaction assertions: **{_checkbox(result.state_redacted and result.cli_output_redacted)}**",
        f"- Owned-resource cleanup: **{_checkbox(result.cleanup_verified)}** — account, home, prefix, full `.claude`, credential and startup files, ownership marker, local per-instance secret scope, hosts record, and temporary provider record absent.",
        f"- Pre-existing fleet records preserved: **{_checkbox(result.preexisting_agents_preserved)}**",
        "",
    ]
    if result.failures:
        lines.extend(
            (
                "## Result",
                "",
                "**FAIL** — " + ", ".join(result.failures),
                "",
                "## Diagnostic category",
                "",
                "- `LOCAL_OAUTH_<CATEGORY>` means the normal provider attachment could not obtain local OAuth. The category is fixed and secret-free; no reader output or credential detail was recorded.",
                "",
            )
        )
    else:
        lines.extend(("## Result", "", "**PASS**", ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="Configured i-wolf host alias.")
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="Markdown evidence path (contains no command transcripts or values).",
    )
    args = parser.parse_args()

    # Keep caller credentials out of this process as well as every child. The
    # real source is selected only by the provider attachment's safe reader.
    for key in _CREDENTIAL_SOURCE_ENVIRONMENT:
        os.environ.pop(key, None)

    runner = ClaudeOAuthProviderE2E(args.host)
    result = runner.run()
    evidence = _render_evidence(args.host, result)
    _assert_output_has_no_credential_assignment(evidence)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(evidence)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
