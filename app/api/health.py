"""Health and readiness endpoints.

Two different questions, deliberately separate:

* ``/healthz`` asks whether the process is alive. It touches nothing external,
  so a database outage does not cause an orchestrator to kill and restart
  every application container, which would turn a recoverable dependency
  failure into an outage.
* ``/readyz`` asks whether the process can serve traffic. It checks each
  dependency and reports per-component detail.

Neither endpoint requires authentication, so neither may disclose version
numbers, hostnames, connection strings or dependency versions. An attacker
learning the exact PostgreSQL build is a free hint.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import text

from app.db.session import get_engine
from app.llm.apertus import ApertusProvider
from app.llm.base import HealthState
from app.observability import get_logger

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


@router.get("/healthz", summary="Liveness probe")
async def healthz() -> dict[str, str]:
    """Report that the process is running. Checks no dependency."""
    return {"status": "alive"}


def _check_database() -> dict[str, Any]:
    """Confirm the database answers a trivial query."""
    started = time.perf_counter()
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - the endpoint must not raise
        # The exception type only. A connection error message can contain the
        # host, port and username from the DSN.
        return {"status": "unavailable", "detail": type(exc).__name__}
    return {"status": "ok", "latency_ms": round((time.perf_counter() - started) * 1000, 1)}


def _check_migrations() -> dict[str, Any]:
    """Confirm migrations have been applied.

    A database that is reachable but has no schema is a common and confusing
    deployment state. Reporting it separately turns "everything is broken"
    into "run the migrations".
    """
    try:
        with get_engine().connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001
        return {"status": "unavailable", "detail": type(exc).__name__}
    if revision is None:
        return {"status": "unavailable", "detail": "no migration has been applied"}
    return {"status": "ok", "revision": revision}


async def _check_apertus() -> dict[str, Any]:
    """Ask the model provider whether it is reachable."""
    provider = ApertusProvider()
    try:
        health = await provider.health()
    finally:
        await provider.aclose()

    status = {
        HealthState.HEALTHY: "ok",
        HealthState.DEGRADED: "degraded",
        HealthState.UNAVAILABLE: "unavailable",
    }[health.state]
    result: dict[str, Any] = {"status": status, "detail": health.detail}
    if health.latency_ms is not None:
        result["latency_ms"] = round(health.latency_ms, 1)
    return result


@router.get("/readyz", summary="Readiness probe")
async def readyz(response: Response) -> dict[str, Any]:
    """Report whether every dependency needed to serve traffic is available.

    Returns 503 when a required dependency is down, so a load balancer removes
    this instance rather than sending it requests it cannot answer.

    Apertus being unavailable is reported but does not make the service
    unready. The site still serves pages, and the chat endpoint returns an
    honest "the assistant is unavailable" message, which is better than the
    whole application disappearing from the pool.
    """
    checks = {
        "database": _check_database(),
        "migrations": _check_migrations(),
        "apertus": await _check_apertus(),
    }

    required = ("database", "migrations")
    ready = all(checks[name]["status"] == "ok" for name in required)

    if not ready:
        response.status_code = 503

    return {"status": "ready" if ready else "not_ready", "checks": checks}
