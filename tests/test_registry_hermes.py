"""Tests for the hermes agent type registration in the bundled registry."""

import pytest

from clawrium.core.registry import (
    check_compatibility,
    get_claw_info,
    list_claws,
    load_manifest,
)


def test_hermes_listed_in_registry():
    """list_claws() should include 'hermes' alongside openclaw and zeroclaw."""
    claws = list_claws()
    assert "hermes" in claws


def test_hermes_manifest_validates():
    """load_manifest('hermes') parses and returns a typed manifest."""
    manifest = load_manifest("hermes")

    assert manifest["agent"]["type"] == "hermes"
    assert manifest["agent"]["description"]
    assert manifest["platforms"]
    # Provider keys are optional in Phase 1; required is empty.
    secrets = manifest.get("secrets", {})
    assert secrets.get("required", []) == []
    optional_keys = [s["key"] for s in secrets.get("optional", [])]
    assert "OPENROUTER_API_KEY" in optional_keys
    assert "ANTHROPIC_API_KEY" in optional_keys
    assert "OPENAI_API_KEY" in optional_keys


def test_hermes_manifest_has_installer_checksum():
    """Every platform entry must declare a non-empty sha256 for installer pinning."""
    manifest = load_manifest("hermes")

    assert len(manifest["platforms"]) >= 1
    for entry in manifest["platforms"]:
        sha256 = entry.get("sha256")
        assert isinstance(sha256, str), (
            f"Platform entry missing sha256: {entry.get('os')} {entry.get('os_version')}"
        )
        assert len(sha256) == 64, (
            f"sha256 should be 64 hex chars, got {len(sha256)}: {sha256!r}"
        )


def test_hermes_manifest_declares_memory_workspace():
    """Phase 3 prerequisite: workspace.memory_path and features.memory must be set."""
    manifest = load_manifest("hermes")

    workspace = manifest.get("workspace", {})
    assert workspace.get("memory_path") == "~/.hermes/memories"

    features = manifest.get("features", {})
    assert features.get("memory") is True


def test_hermes_get_claw_info():
    """get_claw_info('hermes') returns a sane summary."""
    info = get_claw_info("hermes")

    assert info["agent_type"] == "hermes"
    assert info["latest_version"]
    assert any("ubuntu 24.04 x86_64" == p for p in info["supported_platforms"])


def test_hermes_compatibility_ubuntu_2404_x86_64():
    """A vanilla Ubuntu 24.04 x86_64 host with enough RAM should be compatible."""
    hardware = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "x86_64",
        "memtotal_mb": 8192,
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 8,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("hermes", hardware)

    assert result["compatible"] is True
    assert result["matched_entry"] is not None
    assert result["matched_entry"]["os"] == "ubuntu"
    assert result["matched_entry"]["arch"] == "x86_64"


def test_hermes_compatibility_insufficient_memory():
    """A host below min_memory_mb should be reported as incompatible."""
    hardware = {
        "os": "ubuntu",
        "os_version": "24.04",
        "architecture": "x86_64",
        "memtotal_mb": 1024,  # below 2048 min
        "gpu": {"present": False, "vendor": None, "error": None},
        "processor_cores": 4,
        "processor_count": 1,
        "mounts": [],
    }

    result = check_compatibility("hermes", hardware)
    assert result["compatible"] is False
    assert any(
        "memory" in reason.lower() or "ram" in reason.lower()
        for reason in result["reasons"]
    )


