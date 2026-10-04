#!/usr/bin/env python3
"""Redacted real-host Herdr install E2E for Hermes and Claude.

Run after local checks from this worktree::

    uv run python scripts/e2e/herdr_install_e2e.py --host wolf-i \
      --evidence .itx/1018/02_E2E_HERDR.md

The script creates two uniquely named fresh agents, preserves all pre-existing
fleet records, writes only boolean evidence, removes the test agents in a
finally block, and intentionally leaves the host-shared /usr/local/bin/herdr.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from clawrium.core.hosts import get_host
from clawrium.core.keys import get_host_private_key

HERMES_AGENT = "herdr-hermes-e2e"
CLAUDE_AGENT = "herdr-claude-e2e"
# Existing wolf-i test provider. It is attached only to the disposable Hermes
# agent and is never created, edited, or deleted by this script.
HERMES_PROVIDER = "wolf-i-litellm-qwen"
CLI = "from clawrium.cli import app; app()"


class E2EFailure(RuntimeError):
    """A safe assertion failure to record without command transcripts."""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _run(command: list[str], expected: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != expected:
        raise E2EFailure(f"command failed with exit status {result.returncode}")
    return result


def _cli(args: list[str], expected: int = 0) -> subprocess.CompletedProcess[str]:
    try:
        return _run([sys.executable, "-c", CLI, *args], expected)
    except E2EFailure as exc:
        # Arguments are fixed by this harness and contain no credentials.
        raise E2EFailure(f"clawctl {' '.join(args)}: {exc}") from exc


@dataclass
class Evidence:
    started_at: str = field(default_factory=_now)
    host: str = ""
    preexisting_agents_preserved: bool = False
    shared_binary_installed: bool = False
    hermes_plugin_installed: bool = False
    hermes_plugin_persists_after_sync: bool = False
    claude_binary_only: bool = False
    shared_binary_reused: bool = False
    cleanup_verified: bool = False
    shared_binary_retained: bool = False
    failures: list[str] = field(default_factory=list)
    completed_at: str | None = None

    @property
    def passed(self) -> bool:
        return not self.failures and all(
            (
                self.preexisting_agents_preserved,
                self.shared_binary_installed,
                self.hermes_plugin_installed,
                self.hermes_plugin_persists_after_sync,
                self.claude_binary_only,
                self.shared_binary_reused,
                self.cleanup_verified,
                self.shared_binary_retained,
            )
        )


class HerdrE2E:
    def __init__(self, alias: str) -> None:
        self.alias = alias
        self.host = get_host(alias)
        if self.host is None:
            raise E2EFailure(f"host {alias!r} is not registered")
        key = get_host_private_key(
            str(self.host.get("key_id") or self.host["hostname"])
        )
        if key is None:
            raise E2EFailure("i-wolf SSH key is not available")
        self.key = str(key)
        self.preexisting = self._fleet_snapshot()
        self.created: list[str] = []

    def _fleet_snapshot(self) -> set[str]:
        return set(get_host(self.alias).get("agents", {})) - {
            HERMES_AGENT,
            CLAUDE_AGENT,
        }

    def _remote(self, command: str) -> None:
        remote = "sudo -n bash -eu -o pipefail -c " + shlex.quote(command)
        _run(
            [
                "ssh",
                "-i",
                self.key,
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                f"{self.host.get('user', 'xclm')}@{self.host['hostname']}",
                remote,
            ]
        )

    def _create(self, name: str, agent_type: str) -> None:
        _cli(["agent", "create", name, "--type", agent_type, "--host", self.alias])
        self.created.append(name)

    def run(self, evidence: Evidence) -> None:
        self._create(HERMES_AGENT, "hermes")
        self._remote(
            f"test -x /usr/local/bin/herdr && /usr/local/bin/herdr --version >/dev/null && "
            f"test -d /home/{HERMES_AGENT}/.hermes/plugins/herdr-agent-state && "
            f"grep -Eq '^[[:space:]]*-[[:space:]]*herdr-agent-state$' /home/{HERMES_AGENT}/.hermes/config.yaml"
        )
        evidence.shared_binary_installed = True
        evidence.hermes_plugin_installed = True
        # Use the existing wolf-i provider only on this disposable agent, then
        # run the ordinary canonical sync path.
        _cli(
            [
                "agent",
                "provider",
                "attach",
                HERMES_PROVIDER,
                "--agent",
                HERMES_AGENT,
                "--role",
                "primary",
            ]
        )
        _cli(["agent", "sync", HERMES_AGENT])
        self._remote(
            f"grep -Eq '^[[:space:]]*-[[:space:]]*herdr-agent-state$' /home/{HERMES_AGENT}/.hermes/config.yaml"
        )
        evidence.hermes_plugin_persists_after_sync = True

        self._create(CLAUDE_AGENT, "claude")
        self._remote(
            f"su -s /bin/bash - {CLAUDE_AGENT} -c '/home/{CLAUDE_AGENT}/.local/claude/bin/claude --version >/dev/null && herdr --version >/dev/null' && "
            f"test ! -e /home/{CLAUDE_AGENT}/.hermes/plugins/herdr-agent-state"
        )
        evidence.claude_binary_only = True
        evidence.shared_binary_reused = True

    def cleanup(self, evidence: Evidence) -> None:
        for name in reversed(self.created):
            _cli(["agent", "delete", "--yes", name])
        self.created.clear()
        self._remote(
            "test -x /usr/local/bin/herdr && /usr/local/bin/herdr --version >/dev/null"
        )
        evidence.shared_binary_retained = True
        evidence.cleanup_verified = all(
            get_host(self.alias).get("agents", {}).get(name) is None
            for name in (HERMES_AGENT, CLAUDE_AGENT)
        )
        evidence.preexisting_agents_preserved = (
            self._fleet_snapshot() == self.preexisting
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="wolf-i")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    evidence = Evidence(host=args.host)
    runner: HerdrE2E | None = None
    try:
        runner = HerdrE2E(args.host)
        runner.run(evidence)
    except (E2EFailure, KeyError) as exc:
        evidence.failures.append(str(exc))
    finally:
        if runner is not None:
            try:
                runner.cleanup(evidence)
            except E2EFailure as exc:
                evidence.failures.append(f"cleanup: {exc}")
        evidence.completed_at = _now()
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(
            "# Herdr i-wolf E2E\n\n```json\n"
            + json.dumps(asdict(evidence), indent=2, sort_keys=True)
            + "\n```\n"
        )
    return 0 if evidence.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
