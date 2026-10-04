"""Contracts for scoped, checksum-verified Herdr provisioning (#1018)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import clawrium.core.install as install
from clawrium.core.install import InstallationError, run_installation

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


def _mock_install_dependencies(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, os_family: str
) -> None:
    manifest = {
        "name": "test",
        "entries": [
            {
                "version": "1",
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "requirements": {},
            }
        ],
    }
    host = {
        "hostname": "host",
        "alias": "host",
        "agent_name": "agent",
        "port": 22,
        "key_id": "key",
        "os_family": os_family,
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    key = tmp_path / "key"
    key.write_text("key")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(install, "load_manifest", lambda _: manifest)
    monkeypatch.setattr(install, "get_host", lambda _: host)
    monkeypatch.setattr(install, "get_host_private_key", lambda _: key)
    monkeypatch.setattr(
        install,
        "check_compatibility",
        lambda *_: {
            "compatible": True,
            "matched_entry": manifest["entries"][0],
            "reasons": [],
        },
    )
    monkeypatch.setattr(install, "update_host", lambda _, update: update(host))
    monkeypatch.setattr(install, "initialize_onboarding", lambda *_: True)


@pytest.mark.parametrize("agent_type", ["hermes", "claude"])
@pytest.mark.parametrize("os_family, suffix", [("linux", ""), ("darwin", "_macos")])
def test_herdr_dispatch_runs_between_base_and_agent(
    monkeypatch, tmp_path, agent_type, os_family, suffix
) -> None:
    _mock_install_dependencies(monkeypatch, tmp_path, os_family)
    calls = []

    class Result:
        status = "successful"
        config = SimpleNamespace(artifact_dir=str(tmp_path))

    monkeypatch.setattr(
        install.ansible_runner,
        "run",
        lambda **kwargs: calls.append(kwargs["playbook"]) or Result(),
    )
    run_installation(agent_type, "host")
    assert [Path(path).name for path in calls] == [
        f"base{suffix}.yaml",
        f"herdr{suffix}.yaml",
        f"install{suffix}.yaml",
    ]


@pytest.mark.parametrize("agent_type", ["openclaw", "zeroclaw", "ethos"])
def test_excluded_agents_skip_herdr(monkeypatch, tmp_path, agent_type) -> None:
    _mock_install_dependencies(monkeypatch, tmp_path, "linux")
    calls = []

    class Result:
        status = "successful"
        config = SimpleNamespace(artifact_dir=str(tmp_path))

    monkeypatch.setattr(
        install.ansible_runner,
        "run",
        lambda **kwargs: calls.append(kwargs["playbook"]) or Result(),
    )
    run_installation(agent_type, "host")
    assert [Path(path).name for path in calls] == ["base.yaml", "install.yaml"]


def test_herdr_failure_stops_agent_playbook_and_cleans_artifacts(monkeypatch, tmp_path) -> None:
    _mock_install_dependencies(monkeypatch, tmp_path, "linux")
    calls = []
    cleanup_paths = []
    monkeypatch.setattr(install, "_cleanup_ansible_artifacts", cleanup_paths.append)

    class Result:
        config = SimpleNamespace(artifact_dir=str(tmp_path))

        def __init__(self, status):
            self.status = status

    monkeypatch.setattr(
        install.ansible_runner,
        "run",
        lambda **kwargs: (
            calls.append(kwargs["playbook"])
            or Result(
                "failed"
                if Path(kwargs["playbook"]).name == "herdr.yaml"
                else "successful"
            )
        ),
    )
    with pytest.raises(InstallationError, match="Herdr playbook failed"):
        run_installation("hermes", "host")
    assert [Path(path).name for path in calls] == ["base.yaml", "herdr.yaml"]
    # Runner artifacts can contain cacheable credentials. The install finally
    # block must clean all deterministic stage directories even on a Herdr
    # failure, including the stage that never started.
    assert [path.name for path in cleanup_paths] == ["base", "herdr", "claw"]


@pytest.mark.parametrize("os_family", ["windows", "freebsd"])
def test_herdr_resolver_rejects_unsupported_os(os_family) -> None:
    with pytest.raises(ValueError, match="unsupported os_family"):
        resolve_herdr_playbook(os_family)


def test_herdr_resolver_reports_missing_playbook(monkeypatch) -> None:
    import clawrium.core.playbook_resolver as resolver

    monkeypatch.setattr(resolver.Path, "exists", lambda _: False)
    with pytest.raises(FileNotFoundError, match="Herdr playbook.*not found"):
        resolver.resolve_herdr_playbook("linux")


def test_no_removal_playbook_removes_shared_herdr() -> None:
    for path in ROOT.glob("src/clawrium/platform/registry/*/playbooks/remove*.yaml"):
        assert "herdr" not in path.read_text().lower(), path