def test_hermes_install_playbook_shape():
    """The hermes install playbook must encode the documented invocation."""
    from importlib.resources import files
    import yaml

    hermes_pkg = files("clawrium.platform.registry.hermes")
    playbook_path = hermes_pkg / "playbooks" / "install.yaml"

    content = playbook_path.read_text()

    # Required structural elements.
    assert "- hosts:" in content
    assert "agent_name" in content
    # Hermes-specific install command flags.
    assert "--skip-setup" in content
    assert "--branch" in content
    assert "--hermes-home" in content
    assert "/home/{{ agent_name }}/.hermes" in content
    assert "/home/{{ agent_name }}/.local/bin/hermes" in content
    # Hermes upstream installer requires ripgrep and ffmpeg. Verify the
    # playbook installs them via apt rather than expecting them to be
    # pre-provisioned on the target host (issue #344). Structural check
    # (not substring) so a change to state=latest or removal of
    # cache_valid_time is caught here, not in production.
    parsed = yaml.safe_load(content)
    parsed_tasks = parsed[0]["tasks"]
    apt_tasks = [t for t in parsed_tasks if "ansible.builtin.apt" in t]
    assert len(apt_tasks) == 1, (
        "install.yaml must have exactly one apt task installing hermes system deps"
    )
    apt_args = apt_tasks[0]["ansible.builtin.apt"]
    assert apt_args["state"] == "present", (
        "apt task must use state=present (not latest) to remain idempotent"
    )
    assert set(apt_args["name"]) >= {"ripgrep", "ffmpeg"}
    assert apt_args["update_cache"] is True
    assert apt_args["cache_valid_time"] == 3600
    # Service unit MUST NOT be enabled or started in install.yaml.
    # ExecStart must use `hermes gateway run` (NOT `start`): the `start`
    # subcommand fails with "Gateway service is not installed" because hermes
    # treats `start` as a systemd-managed alias and refuses to spawn the
    # foreground process. `run` is the daemon entrypoint suitable for
    # `Type=simple` systemd units.
    assert "ExecStart=/home/{{ agent_name }}/.local/bin/hermes gateway run" in content
    assert "ExecStart=/home/{{ agent_name }}/.local/bin/hermes gateway start" not in content
    assert "EnvironmentFile=/home/{{ agent_name }}/.hermes/.env" in content

    data = yaml.safe_load(content)
    tasks = data[0]["tasks"]
    enable_tasks = [
        t
        for t in tasks
        if t.get("ansible.builtin.systemd", {}).get("enabled") is True
        or t.get("ansible.builtin.systemd", {}).get("state") == "started"
    ]
    assert enable_tasks == [], (
        "install.yaml must not enable or start the hermes service; that is Phase 2's job"
    )


def test_hermes_remove_playbook_cleans_user_and_dirs():
    """remove.yaml must remove the unit, ~/.hermes/, the bin symlink, and the user."""
    from importlib.resources import files

    hermes_pkg = files("clawrium.platform.registry.hermes")
    remove_path = hermes_pkg / "playbooks" / "remove.yaml"
    content = remove_path.read_text()

    assert "/etc/systemd/system/{{ agent_type }}-{{ agent_name }}.service" in content
    assert "/home/{{ agent_name }}/.hermes" in content
    assert "/home/{{ agent_name }}/.local/bin/hermes" in content
    assert "remove: yes" in content
    # Hermes enables linger for its agent user; userdel fails without
    # disable-linger + pkill first.
    assert "loginctl disable-linger" in content
    assert "pkill" in content


def test_hermes_install_force_drops_binary_before_reinstall():
    """install.yaml must remove the binary when force_install=true so the
    `creates:` short-circuit on the runtime install task does not block reinstall."""
    from importlib.resources import files
    import yaml

    hermes_pkg = files("clawrium.platform.registry.hermes")
    install_path = hermes_pkg / "playbooks" / "install.yaml"
    content = install_path.read_text()
    data = yaml.safe_load(content)
    tasks = data[0]["tasks"]

    matching = [
        t
        for t in tasks
        if "Remove existing Hermes binary" in t.get("name", "")
    ]
    assert matching, (
        "install.yaml must remove the existing hermes binary when --force is set"
    )
    task = matching[0]
    when = task.get("when", [])
    assert any("force_install" in w for w in when), (
        "binary-removal task must be gated on force_install"
    )
    assert (
        task["ansible.builtin.file"]["path"]
        == "/home/{{ agent_name }}/.local/bin/hermes"
    )
    assert task["ansible.builtin.file"]["state"] == "absent"


