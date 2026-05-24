"""Hermes onboarding pipeline tests (issue #68 Phase 4).

This module covers the Phase 4 contract for hermes onboarding: the manifest
declares a real pipeline (providers required, identity auto_skip, channels
required cli-only, validate composite), `can_skip_stage` honors per-stage
``auto_skip:true`` so the wizard skips identity without prompting, and
`validate_hermes_health` runs the three composite checks via Ansible on the
agent host.
"""

from unittest.mock import MagicMock, patch

import pytest

from clawrium.core.onboarding import can_skip_stage, get_stage_tasks
from clawrium.core.registry import load_manifest
from clawrium.core.validation import validate_hermes_health


# ---------------------------------------------------------------------------
# Manifest-level contracts.
# ---------------------------------------------------------------------------


def test_hermes_manifest_parses_with_real_onboarding_pipeline():
    """The hermes manifest validates under the existing registry schema and
    exposes the four canonical stages with the Phase 4 shape."""
    manifest = load_manifest("hermes")
    onboarding = manifest.get("onboarding") or {}
    stages = onboarding.get("stages") or {}
    assert set(stages.keys()) == {"providers", "identity", "channels", "validate"}


def test_hermes_providers_stage_is_required():
    manifest = load_manifest("hermes")
    providers = manifest["onboarding"]["stages"]["providers"]
    assert providers["required"] is True
    assert providers.get("auto_skip") is not True


def test_hermes_identity_stage_auto_skips():
    manifest = load_manifest("hermes")
    identity = manifest["onboarding"]["stages"]["identity"]
    assert identity["auto_skip"] is True
    assert identity["description"]


def test_hermes_channels_stage_default_cli():
    """channels stage is required and ships confirm tasks — the first one
    (confirm_cli) defaults to True for the always-on OpenAI API gateway."""
    manifest = load_manifest("hermes")
    channels = manifest["onboarding"]["stages"]["channels"]
    assert channels["required"] is True

    tasks = channels.get("tasks", [])
    assert tasks, "hermes channels stage must declare at least one task"
    confirm_tasks = [t for t in tasks if t.get("type") == "confirm"]
    assert confirm_tasks
    assert confirm_tasks[0].get("default") is True


def test_hermes_validate_stage_runs_binary_env_health():
    manifest = load_manifest("hermes")
    validate_stage = manifest["onboarding"]["stages"]["validate"]
    tasks = validate_stage.get("tasks", [])
    task_ids = [t.get("id") for t in tasks]
    assert task_ids == ["binary_check", "env_check", "health_check"]


def test_hermes_stage_ordering_matches_canonical():
    manifest = load_manifest("hermes")
    stages = list(manifest["onboarding"]["stages"].keys())
    assert stages == ["providers", "identity", "channels", "validate"]


# ---------------------------------------------------------------------------
# can_skip_stage behavior — per-stage auto_skip:true must be honored.
# ---------------------------------------------------------------------------


def test_can_skip_stage_honors_hermes_identity_auto_skip():
    """Phase 4 contract: the configure wizard must skip identity for hermes
    without prompting, because hermes manages identity internally."""
    assert can_skip_stage("hermes", "identity") is True


def test_can_skip_stage_does_not_skip_required_stages():
    """providers/channels/validate are required for hermes — the wizard
    must run them."""
    assert can_skip_stage("hermes", "providers") is False
    assert can_skip_stage("hermes", "channels") is False
    assert can_skip_stage("hermes", "validate") is False


# ---------------------------------------------------------------------------
# get_stage_tasks plumbing.
# ---------------------------------------------------------------------------


def test_get_stage_tasks_returns_provider_select_and_test():
    tasks = get_stage_tasks("hermes", "providers")
    types = [t.get("type") for t in tasks]
    assert "provider_select" in types
    assert "provider_test" in types


# ---------------------------------------------------------------------------
# validate_hermes_health — three composite checks via Ansible.
# ---------------------------------------------------------------------------


@pytest.fixture
def hermes_host_record():
    return {
        "hostname": "192.168.1.36",
        "alias": "wolf-i",
        "user": "xclm",
        "port": 22,
        "key_id": "wolf-i",
        "agents": {
            "hermes-test": {
                "type": "hermes",
                "version": "2026.5.7",
                "agent_name": "hermes-test",
            }
        },
    }


def _build_mock_runner_result(stdout: str, rc: int = 0):
    event = {
        "event": "runner_on_ok",
        "event_data": {"res": {"stdout": stdout, "rc": rc}},
    }
    result = MagicMock()
    result.events = [event]
    return result


