"""Tests for the static-file handler containment guard in server.py.

Closes ATX B5: percent-encoded traversal (and any other path that resolves
outside the frontend directory) must be rejected before FileResponse opens
the target.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from clawrium.gui import server as server_mod


def _build_app_with_frontend(tmp_path: Path, monkeypatch) -> TestClient:
    """Stand up a FastAPI app whose frontend dir is a tmp tree.

    Creates a minimal frontend layout (index.html, topology.html) plus a
    sibling-file outside the frontend root that traversal attempts must
    not reach.
    """
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<html>index</html>")
    (frontend / "topology.html").write_text("<html>topology</html>")

    secret = tmp_path / "secret.txt"
    secret.write_text("DO NOT LEAK")

    # mount_frontend resolves frontend_dir relative to __file__. Point it
    # at our tmp tree by patching the Path expression used inside.
    monkeypatch.setattr(
        server_mod,
        "__file__",
        str(tmp_path / "fake_server.py"),
    )

    app = FastAPI()
    server_mod.mount_frontend(app)
    return TestClient(app)


def test_serves_index_at_root(tmp_path, monkeypatch):
    client = _build_app_with_frontend(tmp_path, monkeypatch)
    r = client.get("/")
    assert r.status_code == 200
    assert "index" in r.text


def test_serves_topology_html(tmp_path, monkeypatch):
    client = _build_app_with_frontend(tmp_path, monkeypatch)
    r = client.get("/topology")
    assert r.status_code == 200
    assert "topology" in r.text


def test_rejects_percent_encoded_traversal(tmp_path, monkeypatch):
    """%2e%2e%2fsecret.txt must not escape the frontend dir."""
    client = _build_app_with_frontend(tmp_path, monkeypatch)
    # Bypass urllib3 normalization by passing the path raw.
    r = client.get("/%2e%2e%2fsecret.txt")
    # Either falls through to index.html or 404 — what matters is the
    # raw secret.txt content must not appear in the response.
    assert "DO NOT LEAK" not in r.text


def test_rejects_raw_dot_dot_traversal(tmp_path, monkeypatch):
    """Plain ../secret.txt must not escape the frontend dir."""
    client = _build_app_with_frontend(tmp_path, monkeypatch)
    r = client.get("/../secret.txt")
    assert "DO NOT LEAK" not in r.text


def test_rejects_absolute_path_attempt(tmp_path, monkeypatch):
    """Absolute filesystem paths must not be served."""
    client = _build_app_with_frontend(tmp_path, monkeypatch)
    # /etc/passwd → joined as frontend/etc/passwd; would 404 anyway, but
    # confirm no panic and no leak.
    r = client.get("/etc/passwd")
    # Frontend fallback returns index.html (client-side routing).
    assert "index" in r.text or r.status_code == 404
