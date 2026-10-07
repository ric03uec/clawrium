"""Codex OAuth provider selection and local-import boundaries (#1035)."""

from __future__ import annotations

import json
import pytest
from typer.testing import CliRunner

from clawrium.cli import app
from clawrium.cli.clawctl.agent import provider as agent_provider
from clawrium.core import codex_credentials, lifecycle
from clawrium.core.codex_credentials import (
    CODEX_OAUTH_DOCUMENT,
    CODEX_OAUTH_PENDING_ACTIVATION,
    CodexOAuthSourceError,
)
from clawrium.core.providers.storage import get_provider
from clawrium.core.secrets import (
    get_instance_key,
    get_instance_secrets,
    set_instance_secret,
)

runner = CliRunner()


def _add_codex_agent(
    fleet_dir, name: str = "codex-cli", agent_type: str = "codex", agent_name: str | None = None
) -> None:
    path = fleet_dir / "hosts.json"
    hosts = json.loads(path.read_text())
    hosts[0]["agents"][name] = {
        "type": agent_type,
        "agent_name": agent_name or name,
        "status": "installed",
        "config": {},
    }
    path.write_text(json.dumps(hosts))


def _create_provider() -> None:
    result = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "local-codex-oauth",
            "--type",
            "codex-oauth",
        ],
    )
    assert result.exit_code == 0, result.output
    record = get_provider("local-codex-oauth")
    assert record is not None
    assert record["name"] == "local-codex-oauth"
    assert record["type"] == "codex-oauth"


def _document() -> str:
    return json.dumps(
        {
            "auth_mode": "chatgpt",
            "tokens": {
                "access_token": "access-test-token",
                "refresh_token": "refresh-test-token",
                "id_token": "id-test-token",
                "account_id": "account-test-id",
            },
        }
    )


def test_codex_configure_dispatches_to_native_lifecycle(
    fleet_dir, monkeypatch
) -> None:
    _add_codex_agent(fleet_dir, name="fleet-codex", agent_name="codex-unix")
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["fleet-codex"]["installed_at"] = "2026-10-06T00:00:00Z"
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))
    hostname = hosts[0]["hostname"]
    calls: list[dict] = []

    class Backend:
        @staticmethod
        def configure_agent(**kwargs):
            calls.append(kwargs)
            return True, None

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.resolve_lifecycle_backend",
        lambda _os_family: Backend(),
    )
    result = runner.invoke(app, ["agent", "configure", "fleet-codex"])

    assert result.exit_code == 0, result.output
    assert "Codex private settings configured" in result.output
    assert len(calls) == 1
    assert calls[0]["hostname"] == hostname
    assert calls[0]["claw_name"] == "codex"
    assert calls[0]["agent_name"] == "fleet-codex"
    assert calls[0]["config_data"] == {}
    assert callable(calls[0]["on_event"])


def test_codex_sync_dispatches_to_refresh_safe_canonical_path(fleet_dir, monkeypatch) -> None:
    _add_codex_agent(fleet_dir, name="fleet-codex", agent_name="codex-unix")
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["fleet-codex"]["installed_at"] = "2026-10-06T00:00:00Z"
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))
    calls: list[tuple[tuple, dict]] = []

    class Result:
        success = True
        files_written = (".codex/auth.json",)
        files_unchanged = ()
        error = None

    def sync(*args, **kwargs):
        calls.append((args, kwargs))
        return Result()

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)
    result = runner.invoke(app, ["agent", "sync", "fleet-codex"])
    assert result.exit_code == 0, result.output
    assert "synced Codex private settings" in result.output
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == ("codex-unix",)
    assert kwargs["agent_key"] == "fleet-codex"
    assert kwargs["restart"] is False
    assert kwargs["verify"] is False
    assert kwargs["push_workspace"] is False
    assert kwargs["workspace_only"] is False
    assert kwargs["dry_run"] is False
    assert callable(kwargs["on_event"])


