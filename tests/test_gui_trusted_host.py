"""TrustedHostMiddleware tests for the GUI server.

Closes issue #418 (DNS rebinding mitigation): requests with a foreign
Host header must be rejected with 400.
"""

from fastapi.testclient import TestClient

from clawrium.gui.server import app


def test_health_endpoint_works():
    """Baseline: health endpoint responds with allowed host."""
    client = TestClient(app, base_url="http://localhost:36000")
    response = client.get("/api/health")
    assert response.status_code == 200


def test_foreign_host_rejected():
    """Requests with a foreign Host header are rejected with 400."""
    client = TestClient(app, base_url="http://localhost:36000")
    response = client.get("/api/health", headers={"host": "evil.com"})
    assert response.status_code == 400


def test_localhost_host_allowed():
    """Host: localhost is allowed."""
    client = TestClient(app, base_url="http://localhost:36000")
    response = client.get("/api/health", headers={"host": "localhost"})
    assert response.status_code == 200


def test_localhost_with_port_allowed():
    """Host: localhost:36000 is allowed."""
    client = TestClient(app, base_url="http://localhost:36000")
    response = client.get("/api/health", headers={"host": "localhost:36000"})
    assert response.status_code == 200


def test_127_0_0_1_allowed():
    """Host: 127.0.0.1 is allowed."""
    client = TestClient(app, base_url="http://localhost:36000")
    response = client.get("/api/health", headers={"host": "127.0.0.1"})
    assert response.status_code == 200


def test_127_0_0_1_with_port_allowed():
    """Host: 127.0.0.1:36000 is allowed."""
    client = TestClient(app, base_url="http://localhost:36000")
    response = client.get("/api/health", headers={"host": "127.0.0.1:36000"})
    assert response.status_code == 200


def test_dns_rebinding_simulation():
    """Simulate DNS rebinding: attacker-controlled domain resolving to 127.0.0.1."""
    client = TestClient(app, base_url="http://localhost:36000")
    response = client.get("/api/health", headers={"host": "attacker.example.com"})
    assert response.status_code == 400
