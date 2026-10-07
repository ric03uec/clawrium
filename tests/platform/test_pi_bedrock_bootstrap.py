"""Executable provider-environment isolation tests for Pi transport bootstraps."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2.nativetypes import NativeEnvironment


PLAYBOOK_ROOT = Path("src/clawrium/platform/registry/pi/playbooks")
PLAYBOOKS = (
    ("chat.yaml", "pi_chat_capture_bootstrap", "chat"),
    ("chat_macos.yaml", "pi_chat_capture_bootstrap", "chat"),
    ("exec.yaml", "pi_exec_capture_bootstrap", "exec"),
    ("exec_macos.yaml", "pi_exec_capture_bootstrap", "exec"),
)
EXEC_PLAYBOOKS = tuple(playbook for playbook in PLAYBOOKS if playbook[2] == "exec")
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
    "HTTP_PROXY": "http://inherited-http-proxy-sentinel",
    "HTTPS_PROXY": "http://inherited-https-proxy-sentinel",
    "ALL_PROXY": "http://inherited-all-proxy-sentinel",
    "NO_PROXY": "inherited-no-proxy-sentinel",
    "http_proxy": "http://inherited-http-proxy-lower-sentinel",
    "https_proxy": "http://inherited-https-proxy-lower-sentinel",
    "all_proxy": "http://inherited-all-proxy-lower-sentinel",
    "no_proxy": "inherited-no-proxy-lower-sentinel",
    "PI_CODING_AGENT_DIR": "/inherited-pi-coding-agent-dir-sentinel",
}


def _playbook_var(filename: str, variable: str) -> str:
    playbook = yaml.safe_load((PLAYBOOK_ROOT / filename).read_text())
    return playbook[0]["vars"][variable]


def _bootstrap(filename: str, variable: str) -> str:
    bootstrap = _playbook_var(filename, variable)
    # The Darwin playbooks use BSD stat. Exercise their production bootstrap
    # unchanged on macOS; use GNU stat only to make its positive contract
    # executable in the Linux CI environment too.
    if filename.endswith("_macos.yaml") and platform.system() != "Darwin":
        bootstrap = bootstrap.replace("/usr/bin/stat -f %Lp", "/usr/bin/stat -c %a")
        bootstrap = bootstrap.replace("/usr/bin/base64 -D", "/usr/bin/base64 -d")
    return bootstrap


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_capture_program_digest_pin_matches_canonical_source(
    filename: str, variable: str, kind: str
) -> None:
    """The bootstrap pin is independent from and matches its canonical Perl source."""
    capture_program = _playbook_var(filename, f"pi_{kind}_capture_program")
    digest = hashlib.sha256(capture_program.encode()).hexdigest()
    bootstrap = _bootstrap(filename, variable)

    assert f'test "$program_digest" = {digest} || exit 126' in bootstrap
    assert "/usr/bin/openssl dgst -sha256" in bootstrap


def _render_task_argv(filename: str, task_name: str, overrides: dict[str, object]) -> list[str]:
    """Render the production command argv with forged Ansible extra-vars."""
    playbook = yaml.safe_load((PLAYBOOK_ROOT / filename).read_text())[0]
    task = next(item for item in playbook["tasks"] if item["name"] == task_name)
    rendered = NativeEnvironment().from_string(
        task["ansible.builtin.command"]["argv"]
    ).render(**overrides)
    assert isinstance(rendered, list)
    return rendered


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_command_task_pins_immutable_bootstrap_hash(
    filename: str, variable: str, kind: str
) -> None:
    """The command-task guard hashes against a literal, not an extra-var."""
    source = _playbook_var(filename, variable)
    digest = hashlib.sha256(source.encode()).hexdigest()
    playbook_text = (PLAYBOOK_ROOT / filename).read_text()
    assert f"expected={digest}; actual=" in playbook_text
    assert "pi_chat_capture_bootstrap" in playbook_text or "pi_exec_capture_bootstrap" in playbook_text


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
    provider_environment_mode: int = 0o600,
    provider_environment_symlink: bool = False,
    pi_arguments: list[str] | None = None,
    extra_pi_arguments: list[str] | None = None,
    pi_command: str | None = None,
    runner_program: str | None = None,
    capture_program: str | None = None,
    codex_auth_recovery: str | None = "false",
    mode: str = "inference",
    codex_auth: bool = False,
    codex_auth_mode: int = 0o600,
    codex_auth_symlink: bool = False,
) -> tuple[dict[str, str], subprocess.CompletedProcess[str]]:
    private_key, certificate = _certificate(tmp_path)
    home = tmp_path / "pi-home"
    agent_dir = home / ".pi" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    if provider_environment is not None:
        provider_env = agent_dir / "clawrium-provider.env"
        provider_env.write_text(provider_environment)
        provider_env.chmod(provider_environment_mode)
        if provider_environment_symlink:
            target = tmp_path / "redirected-provider.env"
            target.write_text(provider_environment)
            provider_env.unlink()
            provider_env.symlink_to(target)
    if codex_auth:
        auth = agent_dir / "auth.json"
        auth.write_text('{"auth": "dedicated"}\n')
        auth.chmod(codex_auth_mode)
        if codex_auth_symlink:
            target = tmp_path / "redirected-auth.json"
            target.write_text('{"auth": "redirected"}\n')
            auth.unlink()
            auth.symlink_to(target)
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to exercise hostile NODE_OPTIONS")
    bash_env_marker = tmp_path / "bash-env-ran"
    node_options_marker = tmp_path / "node-options-ran"
    bash_env = tmp_path / "hostile-bash-env"
    bash_env.write_text(f"/usr/bin/touch {bash_env_marker!s}\n")
    node_hook = tmp_path / "hostile-node-options.js"
    node_hook.write_text(
        "require('fs').writeFileSync(" + json.dumps(str(node_options_marker)) + ", 'ran')\n"
    )
    pi_binary = home / ".local" / "pi" / "bin" / "pi"
    pi_binary.parent.mkdir(parents=True)
    pi_invocation_marker = tmp_path / "pi-invoked"
    pi_binary.write_text(
        f"#!{node}\n"
        "require('fs').writeFileSync(" + json.dumps(str(pi_invocation_marker)) + ", 'ran');\n"
        "const payload = { environment: process.env, argv: process.argv.slice(2) };\n"
        "process.stdout.write(JSON.stringify(payload));\n"
    )
    pi_binary.chmod(0o700)
    command = [
        "/usr/bin/env",
        "-i",
        f"HOME={home}",
        "PATH=/usr/bin:/bin",
        "PI_DISABLE_AUTOUPDATE=1",
        "/bin/bash",
        "-c",
        _bootstrap(filename, variable),
        "clawrium-pi-bootstrap",
        capture_program or _playbook_var(filename, f"pi_{kind}_capture_program"),
        certificate,
    ]
    if codex_auth_recovery is not None:
        command.append(codex_auth_recovery)
    if kind == "exec":
        command.append(mode)
    if kind == "exec" and mode == "inference":
        command.extend(
            [
                "/usr/bin/perl",
                "-e",
                runner_program
                or _playbook_var(filename, "pi_exec_timeout_wrapper"),
                "120",
            ]
        )
    command.append(pi_command or str(pi_binary))
    if pi_arguments is not None:
        expected_argv = pi_arguments
    elif kind == "chat":
        expected_argv = [
            "--provider", provider, "--model", "test/model", "--print", "--no-tools",
            "--no-context-files", "--no-extensions", "--session-dir",
            ".pi/agent/clawrium-sessions/01234567-0123-4567-89ab-0123456789ab",
        ]
    elif mode == "inference":
        expected_argv = [
            "--provider", provider, "--model", "test/model", "--print", "--no-session",
            "--no-tools", "--no-context-files", "--no-extensions", "--no-skills",
            "--no-prompt-templates", "--no-themes",
        ]
    else:
        expected_argv = ["--version"]
    if extra_pi_arguments:
        expected_argv.extend(extra_pi_arguments)
    command.extend(expected_argv)
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HOME": str(home),
            "BASH_ENV": str(bash_env),
            "NODE_OPTIONS": f"--require {node_hook}",
            **HOSTILE_ENVIRONMENT,
        },
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
    pi_result = json.loads(result["stdout"])
    assert pi_result["argv"] == expected_argv
    assert pi_invocation_marker.exists()
    assert not bash_env_marker.exists()
    assert not node_options_marker.exists()
    return pi_result["environment"], completed


def _assert_no_hostile_values(
    environment: dict[str, str],
    completed: subprocess.CompletedProcess[str],
    allowed: set[str] | None = None,
) -> None:
    for name in (*HOSTILE_ENVIRONMENT, "BASH_ENV", "NODE_OPTIONS"):
        if allowed is None or name not in allowed:
            assert name not in environment
    assert not any(name.startswith("AWS_ENDPOINT_URL_") for name in environment)
    for sentinel in HOSTILE_ENVIRONMENT.values():
        assert sentinel not in completed.stdout
        assert sentinel not in completed.stderr


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_command_task_rejects_forged_bootstrap_before_agent_execution(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """An extra-var cannot replace the command task's literal hash guard."""
    home = tmp_path / "pi-home"
    marker = tmp_path / "forged-bootstrap-ran"
    forged = f"/usr/bin/touch {marker}; exit 0"
    certificate = "ignored-before-bootstrap-validation"
    if kind == "chat":
        task_name = "Run finite Pi chat command as dedicated agent user"
        overrides: dict[str, object] = {
            "pi_home": str(home), "pi_chat_timeout": 1,
            "pi_chat_capture_bootstrap": forged,
            "pi_chat_capture_program": _playbook_var(filename, "pi_chat_capture_program"),
            "pi_chat_timeout_wrapper": _playbook_var(filename, "pi_chat_timeout_wrapper") if filename.endswith("_macos.yaml") else "",
            "pi_chat_recipient_certificate": certificate,
            "pi_binary": str(home / ".local/pi/bin/pi"),
            "pi_chat_argv": ["--provider", "openrouter", "--model", "test/model", "--print", "--no-tools", "--no-context-files", "--no-extensions", "--session-dir", ".pi/agent/clawrium-sessions/01234567-0123-4567-89ab-0123456789ab"],
        }
    else:
        task_name = "Run encrypted Pi native command"
        overrides = {
            "pi_home": str(home), "pi_exec_mode": "diagnostic",
            "pi_exec_capture_bootstrap": forged,
            "pi_exec_capture_program": _playbook_var(filename, "pi_exec_capture_program"),
            "pi_exec_recipient_certificate": certificate,
            "pi_binary": str(home / ".local/pi/bin/pi"), "cmd_argv": ["--version"],
            "pi_exec_timeout_wrapper": _playbook_var(filename, "pi_exec_timeout_wrapper"),
            "pi_exec_timeout": 1,
        }
    completed = subprocess.run(
        _render_task_argv(filename, task_name, overrides), capture_output=True, text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, check=False,
    )
    assert completed.returncode == 126
    assert not marker.exists()


