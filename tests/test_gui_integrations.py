"""Tests for the integrations GUI route."""

import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from clawrium.core.integrations import INTEGRATIONS_FILE
from clawrium.gui.routes import integrations as integrations_route


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point integrations storage + secrets module at a temp dir."""
    monkeypatch.setattr("clawrium.core.integrations.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("clawrium.core.integrations.init_config_dir", lambda: tmp_path)
    # Secrets storage also needs isolation so set_integration_credential
    # does not touch the real ~/.config/clawrium.
    monkeypatch.setattr("clawrium.core.secrets.get_config_dir", lambda: tmp_path)
    monkeypatch.setattr("clawrium.core.secrets.init_config_dir", lambda: tmp_path)
    return tmp_path


def _run(coro):
    return asyncio.run(coro)


def test_list_returns_empty_when_no_integrations(isolated_config):
    result = _run(integrations_route.list_integrations())
    assert result == {"integrations": []}


def test_list_returns_summaries_without_credential_values(isolated_config):
    create = integrations_route.IntegrationCreate(
        name="mygh",
        type="github",
        credentials={"GITHUB_TOKEN": "ghp_secret_value"},
    )
    _run(integrations_route.create_integration(create))

    result = _run(integrations_route.list_integrations())
    serialized = json.dumps(result)
    assert "ghp_secret_value" not in serialized

    assert len(result["integrations"]) == 1
    summary = result["integrations"][0]
    assert summary["name"] == "mygh"
    assert summary["type"] == "github"
    assert summary["credential_keys"] == ["GITHUB_TOKEN"]
    assert summary["configured_credential_keys"] == ["GITHUB_TOKEN"]


def test_types_endpoint_returns_all_known_types(isolated_config):
    result = _run(integrations_route.list_integration_types())
    types = result["types"]
    for type_key in ("github", "gitlab", "atlassian", "linear", "notion", "brave"):
        assert type_key in types
        assert "credentials" in types[type_key]
        assert "description" in types[type_key]


def test_brave_type_credential_schema_is_single_api_key(isolated_config):
    """#734: brave has a single required credential `BRAVE_API_KEY`.
    The GUI consumes the types catalog to render one masked field — a
    schema drift here would silently break the create modal."""
    result = _run(integrations_route.list_integration_types())
    brave = result["types"]["brave"]
    keys = brave["credentials"]
    assert [c["key"] for c in keys] == ["BRAVE_API_KEY"]
    assert keys[0]["required"] is True


def test_create_brave_integration_persists_only_credential_key(isolated_config):
    """#734: POST /api/integrations with `type: brave` round-trips the
    credential key (NOT the value) into the summary. The summary
    endpoint MUST NOT leak the raw key value."""
    req = integrations_route.IntegrationCreate(
        name="my-brave",
        type="brave",
        credentials={"BRAVE_API_KEY": "bsk-secret-123"},
    )
    _run(integrations_route.create_integration(req))

    result = _run(integrations_route.list_integrations())
    [summary] = result["integrations"]
    assert summary["type"] == "brave"
    assert summary["configured_credential_keys"] == ["BRAVE_API_KEY"]
    # The raw value MUST NOT appear anywhere in the response.
    import json as _json

    assert "bsk-secret-123" not in _json.dumps(result)


def test_create_rejects_invalid_name(isolated_config):
    bad = integrations_route.IntegrationCreate(
        name="1bad name", type="github", credentials={}
    )
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.create_integration(bad))
    assert exc.value.status_code == 400


def test_create_rejects_invalid_type(isolated_config):
    bad = integrations_route.IntegrationCreate(
        name="ok", type="not-a-type", credentials={}
    )
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.create_integration(bad))
    assert exc.value.status_code == 400


def test_create_rejects_unknown_credential_key(isolated_config):
    bad = integrations_route.IntegrationCreate(
        name="ok",
        type="github",
        credentials={"BOGUS_KEY": "value"},
    )
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.create_integration(bad))
    assert exc.value.status_code == 400
    assert "BOGUS_KEY" in str(exc.value.detail)


def test_create_duplicate_returns_409(isolated_config):
    body = integrations_route.IntegrationCreate(
        name="mygh", type="github", credentials={}
    )
    _run(integrations_route.create_integration(body))
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.create_integration(body))
    assert exc.value.status_code == 409


def test_get_returns_404_when_missing(isolated_config):
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.get_integration_detail("missing"))
    assert exc.value.status_code == 404


def test_get_returns_agents_using(isolated_config, monkeypatch):
    body = integrations_route.IntegrationCreate(
        name="mygh", type="github", credentials={}
    )
    _run(integrations_route.create_integration(body))

    monkeypatch.setattr(
        integrations_route,
        "find_agents_using_integration",
        lambda name: [("wolf-i", "alpha"), ("wolf-ii", "bravo")],
    )

    result = _run(integrations_route.get_integration_detail("mygh"))
    assert result["agents_using"] == [
        {"hostname": "wolf-i", "agent_key": "alpha"},
        {"hostname": "wolf-ii", "agent_key": "bravo"},
    ]


def test_update_credentials_404_when_missing(isolated_config):
    body = integrations_route.IntegrationCredentialsUpdate(
        credentials={"GITHUB_TOKEN": "new"}
    )
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.update_integration_credentials("nope", body))
    assert exc.value.status_code == 404


def test_update_credentials_rejects_unknown_key(isolated_config):
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="mygh", type="github", credentials={}
            )
        )
    )
    bad = integrations_route.IntegrationCredentialsUpdate(
        credentials={"BOGUS": "value"}
    )
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.update_integration_credentials("mygh", bad))
    assert exc.value.status_code == 400


def test_update_credentials_persists_only_non_empty_values(isolated_config):
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="myjira", type="atlassian", credentials={}
            )
        )
    )

    body = integrations_route.IntegrationCredentialsUpdate(
        credentials={
            "ATLASSIAN_URL": "https://co.atlassian.net",
            "ATLASSIAN_EMAIL": "",
            "ATLASSIAN_API_TOKEN": "token-xyz",
        }
    )
    result = _run(integrations_route.update_integration_credentials("myjira", body))
    assert sorted(result["updated_keys"]) == [
        "ATLASSIAN_API_TOKEN",
        "ATLASSIAN_URL",
    ]


def test_delete_404_when_missing(isolated_config):
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.delete_integration("missing"))
    assert exc.value.status_code == 404


def test_delete_returns_409_when_in_use(isolated_config, monkeypatch):
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="mygh", type="github", credentials={}
            )
        )
    )
    monkeypatch.setattr(
        integrations_route,
        "find_agents_using_integration",
        lambda name: [("wolf-i", "alpha")],
    )

    # Patch the underlying core remove_integration so it raises the
    # in-use error without depending on real hosts.json. The route
    # imports the symbol at module load.
    from clawrium.core.integrations import IntegrationInUseError

    def boom(name, force=False):
        raise IntegrationInUseError(f"Integration '{name}' is assigned")

    monkeypatch.setattr(integrations_route, "remove_integration", boom)

    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.delete_integration("mygh"))
    assert exc.value.status_code == 409
    assert exc.value.detail["agents_using"] == [
        {"hostname": "wolf-i", "agent_key": "alpha"}
    ]


def test_delete_success_when_not_in_use(isolated_config, monkeypatch):
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="mygh", type="github", credentials={}
            )
        )
    )
    monkeypatch.setattr(
        integrations_route, "find_agents_using_integration", lambda name: []
    )
    monkeypatch.setattr(
        integrations_route, "remove_integration", lambda name, force=False: True
    )

    result = _run(integrations_route.delete_integration("mygh"))
    assert result == {"success": True, "name": "mygh"}


def test_list_raises_500_when_file_corrupted(isolated_config):
    integrations_file = isolated_config / INTEGRATIONS_FILE
    integrations_file.write_text("not json {")

    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.list_integrations())
    assert exc.value.status_code == 500


def test_router_is_registered_on_app():
    """Sanity check: the FastAPI app exposes the integrations endpoints
    with the expected HTTP methods.

    Asserts path AND method so a credentials endpoint registered under
    the wrong verb (e.g. PUT instead of PATCH) is caught.
    """
    from clawrium.gui import server

    methods_by_path: dict[str, set[str]] = {}
    for route in server.app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        methods_by_path.setdefault(path, set()).update(methods)

    assert "GET" in methods_by_path.get("/api/integrations", set())
    assert "POST" in methods_by_path.get("/api/integrations", set())
    assert "GET" in methods_by_path.get("/api/integrations/types", set())
    assert "GET" in methods_by_path.get("/api/integrations/{name}", set())
    assert "DELETE" in methods_by_path.get("/api/integrations/{name}", set())
    assert "PATCH" in methods_by_path.get("/api/integrations/{name}/credentials", set())


def test_get_detail_raises_500_when_file_corrupted(isolated_config):
    (isolated_config / INTEGRATIONS_FILE).write_text("not json {")
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.get_integration_detail("any"))
    assert exc.value.status_code == 500


def test_update_credentials_raises_500_when_file_corrupted(isolated_config):
    (isolated_config / INTEGRATIONS_FILE).write_text("not json {")
    body = integrations_route.IntegrationCredentialsUpdate(
        credentials={"GITHUB_TOKEN": "x"}
    )
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.update_integration_credentials("any", body))
    assert exc.value.status_code == 500


def test_delete_raises_500_when_file_corrupted(isolated_config):
    (isolated_config / INTEGRATIONS_FILE).write_text("not json {")
    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.delete_integration("any"))
    assert exc.value.status_code == 500


def test_delete_returns_404_on_race_condition(isolated_config, monkeypatch):
    """remove_integration races with another deleter — the second call sees
    the record on read, but `remove_integration` returns False because the
    record disappeared between get_integration and remove_integration.
    """
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="mygh", type="github", credentials={}
            )
        )
    )
    monkeypatch.setattr(
        integrations_route, "find_agents_using_integration", lambda name: []
    )
    monkeypatch.setattr(
        integrations_route,
        "remove_integration",
        lambda name, force=False: False,
    )

    with pytest.raises(HTTPException) as exc:
        _run(integrations_route.delete_integration("mygh"))
    assert exc.value.status_code == 404


def test_update_credentials_response_never_contains_value(isolated_config):
    """PATCH response must echo only key names, never credential values."""
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="mygh", type="github", credentials={}
            )
        )
    )
    body = integrations_route.IntegrationCredentialsUpdate(
        credentials={"GITHUB_TOKEN": "ghp_sentinel_value_xyz"}
    )
    result = _run(integrations_route.update_integration_credentials("mygh", body))
    assert "ghp_sentinel_value_xyz" not in json.dumps(result)
    assert result["updated_keys"] == ["GITHUB_TOKEN"]


def test_create_response_warns_on_credential_write_failure(
    isolated_config, monkeypatch
):
    """A credential write failure during create surfaces in the response
    `warnings.failed_credential_keys` list — clients can prompt for retry
    instead of silently shipping an integration with zero secrets stored.
    """

    def boom(name, key, value, description=""):
        raise RuntimeError("simulated secrets backend failure")

    monkeypatch.setattr(integrations_route, "set_integration_credential", boom)

    body = integrations_route.IntegrationCreate(
        name="mygh",
        type="github",
        credentials={"GITHUB_TOKEN": "ghp_test"},
    )
    result = _run(integrations_route.create_integration(body))

    assert result["success"] is True
    assert "warnings" in result
    assert result["warnings"]["failed_credential_keys"] == ["GITHUB_TOKEN"]


def test_list_endpoint_returns_agent_count_per_integration(
    isolated_config, monkeypatch
):
    """List endpoint surfaces real usage so the UI does not display
    'no agents' for an integration that is actually in use.
    """
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="mygh", type="github", credentials={}
            )
        )
    )

    # Patch load_hosts via the route's lazy import. The route walks all
    # hosts once and counts the integration references per name.
    def fake_load_hosts():
        return [
            {
                "hostname": "wolf-i",
                "agents": {
                    "alpha": {"integrations": ["mygh"]},
                    "beta": {"integrations": ["mygh", "other"]},
                },
            }
        ]

    monkeypatch.setattr("clawrium.core.hosts.load_hosts", fake_load_hosts)

    result = _run(integrations_route.list_integrations())
    summary = next(i for i in result["integrations"] if i["name"] == "mygh")
    assert summary["agent_count"] == 2


def test_credentials_never_appear_in_get_detail(isolated_config, monkeypatch):
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="mygh",
                type="github",
                credentials={"GITHUB_TOKEN": "top-secret-pat-value"},
            )
        )
    )
    monkeypatch.setattr(
        integrations_route, "find_agents_using_integration", lambda name: []
    )

    detail = _run(integrations_route.get_integration_detail("mygh"))
    serialized = json.dumps(detail)
    assert "top-secret-pat-value" not in serialized
    assert detail["configured_credential_keys"] == ["GITHUB_TOKEN"]


def test_summary_handles_credential_read_failure(isolated_config, monkeypatch):
    # Create the integration first, then break the secrets read path so the
    # summarizer hits the except branch.
    _run(
        integrations_route.create_integration(
            integrations_route.IntegrationCreate(
                name="mygh", type="github", credentials={}
            )
        )
    )

    def boom(name):
        raise RuntimeError("secrets backend down")

    with patch.object(integrations_route, "get_integration_credentials", boom):
        result = _run(integrations_route.list_integrations())

    assert result["integrations"][0]["configured_credential_keys"] == []
