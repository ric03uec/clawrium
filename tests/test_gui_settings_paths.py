"""Settings API path-leak tests for the GUI server.

Closes issue #418: /api/settings must not expose absolute filesystem
paths to secrets_file, hosts_file, or providers_file.
"""

from fastapi.testclient import TestClient

from clawrium.gui.server import app


def _make_client(tmp_path, monkeypatch):
    """Build a TestClient with config dir and usage tracker pointed at tmp_path."""
    monkeypatch.setattr(
        "clawrium.gui.routes.settings.get_config_dir", lambda: tmp_path
    )
    monkeypatch.setattr(
        "clawrium.gui.services.usage_tracker.get_config_dir", lambda: tmp_path
    )
    # Reset the usage tracker singleton so each test gets a fresh tracker
    # bound to its own tmp_path rather than inheriting the prior test's.
    monkeypatch.setattr(
        "clawrium.gui.services.usage_tracker._tracker", None
    )
    return TestClient(app, base_url="http://localhost:36000")


def test_settings_omits_secrets_file(tmp_path, monkeypatch):
    """GET /api/settings must not expose secrets_file path."""
    client = _make_client(tmp_path, monkeypatch)
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert "secrets_file" not in response.json()


def test_settings_omits_hosts_file(tmp_path, monkeypatch):
    """GET /api/settings must not expose hosts_file path."""
    client = _make_client(tmp_path, monkeypatch)
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert "hosts_file" not in response.json()


def test_settings_omits_providers_file(tmp_path, monkeypatch):
    """GET /api/settings must not expose providers_file path."""
    client = _make_client(tmp_path, monkeypatch)
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert "providers_file" not in response.json()


def test_settings_secrets_configured_true(tmp_path, monkeypatch):
    """secrets_configured is True when secrets.json exists."""
    (tmp_path / "secrets.json").touch()
    client = _make_client(tmp_path, monkeypatch)
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert response.json()["secrets_configured"] is True


def test_settings_secrets_configured_false(tmp_path, monkeypatch):
    """secrets_configured is False when secrets.json does not exist."""
    client = _make_client(tmp_path, monkeypatch)
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert response.json()["secrets_configured"] is False


def test_settings_keeps_config_dir_and_usage_db(tmp_path, monkeypatch):
    """config_dir and usage_db remain present as non-empty strings."""
    client = _make_client(tmp_path, monkeypatch)
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["config_dir"], str) and body["config_dir"]
    assert isinstance(body["usage_db"], str) and body["usage_db"]
