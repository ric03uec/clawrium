"""Canonical Pi OpenRouter credential activation (#1038)."""

import json
import os
import subprocess
import sys

import pytest

from clawrium.core.pi import (
    render_bedrock_sso_config,
    render_bedrock_sso_environment,
)
from clawrium.core.lifecycle_canonical import (
    CanonicalSyncError,
    SSOAuthRequiredError,
    _sync_pi_openrouter,
    revoke_pi_openrouter,
    _pi_user_environment_operation,
    _verify_pi_bedrock_sso_readiness,
    _PI_BEDROCK_STS_IDENTITY_VALIDATOR,
    _PI_BEDROCK_STS_IDENTITY_VALIDATOR_PERL,
    _PI_BEDROCK_AWS_PATH_VALIDATOR_PERL,
    _PI_BEDROCK_AWS_PATH_VALIDATOR_PYTHON,
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
    assert writes == [
        {
            "agent_name": "pi-demo",
            "path": "/home/pi-demo/.pi/agent/clawrium-aws-config",
            "body": None,
        },
        {
            "agent_name": "pi-demo",
            "path": "/home/pi-demo/.pi/agent/clawrium-aws-credentials",
            "body": None,
        },
        {
            "agent_name": "pi-demo",
            "path": "/home/pi-demo/.pi/agent/clawrium-provider.env",
            "body": "OPENROUTER_API_KEY=private-key\n",
        },
    ]
    assert "private-key" not in client.commands[0][0]


def test_bedrock_to_codex_sync_clears_aws_state_before_codex_activation(monkeypatch):
    client = _Client()
    events = []
    operations = []
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key",
        lambda _: pytest.fail("Codex OAuth must never read a controller credential"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_remote_ownership",
        lambda *_args, **_kwargs: events.append("ownership"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._clear_pi_bedrock_aws_caches",
        lambda *_args, **_kwargs: events.append("cache-cleanup"),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda _client, **kwargs: operations.append(kwargs),
    )

    result = _sync_pi_openrouter(
        agent_name="pi-demo",
        host={"hostname": "wolf-i", "os_family": "linux"},
        claw_record={"providers": ["codex"]},
        workspace_only=False,
        dry_run=False,
        on_event=lambda phase, message: events.append((phase, message)),
    )

    assert result.files_written == ()
    assert events[:2] == ["ownership", "cache-cleanup"]
    assert [entry["path"].rsplit("/", 1)[-1] for entry in operations] == [
        "clawrium-aws-config",
        "clawrium-aws-credentials",
        "clawrium-provider.env",
    ]
    assert all(entry["body"] is None for entry in operations)
    assert all(not entry["path"].endswith("auth.json") for entry in operations)
    assert events[-1][0] == "sync"
    assert client.closed is True


def test_bedrock_to_codex_cache_cleanup_failure_prevents_activation(monkeypatch):
    client = _Client()
    operations = []
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openai-codex", "default_model": "gpt-5.1-codex-mini"},
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._clear_pi_bedrock_aws_caches",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            CanonicalSyncError("could not remove Pi provider activation")
        ),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda _client, **kwargs: operations.append(kwargs),
    )

    with pytest.raises(CanonicalSyncError, match="could not remove Pi provider activation"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": ["codex"]},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )

    assert operations == []
    assert client.closed is True


def test_canonical_pi_sync_stops_before_activation_when_aws_removal_fails(monkeypatch):
    client = _Client()
    operations = []
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.providers.storage.get_provider",
        lambda _: {"type": "openrouter", "default_model": "openai/gpt-4o"},
    )
    monkeypatch.setattr(
        "clawrium.core.providers.get_provider_api_key", lambda _: "private-key"
    )

    def fail_aws_config_removal(_client, **kwargs):
        operations.append(kwargs)
        raise CanonicalSyncError("AWS config removal failed")

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        fail_aws_config_removal,
    )

    with pytest.raises(CanonicalSyncError, match="AWS config removal failed"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": ["router"]},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )

    assert operations == [
        {
            "agent_name": "pi-demo",
            "path": "/home/pi-demo/.pi/agent/clawrium-aws-config",
            "body": None,
        }
    ]
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


@pytest.mark.parametrize(
    ("os_family", "root"),
    [("linux", "/home"), ("darwin", "/Users")],
)
def test_pi_revocation_removes_all_agent_scoped_provider_files(
    monkeypatch, os_family, root
):
    client = _Client()
    client.exec_command = lambda command, timeout: (
        None,
        type("O", (), {"channel": type("C", (), {"recv_exit_status": lambda self: 0})()})(),
        None,
    )
    removals = []
    monkeypatch.setattr("clawrium.core.lifecycle_canonical._open_ssh", lambda _: client)
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda _client, **kwargs: removals.append(kwargs),
    )

    revoke_pi_openrouter(
        agent_name="pi-demo",
        host={"hostname": "wolf-i", "os_family": os_family},
    )

    assert removals == [
        {
            "agent_name": "pi-demo",
            "path": f"{root}/pi-demo/.pi/agent/clawrium-provider.env",
            "body": None,
        },
        {
            "agent_name": "pi-demo",
            "path": f"{root}/pi-demo/.pi/agent/clawrium-aws-config",
            "body": None,
        },
        {
            "agent_name": "pi-demo",
            "path": f"{root}/pi-demo/.pi/agent/clawrium-aws-credentials",
            "body": None,
        },
    ]
    assert client.closed is True


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
    with pytest.raises(
        CanonicalSyncError,
        match="clean Pi Bedrock AWS cache while revoking Bedrock credentials",
    ):
        revoke_pi_openrouter(
            agent_name="pi-demo", host={"hostname": "wolf-i", "os_family": "linux"}
        )
    assert client.closed


@pytest.mark.parametrize(
    ("host_os_family", "os_family", "root"),
    [("linux", "linux", "/home"), ("macos", "darwin", "/Users")],
)
def test_canonical_pi_sync_provisions_only_agent_scoped_sso_configuration(
    monkeypatch, host_os_family, os_family, root
):
    client = _Client()
    events = []
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
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda _client, **kwargs: events.append(("write", kwargs)),
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_bedrock_sso_readiness",
        lambda readiness_client, **kwargs: events.append(
            ("readiness", readiness_client, kwargs)
        ),
    )

    result = _sync_pi_openrouter(
        agent_name="pi-demo",
        host={"hostname": "wolf-i", "os_family": host_os_family},
        claw_record={"providers": ["bedrock"]},
        workspace_only=False,
        dry_run=False,
        on_event=None,
    )

    assert result.files_written == (
        ".pi/agent/clawrium-provider.env",
        ".pi/agent/clawrium-aws-config",
        ".pi/agent/clawrium-aws-credentials",
    )
    assert events == [
        (
            "write",
            {
                "agent_name": "pi-demo",
                "path": f"{root}/pi-demo/.pi/agent/clawrium-provider.env",
                "body": render_bedrock_sso_environment(
                    provider["aws_profile"], provider["region"]
                ),
            },
        ),
        (
            "write",
            {
                "agent_name": "pi-demo",
                "path": f"{root}/pi-demo/.pi/agent/clawrium-aws-config",
                "body": render_bedrock_sso_config(provider),
            },
        ),
        (
            "write",
            {
                "agent_name": "pi-demo",
                "path": f"{root}/pi-demo/.pi/agent/clawrium-aws-credentials",
                "body": "",
            },
        ),
        (
            "readiness",
            client,
            {
                "agent_name": "pi-demo",
                "profile": provider["aws_profile"],
                "region": provider["region"],
                "config_path": f"{root}/pi-demo/.pi/agent/clawrium-aws-config",
                "credentials_path": f"{root}/pi-demo/.pi/agent/clawrium-aws-credentials",
                "account_id": provider["sso_account_id"],
                "role_name": provider["sso_role_name"],
                "os_family": os_family,
            },
        ),
    ]


def test_canonical_pi_sync_propagates_bedrock_sso_readiness_failure(monkeypatch):
    client = _Client()
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
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._pi_user_environment_operation",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical._verify_pi_bedrock_sso_readiness",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            SSOAuthRequiredError("SSO_AUTH_REQUIRED")
        ),
    )

    with pytest.raises(SSOAuthRequiredError, match="SSO_AUTH_REQUIRED"):
        _sync_pi_openrouter(
            agent_name="pi-demo",
            host={"hostname": "wolf-i", "os_family": "linux"},
            claw_record={"providers": ["bedrock"]},
            workspace_only=False,
            dry_run=False,
            on_event=None,
        )

    assert client.closed is True


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


def test_pi_bedrock_path_validators_accept_production_root_and_reject_untrusted_path():
    """Default ``/`` root must not turn trusted paths into ``//`` prefixes."""
    expected_uid = str(os.stat("/").st_uid)
    validators = (
        [sys.executable, "-c", _PI_BEDROCK_AWS_PATH_VALIDATOR_PYTHON],
        ["/usr/bin/perl", "-e", _PI_BEDROCK_AWS_PATH_VALIDATOR_PERL],
    )
    for validator in validators:
        assert subprocess.run(
            validator + ["/usr/bin/dash", expected_uid, "0", "/"], check=False
        ).returncode == 0
        assert subprocess.run(
            validator + ["/tmp", expected_uid, "0", "/"], check=False
        ).returncode != 0


def test_pi_bedrock_probe_stdout_drives_sanitized_auth_required_recovery(tmp_path):
    """The probe emits its trusted CLI path before an expired-SSO failure."""
    root = tmp_path / "trusted"
    candidate = root / "usr" / "local" / "bin" / "aws"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "#!/bin/sh\n"
        "if test \"$1\" = --version; then echo aws-cli/2.15.0; "
        "else echo '{}' ; exit 1; fi\n"
    )
    candidate.chmod(0o555)
    for directory in (root, root / "usr", root / "usr" / "local", candidate.parent):
        directory.chmod(0o555)
    probe = _build_pi_bedrock_sso_readiness_probe(
        account_id="123456789012", role_name="BedrockPiRole", os_family="linux",
        candidates=(str(candidate),), expected_uid=os.getuid(), trusted_root=str(root),
    )
    result = subprocess.run(["/bin/bash", "-c", probe], text=True, capture_output=True)
    assert result.returncode != 0
    assert result.stdout == f"{candidate}\n"

    client = _Client()
    client.exec_command = lambda command, timeout: (
        None,
        type("O", (), {
            "channel": type("C", (), {"recv_exit_status": lambda self: 1})(),
            "read": lambda self: result.stdout.encode(),
        })(),
        None,
    )
    with pytest.raises(SSOAuthRequiredError) as exc_info:
        _verify_pi_bedrock_sso_readiness(
            client, agent_name="pi-demo", profile="pi-bedrock", region="us-east-1",
            config_path="/home/pi-demo/.pi/agent/clawrium-aws-config",
            credentials_path="/home/pi-demo/.pi/agent/clawrium-aws-credentials",
            account_id="123456789012", role_name="BedrockPiRole",
        )
    assert f"{candidate} sso login --profile pi-bedrock" in str(exc_info.value)


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


@pytest.mark.parametrize("aws_cli", ["/usr/bin/aws", "/usr/local/bin/aws", "/opt/homebrew/bin/aws"])
def test_pi_bedrock_readiness_is_actionable_when_identity_is_unavailable(aws_cli):
    client = _Client()
    client.exec_command = lambda command, timeout: (
        None,
        type(
            "O",
            (),
            {
                "channel": type("C", (), {"recv_exit_status": lambda self: 1})(),
                "read": lambda self: f"{aws_cli}\n".encode(),
            },
        )(),
        None,
    )
    with pytest.raises(SSOAuthRequiredError, match="SSO_AUTH_REQUIRED") as exc_info:
        _verify_pi_bedrock_sso_readiness(
            client,
            agent_name="pi-demo",
            profile="pi-bedrock",
            region="us-east-1",
            config_path="/home/pi-demo/.pi/agent/clawrium-aws-config",
            credentials_path="/home/pi-demo/.pi/agent/clawrium-aws-credentials",
            account_id="123456789012",
            role_name="BedrockPiRole",
        )
    message = str(exc_info.value)
    assert "sudo -n -u pi-demo -- env -i" in message
    assert "HOME=/home/pi-demo" in message
    assert "AWS_CONFIG_FILE=/home/pi-demo/.pi/agent/clawrium-aws-config" in message
    assert "AWS_SHARED_CREDENTIALS_FILE=/home/pi-demo/.pi/agent/clawrium-aws-credentials" in message
    assert f"{aws_cli} sso login --profile pi-bedrock" in message
    assert "clawctl agent sync pi-demo" in message


def test_pi_bedrock_readiness_sanitizes_recovery_display_values():
    client = _Client()
    client.exec_command = lambda command, timeout: (
        None,
        type(
            "O",
            (),
            {
                "channel": type("C", (), {"recv_exit_status": lambda self: 1})(),
                "read": lambda self: b"/usr/local/bin/aws\n",
            },
        )(),
        None,
    )
    profile = "pi\u202ebedrock"
    agent_name = "pi\u202edemo"
    region = "us\u2066-east-1\u200b"
    with pytest.raises(CanonicalSyncError) as exc_info:
        _verify_pi_bedrock_sso_readiness(
            client,
            agent_name=agent_name,
            profile=profile,
            region=region,
            config_path="/home/pi-demo/.pi/agent/clawrium-aws-config",
            credentials_path="/home/pi-demo/.pi/agent/clawrium-aws-credentials",
            account_id="123456789012",
            role_name="BedrockPiRole",
        )
    message = str(exc_info.value)
    assert "\u202e" not in message
    assert "\u2066" not in message
    assert "\u200b" not in message
    assert "pibedrock" in message
    assert "pidemo" in message
    assert "us-east-1" in message


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
