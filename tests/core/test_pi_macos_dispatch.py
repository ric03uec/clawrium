"""Mocked Darwin routing contracts for Pi lifecycle playbooks."""

from pathlib import Path

from clawrium.core.playbook_resolver import resolve_agent_playbook


def test_pi_darwin_lifecycle_playbooks_are_selected():
    for operation, suffix in (
        ("install", "install_macos.yaml"),
        ("exec", "exec_macos.yaml"),
        ("remove", "remove_macos.yaml"),
    ):
        path = resolve_agent_playbook("pi", operation, "darwin")
        assert (
            path == Path("src/clawrium/platform/registry/pi/playbooks") / suffix
            or path.name == suffix
        )
