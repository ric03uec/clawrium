"""Install-only boundary contracts for the Claude Code registry type (#995)."""

from __future__ import annotations

import base64
from pathlib import Path
import re
import secrets as stdlib_secrets
from unittest.mock import Mock

from jinja2 import Environment, StrictUndefined
import pytest
import yaml

from clawrium.core.install import _install_was_skipped, run_installation
from clawrium.core.registry import list_claws, load_manifest


PROJECT_ROOT = Path(__file__).parents[2]
CLAUDE_ROOT = PROJECT_ROOT / "src" / "clawrium" / "platform" / "registry" / "claude"
PINNED_VERSION = "2.1.100"
PACKAGE = "@anthropic-ai/claude-code"


def _manifest() -> dict:
    return yaml.safe_load((CLAUDE_ROOT / "manifest.yaml").read_text())


def _tasks(name: str) -> list[dict]:
    playbook = yaml.safe_load((CLAUDE_ROOT / "playbooks" / name).read_text())
    assert isinstance(playbook, list)
    tasks = playbook[0]["tasks"]
    assert isinstance(tasks, list)
    return tasks


def _task(tasks: list[dict], name: str) -> dict:
    return next(task for task in tasks if task["name"] == name)


def _executable_task_texts(tasks: list[dict]) -> list[str]:
    """Return every executable module's payload, excluding task metadata."""
    executable_modules = {
        "ansible.builtin.command",
        "ansible.builtin.raw",
        "ansible.builtin.script",
        "ansible.builtin.shell",
    }
    return [
        yaml.safe_dump(task[module])
        for task in tasks
        for module in executable_modules
        if module in task
    ]


def _successful_runner_result(tmp_path: Path, events: list[dict] | None = None):
    result = Mock()
    result.status = "successful"
    result.events = events or []
    result.config.artifact_dir = str(tmp_path / "artifacts")
    return result


def test_claude_manifest_is_first_class_and_install_only():
    manifest = load_manifest("claude")

    assert "claude" in list_claws()
    assert manifest["agent"] == {
        "type": "claude",
        "description": "Anthropic Claude Code (install-only)",
    }
    assert "features" not in manifest
    assert "secrets" not in manifest
    assert {entry["version"] for entry in manifest["platforms"]} == {PINNED_VERSION}
    assert {
        (entry["os"], entry["os_version"], entry["arch"])
        for entry in manifest["platforms"]
    } == {
        ("ubuntu", "22.04", "x86_64"),
        ("ubuntu", "24.04", "x86_64"),
        ("macos", ">=14", "arm64"),
    }


def test_claude_manifest_pin_matches_both_install_runbooks():
    manifest_versions = {entry["version"] for entry in _manifest()["platforms"]}
    assert manifest_versions == {PINNED_VERSION}

    for name in ("install.yaml", "install_macos.yaml"):
        playbook = yaml.safe_load((CLAUDE_ROOT / "playbooks" / name).read_text())
        assert playbook[0]["vars"]["claude_default_version"] == PINNED_VERSION


