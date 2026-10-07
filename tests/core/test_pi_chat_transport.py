"""Direct Pi finite transport boundary coverage (#1038)."""

from pathlib import Path
import threading
from types import SimpleNamespace
from clawrium.core.chat_pi import run_pi_chat


def setup(monkeypatch, tmp_path, result):
    monkeypatch.setattr(
        "clawrium.core.hosts.get_host",
        lambda _: {
            "hostname": "wolf-i",
            "alias": "wolf-i",
            "key_id": "k",
            "port": 2222,
            "user": "x",
        },
    )
    monkeypatch.setattr(
        "clawrium.core.chat_pi.resolve_agent_playbook",
        lambda *a: Path("/playbook.yaml"),
    )
    monkeypatch.setattr(
        "clawrium.core.chat_pi.core_keys.get_host_private_key", lambda _: Path("/key")
    )
    monkeypatch.setattr("clawrium.core.chat_pi._logs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "clawrium.core.agent_exec._create_pi_exec_keypair",
        lambda d: (d / "private", "CERT"),
    )
    monkeypatch.setattr(
        "clawrium.core.chat_pi._parse_events", lambda r, k: ("ok", "", 0)
    )
    return result


def test_run_pi_chat_builds_private_inventory_and_cleans(monkeypatch, tmp_path):
    calls = []
    result = SimpleNamespace(status="successful", events=[])
    setup(monkeypatch, tmp_path, result)
    monkeypatch.setattr(
        "clawrium.core.chat_pi.ansible_runner.run",
        lambda **kw: calls.append(kw) or result,
    )
    assert run_pi_chat("wolf-i", "pi-demo", ["--print"], "hello", 12) == ("ok", "", 0)
    assert calls[0]["inventory"]["all"]["hosts"]["wolf-i"]["ansible_port"] == 2222
    assert calls[0]["inventory"]["all"]["vars"]["pi_chat_argv"] == ["--print"]
    assert not list(tmp_path.iterdir())


def test_run_pi_chat_maps_timeout_unsuccessful_and_cancel(monkeypatch, tmp_path):
    result = SimpleNamespace(status="timeout", events=[])
    setup(monkeypatch, tmp_path, result)
    monkeypatch.setattr("clawrium.core.chat_pi.ansible_runner.run", lambda **kw: result)
    assert run_pi_chat("wolf-i", "pi-demo", ["x"], "p", 1) == ("", "", 124)
    result.status = "failed"
    assert run_pi_chat("wolf-i", "pi-demo", ["x"], "p", 1) == ("", "", 255)
    result.status = "successful"
    seen = []

    def async_run(**kw):
        seen.append(kw)
        return SimpleNamespace(join=lambda: None), result

    monkeypatch.setattr("clawrium.core.chat_pi.ansible_runner.run_async", async_run)
    event = threading.Event()
    assert run_pi_chat("wolf-i", "pi-demo", ["x"], "p", 1, event) == ("ok", "", 0)
    assert seen[0]["cancel_callback"]() is False
