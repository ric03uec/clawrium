"""Tests for the zeroclaw agent type registration in the bundled registry.

Parity with tests/test_registry_hermes.py — exercises the install playbook
shape, manifest checksums, run_installation extra_vars, and skip detection
specific to zeroclaw. Added per ATX review of PR #361 (NEW-B2).
"""

from clawrium.core.registry import load_manifest


def test_zeroclaw_manifest_has_installer_checksum():
    """Every platform entry must declare a 64-char hex sha256 and version 0.7.5."""
    manifest = load_manifest("zeroclaw")

    assert len(manifest["platforms"]) == 5, (
        "zeroclaw must publish 5 platform entries (armv7l Debian 13, "
        "aarch64 Ubuntu 22.04/24.04, x86_64 Ubuntu 22.04/24.04)"
    )
    for entry in manifest["platforms"]:
        assert entry["version"] == "0.7.5", (
            f"Platform entry version mismatch: {entry.get('os')} "
            f"{entry.get('os_version')} {entry.get('arch')} -> {entry.get('version')!r}"
        )
        sha256 = entry.get("sha256")
        assert isinstance(sha256, str), (
            f"Platform entry missing sha256: {entry.get('os')} {entry.get('os_version')}"
        )
        assert len(sha256) == 64, (
            f"sha256 must be 64 hex chars, got {len(sha256)}: {sha256!r}"
        )
        # Verify all chars are valid hex
        int(sha256, 16)


def test_zeroclaw_install_playbook_shape():
    """The zeroclaw install playbook must encode the install-disabled invariants."""
    from importlib.resources import files
    import yaml

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    playbook_path = zeroclaw_pkg / "playbooks" / "install.yaml"

    content = playbook_path.read_text()

    # Required structural elements.
    assert "- hosts:" in content
    assert "agent_name" in content
    # Agent user is a service account: nologin shell reduces lateral-movement
    # surface if the account is ever compromised.
    assert "shell: /usr/sbin/nologin" in content
    # WorkingDirectory must be inside ~/.zeroclaw (not ~/workspace which is the
    # legacy path; the install playbook now scaffolds ~/.zeroclaw/workspace
    # and ~/.zeroclaw/state).
    assert "WorkingDirectory=/home/{{ agent_name }}/.zeroclaw" in content
    assert "ExecStart=/home/{{ agent_name }}/bin/zeroclaw daemon" in content
    # Workspace + state scaffolding must land inside ~/.zeroclaw.
    assert "/home/{{ agent_name }}/.zeroclaw/workspace" in content
    assert "/home/{{ agent_name }}/.zeroclaw/state" in content
    # Service unit MUST NOT be enabled or started in install.yaml — `clm agent
    # configure` owns the start half of the lifecycle.
    data = yaml.safe_load(content)
    tasks = data[0]["tasks"]
    enable_tasks = [
        t
        for t in tasks
        if t.get("ansible.builtin.systemd", {}).get("enabled") is True
        or t.get("ansible.builtin.systemd", {}).get("state") == "started"
    ]
    assert enable_tasks == [], (
        "install.yaml must not enable or start the zeroclaw service; "
        "configure.yaml owns the start half of the lifecycle"
    )


def test_zeroclaw_start_playbook_uses_argv_list_form():
    """Pin the W9 fix: pgrep in start.yaml MUST use argv-list form, not a
    `cmd:` string. Unquoted agent_name interpolated into a shell-split string
    is a command-injection vector if an agent name ever contains whitespace
    or shell metacharacters."""
    from importlib.resources import files
    import yaml

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    start_path = zeroclaw_pkg / "playbooks" / "start.yaml"
    data = yaml.safe_load(start_path.read_text())
    tasks = data[0]["tasks"]

    pgrep_tasks = [
        t
        for t in tasks
        if isinstance(t.get("ansible.builtin.command"), dict)
        and "pgrep" in str(t["ansible.builtin.command"])
    ]
    assert pgrep_tasks, "start.yaml must contain at least one pgrep task"
    for task in pgrep_tasks:
        cmd_block = task["ansible.builtin.command"]
        assert "cmd" not in cmd_block, (
            f"pgrep task '{task.get('name')}' must use argv-list form, not "
            f"cmd: string (W9). Found: {cmd_block!r}"
        )
        assert "argv" in cmd_block, (
            f"pgrep task '{task.get('name')}' must declare argv: list (W9)."
        )
        argv = cmd_block["argv"]
        assert argv[0] == "pgrep"
        # The agent_name token must be a standalone argv element so shell
        # metacharacters in the name cannot split into extra arguments.
        assert "{{ agent_name }}" in argv


def test_zeroclaw_stop_playbook_uses_argv_list_form():
    """Mirror of test_zeroclaw_start_playbook_uses_argv_list_form for stop.yaml."""
    from importlib.resources import files
    import yaml

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    stop_path = zeroclaw_pkg / "playbooks" / "stop.yaml"
    data = yaml.safe_load(stop_path.read_text())
    tasks = data[0]["tasks"]

    pgrep_tasks = [
        t
        for t in tasks
        if isinstance(t.get("ansible.builtin.command"), dict)
        and "pgrep" in str(t["ansible.builtin.command"])
    ]
    assert pgrep_tasks, "stop.yaml must contain at least one pgrep task"
    for task in pgrep_tasks:
        cmd_block = task["ansible.builtin.command"]
        assert "cmd" not in cmd_block
        assert "argv" in cmd_block
        assert cmd_block["argv"][0] == "pgrep"
        assert "{{ agent_name }}" in cmd_block["argv"]


