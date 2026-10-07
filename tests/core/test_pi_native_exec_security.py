"""Pi native-exec capability boundary (#1038)."""

import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawrium.core import agent_exec


@pytest.fixture
def pi_host(monkeypatch):
    host = {"hostname": "wolf-i", "os_family": "linux", "key_id": "host-key"}
    record = {"type": "pi", "agent_name": "pi-demo", "providers": ["router"]}
    monkeypatch.setattr("clawrium.core.hosts.get_host", lambda _: host)
    monkeypatch.setattr(
        "clawrium.core.hosts.get_agent_by_name", lambda _: (host, "pi", record)
    )
    monkeypatch.setattr(
        "clawrium.core.agent_exec.core_keys.get_host_private_key",
        lambda _: Path("/test-key"),
    )
    return host


def test_pi_native_inference_uses_control_plane_model_and_fixed_capabilities(
    monkeypatch, tmp_path, pi_host
):
    """One-shot exec returns an authenticated result without caller-controlled Pi argv."""
    captured = {}
    prompt = "Reply with exactly: ready"
    bearer = "test-openrouter-bearer"
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(agent_exec, "_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        agent_exec,
        "_create_pi_exec_keypair",
        lambda directory: (directory / "private.pem", "PUBLIC CERTIFICATE"),
    )
    monkeypatch.setattr(
        agent_exec,
        "_parse_pi_secure_result",
        lambda _result, _key: ("ready", "", 0),
    )

    def fake_run(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="successful", events=[])

    monkeypatch.setattr(agent_exec.ansible_runner, "run", fake_run)
    assert agent_exec.run_agent_exec("wolf-i", "pi-demo", "pi", ["--print", prompt]) == (
        "ready",
        "",
        0,
    )

    variables = captured["inventory"]["all"]["vars"]
    assert variables["pi_exec_mode"] == "inference"
    assert variables["cmd_argv"] == [
        "--provider",
        "openrouter",
        "--model",
        "openai/gpt-4o",
        "--print",
        "--no-session",
        "--no-tools",
        "--no-context-files",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
    ]
    assert prompt not in variables["cmd_argv"]
    assert base64.b64decode(variables["pi_exec_prompt_b64"]).decode() == prompt
    assert bearer not in str(variables)


@pytest.mark.parametrize(
    "argv",
    [
        ["--provider", "attacker/model"],
        ["--model", "attacker/model"],
        ["--tools", "bash"],
        ["--extension", "/tmp/evil.mjs"],
        ["--print", "hello", "--tools", "bash"],
        ["--print", "hello", "--no-extensions"],
        ["--print", "   "],
        ["--print", "x" * 100_001],
    ],
)
def test_pi_exec_rejects_option_injection_before_ansible(monkeypatch, pi_host, argv):
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **_kwargs: pytest.fail("unsafe Pi argv reached ansible"),
    )
    with pytest.raises(agent_exec.AgentExecError, match="Pi exec accepts only"):
        agent_exec.run_agent_exec("wolf-i", "pi-demo", "pi", argv)


def test_pi_diagnostic_exec_never_resolves_provider_or_credential(monkeypatch, tmp_path, pi_host):
    """Version/help remain useful without granting the Pi process a bearer."""
    captured = {}
    monkeypatch.setattr(agent_exec, "_logs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        agent_exec,
        "_create_pi_exec_keypair",
        lambda directory: (directory / "private.pem", "PUBLIC CERTIFICATE"),
    )
    monkeypatch.setattr(
        agent_exec,
        "_parse_pi_secure_result",
        lambda _result, _key: ("0.73.1", "", 0),
    )
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: pytest.fail("diagnostic exec must not resolve a provider"),
    )
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kwargs: captured.update(kwargs)
        or SimpleNamespace(status="successful", events=[]),
    )

    assert agent_exec.run_agent_exec("wolf-i", "pi-demo", "pi", ["--version"]) == (
        "0.73.1",
        "",
        0,
    )
    variables = captured["inventory"]["all"]["vars"]
    assert variables["cmd_argv"] == ["--version"]
    assert variables["pi_exec_mode"] == "diagnostic"
    assert "pi_exec_prompt_b64" not in variables
