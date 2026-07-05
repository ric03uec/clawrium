"""CORS security tests for the GUI middleware.

Issue #713: Narrow CORS wildcards when allow_credentials=True to prevent
potential credential leaks if allow_origins drifts.
"""

from fastapi.testclient import TestClient

from clawrium.gui.server import app


def test_health_endpoint_works():
    """Baseline: health endpoint should respond."""
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200


def test_credentials_flag_set_on_allowed_origin():
    """Responses to allowed origins include access-control-allow-credentials."""
    client = TestClient(app)
    response = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.headers.get("access-control-allow-credentials") == "true"
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_alternative_origin_localhost_36000():
    """The localhost:36000 origin should also work."""
    client = TestClient(app)
    response = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:36000"},
    )
    assert response.headers.get("access-control-allow-credentials") == "true"
    assert response.headers.get("access-control-allow-origin") == "http://localhost:36000"


def test_untrusted_origin_no_allow_origin_header():
    """Untrusted origins get NO access-control-allow-origin header.

    This is the critical protection: the browser will not expose the
    response to the untrusted origin when this header is absent.
    The Access-Control-Allow-Credentials header IS always sent (that's
    how Starlette indicates credential-support), but without the
    matching Allow-Origin header, the browser blocks it.
    """
    client = TestClient(app)
    response = client.get(
        "/api/health",
        headers={"Origin": "http://evil.com"},
    )
    # The browser will block this origin since there's no Allow-Origin
    assert response.headers.get("access-control-allow-origin") is None


def test_no_wildcard_methods():
    """Preflight should list explicit methods, not wildcard."""
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    methods = response.headers.get("access-control-allow-methods")
    assert methods is not None
    assert "*" not in methods
    # Should include the methods we allow
    assert "GET" in methods
    assert "POST" in methods


def test_no_wildcard_headers():
    """Preflight should list explicit headers, not wildcard."""
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type",
        },
    )
    headers = response.headers.get("access-control-allow-headers")
    assert headers is not None
    assert "*" not in headers
    # Should include standard headers we allow
    assert "Content-Type" in headers
    assert "Authorization" in headers


def test_preflight_custom_header_blocked():
    """Preflight for custom headers should be rejected."""
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-My-Custom-Header",
        },
    )
    assert response.status_code == 400


def test_preflight_untrusted_origin():
    """Preflight from untrusted origins should not include allow-origin."""
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://evil.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_preflight_allowed_method():
    """POST preflight should succeed for allowed origin."""
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    methods = response.headers.get("access-control-allow-methods")
    assert "POST" in methods


def test_put_method_allowed():
    """PUT should work for allowed origins."""
    client = TestClient(app)
    response = client.put(
        "/api/fleet/agents/foo/memory/test.txt",
        content=b"test",
        headers={"Origin": "http://localhost:3000"},
    )
    # 404 is fine (no such agent), CORS should not block it
    assert response.status_code in (200, 404, 422)


def test_delete_method_allowed():
    """DELETE should work for allowed origins."""
    client = TestClient(app)
    response = client.delete(
        "/api/providers/test",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code in (404, 422)


def test_authorization_header_passes_preflight():
    """Authorization header should pass preflight."""
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )
    headers = response.headers.get("access-control-allow-headers")
    assert "Authorization" in headers


def test_post_works():
    """POST should work for allowed origins."""
    client = TestClient(app)
    response = client.post(
        "/api/fleet/agents/foo/start",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code in (200, 404, 422)


def test_patch_works():
    """PATCH should work for allowed origins."""
    client = TestClient(app)
    response = client.patch(
        "/api/integrations/test/credentials",
        json={"credentials": {}},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code in (200, 404, 422)