def test_zeroclaw_remove_playbook_cleans_workspace_and_state():
    """remove.yaml must clean the unit, ~/.zeroclaw (covers workspace+state),
    the bin directory, and the agent user. Must NOT reference the legacy
    ~/workspace path (NEW-B1)."""
    from importlib.resources import files

    zeroclaw_pkg = files("clawrium.platform.registry.zeroclaw")
    remove_path = zeroclaw_pkg / "playbooks" / "remove.yaml"
    content = remove_path.read_text()

    assert "/etc/systemd/system/{{ agent_type }}-{{ agent_name }}.service" in content
    # Removing ~/.zeroclaw cascades to workspace + state subdirs.
    assert "/home/{{ agent_name }}/.zeroclaw" in content
    assert "/home/{{ agent_name }}/bin" in content
    assert "remove: yes" in content
    # Legacy ~/workspace must not be referenced — install no longer scaffolds it.
    assert "/home/{{ agent_name }}/workspace" not in content


def _zeroclaw_install_setup(monkeypatch, tmp_path, host_record: dict, version: str = "0.7.5"):
    """Shared setup for zeroclaw install mock tests. Mirrors hermes pattern."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    mock_manifest = {
        "name": "zeroclaw",
        "entries": [
            {
                "version": version,
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "sha256": "8bc8276a8d8faefb3e4a824f33876929e7466f632ee7c5363936368a1af2e4f7",
                "requirements": {
                    "min_memory_mb": 1024,
                    "gpu_required": False,
                    "dependencies": {"python": ">=3.9"},
                },
            }
        ],
    }

    import clawrium.core.install

    monkeypatch.setattr(clawrium.core.install, "load_manifest", lambda x: mock_manifest)
    monkeypatch.setattr(
        clawrium.core.install,
        "check_compatibility",
        lambda *args, **kwargs: {
            "compatible": True,
            "matched_entry": mock_manifest["entries"][0],
            "reasons": [],
        },
    )

    host_state = [host_record]

    def mock_get_host(_):
        return host_state[0]

    def mock_update_host(_, updater):
        host_state[0] = updater(host_state[0])
        return True

    monkeypatch.setattr(clawrium.core.install, "get_host", mock_get_host)
    monkeypatch.setattr(clawrium.core.install, "update_host", mock_update_host)

    key_file = tmp_path / "test_key"
    key_file.write_text("fake key")
    monkeypatch.setattr(
        clawrium.core.install, "get_host_private_key", lambda _: key_file
    )
    monkeypatch.setattr(
        clawrium.core.install, "initialize_onboarding", lambda h, c: True
    )

    return host_state


def _capture_run(captured: list):
    """Mock for ansible_runner.run that captures call kwargs and returns
    a successful result with the recorded events."""

    def _runner(*args, **kwargs):
        captured.append(kwargs)

        class Result:
            status = "successful"

            class Config:
                artifact_dir = "/tmp/nonexistent"

            config = Config()
            events = kwargs.get("_events", [])

        return Result()

    return _runner


def test_zeroclaw_install_passes_correct_extra_vars(monkeypatch, tmp_path):
    """run_installation('zeroclaw', ...) must inject agent_type='zeroclaw',
    claw_version='v0.7.5', and the manifest sha256 into the playbook inventory."""
    from clawrium.core.install import run_installation

    host = {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
    }
    _zeroclaw_install_setup(monkeypatch, tmp_path, host)

    import ansible_runner

    captured: list = []
    monkeypatch.setattr(ansible_runner, "run", _capture_run(captured))

    result = run_installation("zeroclaw", "test-host", name="zc-test")

    assert result["success"] is True
    assert result["agent"] == "zeroclaw"
    assert result["version"] == "0.7.5"
    # base + claw playbook
    assert len(captured) == 2
    inv_vars = captured[1]["inventory"]["all"]["vars"]
    assert inv_vars["agent_name"] == "zc-test"
    assert inv_vars["agent_type"] == "zeroclaw"
    assert inv_vars["claw_version"] == "v0.7.5"
    assert (
        inv_vars["claw_sha256"]
        == "8bc8276a8d8faefb3e4a824f33876929e7466f632ee7c5363936368a1af2e4f7"
    )
    assert inv_vars["force_install"] is False

    playbook_path = captured[1]["playbook"]
    assert "registry/zeroclaw/playbooks/install.yaml" in playbook_path


def test_install_was_skipped_handles_zeroclaw_fact():
    """The generalized skip detection helper recognizes zeroclaw_already_installed."""
    from clawrium.core.install import _install_was_skipped

    class Result:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"zeroclaw_already_installed": True}},
                },
            }
        ]

    assert _install_was_skipped(Result(), "zeroclaw") is True
    # hermes fact does not trigger zeroclaw skip detection.
    class HermesResult:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"hermes_already_installed": True}},
                },
            }
        ]

    assert _install_was_skipped(HermesResult(), "zeroclaw") is False
