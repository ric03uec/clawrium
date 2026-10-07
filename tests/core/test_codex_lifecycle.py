"""Core daemonless and native exec dispatch contracts for Codex (#1034)."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

from clawrium.core import agent_exec
from clawrium.core.agent_lifecycle import has_daemon_lifecycle


def _event(message: str) -> dict:
    return {"event": "runner_on_ok", "event_data": {"res": {"msg": message}}}


def test_codex_is_daemonless() -> None:
    assert has_daemon_lifecycle("codex") is False


def test_parse_events_accepts_redacted_codex_transport() -> None:
    payload = base64.b64encode(
        json.dumps({"stdout": "Codex CLI 0.160.1", "stderr": "", "rc": 0}).encode()
    ).decode()

    assert agent_exec._parse_events(SimpleNamespace(events=[_event(f"CODEX_EXEC_RESULT={payload}")])) == (
        "Codex CLI 0.160.1",
        "",
        0,
    )


def test_codex_exec_uses_bounded_native_playbook(
    monkeypatch, tmp_path: Path
) -> None:
    key = tmp_path / "key"
    key.write_text("key")
    captured: dict = {}
    monkeypatch.setattr(agent_exec, "get_config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(agent_exec.core_keys, "get_host_private_key", lambda _: key)
    monkeypatch.setattr(
        "clawrium.core.hosts.get_host",
        lambda _: {"hostname": "host", "alias": "host", "key_id": "host"},
    )
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kwargs: captured.update(kwargs)
        or SimpleNamespace(
            status="successful",
            events=[
                _event(
                    "CODEX_EXEC_RESULT="
                    + base64.b64encode(
                        json.dumps({"stdout": "Codex CLI 0.160.1", "stderr": "", "rc": 0}).encode()
                    ).decode()
                )
            ],
        ),
    )

    assert agent_exec.run_agent_exec("host", "codex-agent", "codex", ["--version"]) == (
        "Codex CLI 0.160.1",
        "",
        0,
    )
    assert captured["inventory"]["all"]["vars"] == {
        "agent_name": "codex-agent",
        "cmd_argv": ["--version"],
        "codex_exec_timeout": 120,
    }
    assert captured["timeout"] == 150
