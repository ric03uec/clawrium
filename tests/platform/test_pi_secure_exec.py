"""Security contracts for Pi native-exec's encrypted Ansible transport."""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml


PLAYBOOK_ROOT = Path("src/clawrium/platform/registry/pi/playbooks")
PLAYBOOKS = ("exec.yaml", "exec_macos.yaml")


def _playbook(filename: str) -> dict[str, Any]:
    loaded = yaml.safe_load((PLAYBOOK_ROOT / filename).read_text())
    assert isinstance(loaded, list) and len(loaded) == 1
    return loaded[0]


def _task(playbook: dict[str, Any], name: str) -> dict[str, Any]:
    return next(task for task in playbook["tasks"] if task["name"] == name)


@pytest.mark.parametrize("filename", PLAYBOOKS)
def test_pi_exec_actual_transport_encrypts_sentinel_output(
    filename: str, tmp_path: Path
) -> None:
    """Execute the playbook's capture variables, not a Python reimplementation."""
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required for Pi secure-exec transport")

    playbook = _playbook(filename)
    private_key = tmp_path / "private.pem"
    public_key = tmp_path / "public.pem"
    subprocess.run(
        [
            openssl,
            "genpkey",
            "-algorithm",
            "RSA",
            "-pkeyopt",
            "rsa_keygen_bits:2048",
            "-out",
            str(private_key),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            openssl,
            "req",
            "-new",
            "-x509",
            "-key",
            str(private_key),
            "-subj",
            "/CN=clawrium-pi-exec",
            "-days",
            "1",
            "-out",
            str(public_key),
        ],
        check=True,
        capture_output=True,
    )
    sentinel = "pi-sensitive-sentinel-never-in-ansible-event"
    inherited_bearer = "inherited-bearer-must-not-reach-diagnostic-exec"
    inherited_static = "inherited-static-key-must-not-reach-diagnostic-exec"
    inherited_secret = "inherited-static-secret-must-not-reach-diagnostic-exec"
    inherited_session = "inherited-session-must-not-reach-diagnostic-exec"
    inherited_shared = "/tmp/inherited-shared-credentials-must-not-reach-diagnostic-exec"
    inherited_bedrock = "inherited-bedrock-bearer-must-not-reach-diagnostic-exec"
    inherited_relative = "/v2/credentials/inherited-relative"
    inherited_full = "http://169.254.170.2/inherited-full"
    inherited_web_identity = "/tmp/inherited-web-identity-token"
    # The bootstrap reads the private artifact as data, never shell source.
    home = tmp_path / "pi-home"
    credential = home / ".pi" / "agent" / "clawrium-provider.env"
    credential.parent.mkdir(parents=True)
    credential.write_text("OPENROUTER_API_KEY=not-a-shell-command;$(ignored)\n")
    shim_dir = tmp_path / "agent-writable-bin"
    shim_dir.mkdir()
    shim_marker = tmp_path / "path-shim-ran"
    for utility in ("openssl", "base64", "tr", "mktemp"):
        shim = shim_dir / utility
        shim.write_text(
            f"#!/bin/sh\nprintf '%s' {str(shim_marker)!r} > /dev/null\ntouch {str(shim_marker)!r}\nprintf '%s' {sentinel!r}\n"
        )
        shim.chmod(0o700)
    completed = subprocess.run(
        [
            "/bin/bash",
            "-c",
            playbook["vars"]["pi_exec_capture_bootstrap"],
            "clawrium-pi-exec",
            playbook["vars"]["pi_exec_capture_program"],
            public_key.read_text(),
            "diagnostic",
            "/bin/sh",
            "-c",
            f'printf "%s:%s:%s:%s:%s:%s:%s:%s:%s:%s" "{sentinel}" "${{OPENROUTER_API_KEY-unset}}" "${{AWS_ACCESS_KEY_ID-unset}}" "${{AWS_SECRET_ACCESS_KEY-unset}}" "${{AWS_SESSION_TOKEN-unset}}" "${{AWS_SHARED_CREDENTIALS_FILE-unset}}" "${{AWS_BEARER_TOKEN_BEDROCK-unset}}" "${{AWS_CONTAINER_CREDENTIALS_RELATIVE_URI-unset}}" "${{AWS_CONTAINER_CREDENTIALS_FULL_URI-unset}}" "${{AWS_WEB_IDENTITY_TOKEN_FILE-unset}}"; printf "%s" "{sentinel}" >&2; exit 17',
        ],
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "PATH": f"{shim_dir}:{os.environ['PATH']}",
            "OPENROUTER_API_KEY": inherited_bearer,
            "AWS_ACCESS_KEY_ID": inherited_static,
            "AWS_SECRET_ACCESS_KEY": inherited_secret,
            "AWS_SESSION_TOKEN": inherited_session,
            "AWS_SHARED_CREDENTIALS_FILE": inherited_shared,
            "AWS_BEARER_TOKEN_BEDROCK": inherited_bedrock,
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": inherited_relative,
            "AWS_CONTAINER_CREDENTIALS_FULL_URI": inherited_full,
            "AWS_WEB_IDENTITY_TOKEN_FILE": inherited_web_identity,
        },
    )

    # The account-writable PATH is ignored before capture begins, so a planted
    # helper cannot turn the persisted event into plaintext.
    assert not shim_marker.exists()
    # This is precisely what the debug event persists: opaque CMS bytes only.
    assert sentinel not in completed.stdout
    assert sentinel not in completed.stderr
    for inherited in (
        inherited_bearer,
        inherited_static,
        inherited_secret,
        inherited_session,
        inherited_shared,
        inherited_bedrock,
        inherited_relative,
        inherited_full,
        inherited_web_identity,
    ):
        assert inherited not in completed.stdout
        assert inherited not in completed.stderr
    decrypted = subprocess.run(
        [
            openssl,
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-inkey",
            str(private_key),
        ],
        input=base64.b64decode(completed.stdout),
        check=True,
        capture_output=True,
    ).stdout
    assert json.loads(decrypted) == {
        "stdout": (
            sentinel
            + ":unset:unset:unset:unset:unset:unset:unset:unset:unset"
        ),
        "stderr": sentinel,
        "rc": 17,
    }


