"""Private, refresh-safe Codex OAuth activation contracts (#1036)."""

from __future__ import annotations

import getpass
import grp
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from clawrium.core import codex_credentials
from clawrium.core import lifecycle
from clawrium.core import lifecycle_canonical
from clawrium.core.render import render_codex_oauth_credentials
from clawrium.core.secrets import get_instance_key, get_instance_secrets, replace_instance_secret


def _document(access: str = "access-test-token") -> str:
    return json.dumps(
        {
            "auth_mode": "chatgpt",
            "tokens": {
                "access_token": access,
                "refresh_token": "refresh-test-token",
                "id_token": "id-test-token",
            },
        }
    )


def _seed(config_dir: Path) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "hosts.json").write_text(
        json.dumps([
            {"hostname": "codex-host", "key_id": "codex-key", "agents": {
                "codex-agent": {"type": "codex", "agent_name": "codex-agent", "config": {}}
            }}
        ])
    )


def test_activation_display_error_allowlists_only_fixed_operational_messages():
    assert codex_credentials.codex_oauth_activation_error_for_display("SSH key not found") == "SSH key not found"
    assert (
        codex_credentials.codex_oauth_activation_error_for_display("access-test-token")
        == "credential activation failed; re-attach the codex-oauth provider"
    )


def test_renderer_normalizes_native_document_without_secret_passthrough():
    body = render_codex_oauth_credentials(_document())
    assert json.loads(body)["auth_mode"] == "chatgpt"
    assert "access-test-token" in body  # private renderer; callers must not diff it


def test_activation_playbooks_preserve_refreshes_and_secure_auth_files():
    root = Path(__file__).parents[2] / "src/clawrium/platform/registry/codex/playbooks"
    for name, home in (
        ("configure.yaml", "/home/{{ agent_name }}"),
        ("configure_macos.yaml", "/Users/{{ agent_name }}"),
    ):
        playbook = yaml.safe_load((root / name).read_text())[0]
        tasks = playbook["tasks"]
        serialized = (root / name).read_text()
        assert f'path: "{home}/.codex/auth.json"' in serialized
        assert "mode: \"0600\"" in serialized
        assert "no_log: true" in serialized
        assert "Validate existing native Codex auth document without following links" in serialized
        assert f'src: "{home}/.codex/auth.json"' not in serialized
        assert "os.O_NOFOLLOW" in serialized
        assert "os.fstat" in serialized
        assert "Refuse interrupted Codex activation without a committed receipt" in serialized
        assert "(codex_remote_auth_valid.rc | default(1)) != 0" in serialized
        assert "(codex_remote_auth_valid.rc | default(1)) == 0" in serialized
        assert "owner:" not in serialized
        assert "group:" not in serialized
        assert "Create private Codex home as the dedicated agent" in serialized
        assert "ansible_user_dir" not in serialized
        assert "follow: false" in serialized
        assert "codex_remote_auth.stat" not in serialized
        assert '"{{ ansible_python.executable }}"' in serialized
        validation_task = next(
            task for task in tasks
            if task["name"] == "Validate existing native Codex auth document without following links"
        )
        assert validation_task["become_user"] == "{{ agent_name }}"
        if name.endswith("macos.yaml"):
            assert tasks[0]["name"].startswith("Refuse to run on non-Darwin")


