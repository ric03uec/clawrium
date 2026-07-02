"""Tests for `clawctl agent integration attach` — attach-time agent-type
gate (B8 fix in #834 / #499 Phase 1).

The gate lives in `src/clawrium/cli/clawctl/agent/integration.py:attach()`
and consumes the `_atype` return from `safe_resolve_agent()`. Without
this guard, the CLI writes hosts.json unconditionally for any
(agent, integration) pair and the render layer is the only enforcement
point — exactly the #555-class regression pattern the plan's
"coming-soon contract" is meant to prevent.

The default `fleet_dir` fixture ships an openclaw agent named
`wise-hypatia` on host `wolf-i`. Tests that need a hermes agent add
one by mutating the seed hosts.json in-place.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from typer.testing import CliRunner

from clawrium.cli import app

runner = CliRunner()


def _add_agent(
    fleet_dir: Path, *, name: str, atype: str, version: str = "1.0.0"
) -> None:
    """Append an agent of the given type to the seed hosts.json."""
    hosts_path = fleet_dir / "hosts.json"
    hosts = json.loads(hosts_path.read_text())
    now = datetime.now(timezone.utc).isoformat()
    hosts[0]["agents"][name] = {
        "type": atype,
        "agent_name": name,
        "name": name,
        "version": version,
        "installed_at": now,
        "status": "installed",
        "onboarding": {"state": "ready", "stages": {}},
        "config": {},
    }
    hosts_path.write_text(json.dumps(hosts, indent=2))


def _add_hermes_agent(fleet_dir: Path, name: str = "maurice") -> None:
    _add_agent(fleet_dir, name=name, atype="hermes", version="2026.5.29.2")


def _add_zeroclaw_agent(fleet_dir: Path, name: str = "kevin") -> None:
    _add_agent(fleet_dir, name=name, atype="zeroclaw", version="2026.6.9")


def _create_integration(name: str, type_: str, credentials: dict[str, str]) -> None:
    """Create an integration and ASSERT success — otherwise gate tests
    would silently degrade to "attach unknown integration" tests. #834
    (ATX iter-1 W4)."""
    argv = [
        "integration",
        "registry",
        "create",
        name,
        "--type",
        type_,
    ]
    for k, v in credentials.items():
        argv.extend(["--credential", f"{k}={v}"])
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, (
        f"integration/{name}: setup failed with exit "
        f"{result.exit_code}: {result.output}"
    )


# ---------------------------------------------------------------------------
# Rejection cases: unsupported (agent-type, integration-type) pairs
# ---------------------------------------------------------------------------


def _hosts_json_agent_integrations(fleet_dir, agent_name: str) -> list[str]:
    """Read back the persisted integration list for an agent so
    positive-path tests can assert the write actually happened.

    The seed hosts.json keys agents by type (`openclaw`, `hermes`, …)
    not by `agent_name`, so we walk every agent record and match on
    `agent_name` to stay symmetric with how the CLI's
    `safe_resolve_agent` picks the record."""
    import json

    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    for host in hosts:
        for _key, agent in host.get("agents", {}).items():
            if agent.get("agent_name") == agent_name:
                return list(agent.get("integrations", []))
    raise AssertionError(f"agent {agent_name!r} not found in hosts.json")


def test_attach_slack_user_to_openclaw_succeeds(fleet_dir, stdin_not_tty) -> None:
    """#835 (Phase 2): openclaw NOW supports slack-user. The gate must
    let the attach through AND persist to hosts.json — an exit-0 that
    silently skipped the write is the exact regression pattern the
    coming-soon contract in #499 is meant to prevent. (ATX #835 iter-2
    W6)."""
    _create_integration(
        "slack-work", "slack-user", {"SLACK_MCP_XOXP_TOKEN": "xoxp-1"}
    )
    result = runner.invoke(
        app,
        ["agent", "integration", "attach", "slack-work", "--agent", "wise-hypatia"],
    )
    assert result.exit_code == 0, result.output
    assert "slack-work" in _hosts_json_agent_integrations(
        fleet_dir, "wise-hypatia"
    )


def test_attach_slack_cookie_to_openclaw_succeeds(fleet_dir, stdin_not_tty) -> None:
    """#835 (Phase 2): cookie mode is also accepted on openclaw. Also
    asserts hosts.json persistence per ATX #835 iter-2 W6."""
    _create_integration(
        "slack-legacy",
        "slack-cookie",
        {"SLACK_MCP_XOXC_TOKEN": "xoxc-1", "SLACK_MCP_XOXD_TOKEN": "xoxd-1"},
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "integration",
            "attach",
            "slack-legacy",
            "--agent",
            "wise-hypatia",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "slack-legacy" in _hosts_json_agent_integrations(
        fleet_dir, "wise-hypatia"
    )


def test_attach_slack_user_to_zeroclaw_succeeds(fleet_dir, stdin_not_tty) -> None:
    """#836 (Phase 3): zeroclaw NOW supports slack-user. The gate must
    let this through — mirrors the openclaw positive-case Phase 2
    transition. Replaces the Phase-1 rejection test."""
    _add_zeroclaw_agent(fleet_dir, name="kevin")
    _create_integration(
        "slack-work", "slack-user", {"SLACK_MCP_XOXP_TOKEN": "xoxp-1"}
    )
    result = runner.invoke(
        app,
        ["agent", "integration", "attach", "slack-work", "--agent", "kevin"],
    )
    assert result.exit_code == 0, result.output
    assert "slack-work" in _hosts_json_agent_integrations(fleet_dir, "kevin")


def test_attach_slack_cookie_to_zeroclaw_succeeds(fleet_dir, stdin_not_tty) -> None:
    """#836: zeroclaw + slack-cookie also accepted."""
    _add_zeroclaw_agent(fleet_dir, name="kevin")
    _create_integration(
        "slack-legacy",
        "slack-cookie",
        {"SLACK_MCP_XOXC_TOKEN": "xoxc-1", "SLACK_MCP_XOXD_TOKEN": "xoxd-1"},
    )
    result = runner.invoke(
        app,
        [
            "agent",
            "integration",
            "attach",
            "slack-legacy",
            "--agent",
            "kevin",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "slack-legacy" in _hosts_json_agent_integrations(fleet_dir, "kevin")


# ---------------------------------------------------------------------------
# Positive cases: supported pairs still work
# ---------------------------------------------------------------------------


def test_attach_slack_user_to_hermes_succeeds(fleet_dir, stdin_not_tty) -> None:
    """hermes DOES support slack-user in Phase 1 — the gate must let
    this through unchanged."""
    _add_hermes_agent(fleet_dir, name="maurice")
    _create_integration(
        "slack-work", "slack-user", {"SLACK_MCP_XOXP_TOKEN": "xoxp-1"}
    )
    result = runner.invoke(
        app,
        ["agent", "integration", "attach", "slack-work", "--agent", "maurice"],
    )
    assert result.exit_code == 0, result.output


def test_attach_slack_cookie_to_hermes_succeeds(fleet_dir, stdin_not_tty) -> None:
    """#834 (ATX iter-1 W6): hermes supports both slack types. A
    future refactor excluding `slack-cookie` from the frozenset would
    be invisible without this positive test."""
    _add_hermes_agent(fleet_dir, name="maurice")
    _create_integration(
        "slack-legacy",
        "slack-cookie",
        {"SLACK_MCP_XOXC_TOKEN": "xoxc-1", "SLACK_MCP_XOXD_TOKEN": "xoxd-1"},
    )
    result = runner.invoke(
        app,
        ["agent", "integration", "attach", "slack-legacy", "--agent", "maurice"],
    )
    assert result.exit_code == 0, result.output


def test_attach_atlassian_to_hermes_still_succeeds(
    fleet_dir, stdin_not_tty
) -> None:
    """Regression guard for the pre-existing atlassian path — the
    gate must not accidentally reject legacy integration types."""
    _add_hermes_agent(fleet_dir, name="maurice")
    _create_integration(
        "atl",
        "atlassian",
        {
            "ATLASSIAN_URL": "https://co.atlassian.net",
            "ATLASSIAN_EMAIL": "u@x.com",
            "ATLASSIAN_API_TOKEN": "tk",
        },
    )
    result = runner.invoke(
        app, ["agent", "integration", "attach", "atl", "--agent", "maurice"]
    )
    assert result.exit_code == 0, result.output


def test_attach_github_to_openclaw_still_succeeds(fleet_dir, stdin_not_tty) -> None:
    """Regression guard: github IS supported on openclaw — the gate
    must not reject it."""
    _create_integration("gh", "github", {"GITHUB_TOKEN": "t"})
    result = runner.invoke(
        app, ["agent", "integration", "attach", "gh", "--agent", "wise-hypatia"]
    )
    assert result.exit_code == 0, result.output
