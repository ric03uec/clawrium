"""#1071 phase 3a: negative route-registration regressions.

Phase 3a deleted the `/chat`, `/chat/info`, `/memory`,
`/memory/<file>`, and `/exec` endpoints under `/api/agents/<name>/`
along with every backing core module. These tests pin that
contract: the API handlers must be fully gone, and the single
retained endpoint (`GET /logs`) must remain registered.

**SPA catch-all caveat.** The GUI server serves the Next.js
static build via a GET catch-all under `/api/...`, so a plain
"did GET 404?" test does not distinguish "handler removed" from
"handler present and returned 404". Instead we assert that:

1. **GET** on a removed path returns `200 text/html` (the SPA
   shell), proving no JSON API handler intercepts it.
2. **POST / PUT** on a removed path returns `405 Method Not
   Allowed` with `Allow: GET` (the catch-all is GET-only), which
   is the shape that could only land if no API handler for the
   mutating method remains.

If a future commit accidentally re-registered any of the removed
API endpoints, (1) would flip to JSON and (2) would flip to a
different code (200/400/404 from the handler itself).

ATX phase-3a round W1.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from clawrium.gui.server import app


client = TestClient(app, base_url="http://localhost:36000")


# (method, path) tuples for every endpoint removed in phase 3a.
REMOVED_MUTATING_ROUTES: list[tuple[str, str]] = [
    ("POST", "/api/agents/some-agent/chat"),
    ("PUT", "/api/agents/some-agent/memory/test.txt"),
    ("POST", "/api/agents/some-agent/exec"),
]

# GET endpoints (the SPA catch-all makes them return the shell).
REMOVED_GET_PATHS: list[str] = [
    "/api/agents/some-agent/chat/info",
    "/api/agents/some-agent/memory",
    "/api/agents/some-agent/memory/test.txt",
]


@pytest.mark.parametrize("method,path", REMOVED_MUTATING_ROUTES)
def test_removed_mutating_endpoint_has_no_handler(method: str, path: str) -> None:
    """POST/PUT/DELETE on removed endpoints must 405 (catch-all is GET-only)."""
    response = client.request(method, path, json={})
    assert response.status_code == 405, (
        f"{method} {path} returned {response.status_code} — "
        "a 2xx/4xx that is NOT 405 means a handler for this method got "
        "re-registered after #1071 phase 3a."
    )
    # The catch-all serves GET, so `Allow` should be exactly GET.
    allow = response.headers.get("allow", "")
    assert "GET" in allow, f"unexpected Allow header: {allow!r}"


@pytest.mark.parametrize("path", REMOVED_GET_PATHS)
def test_removed_get_endpoint_falls_through_to_spa(path: str) -> None:
    """GET on removed endpoints must fall through to the SPA shell, not a JSON handler."""
    response = client.get(path)
    assert response.status_code == 200
    content_type = response.headers.get("content-type", "")
    assert "text/html" in content_type, (
        f"GET {path} returned content-type {content_type!r} — "
        "a JSON body means a GET API handler got re-registered after #1071 phase 3a."
    )
    # Sanity: the response is the Next.js shell, not the API-not-found JSON.
    body = response.text.lstrip()
    assert body.startswith("<!DOCTYPE html"), (
        f"GET {path} returned non-SPA body: {body[:80]!r}"
    )


def test_logs_endpoint_remains_registered() -> None:
    """`GET /api/agents/<name>/logs` — the single retained endpoint — still routes to the API.

    The fixture fleet has no `some-agent`, so the handler emits 404
    JSON ("Agent 'some-agent' not found") — distinct from the SPA
    shell a removed route would serve.
    """
    response = client.get("/api/agents/some-agent/logs")
    assert response.status_code == 404
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type, (
        f"GET /api/agents/<name>/logs now serves {content_type!r} — "
        "the API handler got unregistered, phase-3a slim-down went too far."
    )
    body = response.json()
    assert "not found" in body.get("detail", "").lower()


def test_logs_endpoint_remains_mutating_method_locked() -> None:
    """The retained /logs path must remain GET-only — POST/PUT/DELETE must 405."""
    for method in ("POST", "PUT", "DELETE"):
        response = client.request(method, "/api/agents/some-agent/logs", json={})
        assert response.status_code == 405, (
            f"{method} /api/agents/<name>/logs returned {response.status_code} "
            "— unexpected handler registered for mutating method."
        )