@pytest.mark.parametrize(
    ("playbook_name", "home_template", "is_macos"),
    [
        ("configure.yaml", "/home/{{ agent_name }}", False),
        ("configure_macos.yaml", "/Users/{{ agent_name }}", True),
    ],
)
def test_activation_playbook_executes_replace_preserve_and_restore(
    tmp_path: Path, playbook_name: str, home_template: str, is_macos: bool
):
    """Execute each production task flow against a hermetic local home.

    The copied playbook changes only its home root, host OS dispatcher guard,
    ownership group, and privilege escalation so the actual Ansible conditions,
    no-follow validation, copy atomicity, and permission handling execute
    without touching a developer's native Codex credentials.
    """
    ansible_playbook = shutil.which("ansible-playbook")
    if ansible_playbook is None:
        pytest.skip("ansible-playbook is not installed")

    agent_name = getpass.getuser()
    if (
        not agent_name
        or not agent_name.replace("_", "a").replace("-", "a").isalnum()
        or not agent_name[0].isalpha()
    ):
        pytest.skip("current user cannot be represented as an agent name")

    source = (
        Path(__file__).parents[2]
        / "src/clawrium/platform/registry/codex/playbooks"
        / playbook_name
    )
    sandbox_home = tmp_path / "homes"
    playbook = tmp_path / playbook_name
    source_text = (
        source.read_text()
        .replace(home_template, f"{sandbox_home}/{{{{ agent_name }}}}")
        .replace("  become: yes\n", "  become: no\n")
        .replace('group: "{{ agent_name }}"', f'group: "{grp.getgrgid(os.getgid()).gr_name}"')
    )
    if is_macos:
        source_text = (
            source_text.replace("when: ansible_os_family != \"Darwin\"", "when: false")
            .replace("group: staff", f'group: "{grp.getgrgid(os.getgid()).gr_name}"')
        )
    playbook.write_text(source_text)
    inventory = tmp_path / "inventory"
    inventory.write_text("localhost ansible_connection=local ansible_become=false\n")
    selected = render_codex_oauth_credentials(_document("selected-access"))
    refreshed = render_codex_oauth_credentials(_document("refreshed-access"))

    def run(
        *, replace: bool, expected_returncode: int = 0,
        activation_id: str = "pending:0123456789abcdef0123456789abcdef",
    ) -> str:
        variables = tmp_path / "variables.json"
        variables.write_text(json.dumps({
            "agent_name": agent_name,
            "codex_oauth_credentials": selected,
            "codex_activation_fingerprint": hashlib.sha256(selected.encode()).hexdigest(),
            "codex_activation_id": activation_id if replace else "",
            "codex_replace_auth": replace,
        }))
        result = subprocess.run(
            [ansible_playbook, "-i", str(inventory), str(playbook), "--extra-vars", f"@{variables}"],
            check=False, capture_output=True, text=True,
        )
        assert result.returncode == expected_returncode, result.stderr
        assert "selected-access" not in result.stdout + result.stderr
        assert "refreshed-access" not in result.stdout + result.stderr
        return result.stdout

    run(replace=True)
    auth_path = sandbox_home / agent_name / ".codex" / "auth.json"
    assert auth_path.read_text() == selected
    assert auth_path.stat().st_mode & 0o777 == 0o600

    auth_path.write_text(refreshed)
    run(replace=False)
    assert auth_path.read_text() == refreshed
    assert auth_path.stat().st_mode & 0o777 == 0o600

    # A failed local marker clear leaves replacement requested. The completed
    # receipt proves the selected snapshot once reached auth.json, so a later
    # refresh remains intact instead of being rolled back by routine sync.
    run(replace=True)
    assert auth_path.read_text() == refreshed

    receipt_path = auth_path.with_name(".clawrium-oauth-fingerprint")
    # A pending receipt is never treated as proof that auth.json received the
    # selected generation. Whether the interruption was before or after that
    # write, retry fails closed and requires explicit re-attach.
    auth_path.write_text(selected)
    receipt_path.write_text("pending:0123456789abcdef0123456789abcdef\n")
    run(replace=True, expected_returncode=2)
    assert auth_path.read_text() == selected

    auth_path.write_text(refreshed)
    receipt_path.write_text("pending:0123456789abcdef0123456789abcdef\n")
    run(replace=True, expected_returncode=2)
    assert auth_path.read_text() == refreshed

    # A fresh attachment ID cannot bypass an interrupted receipt: it may
    # overwrite a refresh that occurred after the interrupted auth write.
    new_activation_id = "pending:fedcba9876543210fedcba9876543210"
    run(replace=True, activation_id=new_activation_id, expected_returncode=2)
    assert auth_path.read_text() == refreshed

    # Operator recovery starts only after inspecting the valid on-host auth
    # document and intentionally removing the non-secret interrupted receipt.
    receipt_path.unlink()
    run(replace=True, activation_id=new_activation_id)
    assert auth_path.read_text() == selected
    assert receipt_path.read_text().startswith(f"complete:{new_activation_id}:")

    auth_path.write_text("not-json\n")
    run(replace=False)
    assert auth_path.read_text() == selected
    assert auth_path.stat().st_mode & 0o777 == 0o600

    symlink_target = tmp_path / "outside-auth.json"
    symlink_target.write_text(refreshed)
    auth_path.unlink()
    auth_path.symlink_to(symlink_target)
    run(replace=False)
    assert not auth_path.is_symlink()
    assert auth_path.read_text() == selected
    assert symlink_target.read_text() == refreshed


