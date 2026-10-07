"""Mocked Darwin Pi execution routing and result propagation."""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

from clawrium.core import agent_exec


def _event(message):
    return {"event": "runner_on_ok", "event_data": {"res": {"msg": message}}}


def _result(events, status="successful"):
    return SimpleNamespace(events=events, status=status)


def _secure_result(payload, tmp_path: Path):
    def make_result(**kwargs):
        openssl = shutil.which("openssl")
        assert openssl is not None
        certificate = tmp_path / "recipient.pem"
        certificate.write_text(
            kwargs["inventory"]["all"]["vars"]["pi_exec_recipient_certificate"]
        )
        encrypted = subprocess.run(
            [
                openssl,
                "cms",
                "-encrypt",
                "-binary",
                "-outform",
                "DER",
                "-aes-256-cbc",
                "-recip",
                str(certificate),
            ],
            input=json.dumps(payload).encode(),
            capture_output=True,
            check=True,
        ).stdout
        return _result([_event("PI_EXEC_RESULT=" + base64.b64encode(encrypted).decode())])

    return make_result


def _setup(monkeypatch, tmp_path, result, captured):
    monkeypatch.setattr(agent_exec, "get_config_dir", lambda: tmp_path)
    key = tmp_path / "key"
    key.write_text("key")
    monkeypatch.setattr(agent_exec.core_keys, "get_host_private_key", lambda _: key)
    monkeypatch.setattr(
        "clawrium.core.hosts.get_host",
        lambda _: {
            "hostname": "mac.example",
            "user": "piuser",
            "port": 22,
            "key_id": "mac-key",
            "os_family": "darwin",
        },
    )
    monkeypatch.setattr(
        agent_exec.ansible_runner,
        "run",
        lambda **kw: captured.update(kw) or (result(**kw) if callable(result) else result),
    )


def test_pi_darwin_exec_selects_macos_playbook_and_decodes_success(
    monkeypatch, tmp_path
):
    captured = {}
    _setup(
        monkeypatch,
        tmp_path,
        _secure_result({"stdout": "0.73.1\n", "stderr": "", "rc": 0}, tmp_path),
        captured,
    )
    assert agent_exec.run_agent_exec("mac", "pi-one", "pi", ["--version"]) == (
        "0.73.1\n",
        "",
        0,
    )
    assert str(captured["playbook"]).endswith("pi/playbooks/exec_macos.yaml")
    assert (
        captured["inventory"]["all"]["hosts"]["mac.example"]["ansible_user"] == "piuser"
    )
    assert captured["inventory"]["all"]["vars"]["agent_name"] == "pi-one"
    assert captured["inventory"]["all"]["vars"]["cmd_argv"] == ["--version"]
    assert captured["inventory"]["all"]["vars"]["pi_exec_timeout"] == 120
    assert captured["timeout"] == 150
    assert "BEGIN CERTIFICATE" in captured["inventory"]["all"]["vars"][
        "pi_exec_recipient_certificate"
    ]


def test_pi_darwin_exec_propagates_nonzero_result(monkeypatch, tmp_path):
    captured = {}
    _setup(
        monkeypatch,
        tmp_path,
        _secure_result({"stdout": "", "stderr": "bad\n", "rc": 9}, tmp_path),
        captured,
    )
    assert agent_exec.run_agent_exec("mac", "pi-one", "pi", ["--bad"]) == (
        "",
        "bad\n",
        9,
    )
    assert str(captured["playbook"]).endswith("pi/playbooks/exec_macos.yaml")
