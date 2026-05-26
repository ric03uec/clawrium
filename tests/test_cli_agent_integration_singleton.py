"""Singleton guard: only one `git` integration may be attached per agent.

Phase 2's playbook loop writes ~/.gitconfig once per assigned git integration
with `ansible.builtin.template` (force: yes by default). A second attach
would silently overwrite the first. The CLI rejects the second attach
before it can be persisted. Tests drive the CLI runner against a hosts.json
that wires the agent dict the way `add_agent_integration` expects (keyed
by the agent name returned from `get_installed_claw`).
"""

import json

from typer.testing import CliRunner
from clawrium.cli.main import app
from clawrium.core.integrations import INTEGRATIONS_FILE


runner = CliRunner()


def _seed(config_dir, integrations):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / INTEGRATIONS_FILE).write_text(json.dumps(integrations))
    # hosts.json with the agent dict keyed by agent name so
    # add_agent_integration's `agents[claw_name]` lookup succeeds.
    hosts_data = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "port": 22,
            "agent_name": "xclm",
            "agents": {
                "opc-work": {
                    "type": "openclaw",
                    "version": "0.1.0",
                    "status": "installed",
                    "name": "work",
                    "agent_name": "opc-work",
                    "integrations": [],
                }
            },
        }
    ]
    (config_dir / "hosts.json").write_text(json.dumps(hosts_data))


def test_second_git_attach_is_rejected(isolated_config):
    _seed(
        isolated_config,
        [
            {"name": "git-personal", "type": "git"},
            {"name": "git-work", "type": "git"},
        ],
    )

    first = runner.invoke(
        app, ["agent", "integration", "add", "work", "git-personal"]
    )
    assert first.exit_code == 0, first.output

    second = runner.invoke(
        app, ["agent", "integration", "add", "work", "git-work"]
    )
    assert second.exit_code == 1, second.output
    assert "already has a git integration" in second.output.lower()
    assert "git-personal" in second.output


def test_git_attach_does_not_block_non_git_types(isolated_config):
    _seed(
        isolated_config,
        [
            {"name": "g", "type": "git"},
            {"name": "gh", "type": "github"},
        ],
    )

    first = runner.invoke(app, ["agent", "integration", "add", "work", "g"])
    assert first.exit_code == 0, first.output

    second = runner.invoke(app, ["agent", "integration", "add", "work", "gh"])
    assert second.exit_code == 0, second.output


def test_re_attaching_same_git_integration_is_idempotent(isolated_config):
    _seed(isolated_config, [{"name": "g", "type": "git"}])

    runner.invoke(app, ["agent", "integration", "add", "work", "g"])
    again = runner.invoke(app, ["agent", "integration", "add", "work", "g"])

    assert again.exit_code == 0, again.output
    # Idempotent path emits "already assigned", not the singleton-block error.
    assert "already has a git integration" not in again.output.lower()