def test_validate_hermes_health_passes_when_all_checks_succeed(hermes_host_record):
    stdout = "BINARY_CHECK\nv0.13.0 (2026.5.7)\nBINARY_RC=0\nENV_CHECK\nENV_OK\nHEALTH_CHECK\n200\n"

    with (
        patch(
            "clawrium.core.validation.get_host",
            return_value=hermes_host_record,
        ),
        patch(
            "clawrium.core.keys.get_host_private_key",
            return_value="/tmp/fake-key",
        ),
        patch(
            "ansible_runner.run",
            return_value=_build_mock_runner_result(stdout),
        ),
    ):
        result = validate_hermes_health("wolf-i", "hermes-test")

    assert result.passed is True
    assert result.errors == []
    assert result.details["health_status"] == "200"
    assert result.details["binary_rc"] == 0
    assert result.details["env_ok"] is True


def test_validate_hermes_health_fails_when_health_not_200(hermes_host_record):
    stdout = (
        "BINARY_CHECK\nv0.13.0 (2026.5.7)\nBINARY_RC=0\n"
        "ENV_CHECK\nENV_OK\n"
        "HEALTH_CHECK\nCURL_FAILED\n"
    )

    with (
        patch(
            "clawrium.core.validation.get_host",
            return_value=hermes_host_record,
        ),
        patch(
            "clawrium.core.keys.get_host_private_key",
            return_value="/tmp/fake-key",
        ),
        patch(
            "ansible_runner.run",
            return_value=_build_mock_runner_result(stdout),
        ),
    ):
        result = validate_hermes_health("wolf-i", "hermes-test")

    assert result.passed is False
    assert any("/health" in e for e in result.errors)


def test_validate_hermes_health_fails_when_env_missing(hermes_host_record):
    stdout = (
        "BINARY_CHECK\nv0.13.0 (2026.5.7)\nBINARY_RC=0\n"
        "ENV_CHECK\nENV_MISSING\n"
        "HEALTH_CHECK\n200\n"
    )

    with (
        patch(
            "clawrium.core.validation.get_host",
            return_value=hermes_host_record,
        ),
        patch(
            "clawrium.core.keys.get_host_private_key",
            return_value="/tmp/fake-key",
        ),
        patch(
            "ansible_runner.run",
            return_value=_build_mock_runner_result(stdout),
        ),
    ):
        result = validate_hermes_health("wolf-i", "hermes-test")

    assert result.passed is False
    assert any(".env" in e for e in result.errors)


def test_validate_hermes_health_fails_when_binary_missing(hermes_host_record):
    stdout = (
        "BINARY_CHECK\nhermes: command not found\nBINARY_RC=127\n"
        "ENV_CHECK\nENV_OK\n"
        "HEALTH_CHECK\n200\n"
    )

    with (
        patch(
            "clawrium.core.validation.get_host",
            return_value=hermes_host_record,
        ),
        patch(
            "clawrium.core.keys.get_host_private_key",
            return_value="/tmp/fake-key",
        ),
        patch(
            "ansible_runner.run",
            return_value=_build_mock_runner_result(stdout, rc=127),
        ),
    ):
        result = validate_hermes_health("wolf-i", "hermes-test")

    assert result.passed is False
    assert any("hermes" in e.lower() for e in result.errors)


def test_validate_hermes_health_reports_missing_agent(hermes_host_record):
    """If the agent record is absent on the host, validate_hermes_health must
    return a clean ValidationResult rather than dispatching Ansible."""
    host_without_agent = {**hermes_host_record, "agents": {}}

    with patch(
        "clawrium.core.validation.get_host",
        return_value=host_without_agent,
    ):
        result = validate_hermes_health("wolf-i", "hermes-test")

    assert result.passed is False
    assert any("not" in e.lower() for e in result.errors)


@pytest.mark.parametrize(
    "payload",
    [
        "hermes; rm -rf /",  # command chaining
        "hermes$(whoami)",  # subshell substitution
        "hermes`id`",  # backtick substitution
        "1hermes",  # leading digit
        "Hermes",  # uppercase
        "a" * 33,  # over 32 chars
        "her mes",  # whitespace
        "",  # empty
        "hermes\n--version",  # newline injection
        "hermes/../etc/passwd",  # path traversal
    ],
)
def test_validate_hermes_health_rejects_injection_payload_in_claw_name(payload):
    """Defense-in-depth: claw_name is interpolated into a `sudo -u <name>`
    shell command. Re-validate at point of use so even a corrupted
    hosts.json entry cannot trigger shell injection through this path.

    Multiple payload classes are covered: command chaining, subshell,
    backtick, leading digit, uppercase, oversize, whitespace, empty,
    newline, path traversal. All must be rejected BEFORE any host lookup
    or ansible_runner.run call.
    """
    with (
        patch(
            "ansible_runner.run",
            side_effect=AssertionError(
                "validate_hermes_health must NOT call ansible_runner with an "
                "unsafe agent name"
            ),
        ),
        patch(
            "clawrium.core.validation.get_host",
            side_effect=AssertionError(
                "validate_hermes_health must short-circuit BEFORE host lookup "
                "when claw_name is malformed"
            ),
        ),
    ):
        result = validate_hermes_health("wolf-i", payload)

    assert result.passed is False
    assert any("invalid agent name" in e.lower() for e in result.errors), (
        f"payload {payload!r} did not produce 'invalid agent name' error: "
        f"{result.errors}"
    )