def test_pi_macos_chat_task_rejects_forged_timeout_wrapper_before_bootstrap(
    tmp_path: Path,
) -> None:
    """The Darwin timeout wrapper is pinned before Perl can evaluate it."""
    filename = "chat_macos.yaml"
    home = tmp_path / "pi-home"
    marker = tmp_path / "forged-timeout-ran"
    overrides: dict[str, object] = {
        "pi_home": str(home), "pi_chat_timeout": 1,
        "pi_chat_timeout_wrapper": f"system('/usr/bin/touch {marker}'); exit 0;",
        "pi_chat_capture_bootstrap": _playbook_var(filename, "pi_chat_capture_bootstrap"),
        "pi_chat_capture_program": _playbook_var(filename, "pi_chat_capture_program"),
        "pi_chat_recipient_certificate": "ignored", "pi_binary": str(home / ".local/pi/bin/pi"),
        "pi_chat_argv": ["--provider", "openrouter", "--model", "test/model", "--print", "--no-tools", "--no-context-files", "--no-extensions", "--session-dir", ".pi/agent/clawrium-sessions/01234567-0123-4567-89ab-0123456789ab"],
    }
    completed = subprocess.run(
        _render_task_argv(filename, "Run finite Pi chat command as dedicated agent user", overrides),
        capture_output=True, text=True, env={"HOME": str(home), "PATH": "/usr/bin:/bin"}, check=False,
    )
    assert completed.returncode == 126
    assert not marker.exists()


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_bedrock_bootstrap_uses_only_agent_local_aws_environment(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """Bedrock inference replaces hostile AWS discovery state with agent state."""
    agent_dir = tmp_path / "pi-home" / ".pi" / "agent"
    agent_dir.mkdir(parents=True)
    aws_config = agent_dir / "clawrium-aws-config"
    aws_config.write_text("[profile clawrium-bedrock]\nregion = us-west-2\n")
    aws_config.chmod(0o600)
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


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
@pytest.mark.parametrize(
    ("provider_environment_mode", "provider_environment_symlink"),
    [(0o644, False), (0o600, True)],
)
def test_pi_openrouter_bootstrap_rejects_untrusted_managed_provider_file(
    filename: str, variable: str, kind: str, provider_environment_mode: int,
    provider_environment_symlink: bool, tmp_path: Path,
) -> None:
    """Managed provider data must be a private regular account-owned file."""
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path, filename, variable, kind,
            provider_environment="OPENROUTER_API_KEY=managed-key\n", provider="openrouter",
            provider_environment_mode=provider_environment_mode,
            provider_environment_symlink=provider_environment_symlink,
        )
    assert exc_info.value.returncode == 126
    assert exc_info.value.stdout == ""
    assert not (tmp_path / "pi-invoked").exists()


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_codex_bootstrap_uses_only_private_dedicated_auth(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """Codex invokes Pi with the agent-owned auth document and no provider env."""
    environment, completed = _run_bootstrap(
        tmp_path,
        filename,
        variable,
        kind,
        provider_environment=None,
        provider="openai-codex",
        codex_auth=True,
    )

    assert "OPENROUTER_API_KEY" not in environment
    _assert_no_hostile_values(environment, completed)


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
@pytest.mark.parametrize("codex_auth_recovery", ["true", "forged", None])
def test_pi_codex_bootstrap_rejects_pending_or_missing_recovery_flag(
    filename: str,
    variable: str,
    kind: str,
    codex_auth_recovery: str | None,
    tmp_path: Path,
) -> None:
    """Only the controller's explicit false value permits Codex execution."""
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path, filename, variable, kind, provider_environment=None,
            provider="openai-codex", codex_auth=True,
            codex_auth_recovery=codex_auth_recovery,
        )
    assert exc_info.value.returncode == 126
    assert exc_info.value.stdout == ""
    assert not (tmp_path / "pi-invoked").exists()


