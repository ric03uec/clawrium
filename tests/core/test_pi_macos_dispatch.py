"""Mocked Darwin routing contracts for Pi lifecycle playbooks."""

from pathlib import Path

from clawrium.core.playbook_resolver import resolve_agent_playbook


def test_pi_darwin_lifecycle_playbooks_are_selected():
    # #1071 phase 5 removed `exec_macos.yaml` along with the agent-exec
    # subsystem. Install + remove routing still need the darwin dispatch
    # path — exec is dropped from the probe.
    for operation, suffix in (
        ("install", "install_macos.yaml"),
        ("remove", "remove_macos.yaml"),
    ):
        path = resolve_agent_playbook("pi", operation, "darwin")
        assert (
            path == Path("src/clawrium/platform/registry/pi/playbooks") / suffix
            or path.name == suffix
        )
