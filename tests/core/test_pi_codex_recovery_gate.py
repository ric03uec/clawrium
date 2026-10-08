"""Fail-closed runtime gates for interrupted Pi Codex OAuth recovery (#1048)."""

from __future__ import annotations

import asyncio
import threading
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from clawrium.core import agent_exec, chat_pi, lifecycle_canonical as lc
from clawrium.core.chat import ChatAuthenticationError
from clawrium.core.lifecycle_canonical import CanonicalSyncError


_CODEX_PROVIDER = {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"}


def _pi_record(*, recovery: bool) -> tuple[dict, str, dict]:
    record = {"type": "pi", "agent_name": "pi-demo", "providers": ["codex"]}
    if recovery:
        record["pi_codex_auth_recovery"] = True
    return ({"hostname": "wolf-i"}, "pi", record)


def test_native_pi_codex_inference_rejects_stale_auth_before_transport(monkeypatch, tmp_path):
    """A structurally valid old auth.json cannot reach the exec playbook."""
    from clawrium.core import hosts
    from clawrium.core.providers import storage

    monkeypatch.setattr(
        agent_exec, "get_config_dir", lambda: tmp_path / "config"
    )
    key = tmp_path / "key"
    key.write_text("key")
    monkeypatch.setattr(agent_exec.core_keys, "get_host_private_key", lambda _: key)
    monkeypatch.setattr(hosts, "get_host", lambda _: {"hostname": "wolf-i"})
    monkeypatch.setattr(hosts, "get_agent_by_name", lambda _: _pi_record(recovery=True))
    monkeypatch.setattr(storage, "get_provider", lambda _: _CODEX_PROVIDER)
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **_: pytest.fail("stale Codex auth must not be transported"),
    )

    with pytest.raises(agent_exec.AgentExecError, match="credential recovery is pending"):
        agent_exec.run_agent_exec("wolf-i", "pi-demo", "pi", ["--print", "hello"])


def test_native_pi_diagnostics_remain_available_during_recovery(
    monkeypatch, tmp_path
):
    key = tmp_path / "key"
    key.write_text("key")
    monkeypatch.setattr(agent_exec, "get_config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(agent_exec.core_keys, "get_host_private_key", lambda _: key)
    from clawrium.core import hosts

    monkeypatch.setattr(hosts, "get_host", lambda _: {"hostname": "wolf-i"})
    captured = {}
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kwargs: captured.update(kwargs)
        or SimpleNamespace(status="failed", events=[]),
    )

    assert agent_exec.run_agent_exec("wolf-i", "pi-demo", "pi", ["--version"])[2] == 255
    assert captured["inventory"]["all"]["vars"]["pi_codex_auth_recovery"] is False


def test_pi_codex_chat_rejects_stale_auth_before_runner(monkeypatch):
    from clawrium.core import hosts, pi

    monkeypatch.setattr(pi, "pi_credential_lock", lambda _: nullcontext())
    from clawrium.core.providers import storage

    monkeypatch.setattr(hosts, "get_agent_by_name", lambda _: _pi_record(recovery=True))
    monkeypatch.setattr(storage, "get_provider", lambda _: _CODEX_PROVIDER)
    invoked = False

    def runner(*_args):
        nonlocal invoked
        invoked = True
        return "old auth response", "", 0

    async def exercise():
        backend = chat_pi.PiChatBackend(
            "wolf-i", "pi-demo", "gpt-5.1-codex-mini", provider="openai-codex", command_runner=runner
        )
        await backend.connect()
        with pytest.raises(ChatAuthenticationError, match="credential recovery is pending"):
            await backend.send_message("hello", "session")

    asyncio.run(exercise())
    assert invoked is False


def test_pi_codex_chat_fails_closed_when_its_record_disappears(monkeypatch):
    from clawrium.core import hosts, pi

    monkeypatch.setattr(pi, "pi_credential_lock", lambda _: nullcontext())

    monkeypatch.setattr(hosts, "get_agent_by_name", lambda _: None)

    async def exercise():
        backend = chat_pi.PiChatBackend(
            "wolf-i",
            "pi-demo",
            "gpt-5.1-codex-mini",
            provider="openai-codex",
            command_runner=lambda *_: pytest.fail("changed record must not run Pi"),
        )
        await backend.connect()
        with pytest.raises(ChatAuthenticationError, match="credential recovery is pending"):
            await backend.send_message("hello", "session")

    asyncio.run(exercise())


