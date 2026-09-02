"""Creating sources and starting crawls from the interface.

The allowlist rule is the one worth defending hardest: the form can narrow
what is crawled but must never widen it beyond the hosts the deployment
permits. Someone with the source permission does not thereby gain the power
to point the crawler at an arbitrary website.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import text as sql

from app.db.models import (
    AuditAction,
    AuditEvent,
    CrawlRun,
    CrawlRunState,
    Role,
    Source,
    User,
    UserRole,
)
from app.db.session import db_session
from app.ingest import runner
from app.main import create_app
from app.security.passwords import hash_password

PASSWORD = "correct-horse-battery-staple-77"


@pytest.fixture
def content_db(db):  # type: ignore[no-untyped-def]
    db.execute(
        sql(
            "TRUNCATE upload_jobs, contradiction_findings, chunks, document_versions, "
            "documents, crawled_urls, crawl_runs, sources CASCADE"
        )
    )
    db.commit()
    return db


@pytest.fixture
def users(content_db):  # type: ignore[no-untyped-def]
    for name in ("content_admin", "auditor"):
        content_db.execute(
            sql("INSERT INTO roles (name, description) VALUES (:n, '') ON CONFLICT DO NOTHING"),
            {"n": name},
        )
    content_db.flush()
    roles = {role.name: role for role in content_db.execute(select(Role)).scalars()}
    built: dict[str, User] = {}
    for role_name in ("content_admin", "auditor"):
        user = User(
            email=f"{role_name}@example.ch",
            password_hash=hash_password(PASSWORD),
            must_change_password=False,
            is_active=True,
        )
        content_db.add(user)
        content_db.flush()
        content_db.add(UserRole(user_id=user.id, role_id=roles[role_name].id))
        built[role_name] = user
    content_db.commit()
    return built


@pytest.fixture
def client(content_db, users, monkeypatch):  # type: ignore[no-untyped-def]
    """A client whose crawl scheduling is observed rather than executed.

    The crawl itself is covered end to end in test_crawler.py against a mock
    site. Here the claim under test is the interface: authorisation,
    validation, the run guard, and the audit trail.
    """
    scheduled: list[uuid.UUID] = []

    async def fake_run(source_id, triggered_by_id):  # type: ignore[no-untyped-def]
        scheduled.append(source_id)

    monkeypatch.setattr(runner, "_run_crawl", fake_run)
    runner._active.clear()

    app = create_app()
    app.dependency_overrides[db_session] = lambda: content_db
    with TestClient(app, follow_redirects=False) as test_client:
        test_client.scheduled = scheduled  # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    runner._active.clear()


def sign_in(client, role: str) -> None:
    response = client.post(
        "/admin/login", data={"email": f"{role}@example.ch", "password": PASSWORD}
    )
    assert response.status_code == 303


def create(client, **overrides):  # type: ignore[no-untyped-def]
    fields = {
        "name": "Behoerden",
        "canton": "zug",
        "base_url": "https://www.zug.ch/behoerden",
        "default_language": "de",
        "department": "",
        "excluded_paths": "",
    }
    fields.update(overrides)
    return client.post("/admin/sources", data=fields)


class TestSourceCreation:
    def test_a_source_on_an_allowed_host_is_created(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "content_admin")
        response = create(client)
        assert response.status_code == 303
        assert "message=source.created" in response.headers["location"]

        source = content_db.execute(select(Source)).scalars().one()
        assert source.base_url == "https://www.zug.ch/behoerden"

    def test_a_host_off_the_allowlist_is_refused(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        """The form narrows the crawl; it never widens it."""
        sign_in(client, "content_admin")
        response = create(client, base_url="https://www.evil.example/anything")
        assert "source.host_not_allowed" in response.headers["location"]
        assert content_db.execute(select(Source)).scalars().all() == []

    def test_a_lookalike_host_is_refused(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        """zug.ch.evil.example must not pass as zug.ch."""
        sign_in(client, "content_admin")
        response = create(client, base_url="https://www.zug.ch.evil.example/x")
        assert "source.host_not_allowed" in response.headers["location"]

    def test_plain_http_is_refused(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "content_admin")
        response = create(client, base_url="http://www.zug.ch/behoerden")
        assert "source.invalid_url" in response.headers["location"]

    def test_a_duplicate_base_url_is_refused(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "content_admin")
        create(client)
        response = create(client, name="Nochmal")
        assert "source.duplicate" in response.headers["location"]

    def test_creation_is_audited(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "content_admin")
        create(client)
        actions = [
            event.action
            for event in content_db.execute(select(AuditEvent)).scalars()
        ]
        assert AuditAction.SOURCE_CREATED.value in actions

    def test_an_auditor_cannot_create_a_source(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "auditor")
        assert create(client).status_code == 403


class TestCrawlButton:
    def source(self, client, content_db) -> Source:  # type: ignore[no-untyped-def]
        sign_in(client, "content_admin")
        create(client)
        return content_db.execute(select(Source)).scalars().one()

    def test_the_button_schedules_a_crawl(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        source = self.source(client, content_db)
        response = client.post(f"/admin/sources/{source.id}/crawl")
        assert response.status_code == 303
        assert "message=crawl.started" in response.headers["location"]
        assert client.scheduled == [source.id]

    def test_a_second_click_does_not_start_a_second_crawl(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        source = self.source(client, content_db)
        client.post(f"/admin/sources/{source.id}/crawl")
        response = client.post(f"/admin/sources/{source.id}/crawl")
        assert "crawl.already_running" in response.headers["location"]
        assert client.scheduled == [source.id]

    def test_a_paused_source_is_not_crawled(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        source = self.source(client, content_db)
        source.is_paused = True
        content_db.commit()
        response = client.post(f"/admin/sources/{source.id}/crawl")
        assert "crawl.source_paused" in response.headers["location"]
        assert client.scheduled == []

    def test_an_auditor_cannot_start_a_crawl(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        source = self.source(client, content_db)
        sign_in(client, "auditor")
        assert client.post(f"/admin/sources/{source.id}/crawl").status_code == 403
        assert client.scheduled == []


class TestOrphanedRuns:
    def test_startup_repairs_runs_a_dead_process_left_running(self, content_db, users) -> None:  # type: ignore[no-untyped-def]
        source = Source(name="S", base_url="https://www.zug.ch/x", default_language="de")
        content_db.add(source)
        content_db.flush()
        content_db.add(
            CrawlRun(source_id=source.id, state=CrawlRunState.RUNNING.value)
        )
        content_db.commit()

        repaired = runner.fail_orphaned_runs(content_db)
        content_db.commit()

        assert repaired == 1
        run = content_db.execute(select(CrawlRun)).scalars().one()
        assert run.state == CrawlRunState.FAILED.value
        assert "restarted" in run.error_summary

    def test_a_repaired_source_can_be_crawled_again(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "content_admin")
        create(client)
        source = content_db.execute(select(Source)).scalars().one()
        content_db.add(CrawlRun(source_id=source.id, state=CrawlRunState.RUNNING.value))
        content_db.commit()

        blocked = client.post(f"/admin/sources/{source.id}/crawl")
        assert "crawl.already_running" in blocked.headers["location"]

        runner.fail_orphaned_runs(content_db)
        content_db.commit()

        allowed = client.post(f"/admin/sources/{source.id}/crawl")
        assert "message=crawl.started" in allowed.headers["location"]


class TestRunVisibility:
    async def test_commit_start_makes_the_running_row_visible(self, content_db, users) -> None:  # type: ignore[no-untyped-def]
        """The RUNNING state must be committed before crawling begins, or no
        other session can see that a crawl is underway: the sources page
        would show nothing and a second process could start a duplicate."""
        from app.config import Settings
        from app.ingest.crawler import Crawler
        from app.ingest.fetcher import GuardedFetcher

        source = Source(
            name="S",
            base_url="https://www.zug.ch/x",
            default_language="de",
            is_paused=True,  # returns right after the start bookkeeping
        )
        content_db.add(source)
        content_db.commit()

        settings = Settings(  # type: ignore[call-arg]
            _env_file=None,
            secret_key="test-secret-key-of-adequate-length-000000",
            database_url="postgresql+psycopg://u:p@localhost:5432/d",
            crawler_allowed_hosts="www.zug.ch",
            crawler_contact="test@example.ch",
        )
        fetcher = GuardedFetcher(settings=settings)
        try:
            await Crawler(content_db, fetcher, settings=settings).run(
                source, commit_start=True
            )
        finally:
            await fetcher.aclose()

        # Everything after the start commit is discarded; the committed
        # RUNNING row must survive, which is exactly what another session
        # would have seen mid-crawl.
        content_db.rollback()
        run = content_db.execute(select(CrawlRun)).scalars().one()
        assert run.state == CrawlRunState.RUNNING.value