def test_codex_sync_result_error_is_credential_safe(fleet_dir, monkeypatch) -> None:
    _add_codex_agent(fleet_dir)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["codex-cli"]["installed_at"] = "2026-10-06T00:00:00Z"
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))

    class Result:
        success = False
        error = "access-test-token"

    monkeypatch.setattr(
        "clawrium.core.lifecycle_canonical.sync_agent_canonical",
        lambda *_args, **_kwargs: Result(),
    )
    result = runner.invoke(app, ["agent", "sync", "codex-cli"])
    assert result.exit_code != 0
    assert "access-test-token" not in result.output
    assert "credential activation failed; re-attach the codex-oauth provider" in result.output
    assert "synced Codex private settings" not in result.output


def test_codex_configure_exception_is_credential_safe(fleet_dir, monkeypatch) -> None:
    _add_codex_agent(fleet_dir)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["codex-cli"]["installed_at"] = "2026-10-06T00:00:00Z"
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))
    from clawrium.core.lifecycle import LifecycleError

    class Backend:
        @staticmethod
        def configure_agent(**_kwargs):
            raise LifecycleError("access-test-token")

    monkeypatch.setattr("clawrium.cli.clawctl.agent.configure.resolve_lifecycle_backend", lambda _os: Backend())
    result = runner.invoke(app, ["agent", "configure", "codex-cli"])
    assert result.exit_code != 0
    assert "access-test-token" not in result.output
    assert "Codex settings configure failed" in result.output


def test_codex_sync_exception_is_credential_safe(fleet_dir, monkeypatch) -> None:
    _add_codex_agent(fleet_dir)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["codex-cli"]["installed_at"] = "2026-10-06T00:00:00Z"
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))
    from clawrium.core.lifecycle_canonical import CanonicalSyncError

    def sync(*_args, **_kwargs):
        raise CanonicalSyncError("access-test-token")

    monkeypatch.setattr("clawrium.core.lifecycle_canonical.sync_agent_canonical", sync)
    result = runner.invoke(app, ["agent", "sync", "codex-cli"])
    assert result.exit_code != 0
    assert "access-test-token" not in result.output
    assert "sync failed" in result.output


def test_codex_configure_operational_failure_preserves_fixed_diagnostic(fleet_dir, monkeypatch) -> None:
    _add_codex_agent(fleet_dir)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["codex-cli"]["installed_at"] = "2026-10-06T00:00:00Z"
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))

    class Backend:
        @staticmethod
        def configure_agent(**_kwargs):
            return False, "SSH key not found"

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.resolve_lifecycle_backend",
        lambda _os_family: Backend(),
    )
    result = runner.invoke(app, ["agent", "configure", "codex-cli"])

    assert result.exit_code != 0
    assert "SSH key not found" in result.output


def test_codex_configure_failure_is_credential_safe(fleet_dir, monkeypatch) -> None:
    _add_codex_agent(fleet_dir)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["codex-cli"]["installed_at"] = "2026-10-06T00:00:00Z"
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))

    class Backend:
        @staticmethod
        def configure_agent(**_kwargs):
            return False, "activation rejected for access-test-token"

    monkeypatch.setattr(
        "clawrium.cli.clawctl.agent.configure.resolve_lifecycle_backend",
        lambda _os_family: Backend(),
    )
    result = runner.invoke(app, ["agent", "configure", "codex-cli"])

    assert result.exit_code != 0
    assert "Codex settings configure failed" in result.output
    assert "access-test-token" not in result.output


