"""Canonical Pi OpenRouter credential activation (#1038)."""

import json
import os
import subprocess
import sys

import pytest

from clawrium.core.lifecycle_canonical import (
    CanonicalSyncError,
    _sync_pi_openrouter,
    revoke_pi_openrouter,
    _pi_user_environment_operation,
    _verify_pi_bedrock_sso_readiness,
    _PI_BEDROCK_STS_IDENTITY_VALIDATOR,
    _PI_BEDROCK_STS_IDENTITY_VALIDATOR_PERL,
    _build_pi_bedrock_sso_readiness_probe,
)


class _Channel:
    def recv_exit_status(self):
        return 0


class _Output:
    channel = _Channel()


class _Stdin:
    channel = type("Channel", (), {"shutdown_write": lambda self: None})()

    def write(self, _body):
        pass

    def flush(self):
        pass


class _Client:
    def __init__(self):
        self.commands = []
        self.closed = False

    def exec_command(self, command, timeout):
        self.commands.append((command, timeout))
        return _Stdin(), _Output(), None

    def close(self):
        self.closed = True


def test_canonical_pi_sync_writes_only_account_private_environment(monkeypatch):
    client = _Client()
    writes = []
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda _client, **kwargs: writes.append(kwargs),
    )
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "private-key"
    )

    result = _sync_pi_openrouter(
        agent_name="pi-demo",
        host={"hostname": "wolf-i", "os_family": "linux"},
        claw_record={"providers": ["router"]},
        workspace_only=False,
        dry_run=False,
        on_event=None,
    )

    assert result.success is True
    assert client.closed is True
    assert len(writes) == 3
    assert writes[0]["path"] == "/home/pi-demo/.pi/agent/clawrium-provider.env"
    assert writes[0]["body"] == "OPENROUTER_API_KEY=private-key\n"
    assert writes[1]["path"] == "/home/pi-demo/.pi/agent/clawrium-aws-config"
    assert writes[1]["body"] is None
    assert writes[2]["path"] == "/home/pi-demo/.pi/agent/clawrium-aws-credentials"
    assert writes[2]["body"] is None
    assert "private-key" not in client.commands[0][0]


def test_canonical_pi_sync_closes_ssh_when_private_write_fails(monkeypatch):
    client = _Client()
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "private-key"
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CanonicalSyncError("write failed")
        ),
    )
    with pytest.raises(CanonicalSyncError, match="write failed"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": ["router"]},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )
    assert client.closed is True


def test_canonical_pi_sync_refuses_remote_ownership_validation_failure(monkeypatch):
    client = _Client()
    client_result = _Output()
    client_result.channel.recv_exit_status = lambda: 1
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "private-key"
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda *_a, **_kw: pytest.fail("must not write"),
    )
    client.exec_command = lambda command, timeout: (None, client_result, None)
    with pytest.raises(CanonicalSyncError, match="ownership marker"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": ["router"]},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )
    assert client.closed


def test_pi_environment_write_streams_secret_only_on_stdin():
    events = []

    class Channel:
        def shutdown_write(self):
            events.append("shutdown")

        def recv_exit_status(self):
            return 0

    class Stdin:
        channel = Channel()

        def write(self, value):
            events.append(("write", value))

        def flush(self):
            events.append("flush")

    class Client:
        def exec_command(self, command, timeout):
            assert "private-key" not in command
            assert "sudo -n -u pi-demo" in command
            return Stdin(), type("Out", (), {"channel": Channel()})(), None

    _pi_user_environment_operation(
        Client(),
        agent_name="pi-demo",
        path="/home/pi-demo/.pi/agent/clawrium-provider.env",
        body="OPENROUTER_API_KEY=private-key\\n",
    )
    assert events == [
        ("write", "OPENROUTER_API_KEY=private-key\\n"),
        "flush",
        "shutdown",
    ]


def test_pi_revocation_fails_closed(monkeypatch):
    client = _Client()
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    # The first command validates ownership; revocation fails after it.
    calls = iter([0, 1])
    client.exec_command = lambda command, timeout: (
        None,
        type(
            "O",
            (),
            {
                "channel": type(
                    "C", (), {"recv_exit_status": lambda self: next(calls)}
                )()
            },
        )(),
        None,
    )
    with pytest.raises(CanonicalSyncError, match="remove Pi provider activation"):
        revoke_pi_openrouter(
            agent_name="pi-demo", host={"hostname": "wolf-i", "os_family": "linux"}
        )
    assert client.closed


def test_canonical_pi_sync_provisions_only_agent_scoped_sso_configuration(monkeypatch):
    client = _Client()
    writes = []
    provider = {
        "type": "bedrock", "credential_source": "aws-sso",
        "default_model": "anthropic.claude-3-haiku-20240307-v1:0",
        "aws_profile": "pi-bedrock", "region": "us-east-1",
        "sso_start_url": "https://company.awsapps.com/start", "sso_region": "us-east-1",
        "sso_account_id": "123456789012", "sso_role_name": "BedrockPiRole",
    }
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr("clawrium.core.providers.storage.get_provider", lambda _: provider)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_remote_ownership",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._pi_user_environment_operation", lambda _client, **kwargs: writes.append(kwargs))
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_bedrock_sso_readiness",
        lambda *_args, **_kwargs: None,
    )
    result = _sync_pi_openrouter(agent_name="pi-demo", host={"hostname": "wolf-i", "os_family": "linux"}, claw_record={"providers": ["bedrock"]}, workspace_only=False, dry_run=False, on_event=None)
    assert result.files_written == (
        ".pi/agent/clawrium-provider.env",
        ".pi/agent/clawrium-aws-config",
        ".pi/agent/clawrium-aws-credentials",
    )
    assert writes[0]["body"] == "AWS_PROFILE=pi-bedrock\nAWS_REGION=us-east-1\nAWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n"
    assert "sso_start_url" in writes[1]["body"]
    assert "secret" not in writes[1]["body"].lower()
    assert "aws_access_key" not in str(writes)


def test_pi_bedrock_readiness_does_not_emit_profile_or_config_contents():
    class Client:
        def __init__(self):
            self.commands = []

        def exec_command(self, command, timeout):
            self.commands.append((command, timeout))
            return (
                None,
                type("O", (), {"channel": type("C", (), {"recv_exit_status": lambda self: 0})()})(),
                None,
            )

    client = Client()
    _verify_pi_bedrock_sso_readiness(
        client,
        agent_name="pi-demo",
        profile="pi-bedrock",
        region="us-east-1",
        config_path="/home/pi-demo/.pi/agent/clawrium-aws-config",
        account_id="123456789012",
        role_name="BedrockPiRole",
    )
    command = client.commands[-1][0]
    assert "get-caller-identity" in command
    assert "aws-cli/2\\." in command
    assert '"$resolved" --version' in command
    assert "command -v aws" not in command
    assert "aws sso login" not in command
    assert "sso_start_url" not in command


def test_pi_bedrock_readiness_probe_vets_standard_symlink_and_rejects_bad_ancestors(tmp_path):
    # Test-local UID/root are an adaptation only: production defaults remain
    # UID 0 and /, so every actual production path component is checked.
    root = tmp_path / "trusted"
    candidate = root / "usr" / "local" / "bin" / "aws"
    target = root / "aws-cli" / "v2" / "current" / "bin" / "aws"
    candidate.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    target.write_text(
        "#!/bin/sh\n"
        "if test \"$1\" = --version; then echo aws-cli/2.15.0; "
        "else echo '{\"Account\": \"123456789012\", \"Arn\": \"arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockPiRole_abc123/session\"}'; fi\n"
    )
    target.chmod(0o555)
    candidate.symlink_to(target)
    for directory in root.rglob("*"):
        if directory.is_dir() and not directory.is_symlink():
            directory.chmod(0o555)
    root.chmod(0o555)
    args = dict(
        account_id="123456789012", role_name="BedrockPiRole", os_family="linux",
        expected_uid=os.getuid(), trusted_root=str(root),
    )
    valid = _build_pi_bedrock_sso_readiness_probe(candidates=(str(candidate),), **args)
    assert subprocess.run(["/bin/bash", "-c", valid], check=False).returncode == 0

    # A writable target ancestor and an original-path symlinked ancestor both
    # reject the candidate before the binary can be executed.
    target.parent.chmod(0o755)
    writable = _build_pi_bedrock_sso_readiness_probe(candidates=(str(candidate),), **args)
    assert subprocess.run(["/bin/bash", "-c", writable], check=False).returncode != 0
    target.parent.chmod(0o555)
    linked_bin = root / "linked-bin"
    root.chmod(0o755)
    linked_bin.symlink_to(candidate.parent)
    root.chmod(0o555)
    symlinked = _build_pi_bedrock_sso_readiness_probe(candidates=(str(linked_bin / "aws"),), **args)
    assert subprocess.run(["/bin/bash", "-c", symlinked], check=False).returncode != 0


def test_pi_bedrock_sts_validator_requires_exact_account_and_reserved_sso_role():
    class Client:
        def __init__(self):
            self.command = ""

        def exec_command(self, command, timeout):
            self.command = command
            return (
                None,
                type("O", (), {"channel": type("C", (), {"recv_exit_status": lambda self: 0})()})(),
                None,
            )

    client = Client()
    _verify_pi_bedrock_sso_readiness(
        client,
        agent_name="pi-demo",
        profile="pi-bedrock",
        region="us-east-1",
        config_path="/home/pi-demo/.pi/agent/clawrium-aws-config",
        account_id="123456789012",
        role_name="BedrockPiRole",
    )
    linux_probe = _build_pi_bedrock_sso_readiness_probe(
        account_id="123456789012", role_name="BedrockPiRole", os_family="linux"
    )
    darwin_probe = _build_pi_bedrock_sso_readiness_probe(
        account_id="123456789012", role_name="BedrockPiRole", os_family="darwin"
    )
    assert "/usr/bin/python3 -c" in linux_probe
    assert "/usr/bin/perl" not in linux_probe
    assert "/usr/bin/perl -MJSON::PP -e" in darwin_probe
    assert "/usr/bin/python3" not in darwin_probe

    validators = (
        [sys.executable, "-c", _PI_BEDROCK_STS_IDENTITY_VALIDATOR],
        ["/usr/bin/perl", "-MJSON::PP", "-e", _PI_BEDROCK_STS_IDENTITY_VALIDATOR_PERL],
    )

    def validate(command: list[str], payload: object | str) -> int:
        body = payload if isinstance(payload, str) else json.dumps(payload)
        return subprocess.run(
            command + ["123456789012", "BedrockPiRole"],
            input=body, text=True, capture_output=True, check=False,
        ).returncode

    for validator in validators:
        assert validate(validator, {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockPiRole_abc123/session"}) == 0
        assert validate(validator, {"Account": "999999999999", "Arn": "arn:aws:sts::999999999999:assumed-role/AWSReservedSSO_BedrockPiRole_abc123/session"}) != 0
        # Prefix collision: BedrockPiRoleAdmin must not satisfy BedrockPiRole.
        assert validate(validator, {"Account": "123456789012", "Arn": "arn:aws:sts::123456789012:assumed-role/AWSReservedSSO_BedrockPiRoleAdmin_abc123/session"}) != 0
        assert validate(validator, "{not-json") != 0


def test_pi_bedrock_readiness_is_actionable_when_identity_is_unavailable():
    client = _Client()
    client.exec_command = lambda command, timeout: (
        None,
        type("O", (), {"channel": type("C", (), {"recv_exit_status": lambda self: 1})()})(),
        None,
    )
    with pytest.raises(CanonicalSyncError, match="aws sso login"):
        _verify_pi_bedrock_sso_readiness(
            client,
            agent_name="pi-demo",
            profile="pi-bedrock",
            region="us-east-1",
            config_path="/home/pi-demo/.pi/agent/clawrium-aws-config",
            account_id="123456789012",
            role_name="BedrockPiRole",
        )


def test_canonical_pi_sync_rejects_missing_provider_before_remote_io(monkeypatch):
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._open_ssh",
        lambda _: pytest.fail("must not open SSH"),
    )
    with pytest.raises(CanonicalSyncError, match="exactly one attached"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": []},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )
