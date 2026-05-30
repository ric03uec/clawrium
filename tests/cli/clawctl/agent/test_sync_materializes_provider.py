"""Issue #426 — sync_agent materializes `agent.providers` (attach list)
into `config.provider` (Ansible-rendered dict) and advances the
onboarding state machine through the `providers` stage when needed.

These tests exercise `core/lifecycle.sync_agent` directly with
`configure_agent` mocked out — so the contract under test is exactly the
shape of the `config_data` argument the bridge feeds into the
remote-push call.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from clawrium.core.lifecycle import LifecycleError, sync_agent


def _host_with_agent(
    *,
    state: str = "pending",
    providers_attached: list[str] | None = None,
    config: dict | None = None,
) -> dict:
    """Build a minimal host record carrying one openclaw agent."""
    agent: dict = {
        "type": "openclaw",
        "onboarding": {"state": state},
        "config": {"gateway": {"port": 40000}} if config is None else config,
    }
    if providers_attached is not None:
        agent["providers"] = providers_attached
    return {
        "hostname": "192.168.1.100",
        "key_id": "test",
        "agent_name": "xclm",
        "port": 22,
        "agents": {"opc-work": agent},
    }


def _ollama_provider_record() -> dict:
    return {
        "name": "local-inx",
        "type": "ollama",
        "endpoint": "http://192.168.1.17:11434",
        "default_model": "qwen3-coder:30b-128k",
    }


def test_sync_materializes_attached_provider_into_config():
    """Happy path: agent.providers=["local-inx"] + state=pending →
    sync overlays the provider record from providers.json onto
    config.provider before pushing.
    """
    host = _host_with_agent(state="pending", providers_attached=["local-inx"])

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        captured["claw_name"] = claw_name
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_ollama_provider_record(),
        ),
        patch(
            "clawrium.core.onboarding.complete_stage", return_value=True
        ) as mock_complete,
        patch("clawrium.core.onboarding.transition_state", return_value=True),
        patch("clawrium.core.onboarding.can_skip_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "openclaw")

    assert result["success"] is True
    provider = captured["config_data"]["provider"]
    assert provider["name"] == "local-inx"
    assert provider["type"] == "ollama"
    assert provider["endpoint"] == "http://192.168.1.17:11434"
    assert provider["default_model"] == "qwen3-coder:30b-128k"
    # The providers complete_stage call carries the provider_id metadata
    # (other stages' complete_stage calls do not — they're auto-skip
    # bookkeeping for the Option D walk).
    providers_calls = [
        c for c in mock_complete.call_args_list if c.args[2] == "providers"
    ]
    assert len(providers_calls) == 1
    assert providers_calls[0].args[4] == {"provider_id": "local-inx"}


def test_sync_carries_optional_provider_fields():
    """context_window / max_tokens flow through when present on the
    provider record."""
    host = _host_with_agent(state="ready", providers_attached=["maurice"])
    rec = {
        "name": "maurice",
        "type": "openrouter",
        "endpoint": "https://openrouter.ai/api/v1",
        "default_model": "z-ai/glm-4.5-air",
        "context_window": 128000,
        "max_tokens": 4096,
    }

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.providers.storage.get_provider", return_value=rec),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
        # B-NEW-2 (ATX #555 polish round 4): sync_agent now surfaces
        # registry-incoherence on the post-configure READY transition
        # as success=False. This test stubs get_host but not the
        # transition target — patch transition_state explicitly to
        # exercise the documented success path.
        patch("clawrium.core.onboarding.transition_state", return_value=True),
    ):
        result = sync_agent("192.168.1.100", "openclaw")

    assert result["success"] is True
    provider = captured["config_data"]["provider"]
    assert provider["context_window"] == 128000
    assert provider["max_tokens"] == 4096


def test_sync_legacy_agent_without_attachment_unchanged():
    """Regression guard: agents installed before #426 (no
    `agent.providers` field, `config.provider` already populated by
    the legacy `clm` flow) must sync without the bridge interfering."""
    legacy_config = {
        "gateway": {"port": 40000},
        "provider": {
            "name": "legacy-provider",
            "type": "ollama",
            "endpoint": "http://localhost:11434",
            "default_model": "llama3",
        },
    }
    host = _host_with_agent(state="ready", config=legacy_config)
    # No `providers` key at all on the agent record.
    assert "providers" not in host["agents"]["opc-work"]

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
        # B-NEW-2: see test_sync_carries_optional_provider_fields.
        patch("clawrium.core.onboarding.transition_state", return_value=True),
    ):
        result = sync_agent("192.168.1.100", "openclaw")

    assert result["success"] is True
    # Legacy provider block flows through untouched.
    assert captured["config_data"]["provider"]["name"] == "legacy-provider"


def test_sync_unknown_attached_provider_errors_cleanly():
    """Provider name in `agent.providers` not present in providers.json
    must surface a clear LifecycleError, not a NoneType crash."""
    host = _host_with_agent(state="pending", providers_attached=["ghost"])

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.providers.storage.get_provider", return_value=None),
    ):
        with pytest.raises(LifecycleError) as exc_info:
            sync_agent("192.168.1.100", "openclaw")

    assert "ghost" in str(exc_info.value)
    assert "not registered" in str(exc_info.value)


def test_sync_rejects_multi_provider_hand_edit():
    """Defense-in-depth: hosts.json hand-edited to have two attached
    providers must fail loudly rather than silently picking index 0."""
    host = _host_with_agent(state="ready", providers_attached=["one", "two"])

    with patch("clawrium.core.lifecycle.get_host", return_value=host):
        with pytest.raises(LifecycleError) as exc_info:
            sync_agent("192.168.1.100", "openclaw")

    assert "single-provider invariant" in str(exc_info.value)


def test_sync_pending_without_attachment_keeps_legacy_error():
    """Agent with no provider attached AND state=pending must keep
    erroring at the PENDING-rejection gate so users still get a clear
    signal that the agent needs configuration."""
    host = _host_with_agent(state="pending")
    assert "providers" not in host["agents"]["opc-work"]

    with patch("clawrium.core.lifecycle.get_host", return_value=host):
        with pytest.raises(LifecycleError) as exc_info:
            sync_agent("192.168.1.100", "openclaw")

    assert "onboarding not started" in str(exc_info.value)
    # Error message now points at the new attach surface, not legacy clm.
    assert "clawctl agent provider attach" in str(exc_info.value)


def test_sync_after_detach_preserves_last_known_good_provider():
    """ATX iter-1 B2: agent.providers=[] (post-detach) is distinct from
    `providers` key absent (legacy). The bridge must skip
    re-materialization on an empty list and leave the pre-existing
    `config.provider` (last-known-good) untouched — that is the user
    decision documented on #426.
    """
    last_good = {
        "name": "old-provider",
        "type": "ollama",
        "endpoint": "http://old:11434",
        "default_model": "qwen3",
    }
    host = _host_with_agent(
        state="ready",
        providers_attached=[],
        config={"gateway": {"port": 40000}, "provider": last_good},
    )

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
        # B-NEW-2: see test_sync_carries_optional_provider_fields.
        patch("clawrium.core.onboarding.transition_state", return_value=True),
    ):
        result = sync_agent("192.168.1.100", "openclaw")

    assert result["success"] is True
    # Bridge did NOT overwrite config.provider when attach list is empty.
    assert captured["config_data"]["provider"] == last_good


def test_sync_invalid_transition_routes_to_update_metadata():
    """ATX iter-1 W6: when complete_stage raises InvalidTransitionError
    (re-sync after attach swap on an already-advanced agent),
    sync_agent falls back to update_stage_metadata instead of crashing.
    Verifies the re-sync code path that the original test set did not
    cover."""
    from clawrium.core.onboarding import InvalidTransitionError

    host = _host_with_agent(state="pending", providers_attached=["local-inx"])

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_ollama_provider_record(),
        ),
        patch(
            "clawrium.core.onboarding.complete_stage",
            side_effect=InvalidTransitionError("already past providers"),
        ),
        patch("clawrium.core.onboarding.update_stage_metadata") as mock_update,
        patch("clawrium.core.onboarding.transition_state"),
        patch("clawrium.core.onboarding.can_skip_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "openclaw")

    assert result["success"] is True
    # update_stage_metadata receives the same provider_id metadata.
    mock_update.assert_any_call(
        "192.168.1.100",
        "opc-work",
        "providers",
        {"provider_id": "local-inx"},
    )


def test_sync_drives_state_to_ready_for_auto_skip_agent():
    """B1 fix: when every non-providers stage is auto_skip-able for the
    agent type (the hermes/zeroclaw pattern after manifest evaluation),
    sync transitions state all the way to READY so a subsequent
    `clawctl agent start` succeeds."""
    host = _host_with_agent(state="pending", providers_attached=["local-inx"])

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        return (True, None)

    transitions: list[str] = []

    def capture_transition(_host, _agent, target):
        transitions.append(target.value)
        return True

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_ollama_provider_record(),
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch(
            "clawrium.core.onboarding.transition_state",
            side_effect=capture_transition,
        ),
        patch("clawrium.core.onboarding.can_skip_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "openclaw")

    assert result["success"] is True
    # State machine walked all the way to READY.
    assert transitions[-1] == "ready"
    # The full progression hit each canonical state in order.
    assert "providers" in transitions
    assert "identity" in transitions
    assert "channels" in transitions
    assert "validate" in transitions
    assert "ready" in transitions


def test_sync_refuses_required_stage_without_declarative_surface():
    """Option D (issue #523 tracking): when a non-auto_skip stage lacks
    a clawctl declarative surface (today: identity for openclaw), sync
    must refuse rather than silently mark COMPLETE and advance to READY
    with no actual identity files pushed."""

    def can_skip_only_validate(agent_type: str, stage: str) -> bool:
        # Simulate openclaw: identity required, channels required,
        # validate auto-skipped.
        return stage == "validate"

    host = _host_with_agent(state="pending", providers_attached=["local-inx"])

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_ollama_provider_record(),
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch("clawrium.core.onboarding.transition_state", return_value=True),
        patch(
            "clawrium.core.onboarding.can_skip_stage",
            side_effect=can_skip_only_validate,
        ),
    ):
        with pytest.raises(LifecycleError) as exc_info:
            sync_agent("192.168.1.100", "openclaw")

    msg = str(exc_info.value)
    assert "identity" in msg
    assert "#523" in msg  # Points at the tracking issue.
    assert "clawctl agent configure" in msg  # Workaround named.


def test_sync_passes_when_identity_already_complete_in_ledger():
    """Issue #577: when the operator has already run
    `clawctl agent configure <name> --stage identity` and the onboarding
    ledger records `stages.identity.status == complete`, the providers /
    sync walk must NOT raise the "requires manual identity" gate. The
    gate should consult the same source `clawctl agent describe` reads,
    not a stale proxy."""

    def can_skip_only_validate(agent_type: str, stage: str) -> bool:
        return stage == "validate"

    host = {
        "hostname": "192.168.1.100",
        "key_id": "test",
        "agent_name": "xclm",
        "port": 22,
        "agents": {
            "opc-work": {
                "type": "openclaw",
                "onboarding": {
                    "state": "providers",
                    "stages": {
                        "providers": {"status": "complete"},
                        # Operator already completed identity out-of-band.
                        "identity": {"status": "complete"},
                        "channels": {"status": "pending"},
                        "validate": {"status": "pending"},
                    },
                },
                "config": {"gateway": {"port": 40000}},
                "providers": ["local-inx"],
            }
        },
    }

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_ollama_provider_record(),
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch("clawrium.core.onboarding.transition_state", return_value=True),
        patch(
            "clawrium.core.onboarding.can_skip_stage",
            side_effect=can_skip_only_validate,
        ),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        # Must not raise — the prior identity completion in the ledger
        # is honored. Pre-fix this would raise "requires manual identity".
        result = sync_agent("192.168.1.100", "openclaw")

    assert result["success"] is True


def test_sync_hermes_real_manifest_configure_fail_does_not_persist_ready():
    """ATX iter-2 B-ITER2-1 + B-ITER2-2: with the REAL hermes manifest
    (no can_skip_stage patch), if configure_agent fails the state
    pointer in hosts.json must NOT advance to ready. Channels and
    validate stages are required+non-auto_skip on the real manifest;
    the iter-1 code would have written ready before configure ran.
    """
    host = {
        "hostname": "192.168.1.100",
        "key_id": "test",
        "agent_name": "xclm",
        "port": 22,
        "agents": {
            "test-hermes": {
                "type": "hermes",
                "onboarding": {"state": "pending"},
                "config": {"gateway": {"port": 45000}},
                "providers": ["local-inx"],
            }
        },
    }

    transitions: list[str] = []
    completes: list[tuple[str, str]] = []

    def fake_transition(_host, _agent, target):
        transitions.append(target.value)
        return True

    def fake_complete(_host, _agent, stage, status, _meta=None):
        completes.append((stage, status.value))
        return True

    def fake_configure(*_args, **_kwargs):
        return (False, "ansible exploded")

    rec = _ollama_provider_record()

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.providers.storage.get_provider", return_value=rec),
        # NOTE: can_skip_stage is NOT patched — uses real hermes manifest.
        patch(
            "clawrium.core.onboarding.transition_state", side_effect=fake_transition
        ),
        patch("clawrium.core.onboarding.complete_stage", side_effect=fake_complete),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is False
    assert "ansible exploded" in result["error"]
    # CRITICAL: state must never have been advanced to ready.
    assert "ready" not in transitions, (
        f"state must not advance to ready when configure_agent fails; "
        f"observed transitions: {transitions}"
    )
    # The walk did proceed through earlier stages (visible cosmetic
    # writes), but ready specifically was deferred — which is the
    # safety boundary that gates clawctl agent start.
    assert "providers" in transitions
    # Hermes auto_skips identity per the real manifest.
    assert ("identity", "skipped") in completes
    # Channels and validate are required+non-auto_skip on the real
    # manifest — the walk completes them as state-machine bookkeeping
    # but the ready transition is still deferred.
    assert ("channels", "complete") in completes
    assert ("validate", "complete") in completes


def test_sync_hermes_real_manifest_configure_success_writes_ready():
    """Companion to the failure-path test: with the real hermes
    manifest, configure_agent succeeding does advance state to ready.
    """
    host = {
        "hostname": "192.168.1.100",
        "key_id": "test",
        "agent_name": "xclm",
        "port": 22,
        "agents": {
            "test-hermes": {
                "type": "hermes",
                "onboarding": {"state": "pending"},
                "config": {"gateway": {"port": 45000}},
                "providers": ["local-inx"],
            }
        },
    }

    transitions: list[str] = []

    def fake_transition(_host, _agent, target):
        transitions.append(target.value)
        return True

    def fake_configure(*_args, **_kwargs):
        return (True, None)

    rec = _ollama_provider_record()

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.providers.storage.get_provider", return_value=rec),
        # No can_skip_stage patch — real hermes manifest.
        patch(
            "clawrium.core.onboarding.transition_state", side_effect=fake_transition
        ),
        patch("clawrium.core.onboarding.complete_stage", return_value=True),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is True
    # Now ready IS in transitions — and it comes LAST (post-configure).
    assert transitions[-1] == "ready"


def test_sync_resync_from_validate_state_reaches_ready_on_success():
    """ATX iter-3 W-NEW-2: the gate-widening from `state == PENDING`
    to `state != READY` is the documented behaviour that enables
    re-sync recovery after a previous configure_agent failure. This
    test exercises the re-entry path: state on disk = VALIDATE
    (because a prior sync's walk completed but configure_agent then
    failed), a fresh sync must walk no-ops through the already-past
    stages and finish the READY transition once configure succeeds.
    """
    from clawrium.core.onboarding import InvalidTransitionError

    host = {
        "hostname": "192.168.1.100",
        "key_id": "test",
        "agent_name": "xclm",
        "port": 22,
        "agents": {
            "test-hermes": {
                "type": "hermes",
                "onboarding": {"state": "validate"},
                "config": {"gateway": {"port": 45000}},
                "providers": ["local-inx"],
            }
        },
    }

    transitions: list[str] = []

    def fake_transition(_host, _agent, target):
        # Mirror the real transition_state behaviour: forward
        # transitions from VALIDATE allow ['ready', 'channels'] only
        # — earlier-state targets raise InvalidTransitionError. This
        # ensures the test covers the actual swallowing path that the
        # gate-widening relies on.
        if target.value in ("ready", "channels"):
            transitions.append(target.value)
            return True
        raise InvalidTransitionError(
            f"cannot transition validate → {target.value}"
        )

    def fake_complete(_host, _agent, stage, status, _meta=None):
        # complete_stage rejects from VALIDATE for stages other than
        # 'validate'. This mirrors the real state_to_allowed_stages
        # guard. The `_safe_*` wrappers in sync_agent must swallow the
        # InvalidTransitionError.
        if stage != "validate" and status.value != "skipped":
            raise InvalidTransitionError(
                f"cannot complete {stage} from validate"
            )
        return True

    def fake_configure(*_args, **_kwargs):
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_ollama_provider_record(),
        ),
        patch(
            "clawrium.core.onboarding.transition_state", side_effect=fake_transition
        ),
        patch("clawrium.core.onboarding.complete_stage", side_effect=fake_complete),
        patch(
            "clawrium.core.onboarding.update_stage_metadata", return_value=True
        ),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is True
    # Re-sync from VALIDATE must reach READY.
    assert transitions[-1] == "ready", f"observed transitions: {transitions}"
    # ATX iter-4 B1: assert the walk actually ran (don't false-pass if
    # the gate is reverted to `state == PENDING`). 'channels' is the
    # one transition that can only be produced by the walk —
    # _safe_transition(_OS.CHANNELS) at lifecycle.py:1092 from state=
    # VALIDATE (TRANSITIONS['validate'] = ['ready', 'channels']). The
    # post-configure _transition_post only emits 'ready'. If the gate
    # is wrong and the walk is skipped entirely, 'channels' never
    # appears, this assertion fails.
    assert "channels" in transitions, (
        f"walk must execute when state=VALIDATE and provider attached; "
        f"observed transitions: {transitions}"
    )


def test_sync_resync_from_validate_does_not_advance_on_configure_fail():
    """ATX iter-3 W-NEW-2 companion: re-sync from VALIDATE must NOT
    advance to READY if configure_agent fails again. The walk + state
    re-entry path must preserve the deferred-READY safety boundary."""
    from clawrium.core.onboarding import InvalidTransitionError

    host = {
        "hostname": "192.168.1.100",
        "key_id": "test",
        "agent_name": "xclm",
        "port": 22,
        "agents": {
            "test-hermes": {
                "type": "hermes",
                "onboarding": {"state": "validate"},
                "config": {"gateway": {"port": 45000}},
                "providers": ["local-inx"],
            }
        },
    }

    transitions: list[str] = []

    def fake_transition(_host, _agent, target):
        if target.value in ("ready", "channels"):
            transitions.append(target.value)
            return True
        raise InvalidTransitionError(
            f"cannot transition validate → {target.value}"
        )

    def fake_complete(_host, _agent, stage, status, _meta=None):
        if stage != "validate" and status.value != "skipped":
            raise InvalidTransitionError(
                f"cannot complete {stage} from validate"
            )
        return True

    def fake_configure(*_args, **_kwargs):
        return (False, "second attempt also failed")

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch(
            "clawrium.core.providers.storage.get_provider",
            return_value=_ollama_provider_record(),
        ),
        patch(
            "clawrium.core.onboarding.transition_state", side_effect=fake_transition
        ),
        patch("clawrium.core.onboarding.complete_stage", side_effect=fake_complete),
        patch(
            "clawrium.core.onboarding.update_stage_metadata", return_value=True
        ),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
    ):
        result = sync_agent("192.168.1.100", "hermes")

    assert result["success"] is False
    assert "second attempt also failed" in result["error"]
    # Critical: even on re-entry from VALIDATE, a failed configure
    # must not commit READY.
    assert "ready" not in transitions, (
        f"READY must not be written when configure fails on re-sync; "
        f"observed transitions: {transitions}"
    )
    # ATX iter-4 B1: pin that the walk ran on re-sync, independent of
    # the READY outcome. Without this, a regression that reverts the
    # gate to `state == PENDING` would skip the walk entirely on
    # VALIDATE re-entry but the test would still pass trivially
    # because the configure-fail early-return fires before _transition_post.
    assert "channels" in transitions, (
        f"walk must execute on VALIDATE re-entry even when configure "
        f"fails; observed transitions: {transitions}"
    )


def test_sync_optional_field_max_tokens_zero_preserved():
    """ATX iter-1 S1: max_tokens=0 / context_window=0 are meaningful
    no-limit signals on some provider APIs. The `is not None` checks
    must preserve zero values rather than dropping them on truthy."""
    host = _host_with_agent(state="ready", providers_attached=["unlimited"])
    rec = {
        "name": "unlimited",
        "type": "ollama",
        "endpoint": "http://localhost:11434",
        "default_model": "qwen3",
        "max_tokens": 0,  # Explicit no-limit signal.
    }

    captured: dict = {}

    def fake_configure(hostname, claw_name, config_data, **kwargs):
        captured["config_data"] = config_data
        return (True, None)

    with (
        patch("clawrium.core.lifecycle.get_host", return_value=host),
        patch("clawrium.core.providers.storage.get_provider", return_value=rec),
        patch("clawrium.core.lifecycle.configure_agent", side_effect=fake_configure),
        # B-NEW-2: see test_sync_carries_optional_provider_fields.
        patch("clawrium.core.onboarding.transition_state", return_value=True),
    ):
        result = sync_agent("192.168.1.100", "openclaw")

    assert result["success"] is True
    provider = captured["config_data"]["provider"]
    assert "max_tokens" in provider
    assert provider["max_tokens"] == 0
