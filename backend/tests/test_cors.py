"""Tests for the frontend CORS configuration (Milestone 7).

The React dev server runs on a different origin than the API, so the
browser will only let it read responses when the backend answers with
matching ``Access-Control-Allow-Origin`` headers. These tests pin the
configured origins and confirm unrelated origins get nothing.
"""

from fastapi.testclient import TestClient

from app.main import create_app

ALLOWED_ORIGIN = "http://localhost:5173"
OTHER_ALLOWED_ORIGIN = "http://127.0.0.1:5173"
DISALLOWED_ORIGIN = "http://evil.example.com"


def test_preflight_from_vite_origin_is_allowed() -> None:
    client = TestClient(create_app())
    response = client.options(
        "/tasks",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN


def test_simple_request_from_vite_origin_carries_header() -> None:
    client = TestClient(create_app())
    response = client.get("/health", headers={"Origin": OTHER_ALLOWED_ORIGIN})
    assert response.status_code == 200
    assert (
        response.headers["access-control-allow-origin"] == OTHER_ALLOWED_ORIGIN
    )


def test_preflight_from_unlisted_origin_is_not_allowed() -> None:
    client = TestClient(create_app())
    response = client.options(
        "/tasks",
        headers={
            "Origin": DISALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
        },
    )
    # Starlette answers a disallowed preflight with 400 and no
    # allow-origin header for that origin.
    assert response.status_code == 400
    assert (
        response.headers.get("access-control-allow-origin")
        != DISALLOWED_ORIGIN
    )
