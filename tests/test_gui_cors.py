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

    The browser blocks responses without a matching Allow-Origin,
    so this is the critical protection even though allow-credentials
    remains set (Starlette behavior).
    """
    client = TestClient(app)
    response = client.get(
        "/api/health",
        headers={"Origin": "http://evil.com"},
    )
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
    # Should include at least the methods we expect
    assert "GET" in methods
    assert "POST" in methods
    assert "HEAD" in methods


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
    # Should include all standard headers we allow
    assert "Content-Type" in headers
    assert "Authorization" in headers
    assert "Accept" in headers


def test_preflight_custom_header_blocked():
    """Preflight for unlisted headers should be rejected with 400."""
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
    # Custom header must NOT appear in allow-headers
    allow_headers = response.headers.get("access-control-allow-headers") or ""
    assert "X-My-Custom-Header" not in allow_headers


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
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    methods = response.headers.get("access-control-allow-methods")
    assert methods is not None
    assert "POST" in methods


def test_put_method_cors_headers():
    """PUT should return CORS headers for allowed origins."""
    client = TestClient(app)
    response = client.put(
        "/api/agents/foo/memory/test.txt",
        content=b"test",
        headers={"Origin": "http://localhost:3000"},
    )
    # 404 is fine (no such agent), but CORS should pass through
    assert response.status_code in (200, 404, 422)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_delete_method_cors_headers():
    """DELETE should return CORS headers for allowed origins."""
    client = TestClient(app)
    response = client.delete(
        "/api/providers/test",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code in (404, 422)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_post_cors_headers():
    """POST should return CORS headers for allowed origins."""
    client = TestClient(app)
    response = client.post(
        "/api/agents/foo/start",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code in (200, 404, 422)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_patch_cors_headers():
    """PATCH should return CORS headers for allowed origins."""
    client = TestClient(app)
    response = client.patch(
        "/api/integrations/test/credentials",
        json={"key": "value"},
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code in (200, 404, 422)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_preflight_blocked_method_rejected():
    """B2: Preflight for a method NOT in allow_methods should be rejected.

    This is the core invariant the PR introduces: narrowing from '*'
    to an explicit list must actually block disallowed methods.
    TRACE is not in allow_methods, so its preflight should fail.
    """
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "TRACE",
        },
    )
    assert response.status_code == 400
    # Starlette sets allow-origin for the trusted origin even on rejection;
    # the invariant is the 400 status (method blocked) + blocked method
    # not appearing in allow-methods
    allow_methods = response.headers.get("access-control-allow-methods") or ""
    assert "TRACE" not in allow_methods


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
    assert headers is not None
    assert "Authorization" in headers


def test_pairing_code_cors():
    """W4: Verify /pairing-code endpoint is covered by CORS middleware.

    The connection-token and pairing-code endpoints return bearer secrets.
    This test ensures the global CORS middleware applies to them.
    """
    client = TestClient(app)
    response = client.post(
        "/api/fleet/agents/foo/pairing-code",
        headers={"Origin": "http://localhost:3000"},
    )
    # 404 is fine (no such agent), CORS should be present
    assert response.status_code in (200, 404, 422)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_connection_token_cors():
    """W4: Verify /connection-token endpoint is covered by CORS middleware."""
    client = TestClient(app)
    response = client.post(
        "/api/fleet/agents/foo/connection-token",
        headers={"Origin": "http://localhost:3000"},
    )
    assert response.status_code in (200, 404, 422)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_no_origin_header():
    """W3: Requests without an Origin header should pass through without CORS headers."""
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    # No Origin means no CORS negotiation — browser requests always send Origin
    assert response.headers.get("access-control-allow-origin") is None


def test_wrong_scheme_origin():
    """W3: HTTPS origin should not match HTTP localhost entries."""
    client = TestClient(app)
    response = client.get(
        "/api/health",
        headers={"Origin": "https://localhost:3000"},
    )
    # allow_origins uses exact match, so https won't match http
    assert response.headers.get("access-control-allow-origin") is None


def test_pairing_code_blocked_untrusted():
    """W4: Verify /pairing-code endpoint blocks untrusted origins."""
    client = TestClient(app)
    response = client.post(
        "/api/fleet/agents/foo/pairing-code",
        headers={"Origin": "http://evil.com"},
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_connection_token_blocked_untrusted():
    """W4: Verify /connection-token endpoint blocks untrusted origins."""
    client = TestClient(app)
    response = client.post(
        "/api/fleet/agents/foo/connection-token",
        headers={"Origin": "http://evil.com"},
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_origin_list_no_wildcard():
    """S4: Regression: wildcard origin should not be allowed back in.

    Behavioral test: an explicit, non-localhost origin is blocked rather
    than echoed back. This catches drift where allow_origins gets reset to
    ['*'] by accident.
    """
    client = TestClient(app)
    response = client.get(
        "/api/health",
        headers={"Origin": "http://random-non-localhost-site.com"},
    )
    assert response.headers.get("access-control-allow-origin") is None


def test_head_method_cors_headers():
    """HEAD should pass preflight CORS for allowed origins.

    HEAD is listed in allow_methods so browsers can send HEAD+Authorization
    without preflight failure. Individual endpoints may still return 405,
    but the CORS preflight succeeds.
    """
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "HEAD",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_methods_exact_set():
    """Pin the exact allowed methods to prevent drift."""
    client = TestClient(app)
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    methods = response.headers.get("access-control-allow-methods") or ""
    actual = {m.strip() for m in methods.split(",")}
    assert actual == {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}
