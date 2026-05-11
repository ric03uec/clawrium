"""Tests for onboarding state machine module."""

import json
import pytest
from clawrium.core.onboarding import (
    OnboardingState,
    StageStatus,
    TRANSITIONS,
    get_onboarding_state,
    transition_state,
    complete_stage,
    update_stage_metadata,
    initialize_onboarding,
    can_skip_stage,
    get_stage_tasks,
    run_stage,
    InvalidTransitionError,
    OnboardingNotFoundError,
    AgentNotFoundError,
)


@pytest.fixture
def host_with_claw(isolated_config):
    """Set up hosts.json with a claw installed but no onboarding."""
    hosts_data = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "port": 22,
            "agent_name": "xclm",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installed",
                    "name": "assistant",
                    "agent_name": "opc-assistant",
                }
            },
        }
    ]

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_path = isolated_config / "hosts.json"
    hosts_path.write_text(json.dumps(hosts_data))

    return isolated_config


@pytest.fixture
def host_with_onboarding(isolated_config):
    """Set up hosts.json with a claw that has onboarding initialized."""
    hosts_data = [
        {
            "hostname": "192.168.1.100",
            "alias": "server1",
            "port": 22,
            "agent_name": "xclm",
            "agents": {
                "openclaw": {
                    "version": "0.1.0",
                    "status": "installed",
                    "name": "assistant",
                    "agent_name": "opc-assistant",
                    "onboarding": {
                        "state": "pending",
                        "started_at": "2026-04-06T00:00:00+00:00",
                        "stages": {
                            "providers": {
                                "status": "pending",
                                "completed_at": None,
                                "provider_id": None,
                            },
                            "identity": {"status": "pending", "completed_at": None},
                            "channels": {"status": "pending", "completed_at": None},
                            "validate": {"status": "pending", "completed_at": None},
                        },
                    },
                }
            },
        }
    ]

    isolated_config.mkdir(parents=True, exist_ok=True)
    hosts_path = isolated_config / "hosts.json"
    hosts_path.write_text(json.dumps(hosts_data))

    return isolated_config


class TestOnboardingStateEnum:
    """Tests for OnboardingState enum."""

    def test_all_states_defined(self):
        """All required states are defined."""
        assert OnboardingState.PENDING.value == "pending"
        assert OnboardingState.PROVIDERS.value == "providers"
        assert OnboardingState.IDENTITY.value == "identity"
        assert OnboardingState.CHANNELS.value == "channels"
        assert OnboardingState.VALIDATE.value == "validate"
        assert OnboardingState.READY.value == "ready"

    def test_state_is_string_enum(self):
        """OnboardingState inherits from str."""
        assert isinstance(OnboardingState.PENDING, str)
        assert OnboardingState.PENDING == "pending"


class TestStageStatusEnum:
    """Tests for StageStatus enum."""

    def test_all_statuses_defined(self):
        """All required statuses are defined."""
        assert StageStatus.PENDING.value == "pending"
        assert StageStatus.COMPLETE.value == "complete"
        assert StageStatus.SKIPPED.value == "skipped"

    def test_status_is_string_enum(self):
        """StageStatus inherits from str."""
        assert isinstance(StageStatus.PENDING, str)
        assert StageStatus.PENDING == "pending"


class TestTransitions:
    """Tests for TRANSITIONS state machine."""

    def test_pending_transitions(self):
        """pending transitions to providers (normal) or ready (all stages auto_skip)."""
        assert "providers" in TRANSITIONS["pending"]
        # Direct PENDING → READY supports manifests whose stages are all
        # auto_skip:true (e.g. hermes Phase 1 placeholder); transition_state()
        # must not raise InvalidTransitionError on this path.
        assert "ready" in TRANSITIONS["pending"]

    def test_providers_transitions(self):
        """providers can only transition to identity."""
        assert TRANSITIONS["providers"] == ["identity"]

    def test_identity_transitions(self):
        """identity can only transition to channels."""
        assert TRANSITIONS["identity"] == ["channels"]

    def test_channels_transitions(self):
        """channels can only transition to validate."""
        assert TRANSITIONS["channels"] == ["validate"]

    def test_validate_transitions(self):
        """validate can transition to ready or back to channels."""
        assert "ready" in TRANSITIONS["validate"]
        assert "channels" in TRANSITIONS["validate"]

    def test_ready_is_idempotent(self):
        """ready can transition to itself (idempotent reinstall)."""
        assert TRANSITIONS["ready"] == ["ready"]

    def test_all_states_have_transitions(self):
        """All OnboardingState values are in TRANSITIONS."""
        for state in OnboardingState:
            assert state.value in TRANSITIONS


