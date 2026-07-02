"""Sync-order invariant for zeroclaw slack integration (#836, W2 + S9).

The contract being pinned:

  A slack-hydration failure during `sync_agent_canonical` MUST
  short-circuit BEFORE `_zeroclaw_repair_after_start` rotates the
  gateway bearer. If the bearer rotated on a failed sync,
  `hosts.json.gateway.auth` would carry a fresh token while the daemon
  still holds the old one — reintroducing the #437 stale-bearer failure
  class the plan explicitly protects.

Positive control: a successful zeroclaw sync fires
`gateway_token_rotated` exactly once (via the existing repair path).

Failure control: a zeroclaw sync with a broken slack integration
(missing SLACK_MCP_XOXP_TOKEN) raises before the repair is called;
the mock records zero invocations.

The tests stub `sync_agent_canonical`'s dependencies at the import
sites so the assertion is on the ordering, not on the SSH / Ansible
plumbing.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from clawrium.core import lifecycle_canonical
from clawrium.core.lifecycle_canonical import sync_agent_canonical
from clawrium.core.render import (
    AgentConfigError,
    GatewayInputs,
    IntegrationInputs,
    ProviderInputs,
    RenderInputs,
)
from clawrium.core.workspace_sync import WorkspacePhaseResult


def _fake_push_success() -> WorkspacePhaseResult:
    return WorkspacePhaseResult(success=True, files_pushed=(), files_excluded=())


def _zeroclaw_inputs(*, integrations=()) -> RenderInputs:
    return RenderInputs(
        agent_name="alice",
        agent_type="zeroclaw",
        provider=ProviderInputs(
            name="or",
            type="openrouter",
            default_model="anthropic/claude-opus-4.7",
            api_key="sk-or-1",
        ),
        channels=(),
        integrations=integrations,
        gateway=GatewayInputs(host="0.0.0.0", port=40000, auth="tkn", bind="lan"),
    )


@pytest.fixture
def stub_sync_pipeline(monkeypatch: pytest.MonkeyPatch):
    """Return an event-callback capturing sink so tests can grep for
    `gateway_token_rotated` emissions during the sync run.

    Stubs the entire SSH / restart / verify / workspace path but leaves
    the *real* render (`render_zeroclaw`) in place — that's the code
    under test for the S9 fail-fast branch."""

    events: list[tuple[str, str]] = []

    def on_event(stage: str, message: str) -> None:
        events.append((stage, message))

    def fake_get_agent_by_name(agent_name: str):
        host = {
            "hostname": "h.example",
            "key_id": "h.example",
            "user": "xclm",
            "os_family": "linux",
        }
        return (host, agent_name, {"type": "zeroclaw"})

    fake_client = MagicMock()
    fake_client.close = lambda: None

    def fake_open_ssh(_host, *, timeout=15):
        return fake_client

    def fake_diff_files(**_kwargs):
        return []

    monkeypatch.setattr(
        lifecycle_canonical, "get_agent_by_name", fake_get_agent_by_name
    )
    monkeypatch.setattr(lifecycle_canonical, "_open_ssh", fake_open_ssh)
    monkeypatch.setattr(lifecycle_canonical, "diff_files", fake_diff_files)
    monkeypatch.setattr(
        lifecycle_canonical,
        "probe_host_install",
        lambda *_a, **_kw: lifecycle_canonical.HostInstallProbe(
            unit_present=True,
            home_present=True,
            unit_path="/etc/systemd/system/x.service",
            home_path="/home/x/.x",
        ),
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_restart_unit", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        lifecycle_canonical, "_verify_health", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "clawrium.core.onboarding.transition_state",
        lambda *_a, **_k: None,
    )

    return events, on_event


def test_slack_hydration_failure_blocks_bearer_rotation(
    stub_sync_pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S9/W2 fail-fast: a zeroclaw sync with a slack integration missing
    its SLACK_MCP_XOXP_TOKEN MUST raise AgentConfigError from render
    BEFORE `_zeroclaw_repair_after_start` is called. This is the
    positive proof that the sync ordering (render → write → restart →
    repair) never rotates the bearer on a half-hydrated slack render.

    Regression guard for #437 stale-bearer failure class."""
    events, on_event = stub_sync_pipeline
    repair_mock = MagicMock(return_value=(True, None))

    # Return a zeroclaw fixture with a broken slack integration —
    # empty credentials will trigger the render-time raise.
    inputs = _zeroclaw_inputs(
        integrations=(
            IntegrationInputs(
                name="slack-work",
                type="slack-user",
                credentials=(),  # missing SLACK_MCP_XOXP_TOKEN
            ),
        ),
    )
    monkeypatch.setattr(
        lifecycle_canonical, "build_render_inputs", lambda _n: inputs
    )

    with patch(
        "clawrium.core.lifecycle._zeroclaw_repair_after_start", repair_mock
    ):
        with pytest.raises(AgentConfigError, match="SLACK_MCP_XOXP_TOKEN"):
            sync_agent_canonical(
                "alice",
                force=False,
                restart=True,
                verify=True,
                on_event=on_event,
            )

    # The single most important assertion: bearer rotation was NEVER
    # invoked. A regression that reordered the pipeline (e.g. moved
    # render inside the same try-block as repair) would fire the
    # repair before the render raised, and this assertion would trip.
    repair_mock.assert_not_called()

    # `gateway_token_rotated` events go through the same repair path,
    # so their absence is a second corroboration.
    rotated_events = [
        (stage, msg) for stage, msg in events if "gateway_token_rotated" in msg
    ]
    assert rotated_events == []


def test_slack_success_fires_repair_exactly_once(
    stub_sync_pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: a successful zeroclaw sync with a valid slack
    integration attached fires `_zeroclaw_repair_after_start` exactly
    once (the bearer rotation). Confirms the render+write path does
    NOT accidentally suppress the repair when everything succeeds."""
    events, on_event = stub_sync_pipeline
    repair_mock = MagicMock(return_value=(True, None))

    inputs = _zeroclaw_inputs(
        integrations=(
            IntegrationInputs(
                name="slack-work",
                type="slack-user",
                credentials=(("SLACK_MCP_XOXP_TOKEN", "xoxp-1"),),
            ),
        ),
    )
    monkeypatch.setattr(
        lifecycle_canonical, "build_render_inputs", lambda _n: inputs
    )

    # No files_written path: diff returns [], so restart short-circuits
    # to the zeroclaw "force restart for bearer rotation" branch —
    # exactly the code path we want to exercise. Stub the sync-time
    # slack install helper too so the test doesn't need an SSH key.
    with (
        patch(
            "clawrium.core.workspace_sync.push_workspace_phase",
            return_value=_fake_push_success(),
        ),
        patch.object(
            lifecycle_canonical,
            "_zeroclaw_install_slack_mcp",
            lambda *a, **kw: None,
        ),
        patch(
            "clawrium.core.lifecycle._zeroclaw_repair_after_start",
            repair_mock,
        ),
    ):
        result = sync_agent_canonical(
            "alice",
            force=False,
            restart=True,
            verify=True,
            on_event=on_event,
        )

    assert result.success is True
    # Exactly-once. A regression that double-fires the repair would
    # emit two `gateway_token_rotated` events in a row and the
    # `hosts.json.gateway.auth` invariant would be double-rotated
    # even though the operator ran one sync.
    repair_mock.assert_called_once_with(
        "h.example",
        agent_name="alice",
        on_event=on_event,
        reason="sync",
    )