def test_claude_install_runbooks_are_state_based_and_never_invoke_claude():
    forbidden_modules = {
        "ansible.builtin.systemd",
        "ansible.builtin.service",
        "ansible.builtin.wait_for",
        "ansible.builtin.uri",
    }
    forbidden_words = ("gateway", "launchctl", "login", "auth", "port")
    # Word-boundary match so a shell literal like ``export`` cannot
    # masquerade as the ``port`` network concept the installer refuses.
    forbidden_patterns = tuple(
        re.compile(rf"(?<![A-Za-z0-9_]){word}(?![A-Za-z0-9_])")
        for word in forbidden_words
    )

    for name, home in (
        ("install.yaml", "/home/{{ agent_name }}"),
        ("install_macos.yaml", "/Users/{{ agent_name }}"),
    ):
        tasks = _tasks(name)
        serialized = yaml.safe_dump(tasks).lower()
        module_names = {key for task in tasks for key in task}
        assert forbidden_modules.isdisjoint(module_names)
        assert not any(pattern.search(serialized) for pattern in forbidden_patterns)

        assert (
            _task(tasks, "Check installed Claude Code package metadata")[
                "ansible.builtin.stat"
            ]["path"]
            == "{{ claude_package_metadata }}"
        )
        assert (
            _task(tasks, "Read installed Claude Code package metadata")[
                "ansible.builtin.slurp"
            ]["src"]
            == "{{ claude_package_metadata }}"
        )
        assert "claude_package_at_target" in yaml.safe_dump(
            _task(tasks, "Set install skip condition")
        )
        assert "force_install" in yaml.safe_dump(
            _task(tasks, "Set install skip condition")
        )
        install_argv = _task(
            tasks, "Install pinned Claude Code package into owned prefix"
        )["ansible.builtin.command"]["argv"]
        assert install_argv == [
            "npm",
            "install",
            "--global",
            "--prefix",
            "{{ claude_prefix }}",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "{{ claude_package_name }}@{{ claude_package_version }}",
        ]
        assert (
            _task(tasks, "Record installed Claude Code package state")[
                "ansible.builtin.copy"
            ]["dest"]
            == "{{ claude_install_state }}"
        )
        playbook = yaml.safe_load((CLAUDE_ROOT / "playbooks" / name).read_text())
        assert playbook[0]["vars"]["claude_home"] == home
        assert playbook[0]["vars"]["claude_prefix"] == "{{ claude_home }}/.local/claude"
        assert "claude_ownership_marker" in playbook[0]["vars"]
        assert _task(tasks, "Reject non-immutable Claude Code package version")[
            "ansible.builtin.fail"
        ]
        assert _task(tasks, "Refuse unmanaged or incomplete dedicated Claude Code account")[
            "ansible.builtin.fail"
        ]
        assert _task(tasks, "Record dedicated Claude Code account ownership")[
            "ansible.builtin.copy"
        ]["mode"] == "0600"
        marker_group = "wheel" if name.endswith("_macos.yaml") else "root"
        marker_assertions = _task(
            tasks, "Verify trusted Claude Code ownership marker permissions"
        )["ansible.builtin.assert"]["that"]
        assert marker_assertions == [
            'claude_ownership_dir_stat.stat.pw_name == "root"',
            f'claude_ownership_dir_stat.stat.gr_name == "{marker_group}"',
            'claude_ownership_dir_stat.stat.mode == "0700"',
            'claude_ownership_marker_stat.stat.pw_name == "root"',
            f'claude_ownership_marker_stat.stat.gr_name == "{marker_group}"',
            'claude_ownership_marker_stat.stat.mode == "0600"',
        ]

        forbidden_executable = re.compile(
            r"(?<![A-Za-z0-9_-])(claude|systemctl|service|launchctl)(?![A-Za-z0-9_-])"
        )
        for executable_text in _executable_task_texts(tasks):
            assert not forbidden_executable.search(executable_text.lower())


@pytest.mark.parametrize("name", ("install.yaml", "install_macos.yaml"))
@pytest.mark.parametrize(
    ("metadata_exists", "slurp_result", "expected"),
    (
        (False, {"skipped": True}, "False"),
        (
            True,
            {
                "content": base64.b64encode(
                    b'{"name":"@anthropic-ai/claude-code","version":"2.1.100"}'
                ).decode()
            },
            "True",
        ),
    ),
)
def test_claude_package_metadata_match_handles_skipped_slurp(
    name: str, metadata_exists: bool, slurp_result: dict, expected: str
):
    """Evaluate the exact Ansible Jinja expression for fresh and repeat installs."""
    package_match = _task(
        _tasks(name), "Determine whether installed package metadata matches the pin"
    )["ansible.builtin.set_fact"]["claude_package_at_target"]
    environment = Environment(undefined=StrictUndefined)
    environment.filters["bool"] = bool
    environment.filters["b64decode"] = lambda value: base64.b64decode(value).decode()
    environment.filters["regex_search"] = lambda value, pattern: re.search(
        pattern, value
    )

    result = environment.from_string(package_match).render(
        claude_package_metadata_stat={"stat": {"exists": metadata_exists}},
        claude_package_metadata_content=slurp_result,
        claude_package_version=PINNED_VERSION,
    )

    assert result.strip() == expected