class TestGetOnboardingState:
    """Tests for get_onboarding_state function."""

    def test_get_state_with_onboarding(self, host_with_onboarding):
        """Returns current state when onboarding exists."""
        state = get_onboarding_state("server1", "openclaw")
        assert state == OnboardingState.PENDING

    def test_get_state_claw_not_found(self, host_with_onboarding):
        """Raises AgentNotFoundError when claw doesn't exist."""
        with pytest.raises(AgentNotFoundError) as exc_info:
            get_onboarding_state("server1", "nonexistent")
        assert "not found" in str(exc_info.value).lower()

    def test_get_state_onboarding_not_initialized(self, host_with_claw):
        """Raises OnboardingNotFoundError when onboarding not initialized."""
        with pytest.raises(OnboardingNotFoundError) as exc_info:
            get_onboarding_state("server1", "openclaw")
        assert "not initialized" in str(exc_info.value).lower()

    def test_get_state_host_not_found(self, isolated_config):
        """Raises AgentNotFoundError when host doesn't exist."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_path = isolated_config / "hosts.json"
        hosts_path.write_text("[]")

        with pytest.raises(AgentNotFoundError):
            get_onboarding_state("nonexistent", "openclaw")


class TestTransitionState:
    """Tests for transition_state function."""

    def test_valid_transition_pending_to_providers(self, host_with_onboarding):
        """Allows valid transition from pending to providers."""
        result = transition_state("server1", "openclaw", OnboardingState.PROVIDERS)
        assert result is True

        state = get_onboarding_state("server1", "openclaw")
        assert state == OnboardingState.PROVIDERS

    def test_valid_transition_pending_to_ready_auto_skip(self, host_with_onboarding):
        """Allows direct pending → ready (auto-skip path for all-skipped manifests)."""
        # PENDING → READY is the auto_skip short-circuit; transition_state() must
        # accept it so hermes Phase 1 (and any future all-auto-skip manifest) can
        # reach READY without walking through providers/identity/channels/validate.
        result = transition_state("server1", "openclaw", OnboardingState.READY)
        assert result is True
        state = get_onboarding_state("server1", "openclaw")
        assert state == OnboardingState.READY

    def test_invalid_transition_pending_to_validate(self, host_with_onboarding):
        """Rejects skipping states."""
        with pytest.raises(InvalidTransitionError):
            transition_state("server1", "openclaw", OnboardingState.VALIDATE)

    def test_transition_claw_not_found(self, host_with_onboarding):
        """Raises AgentNotFoundError for non-existent claw."""
        with pytest.raises(AgentNotFoundError):
            transition_state("server1", "nonexistent", OnboardingState.PROVIDERS)

    def test_full_happy_path_transitions(self, host_with_onboarding):
        """Test complete onboarding workflow transitions."""
        # pending -> providers
        transition_state("server1", "openclaw", OnboardingState.PROVIDERS)
        assert get_onboarding_state("server1", "openclaw") == OnboardingState.PROVIDERS

        # providers -> identity
        transition_state("server1", "openclaw", OnboardingState.IDENTITY)
        assert get_onboarding_state("server1", "openclaw") == OnboardingState.IDENTITY

        # identity -> channels
        transition_state("server1", "openclaw", OnboardingState.CHANNELS)
        assert get_onboarding_state("server1", "openclaw") == OnboardingState.CHANNELS

        # channels -> validate
        transition_state("server1", "openclaw", OnboardingState.VALIDATE)
        assert get_onboarding_state("server1", "openclaw") == OnboardingState.VALIDATE

        # validate -> ready
        transition_state("server1", "openclaw", OnboardingState.READY)
        assert get_onboarding_state("server1", "openclaw") == OnboardingState.READY

    def test_validate_can_go_back_to_channels(self, host_with_onboarding):
        """validate state can transition back to channels on failure."""
        # Get to validate state
        transition_state("server1", "openclaw", OnboardingState.PROVIDERS)
        transition_state("server1", "openclaw", OnboardingState.IDENTITY)
        transition_state("server1", "openclaw", OnboardingState.CHANNELS)
        transition_state("server1", "openclaw", OnboardingState.VALIDATE)

        # Go back to channels
        result = transition_state("server1", "openclaw", OnboardingState.CHANNELS)
        assert result is True
        assert get_onboarding_state("server1", "openclaw") == OnboardingState.CHANNELS


class TestCompleteStage:
    """Tests for complete_stage function."""

    def test_complete_stage_success(self, host_with_onboarding):
        """Marks stage as complete with timestamp."""
        result = complete_stage(
            "server1", "openclaw", "providers", StageStatus.COMPLETE
        )
        assert result is True

        # Verify stage data
        from clawrium.core.hosts import get_host

        host = get_host("server1")
        stage = host["agents"]["openclaw"]["onboarding"]["stages"]["providers"]
        assert stage["status"] == "complete"
        assert stage["completed_at"] is not None

    def test_complete_stage_with_metadata(self, host_with_onboarding):
        """Stores metadata with stage completion."""
        metadata = {"provider_id": "openai-default"}
        result = complete_stage(
            "server1", "openclaw", "providers", StageStatus.COMPLETE, metadata
        )
        assert result is True

        from clawrium.core.hosts import get_host

        host = get_host("server1")
        stage = host["agents"]["openclaw"]["onboarding"]["stages"]["providers"]
        assert stage["provider_id"] == "openai-default"

    def test_complete_stage_skipped(self, host_with_onboarding):
        """Marks stage as skipped."""
        result = complete_stage("server1", "openclaw", "channels", StageStatus.SKIPPED)
        assert result is True

        from clawrium.core.hosts import get_host

        host = get_host("server1")
        stage = host["agents"]["openclaw"]["onboarding"]["stages"]["channels"]
        assert stage["status"] == "skipped"

    def test_complete_invalid_stage(self, host_with_onboarding):
        """Raises ValueError for invalid stage name."""
        with pytest.raises(ValueError) as exc_info:
            complete_stage("server1", "openclaw", "invalid", StageStatus.COMPLETE)
        assert "invalid stage" in str(exc_info.value).lower()

    def test_complete_stage_claw_not_found(self, host_with_onboarding):
        """Raises AgentNotFoundError for non-existent claw."""
        with pytest.raises(AgentNotFoundError):
            complete_stage("server1", "nonexistent", "providers", StageStatus.COMPLETE)


class TestUpdateStageMetadata:
    """Tests for update_stage_metadata function (re-configure metadata refresh)."""

    def test_patches_metadata_without_changing_status(self, host_with_onboarding):
        """Updating metadata leaves status and completed_at unchanged."""
        # First mark providers complete with one provider_id
        complete_stage(
            "server1",
            "openclaw",
            "providers",
            StageStatus.COMPLETE,
            {"provider_id": "old-provider"},
        )

        from clawrium.core.hosts import get_host

        before = get_host("server1")["agents"]["openclaw"]["onboarding"]["stages"][
            "providers"
        ]
        original_completed_at = before["completed_at"]

        # Now re-configure with a new provider_id via the metadata-only path
        result = update_stage_metadata(
            "server1", "openclaw", "providers", {"provider_id": "new-provider"}
        )
        assert result is True

        after = get_host("server1")["agents"]["openclaw"]["onboarding"]["stages"][
            "providers"
        ]
        assert after["provider_id"] == "new-provider"
        assert after["status"] == "complete"
        # completed_at is preserved — this is metadata-only, not a re-completion
        assert after["completed_at"] == original_completed_at

    def test_works_when_in_later_state(self, host_with_onboarding):
        """Can patch metadata even when onboarding state has moved past the stage."""
        # Advance state past providers (simulates espresso in VALIDATE state
        # trying to re-configure providers — the original short-circuit bug)
        complete_stage(
            "server1",
            "openclaw",
            "providers",
            StageStatus.COMPLETE,
            {"provider_id": "old"},
        )
        transition_state("server1", "openclaw", OnboardingState.PROVIDERS)
        transition_state("server1", "openclaw", OnboardingState.IDENTITY)
        transition_state("server1", "openclaw", OnboardingState.CHANNELS)
        transition_state("server1", "openclaw", OnboardingState.VALIDATE)

        from clawrium.core.hosts import get_host

        before = get_host("server1")["agents"]["openclaw"]["onboarding"]["stages"][
            "providers"
        ]
        original_completed_at = before["completed_at"]
        original_status = before["status"]

        # Re-configuring providers from VALIDATE state must not raise
        result = update_stage_metadata(
            "server1", "openclaw", "providers", {"provider_id": "new"}
        )
        assert result is True

        stage = get_host("server1")["agents"]["openclaw"]["onboarding"]["stages"][
            "providers"
        ]
        # Metadata updated, but the state-machine invariants are preserved
        assert stage["provider_id"] == "new"
        assert stage["status"] == original_status
        assert stage["status"] == "complete"
        assert stage["completed_at"] == original_completed_at

    def test_rejects_reserved_keys(self, host_with_onboarding):
        """Patching status/completed_at via metadata is rejected (use complete_stage)."""
        complete_stage(
            "server1",
            "openclaw",
            "providers",
            StageStatus.COMPLETE,
            {"provider_id": "x"},
        )
        with pytest.raises(ValueError) as exc:
            update_stage_metadata(
                "server1", "openclaw", "providers", {"status": "pending"}
            )
        assert "reserved" in str(exc.value).lower()

        with pytest.raises(ValueError) as exc:
            update_stage_metadata(
                "server1", "openclaw", "providers", {"completed_at": "1970-01-01"}
            )
        assert "reserved" in str(exc.value).lower()

    def test_rejects_non_complete_stage(self, host_with_onboarding):
        """Refuses to patch metadata on a stage whose status is not 'complete'."""
        # providers stage is still 'pending' in host_with_onboarding fixture
        from clawrium.core.onboarding import InvalidTransitionError

        with pytest.raises(InvalidTransitionError) as exc:
            update_stage_metadata(
                "server1", "openclaw", "providers", {"provider_id": "x"}
            )
        assert "complete" in str(exc.value).lower()

    def test_invalid_stage_raises(self, host_with_onboarding):
        """Rejects unknown stage names."""
        with pytest.raises(ValueError):
            update_stage_metadata("server1", "openclaw", "bogus", {"k": "v"})

    def test_agent_not_found(self, host_with_onboarding):
        """Raises AgentNotFoundError for non-existent claw."""
        with pytest.raises(AgentNotFoundError):
            update_stage_metadata(
                "server1", "nonexistent", "providers", {"provider_id": "x"}
            )


class TestInitializeOnboarding:
    """Tests for initialize_onboarding function."""

    def test_initialize_creates_structure(self, host_with_claw):
        """Creates complete onboarding data structure."""
        result = initialize_onboarding("server1", "openclaw")
        assert result is True

        from clawrium.core.hosts import get_host

        host = get_host("server1")
        onboarding = host["agents"]["openclaw"]["onboarding"]

        assert onboarding["state"] == "pending"
        assert onboarding["started_at"] is not None
        assert "stages" in onboarding
        assert all(
            stage in onboarding["stages"]
            for stage in ["providers", "identity", "channels", "validate"]
        )

    def test_initialize_all_stages_pending(self, host_with_claw):
        """All stages start with pending status."""
        initialize_onboarding("server1", "openclaw")

        from clawrium.core.hosts import get_host

        host = get_host("server1")
        stages = host["agents"]["openclaw"]["onboarding"]["stages"]

        for stage_name, stage_data in stages.items():
            assert stage_data["status"] == "pending", f"Stage {stage_name} not pending"
            assert stage_data["completed_at"] is None

    def test_initialize_claw_not_found(self, host_with_claw):
        """Raises AgentNotFoundError for non-existent claw."""
        with pytest.raises(AgentNotFoundError):
            initialize_onboarding("server1", "nonexistent")

    def test_initialize_host_not_found(self, isolated_config):
        """Raises AgentNotFoundError for non-existent host."""
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_path = isolated_config / "hosts.json"
        hosts_path.write_text("[]")

        with pytest.raises(AgentNotFoundError):
            initialize_onboarding("nonexistent", "openclaw")

    def test_initialize_hermes_starts_pending_after_phase_4(self, isolated_config):
        """Phase 4 replaces the placeholder all-auto_skip pipeline with a real
        onboarding flow (providers required, identity auto_skip, channels
        required, validate required). `initialize_onboarding` must therefore
        leave hermes in PENDING — the auto_skip short-circuit no longer fires
        because `providers` is no longer auto_skip.

        Regression guard: if a future commit reverts hermes back to all-auto_skip
        without intending to, this test starts failing immediately.
        """
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "server1",
                "port": 22,
                "agent_name": "xclm",
                "agents": {
                    "hermes-test": {
                        "type": "hermes",
                        "version": "2026.5.7",
                        "status": "installed",
                        "agent_name": "hermes-test",
                    }
                },
            }
        ]
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_path = isolated_config / "hosts.json"
        hosts_path.write_text(json.dumps(hosts_data))

        result = initialize_onboarding("server1", "hermes-test")
        assert result is True

        from clawrium.core.hosts import get_host

        host = get_host("server1")
        onboarding = host["agents"]["hermes-test"]["onboarding"]

        assert onboarding["state"] == "pending"
        for stage_name, stage_data in onboarding["stages"].items():
            assert stage_data["status"] == "pending", (
                f"hermes stage {stage_name} should be pending after Phase 4, got "
                f"{stage_data['status']}"
            )
            assert stage_data["completed_at"] is None

    def test_initialize_all_auto_skip_short_circuits_to_ready(
        self, isolated_config, monkeypatch
    ):
        """The auto_skip → READY short-circuit contract MUST remain intact
        for hypothetical future agent types whose manifest declares every
        stage as auto_skip:true. Hermes Phase 4 stops being such an agent
        (providers is real and required), but the contract must keep working
        for other agents — exercised here via a manifest mock.
        """
        hosts_data = [
            {
                "hostname": "192.168.1.100",
                "alias": "server1",
                "port": 22,
                "agent_name": "xclm",
                "agents": {
                    "future-claw-test": {
                        "type": "future-claw",
                        "version": "1.0.0",
                        "status": "installed",
                        "agent_name": "future-claw-test",
                    }
                },
            }
        ]
        isolated_config.mkdir(parents=True, exist_ok=True)
        hosts_path = isolated_config / "hosts.json"
        hosts_path.write_text(json.dumps(hosts_data))

        fake_manifest = {
            "agent": {"type": "future-claw", "description": "Future claw type"},
            "platforms": [],
            "onboarding": {
                "stages": {
                    "providers": {
                        "description": "n/a",
                        "auto_skip": True,
                    },
                    "identity": {"description": "n/a", "auto_skip": True},
                    "channels": {"description": "n/a", "auto_skip": True},
                    "validate": {"description": "n/a", "auto_skip": True},
                }
            },
        }

        from clawrium.core import onboarding as onboarding_module

        monkeypatch.setattr(
            onboarding_module,
            "load_manifest",
            lambda agent_type: fake_manifest,
        )

        result = initialize_onboarding("server1", "future-claw-test")
        assert result is True

        from clawrium.core.hosts import get_host

        host = get_host("server1")
        onboarding = host["agents"]["future-claw-test"]["onboarding"]

        assert onboarding["state"] == "ready"
        for stage_name, stage_data in onboarding["stages"].items():
            assert stage_data["status"] == "skipped", (
                f"future-claw stage {stage_name} should be skipped, got "
                f"{stage_data['status']}"
            )
            assert stage_data["completed_at"] is not None


class TestCanSkipStage:
    """Tests for can_skip_stage function."""

    def test_returns_false_for_known_claw(self):
        """Returns False for claws without skip_stages config."""
        # openclaw and zeroclaw don't have skip_stages in their manifests
        result = can_skip_stage("openclaw", "channels")
        assert result is False

    def test_returns_false_for_unknown_claw(self):
        """Returns False when manifest cannot be loaded."""
        result = can_skip_stage("nonexistent-claw", "channels")
        assert result is False


class TestGetStageTasks:
    """Tests for get_stage_tasks function."""

    def test_returns_tasks_for_manifest_stage(self):
        """Returns tasks when onboarding stage is defined in manifest."""
        tasks = get_stage_tasks("openclaw", "providers")
        assert len(tasks) == 2
        assert tasks[0]["type"] == "provider_select"
        assert tasks[1]["type"] == "provider_test"

    def test_returns_empty_for_unknown_claw(self):
        """Returns empty list when manifest cannot be loaded."""
        tasks = get_stage_tasks("nonexistent-claw", "providers")
        assert tasks == []


class TestRunStage:
    """Tests for run_stage function."""

    def test_run_stage_no_tasks_completes(self, host_with_onboarding):
        """Stage with no tasks is marked complete."""
        result = run_stage("openclaw", "server1", "openclaw", "providers")
        assert result is True

        from clawrium.core.hosts import get_host

        host = get_host("server1")
        stage = host["agents"]["openclaw"]["onboarding"]["stages"]["providers"]
        assert stage["status"] == "complete"

    def test_run_stage_claw_not_found(self, host_with_onboarding):
        """Raises AgentNotFoundError for non-existent claw."""
        with pytest.raises(AgentNotFoundError):
            run_stage("openclaw", "server1", "nonexistent", "providers")