def test_hermes_install_env_file_permissions_enforced():
    """install.yaml must enforce 0600 on ~/.hermes/.env, since the upstream
    installer creates it with 0644 and we'll write provider keys there in Phase 2."""
    from importlib.resources import files
    import yaml

    hermes_pkg = files("clawrium.platform.registry.hermes")
    install_path = hermes_pkg / "playbooks" / "install.yaml"
    data = yaml.safe_load(install_path.read_text())
    tasks = data[0]["tasks"]

    enforce = [
        t for t in tasks if "Enforce 0600" in t.get("name", "")
    ]
    assert enforce, "install.yaml must enforce 0600 on ~/.hermes/.env"
    file_args = enforce[0]["ansible.builtin.file"]
    assert file_args["path"] == "/home/{{ agent_name }}/.hermes/.env"
    assert file_args["mode"] == "0600"


def test_hermes_install_env_file_created_with_mode_0600():
    """The `copy` task that creates ~/.hermes/.env must declare mode=0600 ON
    the task itself (not via a separate chmod) so the file is never world-
    readable, even momentarily. This closes the TOCTOU window flagged by ATX
    review B1."""
    from importlib.resources import files
    import yaml

    hermes_pkg = files("clawrium.platform.registry.hermes")
    install_path = hermes_pkg / "playbooks" / "install.yaml"
    data = yaml.safe_load(install_path.read_text())
    tasks = data[0]["tasks"]

    create_tasks = [
        t for t in tasks if t.get("name", "").startswith("Create empty Hermes environment file")
    ]
    assert create_tasks, "install.yaml must have a task that creates ~/.hermes/.env"
    copy_args = create_tasks[0]["ansible.builtin.copy"]
    assert copy_args["dest"] == "/home/{{ agent_name }}/.hermes/.env"
    assert copy_args["mode"] == "0600", (
        "the create task must set mode=0600 directly to avoid a TOCTOU window"
    )


def test_hermes_manifest_onboarding_real_pipeline():
    """Phase 4 replaces the Phase 1 placeholder all-auto_skip block with a real
    onboarding pipeline mirroring openclaw's structure:

      * ``providers`` is required (no auto_skip) and exposes the canonical
        provider_select + provider_test tasks.
      * ``identity`` keeps auto_skip:true (hermes manages SOUL.md/AGENTS.md
        internally inside ~/.hermes/; clm does not push identity files in
        this iteration).
      * ``channels`` is required (no auto_skip) with a confirm task — the
        only legal option is `cli` since the api_server platform is the
        local-CLI-equivalent endpoint.
      * ``validate`` runs a composite shell check (hermes binary present,
        ~/.hermes/.env exists, /health returns 200).

    Each assertion guards a specific contract independently so a future
    regression points at exactly which property changed."""
    manifest = load_manifest("hermes")
    onboarding = manifest.get("onboarding") or {}
    stages = onboarding.get("stages") or {}

    for stage_name in ("providers", "identity", "channels", "validate"):
        assert stage_name in stages, f"hermes onboarding missing stage: {stage_name}"

    # providers — required, exposes provider_select + provider_test
    providers = stages["providers"]
    assert providers.get("required") is True
    assert providers.get("auto_skip") is not True
    task_types = [t.get("type") for t in providers.get("tasks", [])]
    assert "provider_select" in task_types
    assert "provider_test" in task_types

    # identity — auto_skip:true
    identity = stages["identity"]
    assert identity.get("auto_skip") is True
    assert identity.get("required") is not True
    assert identity.get("description")

    # channels — required, cli-only confirm task
    channels = stages["channels"]
    assert channels.get("required") is True
    assert channels.get("auto_skip") is not True
    channel_task_types = [t.get("type") for t in channels.get("tasks", [])]
    assert "confirm" in channel_task_types

    # validate — three composite checks (binary + env + health)
    validate_stage = stages["validate"]
    assert validate_stage.get("auto_skip") is not True
    validate_task_ids = [t.get("id") for t in validate_stage.get("tasks", [])]
    assert "binary_check" in validate_task_ids
    assert "env_check" in validate_task_ids
    assert "health_check" in validate_task_ids


def test_hermes_manifest_onboarding_stage_ordering():
    """Stage order must match the canonical openclaw ordering (providers →
    identity → channels → validate) so the configure wizard walks them in
    the expected sequence."""
    manifest = load_manifest("hermes")
    stages = ((manifest.get("onboarding") or {}).get("stages") or {})
    keys = list(stages.keys())
    assert keys == ["providers", "identity", "channels", "validate"], (
        f"hermes stage ordering must match canonical pipeline, got {keys}"
    )