def test_claude_install_skip_marker_uses_the_generic_idempotency_contract():
    class Result:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"claude_already_installed": True}},
                },
            }
        ]

    assert _install_was_skipped(Result(), "claude") is True


def test_claude_remove_runbooks_only_target_dedicated_resources():
    expected_paths = {
        "{{ claude_home }}/.claude.json",
        "{{ claude_home }}/.claude/.credentials.json",
        "{{ claude_home }}/.claude",
        "{{ claude_prefix }}",
    }

    for name, home in (
        ("remove.yaml", "/home/{{ agent_name }}"),
        ("remove_macos.yaml", "/Users/{{ agent_name }}"),
    ):
        tasks = _tasks(name)
        file_paths = {
            task["ansible.builtin.file"]["path"]
            for task in tasks
            if "ansible.builtin.file" in task
        }
        assert expected_paths.issubset(file_paths)
        assert all(
            not path.startswith(("/usr/", "/etc/", "/opt/")) for path in file_paths
        )
        assert (
            home
            == yaml.safe_load((CLAUDE_ROOT / "playbooks" / name).read_text())[0][
                "vars"
            ]["claude_home"]
        )
        serialized = yaml.safe_dump(tasks).lower()
        assert "systemd" not in serialized
        assert "launchctl" not in serialized
        assert _task(tasks, "Refuse removal of unmanaged or incomplete Claude Code account")[
            "ansible.builtin.fail"
        ]
        assert _task(tasks, "Verify Claude Code account ownership before removal")[
            "ansible.builtin.assert"
        ]
        marker_group = "wheel" if name.endswith("_macos.yaml") else "root"
        assert _task(tasks, "Verify trusted Claude Code ownership marker permissions")[
            "ansible.builtin.assert"
        ]["that"] == [
            'claude_ownership_dir_stat.stat.pw_name == "root"',
            f'claude_ownership_dir_stat.stat.gr_name == "{marker_group}"',
            'claude_ownership_dir_stat.stat.mode == "0700"',
            'claude_ownership_marker_stat.stat.pw_name == "root"',
            f'claude_ownership_marker_stat.stat.gr_name == "{marker_group}"',
            'claude_ownership_marker_stat.stat.mode == "0600"',
        ]
        for task in tasks:
            if task["name"].startswith("Remove ") or task["name"].startswith(
                "Delete dedicated"
            ):
                assert "claude_ownership_marker_stat.stat.exists" in yaml.safe_dump(task)


def test_claude_remove_runbooks_allowlist_dedicated_cleanup_only():
    """Removal must not grow into a global Claude or project cleanup path."""
    shared_install_fragments = (
        "/usr/local",
        "/usr/lib",
        "/etc/",
        "/opt/",
        "/Library/",
    )
    cleanup_tasks = {
        "remove.yaml": [
            "Remove managed Claude Code onboarding marker",
            "Remove native Claude Code credentials",
            "Remove full dedicated Claude Code state directory",
            "Remove owned Claude Code install prefix",
            "Remove dedicated Claude Code agent account and home",
            "Remove Claude Code account ownership marker",
        ],
        "remove_macos.yaml": [
            "Remove managed Claude Code onboarding marker",
            "Remove native Claude Code credentials",
            "Remove full dedicated Claude Code state directory",
            "Remove owned Claude Code install prefix",
            "Delete dedicated Claude Code account via dscl",
            "Remove dedicated Claude Code home directory",
            "Remove Claude Code account ownership marker",
        ],
    }

    for name, expected_cleanup_order in cleanup_tasks.items():
        tasks = _tasks(name)
        file_paths = {
            task["ansible.builtin.file"]["path"]
            for task in tasks
            if "ansible.builtin.file" in task
        }
        allowed_file_paths = {
            "{{ claude_home }}/.claude.json",
            "{{ claude_home }}/.claude/.credentials.json",
            "{{ claude_home }}/.claude",
            "{{ claude_prefix }}",
            "{{ claude_ownership_marker }}",
        }
        if name == "remove_macos.yaml":
            allowed_file_paths.add("{{ claude_home }}")
        assert file_paths == allowed_file_paths
        assert not any(
            fragment in path
            for path in file_paths
            for fragment in shared_install_fragments
        )

        task_names = [task["name"] for task in tasks]
        assert [task_names.index(task_name) for task_name in expected_cleanup_order] == sorted(
            task_names.index(task_name) for task_name in expected_cleanup_order
        )
        for task_name in expected_cleanup_order:
            task = _task(tasks, task_name)
            assert "claude_ownership_marker_stat.stat.exists" in yaml.safe_dump(task)
            if "ansible.builtin.file" in task:
                assert task["ansible.builtin.file"]["state"] == "absent"

        executable_text = "\n".join(_executable_task_texts(tasks)).lower()
        assert not re.search(r"(?<![a-z0-9_-])(npm|claude)(?![a-z0-9_-])", executable_text)

    linux_account = _task(
        _tasks("remove.yaml"), "Remove dedicated Claude Code agent account and home"
    )["ansible.builtin.user"]
    assert linux_account == {
        "name": "{{ agent_name }}",
        "state": "absent",
        "remove": True,
    }
    assert _task(
        _tasks("remove_macos.yaml"), "Delete dedicated Claude Code account via dscl"
    )["ansible.builtin.command"] == "dscl . -delete /Users/{{ agent_name }}"


