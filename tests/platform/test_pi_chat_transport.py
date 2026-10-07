"""Pi chat playbooks keep native output encrypted in runner events (#1038)."""

import base64
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import jinja2
import pytest
import yaml


PLAYBOOKS = (
    Path("src/clawrium/platform/registry/pi/playbooks/chat.yaml"),
    Path("src/clawrium/platform/registry/pi/playbooks/chat_macos.yaml"),
)


def _recipient_certificate(tmp_path: Path) -> tuple[str, Path]:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required for Pi secure-chat transport")
    private_key = tmp_path / "private.pem"
    certificate = tmp_path / "certificate.pem"
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=clawrium-pi-chat",
            "-days",
            "1",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
    )
    return certificate.read_text(), private_key


@pytest.mark.parametrize("path", PLAYBOOKS)
def test_pi_chat_bootstrap_encrypts_native_nonzero_and_marks_pre_result_failure(
    path: Path, tmp_path: Path
) -> None:
    """Both OS bootstraps preserve native failure output inside one CMS event."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required for Pi secure-chat transport")
    playbook = yaml.safe_load(path.read_text())[0]
    certificate, private_key = _recipient_certificate(tmp_path)
    home = tmp_path / "pi-home"
    credential = home / ".pi" / "agent" / "clawrium-openrouter.env"
    credential.parent.mkdir(parents=True)
    credential.write_text("OPENROUTER_API_KEY=fixture-only-not-a-secret\n")

    native = subprocess.run(
        [
            "/bin/bash",
            "-c",
            playbook["vars"]["pi_chat_capture_bootstrap"],
            "clawrium-pi-chat",
            playbook["vars"]["pi_chat_capture_program"],
            certificate,
            "/bin/sh",
            "-c",
            'printf "native-stdout"; printf "native-stderr" >&2; exit 17',
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    # The command task sees zero, so its false failed_when lets the following
    # debug task emit PI_CHAT_RESULT=<native.stdout> even though Pi exited 17.
    assert native.returncode == 0
    event = "PI_CHAT_RESULT=" + native.stdout
    assert "native-stdout" not in event and "native-stderr" not in event
    decoded = subprocess.run(
        [openssl, "cms", "-decrypt", "-binary", "-inform", "DER", "-inkey", str(private_key)],
        input=base64.b64decode(event.removeprefix("PI_CHAT_RESULT=")),
        capture_output=True,
        check=True,
    ).stdout
    assert json.loads(decoded) == {
        "stdout": "native-stdout",
        "stderr": "native-stderr",
        "rc": 17,
    }

    credential.unlink()
    pre_result = subprocess.run(
        [
            "/bin/bash",
            "-c",
            playbook["vars"]["pi_chat_capture_bootstrap"],
            "clawrium-pi-chat",
            playbook["vars"]["pi_chat_capture_program"],
            certificate,
            "/bin/true",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home)},
    )
    assert pre_result.returncode == 126
    assert not pre_result.stdout


def test_macos_chat_guard_accepts_real_dscl_output_and_rejects_mismatch():
    play = yaml.safe_load(PLAYBOOKS[1].read_text())[0]
    rules = next(
        task
        for task in play["tasks"]
        if task["name"] == "Verify Pi chat ownership binding"
    )["ansible.builtin.assert"]["that"]
    facts = {
        "agent_name": "pi-demo",
        "pi_home": "/Users/pi-demo",
        "pi_marker_data": {
            "schema": 2,
            "agent_name": "pi-demo",
            "home": "/Users/pi-demo",
            "uid": 501,
            "transaction_id": "12345678-1234-1234-1234-123456789abc",
        },
        "pi_account_uid": {"stdout": "UniqueID: 501\n"},
        "pi_account_home": {"stdout": "NFSHomeDirectory: /Users/pi-demo\n"},
        "pi_account_comment": {
            "stdout": "Comment: clawrium-pi-12345678-1234-1234-1234-123456789abc\n"
        },
    }
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    env.filters["regex_replace"] = lambda value, pattern, replacement: re.sub(
        pattern, replacement, value
    )

    def evaluate(values):
        return all(
            env.from_string("{{ " + rule + " }}").render(values) == "True"
            for rule in rules
        )

    assert evaluate(facts)
    facts["pi_account_uid"]["stdout"] = "UniqueID: 502\n"
    assert not evaluate(facts)
    facts["pi_account_uid"]["stdout"] = "UniqueID: 501\n"
    facts["pi_account_home"]["stdout"] = "NFSHomeDirectory: /Users/other\n"
    assert not evaluate(facts)
    facts["pi_account_home"]["stdout"] = "NFSHomeDirectory: /Users/pi-demo\n"
    facts["pi_account_comment"]["stdout"] = "Comment: clawrium-pi-wrong\n"
    assert not evaluate(facts)


def test_pi_chat_playbooks_use_cms_result_transport_without_raw_output_events():
    for path in PLAYBOOKS:
        play = yaml.safe_load(path.read_text())[0]
        rendered = path.read_text()
        assert "pi_chat_recipient_certificate" in rendered
        assert "openssl cms -encrypt" in rendered
        assert "PI_CHAT_RESULT=" in rendered
        assert "PI_CHAT_STDOUT=" not in rendered
        assert "PI_CHAT_STDERR=" not in rendered
        assert '. "$HOME/.pi/agent/clawrium-openrouter.env"' not in rendered
        assert "OPENROUTER_API_KEY=${line#OPENROUTER_API_KEY=}" in rendered
        assert "set -o pipefail" in rendered
        task = next(
            task
            for task in play["tasks"]
            if task["name"] == "Run finite Pi chat command as dedicated agent user"
        )
        assert task["no_log"] is True
        assert task["failed_when"] is False
        transport_failure_at = next(
            i
            for i, candidate in enumerate(play["tasks"])
            if candidate["name"] == "Reject Pi chat transport failure before encrypted result"
        )
        transport_failure = play["tasks"][transport_failure_at]
        assert transport_failure["no_log"] is True
        assert transport_failure["when"] == "pi_chat_result.rc != 0"
        switch_at = next(
            i
            for i, task in enumerate(play["tasks"])
            if task["name"] == "Run finite Pi chat command as dedicated agent user"
        )
        binding_at = next(
            i
            for i, task in enumerate(play["tasks"])
            if task["name"] == "Verify Pi chat ownership binding"
        )
        emit_at = next(
            i
            for i, candidate in enumerate(play["tasks"])
            if candidate["name"] == "Emit encrypted Pi chat result"
        )
        assert binding_at < switch_at < transport_failure_at < emit_at
        binding = play["tasks"][binding_at]["ansible.builtin.assert"]
        assert any("agent_name" in rule for rule in binding["that"])
        assert any("uid" in rule for rule in binding["that"])
        assert any("home" in rule for rule in binding["that"])
