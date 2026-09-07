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


def test_the_schema_check_finds_nothing_missing_on_a_migrated_database(db) -> None:  # type: ignore[no-untyped-def]
    """The test database is migrated to head, so the startup check that warns
    about pending migrations must be quiet here; a false alarm on every
    start would teach operators to ignore it."""
    from app.db.schema import schema_lag

    assert schema_lag(db.get_bind()) is None


async def test_a_tight_context_window_is_named_at_startup(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A window too small to hold evidence produced answers built from the
    wrong pages. The setting is legal, so startup reports it rather than
    refusing; this pins that it is actually reported."""
    import structlog
    from fastapi import FastAPI

    from app import main as app_main
    from app.config import Environment, Settings

    def settings_with(context: int) -> Settings:
        return Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment=Environment.DEVELOPMENT,
            secret_key="a-development-secret-key-long-enough-00",
            database_url="postgresql+psycopg://u:p@127.0.0.1:1/none",
            apertus_max_context_tokens=context,
        )

    async def events_for(context: int) -> list[str]:
        monkeypatch.setattr(app_main, "get_settings", lambda: settings_with(context))
        # Startup reconfigures structlog, which would replace the capture.
        monkeypatch.setattr(app_main, "configure_logging", lambda: None)
        # The application caches bound loggers on first use, so a logger
        # bound by an earlier test would bypass the capture entirely.
        structlog.reset_defaults()
        monkeypatch.setattr(app_main, "logger", structlog.get_logger("app.main"))
        with structlog.testing.capture_logs() as captured:
            async with app_main.lifespan(FastAPI()):
                pass
        return [entry["event"] for entry in captured]

    try:
        assert "apertus.context_window_tight" in await events_for(3072)
        assert "apertus.context_window_tight" not in await events_for(4096)
    finally:
        # structlog is global: leave it as the rest of the suite expects.
        from app.observability import configure_logging

        configure_logging()