def test_activation_reconciles_before_read_and_consumes_explicit_replacement(
    isolated_config: Path, monkeypatch
):
    _seed(isolated_config)
    codex_credentials.configure_codex_oauth("codex-agent", document=_document())
    key = get_instance_key("codex-key", "codex", "codex-agent")
    replace_instance_secret(
        key, codex_credentials.CODEX_OAUTH_PENDING_ACTIVATION,
        "pending:0123456789abcdef0123456789abcdef",
    )
    calls: list[str] = []

    def reconcile(**_kwargs):
        calls.append("reconcile")

    def get_document(_agent: str) -> str:
        assert calls == ["reconcile"]
        return _document()

    captured: dict = {}
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.provider._reconcile_codex_oauth_transaction", reconcile
    )
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _key: Path("/key"))
    monkeypatch.setattr(
        "clawrium.core.playbook_resolver.resolve_agent_playbook", lambda *_args: Path("configure.yaml")
    )
    monkeypatch.setattr(codex_credentials, "get_codex_oauth_document", get_document)

    def run(**kwargs):
        captured.update(kwargs["inventory"]["all"]["vars"])
        return SimpleNamespace(status="successful")

    monkeypatch.setattr(lifecycle.ansible_runner, "run", run)
    cleanup_paths: list[Path] = []

    def retrying_rmtree(path: Path) -> None:
        cleanup_paths.append(path)
        if len(cleanup_paths) == 1:
            raise OSError("transient cleanup failure")
        shutil.rmtree(path)

    monkeypatch.setattr(lifecycle, "shutil", SimpleNamespace(rmtree=retrying_rmtree))
    ok, error = lifecycle._configure_codex_credentials(
        hostname="codex-host", host={"hostname": "codex-host", "key_id": "codex-key"},
        agent_key="codex-agent", unix_agent_name="codex-agent", config_data={}, extra_vars=None,
    )
    assert (ok, error) == (True, None)
    assert captured["codex_replace_auth"] is True
    assert captured["codex_activation_id"] == "pending:0123456789abcdef0123456789abcdef"
    assert captured["codex_activation_fingerprint"] == hashlib.sha256(
        captured["codex_oauth_credentials"].encode()
    ).hexdigest()
    assert len(cleanup_paths) == 2
    assert cleanup_paths[0] == cleanup_paths[1]
    assert not cleanup_paths[0].exists()
    assert codex_credentials.CODEX_OAUTH_PENDING_ACTIVATION not in get_instance_secrets(key)


def test_legacy_sync_routes_codex_to_canonical_activation(monkeypatch):
    host = {"hostname": "codex-host"}
    record = {"type": "codex", "agent_name": "codex-agent", "config": {}}
    calls: list[dict] = []
    monkeypatch.setattr(lifecycle, "get_host", lambda _hostname: host)
    monkeypatch.setattr(
        lifecycle, "_resolve_agent_record", lambda *_args, **_kwargs: ("codex-agent", "codex", record)
    )

    class Result:
        success = True
        agent = "codex-agent"
        host = "codex-host"
        error = None

    def canonical(*args, **kwargs):
        calls.append({"args": args, **kwargs})
        return Result()

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", canonical)
    result = lifecycle.sync_agent("codex-host", "codex", agent_name="codex-agent")
    assert result["success"] is True
    assert calls == [{
        "args": ("codex-agent",), "agent_key": "codex-agent", "restart": False,
        "verify": False, "push_workspace": False, "workspace_only": False,
        "on_event": None,
    }]


