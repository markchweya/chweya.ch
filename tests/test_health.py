"""Health and readiness endpoint behaviour."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_touches_no_dependency() -> None:
    """Liveness must not depend on the database.

    If it did, a database outage would make an orchestrator kill and restart
    every container, turning a recoverable dependency failure into an outage.
    """
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_security_headers_present_on_every_response() -> None:
    with TestClient(create_app()) as client:
        headers = client.get("/healthz").headers

    csp = headers["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "object-src 'none'" in csp
    # The application renders text extracted from crawled pages and PDFs. If
    # cleaning ever lets markup through, this is what stops it executing.
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]

    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "geolocation=()" in headers["Permissions-Policy"]


def test_request_id_is_returned() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz")
    assert response.headers["X-Request-ID"]


def test_supplied_request_id_is_echoed_when_it_looks_safe() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Request-ID": "abc123def456"})
    assert response.headers["X-Request-ID"] == "abc123def456"


def test_hostile_request_id_is_replaced_not_reflected() -> None:
    """Reflecting arbitrary client input would be header and log injection."""
    hostile = "abc\r\nSet-Cookie: admin=1"
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Request-ID": hostile})

    returned = response.headers["X-Request-ID"]
    assert returned != hostile
    assert "\r" not in returned and "\n" not in returned
    assert returned.isalnum()


def test_overlong_request_id_is_replaced() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/healthz", headers={"X-Request-ID": "a" * 500})
    assert len(response.headers["X-Request-ID"]) <= 64


def test_readyz_reports_each_dependency() -> None:
    """Readiness names the failing component, so an operator knows what to fix."""
    with TestClient(create_app()) as client:
        body = client.get("/readyz").json()

    assert set(body["checks"]) == {"database", "migrations", "apertus"}
    # Whatever the state, no check may leak connection detail.
    for check in body["checks"].values():
        detail = str(check.get("detail", ""))
        assert "postgresql://" not in detail
        assert "password" not in detail.lower()