@pytest.mark.parametrize("filename", PLAYBOOKS)
@pytest.mark.parametrize(
    "provider_env,symlink",
    [
        ("AWS_PROFILE=p\nAWS_REGION=r\nAWS_CONFIG_FILE=$HOME/../../escape\n", False),
        ("OPENROUTER_API_KEY=x\nAWS_PROFILE=p\nAWS_REGION=r\nAWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n", False),
        ("AWS_PROFILE=p\nAWS_PROFILE=q\nAWS_REGION=r\nAWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n", False),
        ("AWS_PROFILE=p\nAWS_REGION=r\nAWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n", True),
    ],
)
def test_pi_exec_bootstrap_rejects_untrusted_provider_environment(
    filename: str, provider_env: str, symlink: bool, tmp_path: Path
) -> None:
    """Run the production bootstrap and require bad provider files to fail closed."""
    playbook = _playbook(filename)
    home = tmp_path / "pi-home"
    env_file = home / ".pi" / "agent" / "clawrium-provider.env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text(provider_env)
    if symlink:
        target = tmp_path / "provider-config"
        target.write_text("[profile p]\n")
        (env_file.parent / "clawrium-aws-config").symlink_to(target)
    completed = subprocess.run(
        ["/bin/bash", "-c", playbook["vars"]["pi_exec_capture_bootstrap"], "test", "ignored", "ignored", "inference", "/bin/true"],
        text=True, capture_output=True, env={**os.environ, "HOME": str(home)}, check=False,
    )
    assert completed.returncode == 126


@pytest.mark.parametrize("filename", PLAYBOOKS)
def test_pi_exec_playbook_task_flow_never_emits_raw_output(filename: str) -> None:
    """The ownership gates precede a no-log capture and one opaque event."""
    playbook = _playbook(filename)
    tasks = playbook["tasks"]
    names = [task["name"] for task in tasks]
    run = _task(playbook, "Run encrypted Pi native command")
    emit = _task(playbook, "Emit encrypted Pi exec result")

    assert names.index("Verify Pi execution ownership binding") < names.index(
        run["name"]
    )
    assert run["no_log"] is True
    assert run["ansible.builtin.command"]["expand_argument_vars"] is False
    assert "pi_exec_capture_bootstrap" in run["ansible.builtin.command"]["argv"]
    assert "pi_exec_recipient_certificate" in run["ansible.builtin.command"]["argv"]
    assert "pi_exec_mode" in run["ansible.builtin.command"]["argv"]
    assert run["ansible.builtin.command"]["stdin_add_newline"] is False
    assert "pi_exec_safe_result.stdout" in emit["ansible.builtin.debug"]["msg"]
    source = (PLAYBOOK_ROOT / filename).read_text()
    assert "PATH=/usr/bin:/bin; export PATH" in source
    for helper in (
        "/usr/bin/mktemp",
        "/usr/bin/openssl",
        "/usr/bin/base64",
        "/usr/bin/tr",
    ):
        assert helper in source
    assert "EXEC_STDOUT=" not in source
    assert "EXEC_STDERR=" not in source
    assert "EXEC_RC=" not in source
    assert "pi_exec.stdout" not in source
    assert "pi_exec.stderr" not in source
    assert 'case "$mode" in inference)' in source
    assert "diagnostic) ;;" in source
    assert "unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN" in source
    assert "AWS_SHARED_CREDENTIALS_FILE=\"$HOME/.pi/agent/clawrium-aws-credentials\"" in source
    assert "AWS_EC2_METADATA_DISABLED=true" in source


@pytest.mark.parametrize("filename", PLAYBOOKS)
def test_pi_exec_uses_process_group_timeout_wrapper(filename: str) -> None:
    """Both platform playbooks kill the complete Pi process group at deadline."""
    playbook = _playbook(filename)
    wrapper = playbook["vars"]["pi_exec_timeout_wrapper"]
    completed = subprocess.run(
        [
            "/usr/bin/perl",
            "-e",
            wrapper,
            "1",
            "/bin/sh",
            "-c",
            "sleep 30",
        ],
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert completed.returncode == 124
    validate = _task(playbook, "Validate Pi exec argv and timeout")
    assert "pi_exec_timeout" in validate["when"]
    run = _task(playbook, "Run encrypted Pi native command")
    argv = run["ansible.builtin.command"]["argv"]
    assert "pi_exec_mode" in argv
    assert "pi_exec_timeout_wrapper" in argv
    assert "pi_exec_timeout | string" in argv
