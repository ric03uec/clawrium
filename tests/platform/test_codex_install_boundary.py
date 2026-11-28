"""Daemonless Codex installation boundary contracts (#1034)."""

from __future__ import annotations

from pathlib import Path

import yaml

from clawrium.core.registry import list_claws, load_manifest


ROOT = Path(__file__).parents[2]
CODEX_ROOT = ROOT / "src" / "clawrium" / "platform" / "registry" / "codex"
PINNED_VERSION = "0.160.1"


def _playbook(name: str) -> dict:
    document = yaml.safe_load((CODEX_ROOT / "playbooks" / name).read_text())
    assert isinstance(document, list)
    return document[0]


def _task(playbook: dict, name: str) -> dict:
    return next(task for task in playbook["tasks"] if task["name"] == name)


def test_codex_manifest_is_discoverable_and_daemonless() -> None:
    manifest = load_manifest("codex")

    assert "codex" in list_claws()
    assert manifest["agent"] == {
        "type": "codex",
        "description": "OpenAI Codex CLI (on-demand CLI chat; no daemon or web UI)",
    }
    assert manifest["features"] == {"chat": {"type": "codex"}}
    assert {entry["version"] for entry in manifest["platforms"]} == {PINNED_VERSION}
    assert {
        (entry["os"], entry["os_version"], entry["arch"])
        for entry in manifest["platforms"]
    } == {
        ("ubuntu", "22.04", "x86_64"),
        ("ubuntu", "24.04", "x86_64"),
        ("macos", ">=14", "arm64"),
    }


def test_codex_install_runbooks_use_a_private_pinned_npm_prefix() -> None:
    for name, home, group in (
        ("install.yaml", "/home/{{ agent_name }}", "{{ agent_name }}"),
        ("install_macos.yaml", "/Users/{{ agent_name }}", "staff"),
    ):
        playbook = _playbook(name)
        variables = playbook["vars"]
        serialized = yaml.safe_dump(playbook)

        assert variables["codex_package_name"] == "@openai/codex"
        assert variables["codex_default_version"] == PINNED_VERSION
        assert variables["codex_home"] == home
        assert variables["codex_prefix"] == "{{ codex_home }}/.local/codex"
        assert "codex_already_installed" in serialized
        assert "ansible.builtin.systemd" not in serialized
        assert "ansible.builtin.service" not in serialized

        install = _task(playbook, "Install pinned Codex CLI package into owned prefix")
        assert install["ansible.builtin.command"]["argv"][-1] == (
            "{{ codex_package_name }}@{{ codex_package_version }}"
        )
        assert install["become_user"] == "{{ agent_name }}"
        assert _task(playbook, "Create owned Codex CLI install prefix")[
            "ansible.builtin.file"
        ]["group"] == group


# #1071 phase 5 removed `codex/playbooks/exec.yaml` + `exec_macos.yaml`
# along with the agent-exec subsystem. The corresponding boundary test
# (`test_codex_exec_runbooks_run_only_the_private_binary_with_safe_transport`)
# is gone with the runbooks.


def test_codex_remove_runbooks_only_remove_dedicated_resources() -> None:
    for name, home in (
        ("remove.yaml", "/home/{{ agent_name }}"),
        ("remove_macos.yaml", "/Users/{{ agent_name }}"),
    ):
        serialized = yaml.safe_dump(_playbook(name))
        assert "{{ codex_home }}/.local/codex" in serialized
        assert "{{ codex_home }}/.codex/auth.json" in serialized
        assert home in serialized
        assert "npm uninstall" not in serialized
