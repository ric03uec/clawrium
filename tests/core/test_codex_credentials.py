"""Local Codex OAuth document import contracts (#1035)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from clawrium.core import codex_credentials
from clawrium.core.codex_credentials import (
    CODEX_OAUTH_DOCUMENT,
    CodexCredentialError,
    CodexOAuthSourceError,
    configure_codex_oauth,
    get_codex_credential_state,
    get_codex_oauth_document,
    import_codex_oauth_from_local_reader,
    read_local_codex_oauth_document,
)
from clawrium.core.secrets import get_instance_key, get_instance_secrets


def _seed_agent(
    config_dir: Path, name: str = "codex-one", agent_type: str = "codex"
) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    path = config_dir / "hosts.json"
    hosts = (
        json.loads(path.read_text())
        if path.exists()
        else [{"hostname": "codex-host", "key_id": "codex-host-key", "agents": {}}]
    )
    hosts[0]["agents"][name] = {
        "type": agent_type,
        "agent_name": name,
        "status": "installed",
        "config": {},
    }
    path.write_text(json.dumps(hosts))


def _instance_key(name: str = "codex-one") -> str:
    return get_instance_key("codex-host-key", "codex", name)


def _document() -> dict[str, object]:
    return {
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": "access-test-token",
            "refresh_token": "refresh-test-token",
            "id_token": "id-test-token",
            "account_id": "account-test-id",
        },
        "last_refresh": "2026-10-06T00:00:00Z",
    }


def _write_auth(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document))
    path.chmod(0o600)


def test_reader_uses_codex_home_and_keeps_full_native_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    document = _document()
    _write_auth(tmp_path / "codex-home" / "auth.json", document)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))

    assert json.loads(read_local_codex_oauth_document()) == document


@pytest.mark.parametrize(
    "mutate,category",
    [
        (lambda d: d.update(auth_mode="api_key"), "credentials_auth_mode_unsupported"),
        (lambda d: d["tokens"].pop("refresh_token"), "credentials_token_missing"),
        (
            lambda d: d["tokens"].update(extra="secret"),
            "credentials_artifact_malformed",
        ),
    ],
)
def test_reader_rejects_unsupported_or_malformed_documents_without_leaking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutate, category: str
):
    document = _document()
    mutate(document)
    _write_auth(tmp_path / "codex-home" / "auth.json", document)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))

    with pytest.raises(CodexOAuthSourceError) as error:
        read_local_codex_oauth_document()
    assert error.value.category == category
    assert "access-test-token" not in str(error.value)


def test_reader_rejects_insecure_symlink_and_oversize_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    home = tmp_path / "codex-home"
    auth = home / "auth.json"
    _write_auth(auth, _document())
    monkeypatch.setenv("CODEX_HOME", str(home))
    auth.chmod(0o644)
    with pytest.raises(CodexOAuthSourceError) as insecure:
        read_local_codex_oauth_document()
    assert insecure.value.category == "credentials_artifact_insecure"

    auth.unlink()
    auth.mkdir()
    with pytest.raises(CodexOAuthSourceError) as non_regular:
        read_local_codex_oauth_document()
    assert non_regular.value.category == "credentials_artifact_insecure"

    auth.rmdir()
    target = tmp_path / "target.json"
    _write_auth(target, _document())
    auth.symlink_to(target)
    with pytest.raises(CodexOAuthSourceError) as symlink:
        read_local_codex_oauth_document()
    assert symlink.value.category == "credentials_artifact_unavailable"

    auth.unlink()
    (home / "auth.json").write_bytes(
        b"x" * (codex_credentials._CODEX_AUTH_MAX_BYTES + 1)
    )
    (home / "auth.json").chmod(0o600)
    with pytest.raises(CodexOAuthSourceError) as oversized:
        read_local_codex_oauth_document()
    assert oversized.value.category == "credentials_artifact_too_large"


def test_reader_rejects_wrong_owner_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    auth = tmp_path / "codex-home" / "auth.json"
    _write_auth(auth, _document())
    monkeypatch.setenv("CODEX_HOME", str(auth.parent))
    original_fstat = codex_credentials.os.fstat

    def wrong_owner(descriptor: int):
        details = original_fstat(descriptor)
        return SimpleNamespace(
            st_mode=details.st_mode,
            st_uid=os.getuid() + 1,
            st_size=details.st_size,
        )

    monkeypatch.setattr(codex_credentials.os, "fstat", wrong_owner)
    with pytest.raises(CodexOAuthSourceError) as wrong_owner_error:
        read_local_codex_oauth_document()
    assert wrong_owner_error.value.category == "credentials_artifact_insecure"


def test_import_is_per_instance_and_rejects_other_agent_types(isolated_config: Path):
    _seed_agent(isolated_config)
    _seed_agent(isolated_config, "codex-two")
    document = json.dumps(_document())
    import_codex_oauth_from_local_reader("codex-one", reader=lambda: document)

    assert json.loads(get_codex_oauth_document("codex-one")) == _document()
    assert get_instance_secrets(_instance_key("codex-two")) == {}
    _seed_agent(isolated_config, "not-codex", agent_type="openclaw")
    with pytest.raises(CodexCredentialError, match="not a Codex agent"):
        configure_codex_oauth("not-codex", document=document)


def test_credential_state_tracks_selected_document(isolated_config: Path):
    _seed_agent(isolated_config)
    assert get_codex_credential_state("codex-one").configured is False

    import_codex_oauth_from_local_reader(
        "codex-one", reader=lambda: json.dumps(_document())
    )

    assert get_codex_credential_state("codex-one").configured is True


def test_invalid_import_preserves_existing_snapshot(isolated_config: Path):
    _seed_agent(isolated_config)
    document = json.dumps(_document())
    import_codex_oauth_from_local_reader("codex-one", reader=lambda: document)
    before = get_instance_secrets(_instance_key())

    with pytest.raises(CodexCredentialError):
        import_codex_oauth_from_local_reader("codex-one", reader=lambda: "not-json")
    assert get_instance_secrets(_instance_key()) == before
    assert set(before) == {CODEX_OAUTH_DOCUMENT}