def test_pi_codex_chat_and_sync_resume_after_verified_login_clears_marker(monkeypatch):
    """The cleared durable marker, not an old auth.json's shape, authorizes use."""
    from clawrium.core import hosts, pi
    from clawrium.core.providers import storage

    monkeypatch.setattr(pi, "pi_credential_lock", lambda _: nullcontext())
    monkeypatch.setattr(hosts, "get_agent_by_name", lambda _: _pi_record(recovery=False))
    monkeypatch.setattr(storage, "get_provider", lambda _: _CODEX_PROVIDER)
    runner_args = []

    def runner(*args):
        runner_args.append(args)
        return "recovered", "", 0

    async def exercise():
        backend = chat_pi.PiChatBackend(
            "wolf-i", "pi-demo", "gpt-5.1-codex-mini", provider="openai-codex", command_runner=runner
        )
        await backend.connect()
        assert await backend.send_message("hello", "session") == "recovered"

    asyncio.run(exercise())
    assert runner_args[0][-1] is False

    monkeypatch.setattr(lc, "get_provider", lambda _: _CODEX_PROVIDER, raising=False)
    # _sync_pi_openrouter imports storage lazily, so patch that public lookup too.
    monkeypatch.setattr(storage, "get_provider", lambda _: _CODEX_PROVIDER)
    result = lc._sync_pi_openrouter(
        agent_name="pi-demo",
        host={"hostname": "wolf-i", "os_family": "linux"},
        claw_record=_pi_record(recovery=False)[2],
        workspace_only=False,
        dry_run=True,
        on_event=None,
    )
    assert result.success is True


def _install_alias_lock_fixture(monkeypatch, tmp_path):
    """Make two public names resolve to one canonical Pi lock identity."""
    from clawrium.core import hosts, pi
    from clawrium.core.providers import storage

    record = {"type": "pi", "agent_name": "pi-unix", "providers": ["codex"]}
    host = {"hostname": "wolf-i", "key_id": "host-key", "agents": {"canonical": record}}
    monkeypatch.setattr(hosts, "get_agent_by_name", lambda _: (host, "pi", record))
    monkeypatch.setattr(hosts, "get_host", lambda _: host)
    monkeypatch.setattr(storage, "get_provider", lambda _: _CODEX_PROVIDER)
    monkeypatch.setattr(pi, "init_config_dir", lambda: tmp_path)
    return host


def test_native_codex_exec_holds_canonical_lock_through_remote_completion(
    monkeypatch, tmp_path
):
    """A transition via the canonical name cannot enter during alias exec."""
    _install_alias_lock_fixture(monkeypatch, tmp_path)
    key = tmp_path / "key"
    key.write_text("key")
    monkeypatch.setattr(agent_exec, "get_config_dir", lambda: tmp_path / "config")
    monkeypatch.setattr(agent_exec.core_keys, "get_host_private_key", lambda _: key)
    monkeypatch.setattr(
        agent_exec, "_create_pi_exec_keypair", lambda directory: (directory / "key", "CERT")
    )
    started, release, transitioned = threading.Event(), threading.Event(), threading.Event()

    def runner(**_kwargs):
        started.set()
        assert release.wait(1)
        return SimpleNamespace(status="failed", events=[])

    monkeypatch.setattr(agent_exec.ansible_runner, "run", runner)
    execution = threading.Thread(
        target=lambda: agent_exec.run_agent_exec(
            "wolf-i", "alias", "pi", ["--print", "hello"]
        )
    )
    execution.start()
    assert started.wait(1)

    from clawrium.core.pi import pi_credential_lock

    # Use a normal context manager in the transition thread so it cannot leak.
    def transition_target():
        with pi_credential_lock("canonical"):
            transitioned.set()

    transition = threading.Thread(target=transition_target)
    transition.start()
    assert not transitioned.wait(0.1)
    release.set()
    execution.join(1)
    transition.join(1)
    assert not execution.is_alive()
    assert transitioned.is_set()


@pytest.mark.anyio
async def test_codex_chat_holds_canonical_lock_without_blocking_event_loop(
    monkeypatch, tmp_path
):
    _install_alias_lock_fixture(monkeypatch, tmp_path)
    started, release, transitioned = threading.Event(), threading.Event(), threading.Event()

    def runner(*_args):
        started.set()
        assert release.wait(1)
        return "ok", "", 0

    backend = chat_pi.PiChatBackend(
        "wolf-i", "alias", "gpt-5.1-codex-mini", provider="openai-codex", command_runner=runner
    )
    await backend.connect()
    task = asyncio.create_task(backend.send_message("hello", "session"))
    while not started.is_set():
        await asyncio.sleep(0.01)

    from clawrium.core.pi import pi_credential_lock

    def transition_target():
        with pi_credential_lock("canonical"):
            transitioned.set()

    transition = threading.Thread(target=transition_target)
    transition.start()
    await asyncio.sleep(0.05)
    assert not transitioned.is_set()
    release.set()
    assert await asyncio.wait_for(task, timeout=1) == "ok"
    transition.join(1)
    assert transitioned.is_set()


def test_pi_codex_sync_rejects_recovery_before_ssh(monkeypatch):
    from clawrium.core.providers import storage

    monkeypatch.setattr(storage, "get_provider", lambda _: _CODEX_PROVIDER)
    monkeypatch.setattr(
        lc, "_open_ssh", lambda _: pytest.fail("recovery-pending sync must not use SSH")
    )

    with pytest.raises(CanonicalSyncError, match="credential recovery is pending"):
        lc._sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record=_pi_record(recovery=True)[2],
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )
