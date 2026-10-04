"""Contracts for scoped, checksum-verified Herdr provisioning (#1018)."""

from pathlib import Path

import yaml

from clawrium.core.playbook_resolver import resolve_herdr_playbook


ROOT = Path(__file__).parents[2]
PLAYBOOKS = ROOT / "src" / "clawrium" / "platform" / "playbooks"
HERMES = ROOT / "src" / "clawrium" / "platform" / "registry" / "hermes"


def _playbook(name: str) -> dict:
    return yaml.safe_load((PLAYBOOKS / name).read_text())[0]


def test_herdr_playbooks_pin_verified_official_release_assets() -> None:
    """Both OS siblings use v0.9.3 assets and the published release hashes."""
    expected = {
        "herdr.yaml": {
            "x86_64": "18a8dc65f1c2fa485884344356dea1cfd911c6f06cf46fa78e193f4087f4dba7",
            "aarch64": "4de7aa3e25678812e92960de64f7c2aaa1bca1f0f80a3c5e559837e231e1f5c0",
        },
        "herdr_macos.yaml": {
            "x86_64": "db62d548ff3e832b087a96b1894a08d26be3905f1830309cd556783f215d4054",
            "arm64": "5173a3e0ae42d5d1ab7ebfa5d5e6329f7c3d23f8e1a3677c7ce3231da2884157",
        },
    }
    for name, checksums in expected.items():
        play = _playbook(name)
        assert play["vars"]["herdr_version"] == "v0.9.3"
        assert play["vars"]["herdr_sha256_map"] == checksums
        install = next(
            task
            for task in play["tasks"]
            if task["name"] == "Install verified shared Herdr binary"
        )
        spec = install["ansible.builtin.get_url"]
        assert spec["dest"] == "/usr/local/bin/herdr"
        assert spec["owner"] == "root"
        assert spec["checksum"] == "sha256:{{ herdr_sha256_map[ansible_architecture] }}"


def test_herdr_resolver_selects_os_siblings() -> None:
    assert resolve_herdr_playbook("linux").name == "herdr.yaml"
    assert resolve_herdr_playbook("darwin").name == "herdr_macos.yaml"


def test_herdr_is_scoped_to_hermes_and_claude_install_dispatch() -> None:
    body = (ROOT / "src" / "clawrium" / "core" / "install.py").read_text()
    assert 'if claw_name in ("hermes", "claude"):' in body
    assert "herdr_playbook = _get_herdr_playbook_path(host_os_family)" in body
    dispatch = body[
        body.index('if claw_name in ("hermes", "claude"):') : body.index(
            "# Step 9: Run agent playbook"
        )
    ]
    for excluded in ("openclaw", "zeroclaw", "ethos"):
        assert excluded not in dispatch


def test_hermes_installs_official_integration_and_renderer_keeps_plugin() -> None:
    for name in ("install.yaml", "install_macos.yaml"):
        body = (HERMES / "playbooks" / name).read_text()
        assert (
            "herdr integration install hermes" not in body
        )  # argv prevents shell mutation
        assert "- integration\n          - install\n          - hermes" in body
        assert 'become_user: "{{ agent_name }}"' in body
        assert "herdr_hermes_plugin_dir" in body
        assert "herdr_hermes_plugin_config" in body
    template = (HERMES / "templates" / "hermes-config.canonical.yaml.j2").read_text()
    assert "plugins:\n  enabled:\n    - herdr-agent-state" in template


def test_no_removal_playbook_removes_shared_herdr() -> None:
    for path in ROOT.glob("src/clawrium/platform/registry/*/playbooks/remove*.yaml"):
        assert "herdr" not in path.read_text().lower(), path