def test_hermes_start_playbook_fails_on_inactive_service():
    """start.yaml must FAIL when the service is not in active/activating state
    so the Python lifecycle layer does not record runtime.status='running' for
    a service that has already exited (state divergence)."""
    from importlib.resources import files
    import yaml

    hermes_pkg = files("clawrium.platform.registry.hermes")
    start_path = hermes_pkg / "playbooks" / "start.yaml"
    data = yaml.safe_load(start_path.read_text())
    tasks = data[0]["tasks"]

    fail_tasks = [
        t for t in tasks
        if t.get("ansible.builtin.fail") is not None
        and "not active" in t.get("name", "").lower()
    ]
    assert fail_tasks, "start.yaml must explicitly fail when the service is not active"
    # The fail must be gated on a non-active ActiveState.
    when_clause = fail_tasks[0].get("when", "")
    assert "ActiveState" in when_clause
    assert "active" in when_clause


def test_hermes_start_playbook_uses_gateway_run():
    """The re-rendered systemd unit in start.yaml must use `hermes gateway run`,
    not `hermes gateway start` (which is a CLI alias that fails)."""
    from importlib.resources import files

    hermes_pkg = files("clawrium.platform.registry.hermes")
    start_path = hermes_pkg / "playbooks" / "start.yaml"
    content = start_path.read_text()
    assert "ExecStart=/home/{{ agent_name }}/.local/bin/hermes gateway run" in content
    assert "ExecStart=/home/{{ agent_name }}/.local/bin/hermes gateway start" not in content


def test_hermes_stop_playbook_pgrep_matches_python_process():
    """W5: hermes is a Python app; `pgrep -u <user> hermes` won't match the
    python process. The verification must use `pgrep -f 'hermes gateway run'`."""
    from importlib.resources import files

    hermes_pkg = files("clawrium.platform.registry.hermes")
    stop_path = hermes_pkg / "playbooks" / "stop.yaml"
    content = stop_path.read_text()
    # The pgrep invocation must use `-f` and match against the daemon command.
    assert "-f \"hermes gateway run\"" in content or "-f 'hermes gateway run'" in content


# ---------------------------------------------------------------------------
# ansible_runner mock tests for hermes (B7 — parity with openclaw test suite).
#
# These tests exercise run_installation('hermes', ...) end-to-end with a mocked
# ansible_runner so we can assert extra_vars, playbook path, inventory shape,
# and skip-detection behavior without touching the network.
# ---------------------------------------------------------------------------


