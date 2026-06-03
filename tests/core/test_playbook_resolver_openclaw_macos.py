"""Resolver dispatch tests for openclaw on darwin (issue #604).

Asserts that all five op-level playbooks are present, plus exec_macos,
so that runtime never surfaces a FileNotFoundError for a documented op.
"""

import pytest

from clawrium.core.playbook_resolver import resolve_agent_playbook


@pytest.mark.parametrize(
    "op",
    ["install", "configure", "start", "stop", "remove", "exec"],
)
def test_openclaw_darwin_playbook_resolves(op):
    path = resolve_agent_playbook("openclaw", op, "darwin")
    assert path.exists()
    assert path.name == f"{op}_macos.yaml"
    # Guard against accidental mis-routing to another agent's directory.
    assert "registry/openclaw/playbooks" in str(path)
