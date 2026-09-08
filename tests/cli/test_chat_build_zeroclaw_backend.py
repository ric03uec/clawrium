"""Unit tests for `_build_zeroclaw_backend` — the CLI-side factory that
turns a persisted hosts.json agent record into a live
`ZeroClawChatBackend` for `clawctl agent chat`.

#980: the config renderer sanitizes `[agents.<alias>]` and
`[providers.models.<type>.<alias>]` to `[a-z0-9_]+` (matching the
zeroclaw 0.8.2 dashboard alias resolver). The chat client's
`?agent=<alias>` query param on the /ws/chat upgrade MUST use the same
sanitized alias — otherwise a hyphenated agent_name would send
`?agent=clawrium-d01` while the config exposes only
`[agents.clawrium_d01]` and the daemon returns HTTP 400.
"""

from __future__ import annotations

import pytest

from clawrium.cli.chat import _build_zeroclaw_backend


@pytest.fixture()
def _agent_record_factory():
    def _make(agent_name: str) -> dict:
        return {
            "agent_name": agent_name,
            "config": {
                "gateway": {
                    "url": "ws://wolf:40317/ws/chat",
                    "auth": "bearer-token-abc",
                    "port": 40317,
                },
            },
        }

    return _make


def _host_record() -> dict:
    return {"hostname": "wolf"}


def test_build_zeroclaw_backend_passes_raw_alias_for_sanitized_name(
    _agent_record_factory,
):
    """Names already matching `[a-z0-9_]+` should pass through unchanged
    — the sanitizer is a no-op in that case, so the on-wire URL stays
    byte-identical to the pre-#980 behavior for these agents."""
    backend = _build_zeroclaw_backend(
        agent_record=_agent_record_factory("alpha"),
        host_record=_host_record(),
        response_timeout_seconds=30.0,
    )
    assert backend.gateway_url.endswith("?agent=alpha")


def test_build_zeroclaw_backend_sanitizes_hyphenated_alias(
    _agent_record_factory,
):
    """#980: hyphenated agent names must have their `?agent=` param
    sanitized to `[a-z0-9_]+` so the daemon's alias resolver matches
    the sanitized `[agents.<alias>]` sub-table the renderer now emits.
    Sending `?agent=clawrium-d01` while the config has
    `[agents.clawrium_d01]` returns HTTP 400 from `/ws/chat`."""
    backend = _build_zeroclaw_backend(
        agent_record=_agent_record_factory("clawrium-d01"),
        host_record=_host_record(),
        response_timeout_seconds=30.0,
    )
    assert backend.gateway_url.endswith("?agent=clawrium_d01")
    # And the raw hyphenated form MUST NOT reach the wire.
    assert "agent=clawrium-d01" not in backend.gateway_url


def test_build_zeroclaw_backend_sanitizes_uppercase_alias(
    _agent_record_factory,
):
    """Uppercase names sanitize to lowercase (matches
    `_sanitize_zeroclaw_alias`). Uppercase-only names are rare in
    practice but the sanitizer supports them; this test locks the
    contract so a future rename that changes the sanitizer's casing
    behavior trips a test rather than silently breaking chat."""
    backend = _build_zeroclaw_backend(
        agent_record=_agent_record_factory("Clawrium-D01"),
        host_record=_host_record(),
        response_timeout_seconds=30.0,
    )
    assert backend.gateway_url.endswith("?agent=clawrium_d01")
