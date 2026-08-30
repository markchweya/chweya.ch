"""The contradiction review interface, end to end.

Section 9's constraint governs everything here: the detector files findings
and never decides. These tests are the claim that a person can now decide,
that the decision does exactly what the form said it would, and that every
decision is on the audit record.

They run against a real database with findings filed by the real detector,
because a resolution test against a hand-crafted finding proves nothing about
the rows a reviewer will actually see.
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
    ContentStatus,
    ContradictionFinding,
    Document,
    DocumentVersion,
    ReviewState,
    Role,
    User,
    UserRole,
)
from app.db.session import db_session
from app.ingest.contradictions import detect
from app.main import create_app
from app.retrieval.evidence import Confidence, assess
from app.retrieval.search import RetrievedChunk, SearchResult
from app.review import resolution
from app.security.passwords import hash_password

PASSWORD = "correct-horse-battery-staple-77"

# Two passages about the same subject stating different fees. Enough shared
# long terms for the detector to compare them, different enough amounts for a
# finding to be filed.
FIRST = (
    "Die Anmeldung bei der Einwohnerkontrolle der Wohnsitzgemeinde kostet "
    "CHF 20.-- pro Person und ist vor Ort zu entrichten."
)
SECOND = (
    "Die Anmeldung bei der Einwohnerkontrolle der Wohnsitzgemeinde kostet "
    "CHF 120.-- pro Person und ist vor Ort zu entrichten."
)


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
    """A reviewer, who may resolve, and an auditor, who must not."""
    for name in ("super_admin", "reviewer", "auditor"):
        content_db.execute(
            sql("INSERT INTO roles (name, description) VALUES (:n, '') ON CONFLICT DO NOTHING"),
            {"n": name},
        )
    content_db.flush()
    roles = {role.name: role for role in content_db.execute(select(Role)).scalars()}
    built: dict[str, User] = {}
    for role_name in ("super_admin", "reviewer", "auditor"):
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


def seed_documents(db) -> None:  # type: ignore[no-untyped-def]
    """Two approved documents, each one version, each one passage."""
    for index, text in enumerate((FIRST, SECOND)):
        doc_id, version_id = uuid.uuid4(), uuid.uuid4()
        db.execute(
            sql(
                "INSERT INTO documents (id, kind, title, media_type, language,"
                " publication_state, current_version_id, url) "
                "VALUES (:d, 'crawled_page', :t, 'text/html', 'de', 'official', :v, :u)"
            ),
            {
                "d": doc_id,
                "t": f"Seite {index + 1}",
                "v": version_id,
                "u": f"https://www.zug.ch/seite-{index + 1}",
            },
        )
        db.execute(
            sql(
                "INSERT INTO document_versions (id, document_id, version_number,"
                " content_hash, status, extracted_text, extraction_quality,"
                " extraction_notes) "
                "VALUES (:v, :d, 1, :h, 'approved', :t, 'good', '')"
            ),
            {"v": version_id, "d": doc_id, "h": f"hash{index}", "t": text},
        )
        db.execute(
            sql(
                "INSERT INTO chunks (id, version_id, document_id, ordinal, text, language)"
                " VALUES (:c, :v, :d, 0, :t, 'de')"
            ),
            {"c": uuid.uuid4(), "v": version_id, "d": doc_id, "t": text},
        )
    db.commit()


@pytest.fixture
def finding(content_db, users):  # type: ignore[no-untyped-def]
    """One fee finding filed by the real detector."""
    seed_documents(content_db)
    filed = detect(content_db)
    content_db.commit()
    fee = [f for f in filed if f.kind == "fee"]
    assert fee, "the detector must file a fee finding for the seeded passages"
    return fee[0]


def audit_actions(db) -> list[str]:
    return [
        event.action
        for event in db.execute(select(AuditEvent).order_by(AuditEvent.id)).scalars()
    ]


class TestResolutionLogic:
    def test_not_a_contradiction_touches_no_content(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        """The most common outcome must be the least destructive one."""
        problems = resolution.resolve(
            content_db, finding, "not_a_contradiction", actor=users["reviewer"]
        )
        content_db.commit()

        assert problems == []
        assert finding.state == ReviewState.NOT_A_CONTRADICTION.value
        statuses = {
            version.status
            for version in content_db.execute(select(DocumentVersion)).scalars()
        }
        assert statuses == {ContentStatus.APPROVED.value}

    def test_first_current_excludes_the_second_version(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        problems = resolution.resolve(
            content_db,
            finding,
            "resolved_first_current",
            actor=users["reviewer"],
            note="Seite 2 ist veraltet",
        )
        content_db.commit()

        assert problems == []
        context = resolution.load_context(content_db, finding)
        assert context.first_version.status == ContentStatus.APPROVED.value
        assert context.second_version.status == ContentStatus.EXCLUDED.value
        # The excluded version stops being the document's current one.
        assert context.second_document.current_version_id is None
        assert "veraltet" in context.second_version.review_note

    def test_both_excluded_removes_both_versions(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        resolution.resolve(
            content_db,
            finding,
            "resolved_both_excluded",
            actor=users["reviewer"],
            note="Beide Angaben unklar, Rueckfrage laeuft",
        )
        content_db.commit()

        context = resolution.load_context(content_db, finding)
        assert context.first_version.status == ContentStatus.EXCLUDED.value
        assert context.second_version.status == ContentStatus.EXCLUDED.value

    def test_excluding_content_requires_a_reason(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        """Removing official content with no recorded reason leaves nothing
        to revisit when the canton clarifies."""
        problems = resolution.resolve(
            content_db, finding, "resolved_first_current", actor=users["reviewer"], note="  "
        )
        assert problems == ["review.note_required"]
        assert finding.state == ReviewState.OPEN.value

    def test_unresolved_keeps_the_finding_open(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        resolution.resolve(
            content_db, finding, "unresolved", actor=users["reviewer"], note="Kanton gefragt"
        )
        content_db.commit()

        assert ReviewState(finding.state).is_open
        # And it can be decided later, when the canton answers.
        problems = resolution.resolve(
            content_db, finding, "not_a_contradiction", actor=users["reviewer"]
        )
        assert problems == []

    def test_a_decided_finding_stays_decided(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        """A second reviewer must not silently overrule the first."""
        resolution.resolve(
            content_db, finding, "not_a_contradiction", actor=users["reviewer"]
        )
        problems = resolution.resolve(
            content_db,
            finding,
            "resolved_first_current",
            actor=users["super_admin"],
            note="doch",
        )
        assert problems == ["review.already_decided"]
        assert finding.state == ReviewState.NOT_A_CONTRADICTION.value

    def test_an_unknown_outcome_is_refused(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        assert resolution.resolve(
            content_db, finding, "delete_everything", actor=users["reviewer"]
        ) == ["review.unknown_outcome"]
        # OPEN and IN_REVIEW are machinery, not decisions a form may submit.
        assert resolution.resolve(
            content_db, finding, "open", actor=users["reviewer"]
        ) == ["review.unknown_outcome"]

    def test_every_decision_is_audited(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        resolution.resolve(
            content_db,
            finding,
            "resolved_both_excluded",
            actor=users["reviewer"],
            note="Beide unklar",
        )
        content_db.commit()

        actions = audit_actions(content_db)
        assert actions.count(AuditAction.CONTENT_EXCLUDED.value) == 2
        assert AuditAction.CONTRADICTION_RESOLVED.value in actions

    def test_an_already_excluded_version_is_not_reclassified(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        """Resolving an old finding must not rewrite content history."""
        context = resolution.load_context(content_db, finding)
        context.second_version.status = ContentStatus.SUPERSEDED.value
        content_db.flush()

        resolution.resolve(
            content_db,
            finding,
            "resolved_first_current",
            actor=users["reviewer"],
            note="Seite 2 ist veraltet",
        )
        content_db.commit()
        assert context.second_version.status == ContentStatus.SUPERSEDED.value


class TestConfidenceEffect:
    """Section 9: answers touching an open finding must say so."""

    def _result(self) -> SearchResult:
        import datetime as dt

        def chunk(text: str, rank: int) -> RetrievedChunk:
            return RetrievedChunk(
                chunk_id=uuid.uuid4(),
                document_id=uuid.uuid4(),
                version_id=uuid.uuid4(),
                text=text,
                language="de",
                section_path=(),
                page_number=None,
                anchor=None,
                document_title=f"Seite {rank}",
                document_url=None,
                document_language="de",
                department=None,
                last_verified_at=dt.datetime.now(dt.UTC),
                semantic_rank=rank,
                keyword_rank=rank,
                fused_score=1.0 / rank,
            )

        return SearchResult(chunks=[chunk(FIRST, 1), chunk(SECOND, 2)])

    def test_an_open_contradiction_caps_confidence_at_low(self) -> None:
        clean = assess(self._result(), "Was kostet die Anmeldung?")
        contradicted = assess(
            self._result(), "Was kostet die Anmeldung?", open_contradictions=1
        )
        assert clean.confidence is not Confidence.LOW
        assert contradicted.confidence is Confidence.LOW
        assert "sources_inconsistent" in contradicted.reasons

    def test_the_inconsistency_reaches_the_person_as_a_notice(self) -> None:
        from app.retrieval.answer import _notices_for

        contradicted = assess(
            self._result(), "Was kostet die Anmeldung?", open_contradictions=1
        )
        assert "answer.sources_inconsistent" in _notices_for(contradicted)

    def test_resolving_the_finding_removes_the_qualification(
        self, content_db, users, finding
    ) -> None:  # type: ignore[no-untyped-def]
        """The whole point of the queue: a decision changes what residents see."""
        from app.ingest.contradictions import open_findings_for_chunks

        chunk_ids = [finding.first_chunk_id, finding.second_chunk_id]
        assert open_findings_for_chunks(content_db, chunk_ids) == 1

        resolution.resolve(
            content_db, finding, "not_a_contradiction", actor=users["reviewer"]
        )
        content_db.commit()
        assert open_findings_for_chunks(content_db, chunk_ids) == 0

    def test_unresolved_keeps_the_qualification(self, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        from app.ingest.contradictions import open_findings_for_chunks

        resolution.resolve(
            content_db, finding, "unresolved", actor=users["reviewer"]
        )
        content_db.commit()
        assert (
            open_findings_for_chunks(
                content_db, [finding.first_chunk_id, finding.second_chunk_id]
            )
            == 1
        )


@pytest.fixture
def client(content_db, users):  # type: ignore[no-untyped-def]
    app = create_app()
    app.dependency_overrides[db_session] = lambda: content_db
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def sign_in(client, role: str) -> None:
    response = client.post(
        "/admin/login", data={"email": f"{role}@example.ch", "password": PASSWORD}
    )
    assert response.status_code == 303


class TestRoutes:
    def test_the_queue_requires_a_session(self, client) -> None:  # type: ignore[no-untyped-def]
        assert client.get("/admin/review").status_code == 401

    def test_an_auditor_cannot_open_the_queue(self, client) -> None:  # type: ignore[no-untyped-def]
        """The auditor's inability to change anything is the point of the role."""
        sign_in(client, "auditor")
        assert client.get("/admin/review").status_code == 403

    def test_a_reviewer_sees_the_queue(self, client, finding) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "reviewer")
        response = client.get("/admin/review")
        assert response.status_code == 200
        assert "fee" in response.text

    def test_the_detail_page_shows_both_passages_in_full(self, client, finding) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "reviewer")
        response = client.get(f"/admin/review/{finding.id}")
        assert response.status_code == 200
        assert "CHF 20.--" in response.text
        assert "CHF 120.--" in response.text

    def test_a_reviewer_resolves_through_the_form(self, client, content_db, finding) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "reviewer")
        response = client.post(
            f"/admin/review/{finding.id}/resolve",
            data={"outcome": "not_a_contradiction", "note": "Zwei Gemeinden"},
        )
        assert response.status_code == 303

        content_db.expire_all()
        row = content_db.get(ContradictionFinding, finding.id)
        assert row.state == ReviewState.NOT_A_CONTRADICTION.value
        assert row.reviewer_note == "Zwei Gemeinden"

    def test_an_auditor_cannot_resolve(self, client, content_db, finding) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "auditor")
        response = client.post(
            f"/admin/review/{finding.id}/resolve",
            data={"outcome": "not_a_contradiction", "note": ""},
        )
        assert response.status_code == 403

        content_db.expire_all()
        assert (
            content_db.get(ContradictionFinding, finding.id).state
            == ReviewState.OPEN.value
        )

    def test_a_refused_resolution_reports_why(self, client, content_db, finding) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "reviewer")
        response = client.post(
            f"/admin/review/{finding.id}/resolve",
            data={"outcome": "resolved_both_excluded", "note": ""},
        )
        assert response.status_code == 303
        assert "review.note_required" in response.headers["location"]

    def test_claiming_marks_a_finding_in_review(self, client, content_db, finding) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "reviewer")
        response = client.post(f"/admin/review/{finding.id}/claim")
        assert response.status_code == 303

        content_db.expire_all()
        assert (
            content_db.get(ContradictionFinding, finding.id).state
            == ReviewState.IN_REVIEW.value
        )

    def test_detection_can_be_run_from_the_interface(self, client, content_db, users) -> None:  # type: ignore[no-untyped-def]
        seed_documents(content_db)
        sign_in(client, "reviewer")
        response = client.post("/admin/review/detect")
        assert response.status_code == 303

        content_db.expire_all()
        filed = content_db.execute(select(ContradictionFinding)).scalars().all()
        assert filed
        assert AuditAction.CONTRADICTION_DETECTION_RUN.value in audit_actions(content_db)

    def test_a_decided_finding_shows_no_decision_form(self, client, content_db, users, finding) -> None:  # type: ignore[no-untyped-def]
        resolution.resolve(
            content_db, finding, "not_a_contradiction", actor=users["reviewer"]
        )
        content_db.commit()

        sign_in(client, "reviewer")
        response = client.get(f"/admin/review/{finding.id}")
        assert response.status_code == 200
        assert "Record decision" not in response.text
        assert "stays decided" in response.text