def test_validate_hermes_health_handles_ansible_exception(hermes_host_record):
    """If ansible_runner.run raises (e.g. SSH timeout, network failure,
    runner bootstrap error), validate_hermes_health must surface a
    ValidationResult with a single, well-shaped error instead of
    propagating an uncaught exception out of the validation layer."""
    with (
        patch(
            "clawrium.core.validation.get_host",
            return_value=hermes_host_record,
        ),
        patch(
            "clawrium.core.keys.get_host_private_key",
            return_value="/tmp/fake-key",
        ),
        patch(
            "ansible_runner.run",
            side_effect=RuntimeError("ssh: connect to host: timeout"),
        ),
    ):
        result = validate_hermes_health("wolf-i", "hermes-test")

    assert result.passed is False
    assert len(result.errors) == 1
    assert "hermes health checks" in result.errors[0].lower()
    assert "timeout" in result.errors[0].lower()


def test_validate_hermes_health_cleans_up_runner_directory(hermes_host_record):
    """Ansible-runner writes inventory (host IPs, SSH key paths) under its
    `private_data_dir`. validate_hermes_health must allocate a 0o700 temp
    directory and remove it unconditionally, so secrets do not leak to other
    local users via /tmp world-readable inventory files."""
    import os

    captured_paths: list[str] = []

    def fake_run(*, private_data_dir, **kwargs):
        captured_paths.append(private_data_dir)
        # Confirm permissions match the security contract while the dir
        # still exists.
        mode = os.stat(private_data_dir).st_mode & 0o777
        assert mode == 0o700, f"runner dir must be 0o700, got {oct(mode)}"
        return _build_mock_runner_result(
            "BINARY_CHECK\nv1\nBINARY_RC=0\nENV_CHECK\nENV_OK\nHEALTH_CHECK\n200\n"
        )

    with (
        patch(
            "clawrium.core.validation.get_host",
            return_value=hermes_host_record,
        ),
        patch(
            "clawrium.core.keys.get_host_private_key",
            return_value="/tmp/fake-key",
        ),
        patch("ansible_runner.run", side_effect=fake_run),
    ):
        result = validate_hermes_health("wolf-i", "hermes-test")

    assert result.passed is True
    assert captured_paths, "ansible_runner.run was not called"
    # The directory MUST be cleaned up after validate returns.
    assert not os.path.exists(captured_paths[0]), (
        f"runner dir {captured_paths[0]} leaked after validate_hermes_health"
    )


def test_validate_hermes_health_cleans_up_runner_directory_on_exception(
    hermes_host_record,
):
    """ATX B5: cleanup must fire on the exception path too. If
    ansible_runner.run raises, the per-run private_data_dir must still be
    removed — otherwise a long-running clm process with many failures would
    accumulate inventory files in /tmp."""
    import os

    captured_paths: list[str] = []

    def fake_run(*, private_data_dir, **kwargs):
        captured_paths.append(private_data_dir)
        raise RuntimeError("ssh: connect to host: timeout")

    with (
        patch(
            "clawrium.core.validation.get_host",
            return_value=hermes_host_record,
        ),
        patch(
            "clawrium.core.keys.get_host_private_key",
            return_value="/tmp/fake-key",
        ),
        patch("ansible_runner.run", side_effect=fake_run),
    ):
        result = validate_hermes_health("wolf-i", "hermes-test")

    assert result.passed is False
    assert captured_paths, "ansible_runner.run was not called"
    assert not os.path.exists(captured_paths[0]), (
        f"runner dir {captured_paths[0]} leaked after ansible_runner exception"
    )


# ---------------------------------------------------------------------------
# can_skip_stage edge cases (S6).
# ---------------------------------------------------------------------------


def test_can_skip_stage_unknown_stage_returns_false():
    """A stage name that isn't present in the manifest cannot be skipped."""
    assert can_skip_stage("hermes", "nonexistent-stage") is False


def test_can_skip_stage_stage_without_auto_skip_returns_false():
    """A stage that omits the auto_skip key entirely is not auto-skipped."""
    # The hermes manifest's providers stage has no auto_skip key, only required:true.
    assert can_skip_stage("hermes", "providers") is False


def test_can_skip_stage_unknown_claw_type_returns_false():
    """An unknown claw type whose manifest can't be loaded must not be
    treated as auto-skippable — the function must return False so the
    wizard does NOT silently skip stages it doesn't recognize."""
    assert can_skip_stage("does-not-exist-claw", "identity") is False