def test_attach_imports_only_to_selected_codex_agent_and_reattaches(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _add_codex_agent(fleet_dir, "codex-second")
    _create_provider()
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", _document)

    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"],
    )
    assert result.exit_code == 0, result.output
    assert "access-test-token" not in result.output
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    assert CODEX_OAUTH_DOCUMENT in get_instance_secrets(key)
    assert get_instance_secrets(key)[CODEX_OAUTH_PENDING_ACTIVATION]["value"].startswith("pending:")
    other = get_instance_key("10.0.0.1", "codex", "codex-second")
    assert get_instance_secrets(other) == {}
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert hosts[0]["agents"]["codex-cli"]["providers"] == ["local-codex-oauth"]
    assert "access-test-token" not in (fleet_dir / "hosts.json").read_text()
    assert "access-test-token" not in (fleet_dir / "providers.json").read_text()

    refreshed = _document().replace("access-test-token", "refreshed-token")
    monkeypatch.setattr(
        codex_credentials, "read_local_codex_oauth_document", lambda: refreshed
    )
    second = runner.invoke(
        app,
        ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"],
    )
    assert second.exit_code == 0, second.output
    assert "refreshed-token" not in second.output
    assert "refreshed-token" in get_instance_secrets(key)[CODEX_OAUTH_DOCUMENT]["value"]
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert hosts[0]["agents"]["codex-cli"]["providers"] == ["local-codex-oauth"]

    detached = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "detach",
            "local-codex-oauth",
            "--agent",
            "codex-cli",
            "--yes",
        ],
    )
    assert detached.exit_code == 0, detached.output
    assert CODEX_OAUTH_DOCUMENT not in get_instance_secrets(key)
    assert CODEX_OAUTH_PENDING_ACTIVATION not in get_instance_secrets(key)
    assert get_instance_secrets(other) == {}


def test_attach_failure_rolls_back_new_metadata_and_redacts_error(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    secret = "reader-sensitive-detail"
    monkeypatch.setattr(
        codex_credentials,
        "read_local_codex_oauth_document",
        lambda: (_ for _ in ()).throw(CodexOAuthSourceError(secret)),
    )

    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"],
    )
    assert result.exit_code != 0
    assert "could not import the local Codex OAuth credential" in result.output
    assert secret not in result.output
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert "providers" not in hosts[0]["agents"]["codex-cli"]


def test_initial_attach_never_selects_stale_credential_if_metadata_write_is_interrupted(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    stale_document = _document().replace("access-test-token", "stale-token")
    fresh_document = _document().replace("access-test-token", "fresh-token")
    set_instance_secret(key, CODEX_OAUTH_DOCUMENT, stale_document)
    monkeypatch.setattr(
        codex_credentials, "read_local_codex_oauth_document", lambda: fresh_document
    )
    monkeypatch.setattr(
        agent_provider,
        "_set_attachments",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"],
    )

    assert result.exit_code != 0
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert "providers" not in hosts[0]["agents"]["codex-cli"]
    hosts[0]["agents"]["codex-cli"].update(
        status="installed", installed_at="2026-10-06T00:00:00Z"
    )
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))
    # The compare-and-swap rollback restores the pre-existing unselected
    # snapshot; neither stale nor fresh auth is activated without metadata.
    assert json.loads(
        get_instance_secrets(key)[CODEX_OAUTH_DOCUMENT]["value"]
    ) == json.loads(stale_document)
    assert CODEX_OAUTH_PENDING_ACTIVATION not in get_instance_secrets(key)

    activation_calls: list[dict] = []
    monkeypatch.setattr(
        lifecycle,
        "_configure_codex_credentials",
        lambda **kwargs: activation_calls.append(kwargs) or (True, None),
    )
    sync_result = lifecycle.sync_agent("10.0.0.1", "codex", agent_name="codex-cli")
    assert sync_result["success"] is True
    assert activation_calls[0]["agent_key"] == "codex-cli"


def test_metadata_failure_removes_new_document_without_prior_secret(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", _document)
    monkeypatch.setattr(agent_provider, "_set_attachments", lambda *_args: False)

    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"],
    )

    assert result.exit_code != 0
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    assert CODEX_OAUTH_DOCUMENT not in get_instance_secrets(key)
    assert CODEX_OAUTH_PENDING_ACTIVATION not in get_instance_secrets(key)


def test_attach_secret_transaction_failure_cannot_select_provider_when_error_handler_returns(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", _document)
    monkeypatch.setattr(
        agent_provider,
        "replace_instance_secrets",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private failure")),
    )
    messages = []
    monkeypatch.setattr(
        agent_provider, "emit_error", lambda message, **_kwargs: messages.append(message)
    )

    result = runner.invoke(
        app, ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"]
    )

    assert result.exit_code == 0
    assert messages == ["could not import the local Codex OAuth credential"]
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert "providers" not in hosts[0]["agents"]["codex-cli"]


def test_codex_oauth_rejects_non_codex_agent_before_reader(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir, agent_type="openclaw")
    _create_provider()
    monkeypatch.setattr(
        codex_credentials,
        "read_local_codex_oauth_document",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )

    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"],
    )
    assert result.exit_code != 0
    assert "only be attached to Codex agents" in result.output


def test_codex_rejects_non_oauth_and_second_provider_before_reader(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    ordinary = runner.invoke(
        app,
        [
            "provider",
            "registry",
            "create",
            "ordinary-openai",
            "--type",
            "openai",
            "--api-key",
            "test-key",
        ],
    )
    assert ordinary.exit_code == 0, ordinary.output
    monkeypatch.setattr(
        codex_credentials,
        "read_local_codex_oauth_document",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )
    rejected = runner.invoke(
        app, ["agent", "provider", "attach", "ordinary-openai", "--agent", "codex-cli"]
    )
    assert rejected.exit_code != 0
    assert "require a codex-oauth provider" in rejected.output

    _create_provider()
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["codex-cli"]["providers"] = ["ordinary-openai"]
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))
    second = runner.invoke(
        app,
        ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"],
    )
    assert second.exit_code != 0
    assert "already has provider 'ordinary-openai'" in second.output


def test_attach_unexpected_and_interrupt_failures_restore_new_selection(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    for failure in (RuntimeError("private failure"), KeyboardInterrupt()):
        monkeypatch.setattr(
            codex_credentials,
            "read_local_codex_oauth_document",
            lambda failure=failure: (_ for _ in ()).throw(failure),
        )
        result = runner.invoke(
            app,
            [
                "agent",
                "provider",
                "attach",
                "local-codex-oauth",
                "--agent",
                "codex-cli",
            ],
        )
        assert result.exit_code != 0
        hosts = json.loads((fleet_dir / "hosts.json").read_text())
        assert "providers" not in hosts[0]["agents"]["codex-cli"]


def test_detach_secret_removal_failure_preserves_selection_and_redacts_error(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", _document)
    assert (
        runner.invoke(
            app,
            [
                "agent",
                "provider",
                "attach",
                "local-codex-oauth",
                "--agent",
                "codex-cli",
            ],
        ).exit_code
        == 0
    )
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    before = get_instance_secrets(key)
    def fail_secret_transaction(*_args, **_kwargs):
        raise OSError("private secret store failure")

    monkeypatch.setattr(agent_provider, "replace_instance_secrets", fail_secret_transaction)

    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "detach",
            "local-codex-oauth",
            "--agent",
            "codex-cli",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert (
        "could not remove Codex OAuth credential for agent 'codex-cli'" in result.output
    )
    assert "provider 'local-codex-oauth'" in result.output
    assert "access-test-token" not in result.output
    assert get_instance_secrets(key) == before
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert hosts[0]["agents"]["codex-cli"]["providers"] == ["local-codex-oauth"]


def test_detach_metadata_failure_restores_selected_document_only(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _add_codex_agent(fleet_dir, "codex-second")
    _create_provider()
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", _document)
    assert (
        runner.invoke(
            app,
            [
                "agent",
                "provider",
                "attach",
                "local-codex-oauth",
                "--agent",
                "codex-cli",
            ],
        ).exit_code
        == 0
    )
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    before = get_instance_secrets(key)
    other = get_instance_key("10.0.0.1", "codex", "codex-second")
    original_set = agent_provider._set_attachments
    monkeypatch.setattr(
        agent_provider, "_set_attachments", lambda *_args, **_kwargs: False
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "detach",
            "local-codex-oauth",
            "--agent",
            "codex-cli",
            "--yes",
        ],
    )
    assert result.exit_code != 0
    assert "failed to detach provider" in result.output
    assert (
        get_instance_secrets(key)[CODEX_OAUTH_DOCUMENT]["value"]
        == before[CODEX_OAUTH_DOCUMENT]["value"]
    )
    assert get_instance_secrets(other) == {}
    monkeypatch.setattr(agent_provider, "_set_attachments", original_set)


def test_detach_removes_malformed_stored_document(fleet_dir, stdin_not_tty):
    _add_codex_agent(fleet_dir)
    _create_provider()
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    hosts[0]["agents"]["codex-cli"]["providers"] = ["local-codex-oauth"]
    (fleet_dir / "hosts.json").write_text(json.dumps(hosts))
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    set_instance_secret(key, CODEX_OAUTH_DOCUMENT, "not-valid-json")

    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "detach",
            "local-codex-oauth",
            "--agent",
            "codex-cli",
            "--yes",
        ],
    )

    assert result.exit_code == 0, result.output
    assert CODEX_OAUTH_DOCUMENT not in get_instance_secrets(key)


def test_failed_reattach_preserves_existing_document(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", _document)
    assert (
        runner.invoke(
            app,
            [
                "agent",
                "provider",
                "attach",
                "local-codex-oauth",
                "--agent",
                "codex-cli",
            ],
        ).exit_code
        == 0
    )
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    before = get_instance_secrets(key)[CODEX_OAUTH_DOCUMENT]["value"]
    for failure in (
        CodexOAuthSourceError("credentials_token_missing"),
        RuntimeError("private reader failure"),
    ):
        monkeypatch.setattr(
            codex_credentials,
            "read_local_codex_oauth_document",
            lambda failure=failure: (_ for _ in ()).throw(failure),
        )
        result = runner.invoke(
            app,
            [
                "agent",
                "provider",
                "attach",
                "local-codex-oauth",
                "--agent",
                "codex-cli",
            ],
        )

        assert result.exit_code != 0
        hosts = json.loads((fleet_dir / "hosts.json").read_text())
        assert hosts[0]["agents"]["codex-cli"]["providers"] == ["local-codex-oauth"]
        assert get_instance_secrets(key)[CODEX_OAUTH_DOCUMENT]["value"] == before


def test_failed_attach_does_not_activate_unattached_stale_document(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    stale_document = _document()
    set_instance_secret(key, CODEX_OAUTH_DOCUMENT, stale_document)
    monkeypatch.setattr(
        codex_credentials,
        "read_local_codex_oauth_document",
        lambda: (_ for _ in ()).throw(
            CodexOAuthSourceError("credentials_token_missing")
        ),
    )

    result = runner.invoke(
        app,
        ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"],
    )

    assert result.exit_code != 0
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert "providers" not in hosts[0]["agents"]["codex-cli"]
    assert get_instance_secrets(key)[CODEX_OAUTH_DOCUMENT]["value"] == stale_document


def test_detach_metadata_rollback_does_not_overwrite_concurrent_reattach(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", _document)
    assert (
        runner.invoke(
            app,
            [
                "agent",
                "provider",
                "attach",
                "local-codex-oauth",
                "--agent",
                "codex-cli",
            ],
        ).exit_code
        == 0
    )
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    refreshed = _document().replace("access-test-token", "newer-token")

    def fail_metadata(*_args, **_kwargs):
        set_instance_secret(
            key,
            CODEX_OAUTH_DOCUMENT,
            refreshed,
            description="Codex OAuth credential document",
        )
        return False

    monkeypatch.setattr(agent_provider, "_set_attachments", fail_metadata)
    result = runner.invoke(
        app,
        [
            "agent",
            "provider",
            "detach",
            "local-codex-oauth",
            "--agent",
            "codex-cli",
            "--yes",
        ],
    )

    assert result.exit_code != 0
    assert get_instance_secrets(key)[CODEX_OAUTH_DOCUMENT]["value"] == refreshed


@pytest.mark.parametrize("interrupt_step", ["attach_secret", "attach_metadata"])
def test_attach_recovers_durable_journal_after_interruption(
    fleet_dir, stdin_not_tty, monkeypatch, interrupt_step
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    document = _document().replace("access-test-token", "recovered-token")
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", lambda: document)
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")

    interrupted = False

    def interrupt_after_secret(step: str) -> None:
        nonlocal interrupted
        if step == interrupt_step and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()

    monkeypatch.setattr(
        agent_provider, "_after_codex_oauth_durable_step", interrupt_after_secret
    )
    failed = runner.invoke(
        app, ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"]
    )
    assert failed.exit_code != 0
    assert agent_provider.CODEX_OAUTH_PENDING_TRANSACTION in get_instance_secrets(key)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    if interrupt_step == "attach_secret":
        assert "providers" not in hosts[0]["agents"]["codex-cli"]
    else:
        assert hosts[0]["agents"]["codex-cli"]["providers"] == ["local-codex-oauth"]

    recovered = runner.invoke(
        app, ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"]
    )
    assert recovered.exit_code == 0, recovered.output
    entries = get_instance_secrets(key)
    assert agent_provider.CODEX_OAUTH_PENDING_TRANSACTION not in entries
    assert json.loads(entries[CODEX_OAUTH_DOCUMENT]["value"]) == json.loads(document)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    assert hosts[0]["agents"]["codex-cli"]["providers"] == ["local-codex-oauth"]


@pytest.mark.parametrize("interrupt_step", ["detach_secret", "detach_metadata"])
def test_detach_recovers_durable_journal_after_interruption(
    fleet_dir, stdin_not_tty, monkeypatch, interrupt_step
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    monkeypatch.setattr(codex_credentials, "read_local_codex_oauth_document", _document)
    assert runner.invoke(
        app, ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"]
    ).exit_code == 0
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")

    interrupted = False

    def interrupt_after_metadata(step: str) -> None:
        nonlocal interrupted
        if step == interrupt_step and not interrupted:
            interrupted = True
            raise KeyboardInterrupt()

    monkeypatch.setattr(
        agent_provider, "_after_codex_oauth_durable_step", interrupt_after_metadata
    )
    failed = runner.invoke(
        app,
        [
            "agent", "provider", "detach", "local-codex-oauth", "--agent", "codex-cli", "--yes"
        ],
    )
    assert failed.exit_code != 0
    assert agent_provider.CODEX_OAUTH_PENDING_TRANSACTION in get_instance_secrets(key)
    hosts = json.loads((fleet_dir / "hosts.json").read_text())
    if interrupt_step == "detach_secret":
        assert hosts[0]["agents"]["codex-cli"]["providers"] == ["local-codex-oauth"]
    else:
        assert hosts[0]["agents"]["codex-cli"]["providers"] == []

    # The next operation reconciles the journal before reporting that the
    # provider is already detached, leaving both durable stores detached.
    recovered = runner.invoke(
        app,
        [
            "agent", "provider", "detach", "local-codex-oauth", "--agent", "codex-cli", "--yes"
        ],
    )
    assert recovered.exit_code == (0 if interrupt_step == "detach_secret" else 1)
    entries = get_instance_secrets(key)
    assert agent_provider.CODEX_OAUTH_PENDING_TRANSACTION not in entries
    assert CODEX_OAUTH_DOCUMENT not in entries


def test_failed_cas_recovery_never_overwrites_newer_document(
    fleet_dir, stdin_not_tty, monkeypatch
):
    _add_codex_agent(fleet_dir)
    _create_provider()
    imported = _document().replace("access-test-token", "imported-token")
    newer = _document().replace("access-test-token", "newer-token")
    monkeypatch.setattr(
        codex_credentials, "read_local_codex_oauth_document", lambda: imported
    )
    key = get_instance_key("10.0.0.1", "codex", "codex-cli")
    cas_results = []
    original_cas = agent_provider.replace_instance_secret_if_matches

    def record_cas(*args, **kwargs):
        result = original_cas(*args, **kwargs)
        cas_results.append(result)
        return result

    def fail_metadata(*_args, **_kwargs):
        set_instance_secret(key, CODEX_OAUTH_DOCUMENT, newer)
        return False

    monkeypatch.setattr(agent_provider, "replace_instance_secret_if_matches", record_cas)
    monkeypatch.setattr(agent_provider, "_set_attachments", fail_metadata)
    result = runner.invoke(
        app, ["agent", "provider", "attach", "local-codex-oauth", "--agent", "codex-cli"]
    )
    assert result.exit_code != 0
    # The rollback's CAS fails because another writer replaced the imported
    # value; recovery clears its marker but never overwrites the newer secret.
    assert False in cas_results
    assert get_instance_secrets(key)[CODEX_OAUTH_DOCUMENT]["value"] == newer