def _hermes_install_setup(monkeypatch, tmp_path, host_record: dict, version: str = "2026.5.7"):
    """Shared setup for hermes install mock tests. Mirrors the openclaw
    pattern in tests/test_install_skip.py."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    mock_manifest = {
        "name": "hermes",
        "entries": [
            {
                "version": version,
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "sha256": "b34368cb0628d5acbdc48fe6f4160fb6f51bb33377e8f5a7415fd790a57456e5",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"python": ">=3.11"},
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
    """Mock for ansible_runner.run that captures call kwargs and returns a
    successful result with the recorded events."""

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


def test_hermes_install_passes_correct_extra_vars(monkeypatch, tmp_path):
    """run_installation('hermes', ...) must inject agent_type='hermes',
    claw_version='v2026.5.7', and the manifest sha256 into the playbook inventory."""
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
    _hermes_install_setup(monkeypatch, tmp_path, host)

    import ansible_runner

    captured: list = []
    monkeypatch.setattr(ansible_runner, "run", _capture_run(captured))

    result = run_installation("hermes", "test-host", name="hermes-test")

    assert result["success"] is True
    assert result["agent"] == "hermes"
    assert result["version"] == "2026.5.7"
    # base + claw playbook
    assert len(captured) == 2
    inv_vars = captured[1]["inventory"]["all"]["vars"]
    assert inv_vars["agent_name"] == "hermes-test"
    assert inv_vars["agent_type"] == "hermes"
    assert inv_vars["claw_version"] == "v2026.5.7"
    assert (
        inv_vars["claw_sha256"]
        == "b34368cb0628d5acbdc48fe6f4160fb6f51bb33377e8f5a7415fd790a57456e5"
    )
    assert inv_vars["force_install"] is False


def test_hermes_install_uses_hermes_playbook(monkeypatch, tmp_path):
    """The second ansible_runner call must target the hermes install.yaml,
    not openclaw's or another agent's playbook."""
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
    _hermes_install_setup(monkeypatch, tmp_path, host)

    import ansible_runner

    captured: list = []
    monkeypatch.setattr(ansible_runner, "run", _capture_run(captured))

    run_installation("hermes", "test-host", name="hermes-test")

    playbook_path = captured[1]["playbook"]
    assert "registry/hermes/playbooks/install.yaml" in playbook_path


def test_hermes_install_force_propagates_force_install_true(monkeypatch, tmp_path):
    """force=True must propagate as force_install=true into the playbook inventory."""
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
        "agents": {
            "hermes-test": {
                "type": "hermes",
                "status": "installed",
                "installed_at": "2026-05-09T00:00:00+00:00",
                "error": None,
                "agent_name": "hermes-test",
                "version": "2026.5.7",
            }
        },
    }
    _hermes_install_setup(monkeypatch, tmp_path, host)

    import ansible_runner

    captured: list = []
    monkeypatch.setattr(ansible_runner, "run", _capture_run(captured))

    run_installation("hermes", "test-host", force=True)

    for entry in captured:
        assert entry["inventory"]["all"]["vars"]["force_install"] is True


def test_hermes_install_skip_detection_via_fact(monkeypatch, tmp_path):
    """When the hermes playbook emits `hermes_already_installed=true`,
    `_install_was_skipped` must detect it and run_installation reports
    skipped=True. Proves the generalized (non-openclaw-specific) skip
    detection introduced for W8."""
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
        "agents": {
            "hermes-test": {
                "type": "hermes",
                "status": "installed",
                "installed_at": "2026-05-09T00:00:00+00:00",
                "error": None,
                "agent_name": "hermes-test",
                "version": "2026.5.7",
            }
        },
    }
    _hermes_install_setup(monkeypatch, tmp_path, host)

    import ansible_runner
    from unittest.mock import Mock

    class Result:
        def __init__(self, events):
            self.events = events

        status = "successful"

        class Config:
            artifact_dir = "/tmp/nonexistent"

        config = Config()

    base_result = Result([])
    claw_result = Result(
        [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"hermes_already_installed": True}},
                },
            }
        ]
    )
    monkeypatch.setattr(
        ansible_runner, "run", Mock(side_effect=[base_result, claw_result])
    )

    result = run_installation("hermes", "test-host")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skip_reason"] == "already_installed"


def test_install_was_skipped_handles_hermes_fact():
    """Unit test for the generalized skip detection helper."""
    from clawrium.core.install import _install_was_skipped

    class Result:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"hermes_already_installed": True}},
                },
            }
        ]

    assert _install_was_skipped(Result(), "hermes") is True
    # openclaw fact does not trigger hermes skip detection.
    assert _install_was_skipped(Result(), "openclaw") is False


def test_hermes_install_checksum_failure_raises(monkeypatch, tmp_path):
    """B9: when the get_url task fails (e.g., installer checksum mismatch),
    ansible_runner returns status='failed' and run_installation must raise
    InstallationError. Guards the security-critical installer-pinning path."""
    from clawrium.core.install import InstallationError, run_installation

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
    _hermes_install_setup(monkeypatch, tmp_path, host)

    import ansible_runner
    from unittest.mock import Mock

    class BaseResult:
        status = "successful"

        class Config:
            artifact_dir = "/tmp/nonexistent"

        config = Config()
        events = []

    class FailedResult:
        # Simulates the claw playbook failing partway through (e.g., on the
        # get_url task) because the SHA256 of the downloaded installer does
        # not match the manifest-pinned checksum.
        status = "failed"

        class Config:
            artifact_dir = "/tmp/nonexistent"

        config = Config()
        events = [
            {
                "event": "runner_on_failed",
                "event_data": {
                    "task": "Download Hermes installer script",
                    "res": {
                        "msg": (
                            "The checksum for /home/hermes-test/hermes-install.sh "
                            "did not match the expected value."
                        ),
                        "failed": True,
                    },
                },
            }
        ]

    monkeypatch.setattr(
        ansible_runner, "run", Mock(side_effect=[BaseResult(), FailedResult()])
    )

    with pytest.raises(InstallationError, match="Agent playbook failed"):
        run_installation("hermes", "test-host", name="hermes-test")


def test_hermes_install_playbook_apt_idempotency_attrs():
    """Dedicated guard for the apt task's idempotency contract (issue #344
    ATX review B3): a code change to state=latest or removal of
    cache_valid_time must fail CI even if the broader playbook-shape test
    is refactored."""
    from importlib.resources import files
    import yaml

    hermes_pkg = files("clawrium.platform.registry.hermes")
    install_path = hermes_pkg / "playbooks" / "install.yaml"
    data = yaml.safe_load(install_path.read_text())
    tasks = data[0]["tasks"]

    apt_tasks = [t for t in tasks if "ansible.builtin.apt" in t]
    assert len(apt_tasks) == 1
    apt_args = apt_tasks[0]["ansible.builtin.apt"]
    assert apt_args["state"] == "present"
    assert apt_args["cache_valid_time"] == 3600
    assert apt_args["update_cache"] is True
    assert set(apt_args["name"]) >= {"ripgrep", "ffmpeg"}


def test_hermes_install_apt_failure_raises(monkeypatch, tmp_path):
    """Issue #344 ATX review B2: when the apt task fails (e.g. package
    not found, mirror unreachable), ansible_runner returns status='failed'
    and run_installation must raise InstallationError."""
    from clawrium.core.install import InstallationError, run_installation

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
    _hermes_install_setup(monkeypatch, tmp_path, host)

    import ansible_runner
    from unittest.mock import Mock

    class BaseResult:
        status = "successful"

        class Config:
            artifact_dir = "/tmp/nonexistent"

        config = Config()
        events = []

    class AptFailedResult:
        # Simulates `apt-get install ripgrep` failing with
        # "E: Unable to locate package". Error detection in
        # run_installation is status-driven, not event-driven, so the
        # events list is intentionally empty.
        status = "failed"

        class Config:
            artifact_dir = "/tmp/nonexistent"

        config = Config()
        events = []

    monkeypatch.setattr(
        ansible_runner, "run", Mock(side_effect=[BaseResult(), AptFailedResult()])
    )

    with pytest.raises(InstallationError, match="Agent playbook failed"):
        run_installation("hermes", "test-host", name="hermes-test")


# ---------------------------------------------------------------------------
# Version-parsing regex tests (B8).
#
# The Jinja2 regex pipeline in install.yaml that parses `hermes --version`
# output is encoded as a single expression. Rather than re-execute Jinja2 in
# unit tests, we extract the regex into a pure-Python helper and test it
# directly. The playbook continues to use the same regex (kept in sync via
# the shared constant in core.registry).
# ---------------------------------------------------------------------------


def test_parse_hermes_version_matches_canonical_output():
    """Canonical `hermes --version` output -> parsed upstream tag."""
    from clawrium.core.registry import parse_hermes_version

    assert parse_hermes_version("Hermes Agent v0.13.0 (2026.5.7)") == "2026.5.7"


def test_parse_hermes_version_different_release_tag():
    """A different patch tag still parses correctly."""
    from clawrium.core.registry import parse_hermes_version

    assert parse_hermes_version("Hermes Agent v0.13.0 (2026.5.10)") == "2026.5.10"


def test_parse_hermes_version_unparseable_returns_empty_string():
    """Garbage / unexpected output returns '' so the playbook treats it as
    'version unknown' and triggers a safe reinstall."""
    from clawrium.core.registry import parse_hermes_version

    assert parse_hermes_version("hermes: command moved, please reinstall") == ""
    assert parse_hermes_version("") == ""
    assert parse_hermes_version("Hermes Agent v0.13.0") == ""


def test_parse_hermes_version_handles_absent_binary():
    """When the binary is absent, callers pass None; helper must not crash."""
    from clawrium.core.registry import parse_hermes_version

    assert parse_hermes_version(None) == ""