def test_legacy_sync_uses_record_key_for_pending_activation_reconciliation(
    isolated_config: Path, monkeypatch
):
    unix_agent_name = "codex-unix"
    record_key = "fleet-codex"
    host = {
        "hostname": "codex-host", "key_id": "codex-key", "agents": {
            record_key: {"type": "codex", "agent_name": unix_agent_name, "config": {}}
        },
    }
    isolated_config.mkdir(parents=True, exist_ok=True)
    (isolated_config / "hosts.json").write_text(json.dumps([host]))
    codex_credentials.configure_codex_oauth(unix_agent_name, document=_document())
    secret_key = get_instance_key("codex-key", "codex", unix_agent_name)
    replace_instance_secret(
        secret_key, codex_credentials.CODEX_OAUTH_PENDING_ACTIVATION,
        "pending:0123456789abcdef0123456789abcdef",
    )
    reconcile_calls: list[dict] = []
    captured: dict = {}
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.provider._reconcile_codex_oauth_transaction",
        lambda **kwargs: reconcile_calls.append(kwargs),
    )
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _key: Path("/key"))
    monkeypatch.setattr(
        "clawrium.core.playbook_resolver.resolve_agent_playbook", lambda *_args: Path("configure.yaml")
    )
    monkeypatch.setattr(
        lifecycle.ansible_runner, "run",
        lambda **kwargs: (
            captured.update(kwargs["inventory"]["all"]["vars"])
            or SimpleNamespace(status="successful")
        ),
    )

    result = lifecycle.sync_agent("codex-host", "codex", agent_name=record_key)

    assert result["success"] is True
    assert len(reconcile_calls) == 1
    assert reconcile_calls[0]["agent_key"] == record_key
    assert reconcile_calls[0]["agent"] == unix_agent_name
    assert captured["agent_name"] == unix_agent_name
    assert captured["codex_replace_auth"] is True
    assert codex_credentials.CODEX_OAUTH_PENDING_ACTIVATION not in get_instance_secrets(secret_key)


def test_configure_agent_routes_codex_to_private_activation(monkeypatch):
    host = {"hostname": "codex-host"}
    record = {"type": "codex", "agent_name": "codex-unix", "config": {}}
    calls: list[dict] = []
    monkeypatch.setattr(lifecycle, "get_host", lambda _hostname: host)
    monkeypatch.setattr(
        lifecycle, "_resolve_agent_record", lambda *_args, **_kwargs: ("fleet-codex", "codex", record)
    )
    monkeypatch.setattr(
        lifecycle, "_configure_codex_credentials",
        lambda **kwargs: calls.append(kwargs) or (True, None),
    )

    assert lifecycle.configure_agent("codex-host", "codex", {}, agent_name="fleet-codex") == (True, None)
    assert calls == [{
        "hostname": "codex-host", "host": host, "agent_key": "fleet-codex",
        "unix_agent_name": "codex-unix", "config_data": {}, "extra_vars": None,
    }]


def test_configure_agent_propagates_codex_activation_failure(monkeypatch):
    host = {"hostname": "codex-host"}
    record = {"type": "codex", "agent_name": "codex-agent", "config": {}}
    monkeypatch.setattr(lifecycle, "get_host", lambda _hostname: host)
    monkeypatch.setattr(
        lifecycle, "_resolve_agent_record", lambda *_args, **_kwargs: ("codex-agent", "codex", record)
    )
    monkeypatch.setattr(
        lifecycle, "_configure_codex_credentials", lambda **_kwargs: (False, "sanitized failure")
    )

    assert lifecycle.configure_agent("codex-host", "codex", {}, agent_name="codex-agent") == (
        False, "sanitized failure",
    )


def test_canonical_sync_routes_codex_to_refresh_safe_activation(
    isolated_config: Path, monkeypatch
):
    _seed(isolated_config)
    host = {"hostname": "codex-host", "key_id": "codex-key"}
    record = {"type": "codex", "agent_name": "codex-agent", "config": {}}
    calls: list[dict] = []
    monkeypatch.setattr(
        lifecycle_canonical, "get_agent_by_name", lambda _name: (host, "codex", record)
    )
    monkeypatch.setattr(
        lifecycle_canonical,
        "has_completed_install",
        lambda _record: True,
        raising=False,
    )

    def activate(**kwargs):
        calls.append(kwargs)
        return True, None

    monkeypatch.setattr(lifecycle, "_configure_codex_credentials", activate)
    result = lifecycle_canonical.sync_agent_canonical(
        "codex-agent", restart=False, verify=False, push_workspace=False
    )
    assert result.success is True
    assert result.files_written == (".codex/auth.json",)
    assert calls == [{
        "hostname": "codex-host", "host": host, "agent_key": "codex-agent",
        "unix_agent_name": "codex-agent", "config_data": {}, "extra_vars": None,
    }]


@pytest.mark.parametrize("flag", ["workspace_only", "dry_run"])
def test_canonical_sync_codex_safe_modes_skip_private_activation(
    isolated_config: Path, monkeypatch, flag: str
):
    _seed(isolated_config)
    host = {"hostname": "codex-host", "key_id": "codex-key"}
    record = {"type": "codex", "agent_name": "codex-agent", "config": {}}
    monkeypatch.setattr(
        lifecycle_canonical, "get_agent_by_name", lambda _name: (host, "codex", record)
    )
    monkeypatch.setattr(
        lifecycle,
        "_configure_codex_credentials",
        lambda **_kwargs: pytest.fail("private activation must not run"),
    )
    result = lifecycle_canonical.sync_agent_canonical(
        "codex-agent", restart=False, verify=False, push_workspace=False,
        **{flag: True},
    )
    assert result.success is True
    assert result.files_written == ()
    assert result.files_unchanged == ()


def test_activation_failure_returns_sanitized_playbook_summary(
    isolated_config: Path, monkeypatch
):
    _seed(isolated_config)
    codex_credentials.configure_codex_oauth("codex-agent", document=_document())
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.provider._reconcile_codex_oauth_transaction", lambda **_kw: None
    )
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _key: Path("/key"))
    monkeypatch.setattr(
        "clawrium.core.playbook_resolver.resolve_agent_playbook", lambda *_args: Path("configure.yaml")
    )
    monkeypatch.setattr(
        lifecycle.ansible_runner, "run",
        lambda **_kwargs: SimpleNamespace(status="failed", rc=1, events=[]),
    )
    ok, error = lifecycle._configure_codex_credentials(
        hostname="codex-host", host={"hostname": "codex-host", "key_id": "codex-key"},
        agent_key="codex-agent", unix_agent_name="codex-agent", config_data={}, extra_vars=None,
    )
    assert ok is False
    assert error == "Codex activation playbook did not complete successfully; inspect agent-host Ansible logs"
    assert "access-test-token" not in error


def test_interrupted_receipt_failure_has_safe_operator_recovery_diagnostic(
    isolated_config: Path, monkeypatch
):
    _seed(isolated_config)
    codex_credentials.configure_codex_oauth("codex-agent", document=_document())
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.provider._reconcile_codex_oauth_transaction", lambda **_kw: None
    )
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _key: Path("/key"))
    monkeypatch.setattr(
        "clawrium.core.playbook_resolver.resolve_agent_playbook", lambda *_args: Path("configure.yaml")
    )
    monkeypatch.setattr(
        "clawrium.core.playbook_resolver.home_root_for", lambda _os: "/safe-home"
    )
    monkeypatch.setattr(
        lifecycle.ansible_runner, "run",
        lambda **_kwargs: SimpleNamespace(status="failed", events=[{
            "event": "runner_on_failed", "event_data": {
                "task": "Refuse interrupted Codex activation without a committed receipt"
            },
        }]),
    )
    ok, error = lifecycle._configure_codex_credentials(
        hostname="codex-host", host={
            "hostname": "codex-host", "key_id": "codex-key", "os_family": "darwin"
        },
        agent_key="fleet-codex", unix_agent_name="codex-agent", config_data={}, extra_vars=None,
    )
    assert ok is False
    assert error is not None
    assert "/safe-home/codex-agent/.codex/.clawrium-oauth-fingerprint" in error
    assert "clawctl agent provider attach <provider> --agent fleet-codex" in error
    assert "access-test-token" not in error


def test_routine_activation_preserves_refreshed_remote_auth_request(
    isolated_config: Path, monkeypatch
):
    _seed(isolated_config)
    codex_credentials.configure_codex_oauth("codex-agent", document=_document())
    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.provider._reconcile_codex_oauth_transaction", lambda **_kw: None
    )
    monkeypatch.setattr(lifecycle, "get_host_private_key", lambda _key: Path("/key"))
    monkeypatch.setattr(
        "clawrium.core.playbook_resolver.resolve_agent_playbook", lambda *_args: Path("configure.yaml")
    )
    captured: dict = {}
    monkeypatch.setattr(
        lifecycle.ansible_runner, "run",
        lambda **kwargs: (captured.update(kwargs["inventory"]["all"]["vars"]) or SimpleNamespace(status="successful")),
    )
    ok, error = lifecycle._configure_codex_credentials(
        hostname="codex-host", host={"hostname": "codex-host", "key_id": "codex-key"},
        agent_key="codex-agent", unix_agent_name="codex-agent", config_data={}, extra_vars=None,
    )
    assert (ok, error) == (True, None)
    assert captured["codex_replace_auth"] is False
