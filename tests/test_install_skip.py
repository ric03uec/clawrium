"""Tests for installed-version skip behavior during install."""

from unittest.mock import Mock

import pytest


def _setup_common(monkeypatch, tmp_path, host_record: dict, version: str = "2026.4.2"):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    mock_manifest = {
        "name": "openclaw",
        "entries": [
            {
                "version": version,
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "sha256": "abc123",
                "requirements": {
                    "min_memory_mb": 2048,
                    "gpu_required": False,
                    "dependencies": {"nodejs": ">=20.0.0"},
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


def _result_with_events(tmp_path, events):
    class SuccessfulResult:
        status = "successful"

        class Config:
            artifact_dir = str(tmp_path / "artifacts")

        config = Config()

    SuccessfulResult.events = events

    return SuccessfulResult()


def _stat_event(
    task_name: str,
    path: str,
    exists: bool,
    executable: bool = True,
    size: int = 1024,
) -> dict:
    """Emit a `runner_on_ok` event shaped like ansible.builtin.stat output.

    Used to simulate the `Check per-agent openclaw binary` task without invoking
    real ansible. Note the `res.stat.exists` / `res.stat.path` / `res.stat.executable`
    / `res.stat.size` shape — distinct from `res.stdout` / `res.rc` used by
    `command` tasks. The executable + size fields are load-bearing: the resolve
    set_fact in the playbook gates the per-agent branch on `stat.exists AND
    stat.executable AND stat.size > 0`, so a mock that omits them would model
    an event that would NOT take the per-agent branch under real ansible.
    """
    if exists:
        stat_payload: dict = {
            "exists": True,
            "path": path,
            "executable": executable,
            "size": size,
        }
    else:
        stat_payload = {"exists": False}
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": task_name,
            "res": {"stat": stat_payload, "changed": False},
        },
    }


def _which_event(stdout: str, rc: int = 0) -> dict:
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": "Discover openclaw binary in PATH",
            "res": {"stdout": stdout, "rc": rc},
        },
    }


def _resolved_binary_event(path: str) -> dict:
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": "Resolve openclaw binary (per-agent preferred, PATH fallback)",
            "res": {"ansible_facts": {"openclaw_discovered_binary": path}},
        },
    }


def _version_event(stdout: str, rc: int = 0) -> dict:
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": "Get installed openclaw version",
            "res": {"stdout": stdout, "rc": rc},
        },
    }


def _parse_version_event(version: str) -> dict:
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": "Parse installed openclaw version",
            "res": {"ansible_facts": {"openclaw_installed_version": version}},
        },
    }


def _skip_condition_event(already_installed: bool, runtime_binary: str) -> dict:
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": "Set install skip condition",
            "res": {
                "ansible_facts": {
                    "openclaw_already_installed": already_installed,
                    "openclaw_runtime_binary": runtime_binary,
                }
            },
        },
    }


def _skip_marker_event(version: str, path: str) -> dict:
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": "Mark install as skipped when already installed",
            "res": {
                "msg": (
                    f"OpenClaw v{version} already installed at {path}. "
                    "Skipping binary install."
                )
            },
        },
    }


