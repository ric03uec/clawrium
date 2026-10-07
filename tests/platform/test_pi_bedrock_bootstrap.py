"""Executable provider-environment isolation tests for Pi transport bootstraps."""

from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


PLAYBOOK_ROOT = Path("src/clawrium/platform/registry/pi/playbooks")
PLAYBOOKS = (
    ("chat.yaml", "pi_chat_capture_bootstrap", "chat"),
    ("chat_macos.yaml", "pi_chat_capture_bootstrap", "chat"),
    ("exec.yaml", "pi_exec_capture_bootstrap", "exec"),
    ("exec_macos.yaml", "pi_exec_capture_bootstrap", "exec"),
)
EXEC_PLAYBOOKS = tuple(playbook for playbook in PLAYBOOKS if playbook[2] == "exec")
CAPTURE_PROGRAM = (
    "use strict; use warnings; use Encode qw(decode FB_DEFAULT); "
    "use JSON::PP qw(encode_json); sub read_text { my ($path) = @_; "
    "open my $fh, '<:raw', $path or return ''; local $/; my $raw = <$fh>; "
    "return decode('UTF-8', $raw // '', FB_DEFAULT); } "
    "my ($stdout_path, $stderr_path, $rc_raw) = @ARGV; "
    "print encode_json({ stdout => read_text($stdout_path), "
    "stderr => read_text($stderr_path), rc => int($rc_raw) });"
)
HOSTILE_ENVIRONMENT = {
    "OPENROUTER_API_KEY": "inherited-openrouter-sentinel",
    "AWS_ACCESS_KEY_ID": "inherited-access-key-sentinel",
    "AWS_SECRET_ACCESS_KEY": "inherited-secret-key-sentinel",
    "AWS_SESSION_TOKEN": "inherited-session-token-sentinel",
    "AWS_SECURITY_TOKEN": "inherited-security-token-sentinel",
    "AWS_BEARER_TOKEN_BEDROCK": "inherited-bearer-sentinel",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/inherited-container-sentinel",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI": "http://inherited-container-sentinel",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN": "inherited-container-auth-token-sentinel",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE": "/inherited-container-auth-token-sentinel",
    "AWS_WEB_IDENTITY_TOKEN_FILE": "/inherited-web-identity-sentinel",
    "AWS_ROLE_ARN": "arn:aws:iam::123456789012:role/inherited-sentinel",
    "AWS_ROLE_SESSION_NAME": "inherited-role-session-sentinel",
    "AWS_ROLE_SESSION_DURATION": "inherited-role-session-duration-sentinel",
    "AWS_SHARED_CREDENTIALS_FILE": "/inherited-credentials-sentinel",
    "AWS_PROFILE": "inherited-profile-sentinel",
    "AWS_DEFAULT_PROFILE": "inherited-default-profile-sentinel",
    "AWS_REGION": "inherited-region-sentinel",
    "AWS_DEFAULT_REGION": "inherited-default-region-sentinel",
    "AWS_CONFIG_FILE": "/inherited-config-sentinel",
    "AWS_SDK_LOAD_CONFIG": "inherited-sdk-load-config-sentinel",
    "AWS_CA_BUNDLE": "/inherited-ca-bundle-sentinel",
    "AWS_STS_REGIONAL_ENDPOINTS": "inherited-sts-regional-sentinel",
    "AWS_EC2_METADATA_SERVICE_ENDPOINT": "http://inherited-imds-sentinel",
    "AWS_EC2_METADATA_SERVICE_ENDPOINT_MODE": "inherited-imds-mode-sentinel",
    "AWS_USE_FIPS_ENDPOINT": "inherited-fips-sentinel",
    "AWS_USE_DUALSTACK_ENDPOINT": "inherited-dualstack-sentinel",
    "AWS_ENDPOINT_URL": "http://inherited-endpoint-sentinel",
    "AWS_ENDPOINT_URL_S3": "http://inherited-s3-endpoint-sentinel",
    "AWS_ENDPOINT_URL_BEDROCK_RUNTIME": "http://inherited-bedrock-endpoint-sentinel",
}


def _bootstrap(filename: str, variable: str) -> str:
    playbook = yaml.safe_load((PLAYBOOK_ROOT / filename).read_text())
    bootstrap = playbook[0]["vars"][variable]
    # The Darwin playbooks use BSD stat. Exercise their production bootstrap
    # unchanged on macOS; use GNU stat only to make its positive contract
    # executable in the Linux CI environment too.
    if filename.endswith("_macos.yaml") and platform.system() != "Darwin":
        bootstrap = bootstrap.replace("/usr/bin/stat -f %Lp", "/usr/bin/stat -c %a")
    return bootstrap


def _certificate(tmp_path: Path) -> tuple[Path, str]:
    openssl = shutil.which("openssl")
    if openssl is None:
        pytest.skip("openssl is required for Pi bootstrap tests")
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
            "-keyout",
            str(private_key),
            "-subj",
            "/CN=clawrium-pi-bootstrap",
            "-days",
            "1",
            "-out",
            str(certificate),
        ],
        check=True,
        capture_output=True,
    )
    return private_key, certificate.read_text()


def _run_bootstrap(
    tmp_path: Path,
    filename: str,
    variable: str,
    kind: str,
    provider_environment: str | None,
    provider: str | None = None,
    mode: str = "inference",
) -> tuple[dict[str, str], subprocess.CompletedProcess[str]]:
    private_key, certificate = _certificate(tmp_path)
    home = tmp_path / "pi-home"
    agent_dir = home / ".pi" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    if provider_environment is not None:
        (agent_dir / "clawrium-provider.env").write_text(provider_environment)
    pi_binary = tmp_path / "pi"
    pi_binary.write_text("#!/bin/sh\nexec /usr/bin/env\n")
    pi_binary.chmod(0o700)
    command = [
        "/bin/bash",
        "-c",
        _bootstrap(filename, variable),
        "clawrium-pi-bootstrap",
        CAPTURE_PROGRAM,
        certificate,
    ]
    if kind == "exec":
        command.extend(
            [
                mode,
                "/usr/bin/perl",
                "-e",
                "shift @ARGV; exec @ARGV",
                "120",
            ]
        )
    command.append(str(pi_binary))
    if provider is not None:
        command.extend(["--provider", provider])
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "HOME": str(home), **HOSTILE_ENVIRONMENT},
    )
    decrypted = subprocess.run(
        [
            shutil.which("openssl") or "/usr/bin/openssl",
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
    result = json.loads(decrypted)
    assert result["stderr"] == ""
    assert result["rc"] == 0
    return (
        dict(line.split("=", 1) for line in result["stdout"].splitlines()),
        completed,
    )


def _assert_no_hostile_values(
    environment: dict[str, str],
    completed: subprocess.CompletedProcess[str],
    allowed: set[str] | None = None,
) -> None:
    for name in HOSTILE_ENVIRONMENT:
        if allowed is None or name not in allowed:
            assert name not in environment
    assert not any(name.startswith("AWS_ENDPOINT_URL_") for name in environment)
    for sentinel in HOSTILE_ENVIRONMENT.values():
        assert sentinel not in completed.stdout
        assert sentinel not in completed.stderr


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_bedrock_bootstrap_uses_only_agent_local_aws_environment(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """Bedrock inference replaces hostile AWS discovery state with agent state."""
    agent_dir = tmp_path / "pi-home" / ".pi" / "agent"
    agent_dir.mkdir(parents=True)
    aws_config = agent_dir / "clawrium-aws-config"
    aws_config.write_text("[profile clawrium-bedrock]\nregion = us-west-2\n")
    credentials = agent_dir / "clawrium-aws-credentials"
    credentials.touch()
    credentials.chmod(0o600)
    environment, completed = _run_bootstrap(
        tmp_path,
        filename,
        variable,
        kind,
        "AWS_PROFILE=clawrium-bedrock\n"
        "AWS_REGION=us-west-2\n"
        "AWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n",
        provider="amazon-bedrock",
    )

    assert environment["AWS_PROFILE"] == "clawrium-bedrock"
    assert environment["AWS_REGION"] == "us-west-2"
    assert environment["AWS_CONFIG_FILE"] == str(aws_config)
    assert environment["AWS_SHARED_CREDENTIALS_FILE"] == str(credentials)
    assert credentials.stat().st_mode & 0o777 == 0o600
    assert credentials.read_text() == ""
    _assert_no_hostile_values(
        environment,
        completed,
        {"AWS_PROFILE", "AWS_REGION", "AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"},
    )


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_openrouter_bootstrap_uses_only_managed_provider_credential(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """OpenRouter inference restores only its managed key after sanitization."""
    environment, completed = _run_bootstrap(
        tmp_path,
        filename,
        variable,
        kind,
        "OPENROUTER_API_KEY=managed-openrouter-key\n",
        provider="openrouter",
    )

    assert environment["OPENROUTER_API_KEY"] == "managed-openrouter-key"
    for name in HOSTILE_ENVIRONMENT:
        if name != "OPENROUTER_API_KEY":
            assert name not in environment
    assert not any(name.startswith("AWS_ENDPOINT_URL_") for name in environment)
    for sentinel in HOSTILE_ENVIRONMENT.values():
        assert sentinel not in completed.stdout
        assert sentinel not in completed.stderr


@pytest.mark.parametrize(("filename", "variable", "kind"), EXEC_PLAYBOOKS)
def test_pi_exec_diagnostic_mode_intentionally_runs_in_isolated_environment(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """Diagnostics are credential-free and cannot expose host AWS endpoints."""
    environment, completed = _run_bootstrap(
        tmp_path, filename, variable, kind, provider_environment=None, mode="diagnostic"
    )

    _assert_no_hostile_values(environment, completed)