@pytest.mark.parametrize(("filename", "variable", "kind"), EXEC_PLAYBOOKS)
def test_pi_exec_diagnostic_ignores_codex_recovery_flag(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """Credential-free diagnostics remain available while Codex is recovering."""
    environment, _ = _run_bootstrap(
        tmp_path, filename, variable, kind, provider_environment=None,
        mode="diagnostic", codex_auth_recovery="true",
    )
    assert "OPENROUTER_API_KEY" not in environment


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
@pytest.mark.parametrize(
    ("codex_auth_mode", "codex_auth_symlink"),
    [(0o644, False), (0o600, True)],
)
def test_pi_codex_bootstrap_rejects_untrusted_auth_before_pi_invocation(
    filename: str,
    variable: str,
    kind: str,
    codex_auth_mode: int,
    codex_auth_symlink: bool,
    tmp_path: Path,
) -> None:
    """Codex auth must be agent-owned regular mode-0600 before Pi starts."""
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path, filename, variable, kind, provider_environment=None,
            provider="openai-codex", codex_auth=True,
            codex_auth_mode=codex_auth_mode, codex_auth_symlink=codex_auth_symlink,
        )
    assert exc_info.value.returncode == 126
    assert exc_info.value.stdout == ""
    assert exc_info.value.stderr == ""
    assert not (tmp_path / "pi-invoked").exists()


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
@pytest.mark.parametrize(
    ("provider", "provider_environment"),
    [
        ("openrouter", None),
        (
            "amazon-bedrock",
            "AWS_PROFILE=clawrium-bedrock\n"
            "AWS_REGION=us-west-2\n"
            "AWS_CONFIG_FILE=$HOME/.pi/agent/clawrium-aws-config\n",
        ),
        ("openai-codex", None),
    ],
)
def test_pi_bootstrap_rejects_missing_provider_credential(
    filename: str,
    variable: str,
    kind: str,
    provider: str,
    provider_environment: str | None,
    tmp_path: Path,
) -> None:
    """A selected provider fails closed when its agent-local credential is absent."""
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path,
            filename,
            variable,
            kind,
            provider_environment=provider_environment,
            provider=provider,
        )
    assert exc_info.value.returncode == 126


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_bootstrap_rejects_untrusted_capture_program_before_provider_auth(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """A forged capture source cannot read auth or run before provider validation."""
    malicious_marker = tmp_path / "malicious-capture-ran"
    malicious_capture = (
        "BEGIN { open my $fh, '>', "
        + json.dumps(str(malicious_marker))
        + "; print {$fh} $ENV{HOME}; close $fh; "
        + "open my $auth, '<', $ENV{HOME} . '/.pi/agent/auth.json'; } print 'plaintext';"
    )

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path,
            filename,
            variable,
            kind,
            provider_environment="OPENROUTER_API_KEY=dummy-account-specific-key\n",
            provider="openrouter",
            capture_program=malicious_capture,
        )

    completed = exc_info.value
    assert completed.returncode == 126
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert not malicious_marker.exists()
    assert not (tmp_path / "pi-invoked").exists()


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_bootstrap_rejects_untrusted_pi_command_before_provider_auth(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """A forged Pi executable cannot run as the credential-owning agent user."""
    malicious_marker = tmp_path / "malicious-pi-ran"
    malicious_pi = tmp_path / "malicious-pi"
    malicious_pi.write_text(f"#!/bin/sh\n/usr/bin/touch {malicious_marker!s}\n")
    malicious_pi.chmod(0o700)

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path,
            filename,
            variable,
            kind,
            provider_environment="OPENROUTER_API_KEY=dummy-account-specific-key\n",
            provider="openrouter",
            pi_command=str(malicious_pi),
        )

    completed = exc_info.value
    assert completed.returncode == 126
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert not malicious_marker.exists()
    assert not (tmp_path / "pi-invoked").exists()


@pytest.mark.parametrize(("filename", "variable", "kind"), EXEC_PLAYBOOKS)
def test_pi_exec_bootstrap_rejects_untrusted_perl_before_provider_auth(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """A forged timeout Perl source is rejected before managed auth is loaded."""
    malicious_marker = tmp_path / "malicious-perl-ran"
    malicious_perl = (
        "BEGIN { open my $fh, '>', "
        + json.dumps(str(malicious_marker))
        + "; print {$fh} 'ran'; close $fh; } 1;"
    )

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path,
            filename,
            variable,
            kind,
            provider_environment="OPENROUTER_API_KEY=dummy-account-specific-key\n",
            provider="openrouter",
            runner_program=malicious_perl,
        )

    completed = exc_info.value
    assert completed.returncode == 126
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert not malicious_marker.exists()
    assert not (tmp_path / "pi-invoked").exists()


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
def test_pi_bootstrap_rejects_capability_flag_before_provider_auth(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """Forged extra CLI flags cannot enable discovery or tool capabilities."""
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path,
            filename,
            variable,
            kind,
            provider_environment="OPENROUTER_API_KEY=dummy-account-specific-key\n",
            provider="openrouter",
            extra_pi_arguments=["--tools"],
        )

    completed = exc_info.value
    assert completed.returncode == 126
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert not (tmp_path / "pi-invoked").exists()


MALFORMED_PROVIDER_ARGUMENTS = (
    (),
    ("--provider",),
    ("openrouter", "--provider"),
    ("--provider", "openrouter", "--provider", "amazon-bedrock"),
    ("--provider", "/tmp/unauthorized-pi"),
)


@pytest.mark.parametrize(("filename", "variable", "kind"), PLAYBOOKS)
@pytest.mark.parametrize("pi_arguments", MALFORMED_PROVIDER_ARGUMENTS)
def test_pi_bootstrap_rejects_malformed_or_extra_provider_before_pi_invocation(
    filename: str,
    variable: str,
    kind: str,
    pi_arguments: tuple[str, ...],
    tmp_path: Path,
) -> None:
    """Provider-shape failures emit no plaintext result and never invoke Pi."""
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_bootstrap(
            tmp_path,
            filename,
            variable,
            kind,
            provider_environment="OPENROUTER_API_KEY=managed-openrouter-key\n",
            pi_arguments=list(pi_arguments),
        )

    completed = exc_info.value
    assert completed.returncode == 126
    assert completed.stdout == ""
    assert completed.stderr == ""
    assert not (tmp_path / "pi-invoked").exists()
    assert not (tmp_path / "bash-env-ran").exists()
    assert not (tmp_path / "node-options-ran").exists()


@pytest.mark.parametrize(("filename", "variable", "kind"), EXEC_PLAYBOOKS)
def test_pi_exec_diagnostic_mode_intentionally_runs_in_isolated_environment(
    filename: str, variable: str, kind: str, tmp_path: Path
) -> None:
    """Diagnostics are credential-free and cannot expose host AWS endpoints."""
    environment, completed = _run_bootstrap(
        tmp_path, filename, variable, kind, provider_environment=None, mode="diagnostic"
    )

    _assert_no_hostile_values(environment, completed)