def test_claude_install_does_not_mint_gateway_state(monkeypatch, tmp_path):
    """Install orchestration must leave an install-only record free of gateway state."""
    host = {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
        "agents": {},
    }
    host_state = [host]
    captured_inventories: list[dict] = []

    def update_host(_hostname: str, updater):
        host_state[0] = updater(host_state[0])
        return True

    def run_playbook(**kwargs):
        captured_inventories.append(kwargs["inventory"])
        events = []
        if len(captured_inventories) == 3:
            events = [
                {
                    "event": "runner_on_ok",
                    "event_data": {
                        "task": "Set install skip condition",
                        "res": {
                            "ansible_facts": {"claude_already_installed": True}
                        },
                    },
                }
            ]
        return _successful_runner_result(tmp_path, events)

    key_path = tmp_path / "test-key"
    key_path.write_text("not a real key")

    monkeypatch.setattr("clawrium.core.install.get_host", lambda _: host_state[0])
    monkeypatch.setattr("clawrium.core.install.update_host", update_host)
    monkeypatch.setattr(
        "clawrium.core.install.get_host_private_key", lambda _: key_path
    )
    monkeypatch.setattr("clawrium.core.install.get_instance_secrets", lambda _: {})
    monkeypatch.setattr("clawrium.core.install.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("clawrium.core.install.initialize_onboarding", lambda *_: True)
    monkeypatch.setattr("clawrium.core.install.ansible_runner.run", run_playbook)
    monkeypatch.setattr(
        stdlib_secrets,
        "token_hex",
        lambda *_: (_ for _ in ()).throw(
            AssertionError("must not mint a gateway token")
        ),
    )

    result = run_installation("claude", "test-host", name="claude-agent")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skip_reason"] == "already_installed"
    assert len(captured_inventories) == 3
    assert captured_inventories[-1]["all"]["vars"]["config"] == {}
    record = host_state[0]["agents"]["claude-agent"]
    assert record["type"] == "claude"
    assert record["status"] == "installed"
    assert record.get("config", {}) == {}


# ---------------------------------------------------------------------------
# #1021 Round 5: ~/.bashrc placement regression
# ---------------------------------------------------------------------------


def _blockinfile_task(playbook_name: str) -> dict:
    return _task(
        _tasks(playbook_name),
        "Expose Claude Code binary on PATH and disable upstream auto-updater",
    )["ansible.builtin.blockinfile"]


@pytest.mark.parametrize("name", ("install.yaml", "install_macos.yaml"))
def test_claude_bashrc_block_is_prepended_before_default_guards(name: str):
    """The managed shell block MUST land at BOF (verified contract).

    Appending the block to EOF — Ansible's default — places it *below*
    Ubuntu's distro-shipped early-return guard (``[ -z "$PS1" ] &&
    return`` / ``case $- in *i*) ... *) return;; esac``). A
    non-interactive ``clawctl agent shell`` session sources .bashrc but
    returns before reaching the PATH export, hiding the Claude binary.
    """
    task = _blockinfile_task(name)
    assert task["insertbefore"] == "BOF"
    assert task["marker"] == "# {mark} CLAWRIUM-CLAUDE-MANAGED"
    assert 'export PATH="{{ claude_prefix }}/bin:$PATH"' in task["block"]
    assert "export DISABLE_AUTOUPDATER=1" in task["block"]


@pytest.mark.parametrize(
    "guard",
    [
        # Ubuntu's distro-shipped non-interactive early return.
        '[ -z "$PS1" ] && return\n',
        # Alternative form shipped on some Debian/Ubuntu images.
        'case $- in\n    *i*) ;;\n      *) return;;\nesac\n',
    ],
)
def test_bashrc_prepend_survives_noninteractive_early_return(
    tmp_path: Path, guard: str
):
    """Source a guarded .bashrc non-interactively; PATH MUST contain Claude.

    The playbook writes the Ansible-managed block at BOF. This test
    reproduces that layout against two real-world non-interactive
    early-return guards and sources the file through plain ``bash -c``
    (no ``-i``) exactly as ``clawctl agent shell`` does on the host.
    """
    claude_bin = tmp_path / "prefix" / "bin"
    claude_bin.mkdir(parents=True)
    bashrc = tmp_path / ".bashrc"
    managed_block = (
        "# BEGIN CLAWRIUM-CLAUDE-MANAGED\n"
        f'export PATH="{claude_bin}:$PATH"\n'
        "export DISABLE_AUTOUPDATER=1\n"
        "# END CLAWRIUM-CLAUDE-MANAGED\n"
    )
    # BOF prepend: managed block comes BEFORE the distro guard.
    bashrc.write_text(managed_block + guard + 'echo "post-guard reached"\n')

    import os
    import subprocess

    result = subprocess.run(
        ["bash", "-c", f'. "{bashrc}"; printf "%s" "$PATH"'],
        # No -i: deliberately non-interactive, matching ``agent shell``.
        env={**os.environ, "HOME": str(tmp_path), "PS1": ""},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    # Claude bin dir MUST appear on PATH even though the guard would
    # have early-returned if the block were at EOF.
    assert str(claude_bin) in result.stdout
    assert result.stdout.startswith(str(claude_bin) + ":")


@pytest.mark.parametrize(
    "guard",
    [
        '[ -z "$PS1" ] && return\n',
        'case $- in\n    *i*) ;;\n      *) return;;\nesac\n',
    ],
)
def test_bashrc_append_would_fail_without_prepend(tmp_path: Path, guard: str):
    """Negative control: EOF append (the pre-fix behavior) hides Claude.

    This asserts the exact regression the Round-5 UAT caught: when the
    managed block is appended to EOF (Ansible's default), a
    non-interactive source hits the early-return guard first and never
    exports PATH. Keeping this test in-tree prevents a silent regression
    if the ``insertbefore: BOF`` option is ever dropped.
    """
    claude_bin = tmp_path / "prefix" / "bin"
    claude_bin.mkdir(parents=True)
    bashrc = tmp_path / ".bashrc"
    managed_block = (
        "# BEGIN CLAWRIUM-CLAUDE-MANAGED\n"
        f'export PATH="{claude_bin}:$PATH"\n'
        "export DISABLE_AUTOUPDATER=1\n"
        "# END CLAWRIUM-CLAUDE-MANAGED\n"
    )
    # EOF append (the buggy pre-fix layout).
    bashrc.write_text(guard + managed_block)

    import os
    import subprocess

    result = subprocess.run(
        ["bash", "-c", f'. "{bashrc}"; printf "%s" "$PATH"'],
        env={**os.environ, "HOME": str(tmp_path), "PS1": ""},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert str(claude_bin) not in result.stdout