def _setup_common_zeroclaw(
    monkeypatch, tmp_path, host_record: dict, version: str = "0.7.5"
):
    """Same as `_setup_common` but pinned to the zeroclaw manifest shape.

    Added for ATX Round 1 W1: re-install on a paired zeroclaw must not
    wipe `config.gateway.auth`. The B3 regression guard from issue #357
    needs the same skip-path harness openclaw uses, with a manifest the
    install code accepts.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    mock_manifest = {
        "name": "zeroclaw",
        "entries": [
            {
                "version": version,
                "os": "ubuntu",
                "os_version": "24.04",
                "arch": "x86_64",
                "sha256": "deadbeef",
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

    monkeypatch.setattr(clawrium.core.install, "get_host", lambda _: host_state[0])

    def mock_update_host(_, updater):
        host_state[0] = updater(host_state[0])
        return True

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


def _zeroclaw_skip_marker_event(version: str) -> dict:
    """Emit the playbook task that triggers `_install_was_skipped`."""
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": "Mark install as skipped when already installed",
            "res": {
                "msg": (
                    f"ZeroClaw v{version} already installed at "
                    "/home/zer-test/bin/zeroclaw. Skipping binary install."
                )
            },
        },
    }


def _zeroclaw_skip_fact_event() -> dict:
    """Emit the playbook task that sets the skip fact."""
    return {
        "event": "runner_on_ok",
        "event_data": {
            "task": "Set install skip condition",
            "res": {"ansible_facts": {"zeroclaw_already_installed": True}},
        },
    }


def test_zeroclaw_reinstall_preserves_paired_gateway_token(monkeypatch, tmp_path):
    """ATX Round 1 W1: re-installing on an already-paired zeroclaw must
    preserve the `config.gateway.auth` bearer token in hosts.json.

    Pre-#357 install.py only restored `preserved_gateway` for openclaw.
    The B3 generalization adds zeroclaw to the restore set; this test
    pins the contract so a future refactor of the guard doesn't silently
    drop zeroclaw."""
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
            "zer-paired": {
                "type": "zeroclaw",
                "status": "installed",
                "installed_at": "2026-05-01T00:00:00+00:00",
                "error": None,
                "agent_name": "zer-paired",
                "version": "0.7.5",
                "config": {
                    "gateway": {
                        "url": "ws://test-host:40000/ws/chat",
                        "auth": "paired-token-from-prior-configure-abc123",
                    }
                },
            }
        },
    }

    host_state = _setup_common_zeroclaw(monkeypatch, tmp_path, host)

    import ansible_runner

    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                _zeroclaw_skip_fact_event(),
                _zeroclaw_skip_marker_event("0.7.5"),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("zeroclaw", "test-host", name="zer-paired")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skip_reason"] == "already_installed"

    # The bearer token MUST be byte-identical after the skip. Pre-#357
    # generalization, `claw_name == "openclaw"` excluded zeroclaw from
    # the restore path and this assertion would fail.
    agent_record = host_state[0]["agents"]["zer-paired"]
    gateway = agent_record["config"]["gateway"]
    assert gateway["auth"] == "paired-token-from-prior-configure-abc123"
    assert gateway["url"] == "ws://test-host:40000/ws/chat"


def test_install_reuses_existing_installed_name_and_reports_skip(monkeypatch, tmp_path):
    """Skip path must preserve the existing agent's gateway credentials.

    B2 fix (ATX review v1): the agent record is keyed by agent name, not by
    claw type, and `run_installation` is invoked with `name='existing-agent'`
    so it targets the same key. Otherwise the install code would generate a
    random new name, the `agents.openclaw` record would stay untouched, and
    the credential assertions below would pass trivially regardless of what
    the install code actually wrote (the false positive flagged in review v1).
    """
    from clawrium.core.install import run_installation

    preserved_device = {
        "id": "device-abc",
        "token": "token-xyz",
        "privateKey": "PEM-DATA-HERE",
    }
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
            "existing-agent": {
                "type": "openclaw",
                "status": "installed",
                "installed_at": "2026-04-10T00:00:00+00:00",
                "error": None,
                "agent_name": "existing-agent",
                "version": "2026.4.2",
                "config": {
                    "gateway": {
                        "url": "ws://example:40001",
                        "auth": "preserved-gateway-token-aaaaaaaaaaaaaa",
                        "device": preserved_device,
                    }
                },
            }
        },
    }

    host_state = _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    per_agent_path = "/home/existing-agent/.openclaw/bin/openclaw"
    # Per-agent binary present at target version; a stale system-wide binary
    # also exists at a different version — discovery must prefer per-agent.
    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                _stat_event(
                    "Check per-agent openclaw binary", per_agent_path, exists=True
                ),
                _which_event("/usr/local/bin/openclaw", rc=0),
                _resolved_binary_event(per_agent_path),
                _version_event("openclaw 2026.4.2", rc=0),
                _parse_version_event("2026.4.2"),
                _skip_condition_event(
                    already_installed=True, runtime_binary=per_agent_path
                ),
                _skip_marker_event("2026.4.2", per_agent_path),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host", name="existing-agent")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skip_reason"] == "already_installed"
    agent_record = host_state[0]["agents"]["existing-agent"]
    assert agent_record["agent_name"] == "existing-agent"
    assert agent_record["status"] == "installed"
    # B3 regression guard: gateway URL, auth token, and device credentials
    # must be byte-identical after the skip. Pre-fix, set_installing() wiped
    # the agent record and set_installed() had no captured snapshot to write
    # back, so credentials silently disappeared even though `skipped=True`
    # was reported. The `preserved_gateway` capture in install.py restores
    # them under `install_skipped=True and gateway_token is None`.
    gateway = agent_record["config"]["gateway"]
    assert gateway["url"] == "ws://example:40001"
    assert gateway["auth"] == "preserved-gateway-token-aaaaaaaaaaaaaa"
    assert gateway["device"] == preserved_device
    assert mock_run.call_count == 2


def test_install_existing_agent_different_version_proceeds_with_install(
    monkeypatch, tmp_path
):
    """When the installed version differs from the requested version, the
    playbook does NOT emit the skip marker (openclaw_already_installed=false),
    so installation proceeds. Validates the version-aware skip introduced in
    issue #163.
    """
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
            "existing-agent": {
                "type": "openclaw",
                "status": "installed",
                "installed_at": "2026-04-10T00:00:00+00:00",
                "error": None,
                "agent_name": "existing-agent",
                "version": "2026.3.1",
            }
        },
    }

    host_state = _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    # Mismatched version: installed=2026.3.1, target=2026.4.2 (from manifest in
    # _setup_common). Playbook emits the version facts but NOT the skip marker.
    per_agent_path = "/home/existing-agent/.openclaw/bin/openclaw"
    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                _stat_event(
                    "Check per-agent openclaw binary", per_agent_path, exists=False
                ),
                _which_event("/usr/local/bin/openclaw", rc=0),
                _resolved_binary_event("/usr/local/bin/openclaw"),
                _version_event("openclaw 2026.3.1", rc=0),
                _parse_version_event("2026.3.1"),
                _skip_condition_event(
                    already_installed=False, runtime_binary="/usr/local/bin/openclaw"
                ),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    # `name=` targets the existing agent record. Without it install would
    # generate a fresh name and the "different version" scenario the test
    # claims to exercise wouldn't actually be exercised.
    result = run_installation("openclaw", "test-host", name="existing-agent")

    assert result["success"] is True
    assert result.get("skipped") is not True
    assert result.get("skip_reason") is None
    assert mock_run.call_count == 2
    # R3-W4 / R4-W2: only `status` and `installed_at` prove set_installed
    # actually ran; `version` is written by set_installing BEFORE ansible
    # executes, so a version assertion on its own would not catch a
    # set_installed failure. Asserting all three discriminates between
    # "manifest cache regression" (would also flip version) and "set_installed
    # never reached" (would leave status=installing, installed_at=None).
    agent_record = host_state[0]["agents"]["existing-agent"]
    assert agent_record["status"] == "installed"
    assert agent_record["installed_at"] is not None
    assert agent_record["version"] == "2026.4.2"


def test_openclaw_skip_detection_matches_fact_and_marker():
    from clawrium.core.install import _openclaw_install_was_skipped

    class Result:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {"ansible_facts": {"openclaw_already_installed": True}},
                },
            }
        ]

    assert _openclaw_install_was_skipped(Result()) is True

    class ResultByTask:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Mark install as skipped when already installed",
                    "res": {"msg": "already installed at /usr/local/bin/openclaw"},
                },
            }
        ]

    assert _openclaw_install_was_skipped(ResultByTask()) is True

    class ResultNoSkip:
        events = []

    assert _openclaw_install_was_skipped(ResultNoSkip()) is False

    class ResultFalsePositive:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Download OpenClaw installer script",
                    "res": {
                        "msg": "Package already installed by another process, skipping"
                    },
                },
            }
        ]

    assert _openclaw_install_was_skipped(ResultFalsePositive()) is False

    # W4 (#305): the resolved-binary set_fact does NOT itself signal a skip.
    # Only `openclaw_already_installed=True` or the skip-marker task name does.
    # This guards against future regressions where someone adds an over-broad
    # substring match on `openclaw_discovered_binary` and accidentally claims
    # every install was skipped.
    class ResultResolvedOnly:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": (
                        "Resolve openclaw binary (per-agent preferred, PATH fallback)"
                    ),
                    "res": {
                        "ansible_facts": {
                            "openclaw_discovered_binary": (
                                "/home/agent/.openclaw/bin/openclaw"
                            )
                        }
                    },
                },
            }
        ]

    assert _openclaw_install_was_skipped(ResultResolvedOnly()) is False

    # And once the skip-condition fact also lands, detection flips True.
    class ResultResolvedAndSkipped:
        events = [
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": (
                        "Resolve openclaw binary (per-agent preferred, PATH fallback)"
                    ),
                    "res": {
                        "ansible_facts": {
                            "openclaw_discovered_binary": (
                                "/home/agent/.openclaw/bin/openclaw"
                            )
                        }
                    },
                },
            },
            {
                "event": "runner_on_ok",
                "event_data": {
                    "task": "Set install skip condition",
                    "res": {
                        "ansible_facts": {
                            "openclaw_already_installed": True,
                            "openclaw_runtime_binary": (
                                "/home/agent/.openclaw/bin/openclaw"
                            ),
                        }
                    },
                },
            },
        ]

    assert _openclaw_install_was_skipped(ResultResolvedAndSkipped()) is True


def test_install_failure_sets_failed_status_without_installed_timestamp(
    monkeypatch, tmp_path
):
    from clawrium.core.install import InstallationError, run_installation

    # Use a fixed name to make assertions deterministic
    test_agent_name = "test-agent"

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
    host_state = _setup_common(monkeypatch, tmp_path, host)

    import clawrium.core.install

    monkeypatch.setattr(
        clawrium.core.install,
        "_get_base_playbook_path",
        lambda: tmp_path / "missing-base.yaml",
    )

    with pytest.raises(InstallationError, match="Base playbook not found"):
        run_installation("openclaw", "test-host", name=test_agent_name)

    assert host_state[0]["agents"][test_agent_name]["status"] == "failed"
    assert host_state[0]["agents"][test_agent_name]["installed_at"] is None


def _capture_inventory_run(captured: list):
    """Build a mock for ansible_runner.run that captures the inventory it
    receives so tests can assert on extra_vars (e.g., force_install)."""

    def _runner(*args, **kwargs):
        captured.append(kwargs.get("inventory"))

        class Result:
            status = "successful"

            class Config:
                artifact_dir = "/tmp/nonexistent"

            config = Config()
            events = []

        return Result()

    return _runner


def test_install_with_force_skips_skip_logic(monkeypatch, tmp_path):
    """force=True must inject force_install=true into the playbook inventory
    AND not result in skipped=True even when the installed version matches.
    """
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
            "existing-agent": {
                "type": "openclaw",
                "status": "installed",
                "installed_at": "2026-04-10T00:00:00+00:00",
                "error": None,
                "agent_name": "existing-agent",
                "version": "2026.4.2",
                "config": {
                    "gateway": {
                        "url": "ws://example:40001",
                        "auth": "preserved-gateway-token-aaaaaaaaaaaaaa",
                        "device": {
                            "id": "d",
                            "token": "t",
                            "privateKey": "k",
                        },
                    }
                },
            }
        },
    }

    _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    captured_inventories: list = []
    monkeypatch.setattr(
        ansible_runner, "run", _capture_inventory_run(captured_inventories)
    )

    result = run_installation(
        "openclaw", "test-host", name="existing-agent", force=True
    )

    # Two playbooks run: base + agent. Both receive the same inventory vars.
    assert len(captured_inventories) == 2
    for inv in captured_inventories:
        assert inv["all"]["vars"]["force_install"] is True

    # No skip marker in the (empty) event stream -> not skipped.
    assert result["success"] is True
    assert result.get("skipped") is not True


def test_install_without_force_passes_force_install_false(monkeypatch, tmp_path):
    """Default force=False propagates as force_install=false into inventory."""
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
    _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    captured_inventories: list = []
    monkeypatch.setattr(
        ansible_runner, "run", _capture_inventory_run(captured_inventories)
    )

    run_installation("openclaw", "test-host", name="fresh-agent")

    assert len(captured_inventories) == 2
    for inv in captured_inventories:
        assert inv["all"]["vars"]["force_install"] is False


def test_install_with_unparseable_version_proceeds_with_install(monkeypatch, tmp_path):
    """If `openclaw --version` produces output that doesn't match the SemVer
    regex, the playbook treats installed_version as empty -> not equal to
    target -> installation proceeds (safe default to reinstall).

    This test exercises the Python-side detection: when the playbook does NOT
    emit the skip marker (because version parsing failed and produced empty
    string != target), the result is not skipped.
    """
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
            "existing-agent": {
                "type": "openclaw",
                "status": "installed",
                "installed_at": "2026-04-10T00:00:00+00:00",
                "error": None,
                "agent_name": "existing-agent",
                "version": "2026.4.2",
            }
        },
    }
    host_state = _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    # Playbook reports binary exists but version output is garbage; skip marker
    # is NOT emitted because installed_version != target_version.
    per_agent_path = "/home/existing-agent/.openclaw/bin/openclaw"
    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                _stat_event(
                    "Check per-agent openclaw binary", per_agent_path, exists=False
                ),
                _which_event("/usr/local/bin/openclaw", rc=0),
                _resolved_binary_event("/usr/local/bin/openclaw"),
                _version_event("openclaw: command moved, please reinstall", rc=0),
                _parse_version_event(""),
                _skip_condition_event(
                    already_installed=False, runtime_binary="/usr/local/bin/openclaw"
                ),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    # `name=` so the install code targets the existing record rather than
    # generating a fresh name (which would make "no skip marker" trivially true).
    result = run_installation("openclaw", "test-host", name="existing-agent")

    assert result["success"] is True
    assert result.get("skipped") is not True
    # R3-W4 + R4-W1: status + installed_at confirm set_installed ran;
    # version assertion catches manifest-cache regressions that would write
    # the wrong matched_version. Symmetric with the different-version test.
    agent_record = host_state[0]["agents"]["existing-agent"]
    assert agent_record["status"] == "installed"
    assert agent_record["installed_at"] is not None
    assert agent_record["version"] == "2026.4.2"


# -----------------------------------------------------------------------------
# Issue #305 — binary discovery convergence tests
#
# These cases exercise the "per-agent stat then PATH fallback" precedence
# explicitly. They prove:
#   * the skip path fires when the per-agent binary is at target *even if* a
#     system-wide binary at a different version exists (T1 — the #305 fix);
#   * a per-agent binary at the wrong version forces a reinstall, even if a
#     system-wide binary happens to be at the target version (T2 — per-agent
#     wins, so the playbook converges on the binary clawrium manages);
#   * PATH fallback still works when the per-agent path is absent (T3);
#   * with no binary anywhere, install proceeds and `openclaw_runtime_binary`
#     falls back to the static per-agent path (T4).
# -----------------------------------------------------------------------------


def _host_with_existing_agent(version: str = "2026.4.2") -> dict:
    # B2 fix (ATX v1): keyed by agent name, with explicit `type` field, so the
    # install code's lookups actually find this record when invoked with
    # `name='existing-agent'`. The pre-fix shape (`agents.openclaw`) was never
    # touched by install.py and made the credential assertions trivially pass.
    return {
        "hostname": "test-host",
        "key_id": "test-host",
        "hardware": {
            "architecture": "x86_64",
            "os": "ubuntu",
            "os_version": "24.04",
            "memtotal_mb": 4096,
        },
        "agents": {
            "existing-agent": {
                "type": "openclaw",
                "status": "installed",
                "installed_at": "2026-04-10T00:00:00+00:00",
                "error": None,
                "agent_name": "existing-agent",
                "version": version,
                "config": {
                    "gateway": {
                        "url": "ws://example:40001",
                        "auth": "preserved-gateway-token-aaaaaaaaaaaaaa",
                        "device": {
                            "id": "device-abc",
                            "token": "token-xyz",
                            "privateKey": "PEM-DATA-HERE",
                        },
                    }
                },
            }
        },
    }


def test_install_skips_when_per_agent_binary_at_target_and_system_diverges(
    monkeypatch, tmp_path
):
    """T1 — the #305 fix.

    Per-agent binary exists at the target version; a system-wide binary also
    exists but at a different version. The playbook must prefer the per-agent
    binary, observe a version match, fire the skip path, and preserve the
    existing gateway credentials byte-identical.
    """
    from clawrium.core.install import run_installation

    per_agent_path = "/home/existing-agent/.openclaw/bin/openclaw"
    host = _host_with_existing_agent()
    host_state = _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                _stat_event(
                    "Check per-agent openclaw binary", per_agent_path, exists=True
                ),
                _which_event("/usr/local/bin/openclaw", rc=0),
                _resolved_binary_event(per_agent_path),
                _version_event("openclaw 2026.4.2", rc=0),
                _parse_version_event("2026.4.2"),
                _skip_condition_event(
                    already_installed=True, runtime_binary=per_agent_path
                ),
                _skip_marker_event("2026.4.2", per_agent_path),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host", name="existing-agent")

    assert result["success"] is True
    assert result["skipped"] is True
    assert result["skip_reason"] == "already_installed"
    gateway = host_state[0]["agents"]["existing-agent"]["config"]["gateway"]
    assert gateway["auth"] == "preserved-gateway-token-aaaaaaaaaaaaaa"
    assert gateway["device"]["id"] == "device-abc"
    assert gateway["device"]["token"] == "token-xyz"


def test_install_reinstalls_when_per_agent_binary_at_non_target_even_if_system_matches(
    monkeypatch, tmp_path
):
    """T2 — per-agent precedence regression guard.

    Per-agent binary at the wrong version, system-wide binary at the target
    version. Per-agent must win, the version mismatch must defeat the skip
    path, and the install must proceed. The previous `creates:` guard on the
    install task would have silently masked this case — that guard is removed.
    """
    from clawrium.core.install import run_installation

    per_agent_path = "/home/existing-agent/.openclaw/bin/openclaw"
    host = _host_with_existing_agent()
    _setup_common(monkeypatch, tmp_path, host)
    # Need `name=` so the agent record under "existing-agent" is targeted;
    # otherwise install would generate a random name and a different code
    # path that doesn't exercise the per-agent stat precedence rule.

    import ansible_runner

    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                _stat_event(
                    "Check per-agent openclaw binary", per_agent_path, exists=True
                ),
                _which_event("/usr/local/bin/openclaw", rc=0),
                _resolved_binary_event(per_agent_path),
                _version_event("openclaw 2026.3.1", rc=0),
                _parse_version_event("2026.3.1"),
                _skip_condition_event(
                    already_installed=False, runtime_binary=per_agent_path
                ),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host", name="existing-agent")

    assert result["success"] is True
    assert result.get("skipped") is not True


def test_install_falls_back_to_path_when_per_agent_binary_absent(monkeypatch, tmp_path):
    """T3 — PATH fallback when no per-agent binary exists.

    A legacy host where someone hand-installed `/usr/local/bin/openclaw` at the
    target version, and the agent has never been installed by clawrium. The
    skip path still fires via the PATH-discovered binary; runtime path is the
    `which` result.
    """
    from clawrium.core.install import run_installation

    per_agent_path = "/home/existing-agent/.openclaw/bin/openclaw"
    host = _host_with_existing_agent()
    _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                _stat_event(
                    "Check per-agent openclaw binary", per_agent_path, exists=False
                ),
                _which_event("/usr/local/bin/openclaw", rc=0),
                _resolved_binary_event("/usr/local/bin/openclaw"),
                _version_event("openclaw 2026.4.2", rc=0),
                _parse_version_event("2026.4.2"),
                _skip_condition_event(
                    already_installed=True,
                    runtime_binary="/usr/local/bin/openclaw",
                ),
                _skip_marker_event("2026.4.2", "/usr/local/bin/openclaw"),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host", name="existing-agent")

    assert result["success"] is True
    assert result["skipped"] is True


def test_install_proceeds_with_install_when_no_binary_anywhere(monkeypatch, tmp_path):
    """T4 — fresh install: no binary anywhere.

    Neither the per-agent path nor `which openclaw` resolves. The skip path
    does not fire; `openclaw_runtime_binary` falls back to the static
    per-agent path so the systemd unit's ExecStart converges on the binary the
    install step is about to write.
    """
    from clawrium.core.install import run_installation

    per_agent_path = "/home/fresh-agent/.openclaw/bin/openclaw"
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
    _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                _stat_event(
                    "Check per-agent openclaw binary", per_agent_path, exists=False
                ),
                _which_event("", rc=1),
                _resolved_binary_event(""),
                _skip_condition_event(
                    already_installed=False, runtime_binary=per_agent_path
                ),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host", name="fresh-agent")

    assert result["success"] is True
    assert result.get("skipped") is not True


def test_install_python_skip_detection_with_path_fallback_runtime_binary(
    monkeypatch, tmp_path
):
    """Round 3 B2: Python skip detection is path-agnostic.

    Python's `_install_was_skipped` reads only the `Set install skip condition`
    fact and the `Mark install as skipped` task name — never the stat or
    resolved-binary events. So a non-executable per-agent stat (which the
    playbook's `stat.executable AND stat.size > 0` guard rejects in favour of
    PATH fallback) is BYTE-EQUIVALENT to "no per-agent binary" from the Python
    layer's perspective. The corresponding playbook guard is verified
    statically in `tests/test_install_binary_discovery.py`; the Python-side
    behavior we still need to pin is: when the runtime_binary in the
    skip-condition event is the PATH fallback, the skip is still detected and
    the existing gateway credentials are still preserved by the openclaw-
    specific restore branch in `set_installed`.
    """
    from clawrium.core.install import run_installation

    per_agent_path = "/home/existing-agent/.openclaw/bin/openclaw"
    host = _host_with_existing_agent()
    host_state = _setup_common(monkeypatch, tmp_path, host)

    import ansible_runner

    run_side_effect = [
        _result_with_events(tmp_path, []),
        _result_with_events(
            tmp_path,
            [
                # Per-agent file present but non-executable -> per-agent branch
                # of the resolve set_fact would reject it under real ansible;
                # event stream models the PATH-fallback path.
                _stat_event(
                    "Check per-agent openclaw binary",
                    per_agent_path,
                    exists=True,
                    executable=False,
                    size=0,
                ),
                _which_event("/usr/local/bin/openclaw", rc=0),
                _resolved_binary_event("/usr/local/bin/openclaw"),
                _version_event("openclaw 2026.4.2", rc=0),
                _parse_version_event("2026.4.2"),
                _skip_condition_event(
                    already_installed=True,
                    runtime_binary="/usr/local/bin/openclaw",
                ),
                _skip_marker_event("2026.4.2", "/usr/local/bin/openclaw"),
            ],
        ),
    ]
    mock_run = Mock(side_effect=run_side_effect)
    monkeypatch.setattr(ansible_runner, "run", mock_run)

    result = run_installation("openclaw", "test-host", name="existing-agent")

    assert result["success"] is True
    assert result["skipped"] is True
    # Distinct from T3 (per-agent absent / path target): here a per-agent file
    # exists but is broken. The credential-preservation branch in
    # set_installed() must still fire — preservation does NOT depend on which
    # branch resolved the binary, only on `install_skipped` + captured
    # `preserved_gateway`. R4-W3: assert ALL four sub-fields so a partial-dict
    # corruption (e.g. accidental merge instead of atomic replace) is caught,
    # not only top-level auth/device.id.
    gateway = host_state[0]["agents"]["existing-agent"]["config"]["gateway"]
    assert gateway["url"] == "ws://example:40001"
    assert gateway["auth"] == "preserved-gateway-token-aaaaaaaaaaaaaa"
    assert gateway["device"]["id"] == "device-abc"
    assert gateway["device"]["token"] == "token-xyz"
    assert gateway["device"]["privateKey"] == "PEM-DATA-HERE"
