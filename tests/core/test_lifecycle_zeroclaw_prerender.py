"""Tests for the #836 (ATX iter-1 B1) zeroclaw prerender error surface.

Mirrors the openclaw + hermes prerender-error tests
(`test_lifecycle_openclaw_prerender.py::test_configure_agent_openclaw_render_config_error_returns_false`,
etc.). Focused on the specific ATX iter-1 blocker: `configure_agent`
for zeroclaw must return `(False, msg)` when `render_zeroclaw` raises
`AgentConfigError`, rather than swallowing the exception via the
broad `except Exception` and continuing with an empty config.toml.

The failure surface widened significantly in Phase 3: missing
`SLACK_MCP_XOXP_TOKEN` / XOXC / XOXD, colliding slugs, empty slug,
unsupported os_family. Without the tightened handler an operator
error at configure time would deploy an empty config.toml and still
mint a fresh bearer via the unconditional re-pair (#437) — the same
data-corruption class the S9/W2 sync-ordering invariant guards
against on the sync path.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from clawrium.core import lifecycle


@pytest.fixture
def zeroclaw_configure_env(monkeypatch, tmp_path):
    """Compact zeroclaw configure fixture — stubs every collaborator
    between `configure_agent` argv unpacking and the zeroclaw
    prerender block so the test can drive the failure path without
    reaching Ansible.
    """
    captured = {}

    host = {
        "hostname": "host-1",
        "user": "xclm",
        "port": 22,
        "key_id": "host-1",
        "os_family": "linux",
        "agents": {
            "alpha": {
                "type": "zeroclaw",
                "agent_name": "alpha",
                "providers": [],
                "config": {
                    "gateway": {
                        "port": 40500,
                        "bind": "lan",
                        "auth": "install-time-bearer",
                    },
                },
            }
        },
    }
    monkeypatch.setattr(lifecycle, "get_host", lambda _h: host)

    fake_key = tmp_path / "id_rsa"
    fake_key.write_text("PRIVATE")
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _k: fake_key)

    monkeypatch.setattr(lifecycle, "get_instance_secrets", lambda _k: {})

    monkeypatch.setattr(
        "clawrium.core.integrations.get_agent_integrations",
        lambda *_a, **_kw: [],
    )

    def _record(**kwargs):
        captured["inventory"] = kwargs.get("inventory")
        captured["playbook"] = kwargs.get("playbook")
        return SimpleNamespace(status="successful", rc=0, stats=None)

    monkeypatch.setattr(
        lifecycle.ansible_runner, "run", MagicMock(side_effect=_record)
    )
    monkeypatch.setattr(lifecycle, "update_host", lambda *_a, **_kw: True)

    return SimpleNamespace(host=host, captured=captured, tmp_path=tmp_path)


def _invoke_configure(env) -> tuple[bool, str | None]:
    config_data = {
        "gateway": {
            "port": 40500,
            "bind": "lan",
            "auth": "install-time-bearer",
        },
        "provider": {
            "name": "or",
            "type": "openrouter",
            "default_model": "anthropic/claude-opus-4",
        },
    }
    return lifecycle.configure_agent(
        hostname="host-1",
        claw_name="zeroclaw",
        config_data=config_data,
        agent_name="alpha",
    )


def test_configure_agent_zeroclaw_render_config_error_returns_false(
    zeroclaw_configure_env, monkeypatch
) -> None:
    """ATX iter-1 B1 fix: an `AgentConfigError` raised by
    `render_zeroclaw` (e.g. missing SLACK_MCP_XOXP_TOKEN, colliding
    slack slugs, unsupported os_family) MUST short-circuit
    `configure_agent` with `(False, "Zeroclaw render failed: ...")`
    — not fall through to the broad `except Exception` warning
    branch that would deploy an empty config.toml and still let the
    re-pair mint a fresh bearer.

    Regression guard: without this, an operator error at configure
    time would reintroduce the #437 stale-bearer failure class on
    the configure path (the sync path is already protected via S9/W2).
    """
    from clawrium.core.render import AgentConfigError

    slack_msg = (
        "render_zeroclaw: slack-user integration 'slack-work' is "
        "missing SLACK_MCP_XOXP_TOKEN in its credential store"
    )

    def _boom(_inputs, *, os_family="linux"):
        raise AgentConfigError(slack_msg)

    # Stub build_render_inputs so it doesn't reach the real store
    # (unrelated to what we're testing). The important call is
    # render_zeroclaw raising AgentConfigError below.
    monkeypatch.setattr(
        "clawrium.core.render.build_render_inputs", lambda _n: object()
    )
    # configure_agent does `from clawrium.core.render import
    # render_zeroclaw` inside the zeroclaw branch, so patch the
    # source module not lifecycle.
    monkeypatch.setattr("clawrium.core.render.render_zeroclaw", _boom)

    ok, err = _invoke_configure(zeroclaw_configure_env)

    assert not ok
    assert err is not None
    assert "Zeroclaw render failed" in err
    assert "SLACK_MCP_XOXP_TOKEN" in err
    # Ansible-runner.run must not have been invoked — the play never
    # ran, so no bearer rotation could have fired.
    assert "inventory" not in zeroclaw_configure_env.captured


def test_configure_agent_zeroclaw_unexpected_render_exception_still_falls_through(
    zeroclaw_configure_env, monkeypatch
) -> None:
    """Round-trip: non-`AgentConfigError` from `render_zeroclaw`
    (e.g. jinja `TemplateError`, `IOError` on template load) still
    falls through the broad-except warning branch so a corrupted
    wheel does not brick every zeroclaw configure run — only the
    pre-render path fails and the legacy playbook-template path
    picks up the slack rendering server-side. Mirrors the hermes
    round-trip at `test_lifecycle_hermes_prerender.py:443`."""

    def _boom(_inputs, *, os_family="linux"):
        raise RuntimeError("simulated jinja TemplateError")

    monkeypatch.setattr(
        "clawrium.core.render.build_render_inputs", lambda _n: object()
    )
    monkeypatch.setattr("clawrium.core.render.render_zeroclaw", _boom)

    # This exercises the fall-through branch — the test just proves
    # that a non-AgentConfigError does NOT trigger the new
    # (False, "Zeroclaw render failed: ...") return. The configure
    # run may or may not succeed downstream (depending on how far
    # the fixture stubs go); the assertion is only on the
    # first-line failure discrimination.
    ok, err = _invoke_configure(zeroclaw_configure_env)

    # If it fails, the failure message MUST NOT be the tightened
    # `Zeroclaw render failed:` prefix (that's reserved for
    # `AgentConfigError`). If it succeeds, that's also acceptable —
    # the legacy playbook path handled the render server-side.
    if not ok:
        assert err is not None
        assert "Zeroclaw render failed" not in err
