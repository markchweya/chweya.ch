"""The document upload workflow, end to end, against a real database.

Section 16 requires that an administrator can upload a document, correct its
metadata, preview what was extracted, approve it, replace it while keeping the
history, withdraw it and delete it. Section 13 requires that every one of
those actions is on the audit record.

These tests are that claim. They run the real pipeline against a real
PostgreSQL database and a real temporary storage tree; nothing about
validation, storage or persistence is mocked.
"""

from __future__ import annotations

import io
import pathlib
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import text as sql

from app.config import Settings
from app.db.models import (
    AuditAction,
    AuditEvent,
    Chunk,
    ContentStatus,
    Document,
    DocumentVersion,
    PublicationState,
    Role,
    UploadJob,
    UploadState,
    User,
    UserRole,
)
from app.db.session import db_session
from app.main import create_app
from app.security.passwords import hash_password
from app.uploads import pipeline
from app.uploads.pipeline import DocumentMetadata
from app.uploads.storage import DocumentStore

PASSWORD = "correct-horse-battery-staple-77"

ANMELDUNG = (
    b"Anmeldung bei der Einwohnerkontrolle\n\n"
    b"Sie muessen sich innert 14 Tagen nach dem Zuzug bei der Einwohnerkontrolle "
    b"der Wohnsitzgemeinde anmelden. Bringen Sie den Heimatschein, einen "
    b"gueltigen Ausweis und den Mietvertrag mit.\n\n"
    b"Die Anmeldung kostet CHF 20.-- pro Person und ist vor Ort zu entrichten. "
    b"Fuer auslaendische Staatsangehoerige gelten abweichende Fristen."
)

ANMELDUNG_NEU = ANMELDUNG.replace(b"14 Tagen", b"acht Tagen")


def make_settings(tmp_path: pathlib.Path, **overrides: object) -> Settings:
    """Settings pointing at a temporary storage tree.

    _env_file=None so the outcome does not depend on the developer's local
    .env, and no malware scanner, which is what a development environment
    looks like.
    """
    (tmp_path / "accepted").mkdir(exist_ok=True)
    (tmp_path / "quarantine").mkdir(exist_ok=True)
    base: dict[str, object] = {
        "secret_key": "test-secret-key-of-adequate-length-000000",
        "database_url": "postgresql+psycopg://u:p@localhost:5432/d",
        "upload_storage_path": str(tmp_path / "accepted"),
        "upload_quarantine_path": str(tmp_path / "quarantine"),
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.fixture
def content_db(db):  # type: ignore[no-untyped-def]
    """The shared session with the content and upload tables emptied.

    The conftest fixture truncates identity tables only, and an upload leaves
    rows in five more.
    """
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
    """One account per role the upload routes distinguish."""
    for name in ("super_admin", "content_admin", "reviewer", "auditor"):
        content_db.execute(
            sql("INSERT INTO roles (name, description) VALUES (:n, '') ON CONFLICT DO NOTHING"),
            {"n": name},
        )
    content_db.flush()

    roles = {role.name: role for role in content_db.execute(select(Role)).scalars()}
    built: dict[str, User] = {}
    for role_name in ("super_admin", "content_admin", "reviewer", "auditor"):
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
def env(content_db, users, tmp_path):  # type: ignore[no-untyped-def]
    """Settings, a store and the accounts, ready for a pipeline call."""
    settings = make_settings(tmp_path)
    return settings, DocumentStore(settings), users


def upload(env, content_db, data: bytes = ANMELDUNG, name: str = "anmeldung.txt", **kwargs):  # type: ignore[no-untyped-def]
    settings, store, users = env
    return pipeline.receive_upload(
        content_db,
        filename=name,
        declared_media_type=kwargs.pop("media_type", "text/plain"),
        data=data,
        actor=kwargs.pop("actor", users["content_admin"]),
        settings=settings,
        store=store,
        **kwargs,
    )


def complete_metadata(content_db, job, users, **overrides):  # type: ignore[no-untyped-def]
    fields: dict[str, object] = {
        "title": "Anmeldung bei der Einwohnerkontrolle",
        "department": "Einwohnerkontrolle",
        "language": "de",
        "publication_state": PublicationState.OFFICIAL.value,
    }
    fields.update(overrides)
    return pipeline.apply_metadata(
        content_db,
        job,
        DocumentMetadata(**fields),  # type: ignore[arg-type]
        actor=users["content_admin"],
    )


def audit_actions(content_db) -> list[str]:
    return [
        event.action
        for event in content_db.execute(
            select(AuditEvent).order_by(AuditEvent.id)
        ).scalars()
    ]


class TestReceiving:
    def test_an_accepted_upload_produces_a_document_and_chunks(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        content_db.commit()

        assert outcome.accepted
        assert outcome.job.state == UploadState.AWAITING_METADATA.value
        assert outcome.job.document_id is not None

        chunks = content_db.execute(
            select(Chunk).where(Chunk.version_id == outcome.job.version_id)
        ).scalars()
        texts = [chunk.text for chunk in chunks]
        assert texts
        assert any("CHF 20.--" in text for text in texts)

    def test_an_uploaded_version_is_never_approved_on_arrival(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        """The difference from a crawled page: nobody can check the source."""
        outcome = upload(env, content_db)
        version = content_db.get(DocumentVersion, outcome.job.version_id)
        assert version.status == ContentStatus.AWAITING_REVIEW.value

    def test_an_uploaded_document_starts_as_a_draft(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        """It claims nothing until a person says what it is."""
        outcome = upload(env, content_db)
        document = content_db.get(Document, outcome.job.document_id)
        assert document.publication_state == PublicationState.DRAFT.value

    def test_the_file_leaves_quarantine_only_after_the_scan(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        settings, store, _ = env
        outcome = upload(env, content_db)
        assert outcome.job.is_quarantined is False
        assert store.exists(outcome.job.storage_path, quarantined=False)
        assert not store.exists(outcome.job.storage_path, quarantined=True)

    def test_a_refused_file_keeps_no_bytes(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(
            env, content_db, data=b"MZ\x90\x00" + b"\x00" * 400, name="bericht.pdf",
            media_type="application/pdf",
        )
        content_db.commit()

        assert not outcome.accepted
        assert outcome.job.state == UploadState.REFUSED.value
        assert outcome.job.refusal_reason == "refused_windows_executable"
        assert outcome.job.storage_path is None
        assert outcome.job.document_id is None

    def test_a_refusal_is_still_recorded(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        """Section 13: the attempt is the thing worth having on record."""
        upload(env, content_db, data=b"MZ\x90\x00" + b"\x00" * 400, name="bericht.pdf")
        content_db.commit()
        assert AuditAction.DOCUMENT_UPLOADED.value in audit_actions(content_db)

    def test_an_infected_file_is_deleted_and_recorded(self, content_db, users, tmp_path) -> None:  # type: ignore[no-untyped-def]
        """Exit code 1 is a detection. The bytes go, the record stays."""
        settings = make_settings(tmp_path, malware_scanner_command="/bin/false")
        store = DocumentStore(settings)

        outcome = pipeline.receive_upload(
            content_db,
            filename="anmeldung.txt",
            declared_media_type="text/plain",
            data=ANMELDUNG,
            actor=users["content_admin"],
            settings=settings,
            store=store,
        )
        content_db.commit()

        assert not outcome.accepted
        assert outcome.job.state == UploadState.INFECTED.value
        assert outcome.job.storage_path is None
        assert list(tmp_path.glob("quarantine/*/*")) == []
        assert AuditAction.DOCUMENT_QUARANTINED.value in audit_actions(content_db)

    def test_a_scanner_that_cannot_decide_holds_the_file_in_quarantine(
        self, content_db, users, tmp_path
    ) -> None:  # type: ignore[no-untyped-def]
        """A failed scan is not a detection. Deleting would destroy the only copy."""
        settings = make_settings(tmp_path, malware_scanner_command="/nonexistent/clamscan")
        store = DocumentStore(settings)

        outcome = pipeline.receive_upload(
            content_db,
            filename="anmeldung.txt",
            declared_media_type="text/plain",
            data=ANMELDUNG,
            actor=users["content_admin"],
            settings=settings,
            store=store,
        )
        content_db.commit()

        assert outcome.job.state == UploadState.SCAN_FAILED.value
        assert outcome.job.storage_path is not None
        assert store.exists(outcome.job.storage_path, quarantined=True)

    def test_a_file_with_no_extractable_text_does_not_become_a_document(
        self, env, content_db
    ) -> None:  # type: ignore[no-untyped-def]
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")

        outcome = upload(
            env,
            content_db,
            data=buffer.getvalue(),
            name="leer.docx",
            media_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
        )
        content_db.commit()

        assert outcome.job.state == UploadState.EXTRACTION_FAILED.value
        assert outcome.job.document_id is None

    def test_the_same_bytes_uploaded_twice_are_recognised(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        first = upload(env, content_db)
        content_db.commit()
        found = pipeline.find_duplicate(content_db, first.job.content_hash)
        assert found is not None
        assert found.id == first.job.id


class TestMetadata:
    def test_incomplete_metadata_is_refused_with_reasons(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        problems = complete_metadata(
            content_db, outcome.job, env[2], title="", department=""
        )
        assert "upload.metadata.title_required" in problems
        assert "upload.metadata.department_required" in problems

    def test_a_reversed_validity_range_is_refused(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        import datetime as dt

        outcome = upload(env, content_db)
        problems = complete_metadata(
            content_db,
            outcome.job,
            env[2],
            valid_from=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
            valid_until=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        )
        assert problems == ["upload.metadata.validity_reversed"]

    def test_complete_metadata_moves_the_upload_to_awaiting_approval(
        self, env, content_db
    ) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        assert complete_metadata(content_db, outcome.job, env[2]) == []
        content_db.commit()

        assert outcome.job.state == UploadState.AWAITING_APPROVAL.value
        document = content_db.get(Document, outcome.job.document_id)
        assert document.department == "Einwohnerkontrolle"
        assert document.publication_state == PublicationState.OFFICIAL.value

    def test_correcting_the_language_re_stems_the_passages(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        """A German passage indexed as French is never found again."""
        outcome = upload(env, content_db)
        complete_metadata(content_db, outcome.job, env[2], language="fr")
        content_db.commit()

        languages = {
            chunk.language
            for chunk in content_db.execute(
                select(Chunk).where(Chunk.version_id == outcome.job.version_id)
            ).scalars()
        }
        assert languages == {"fr"}


class TestApproval:
    def test_approval_puts_the_version_into_the_index(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        complete_metadata(content_db, outcome.job, env[2])
        assert pipeline.approve(content_db, outcome.job, actor=env[2]["super_admin"]) == []
        content_db.commit()

        version = content_db.get(DocumentVersion, outcome.job.version_id)
        document = content_db.get(Document, outcome.job.document_id)
        assert version.status == ContentStatus.APPROVED.value
        assert document.current_version_id == version.id
        assert outcome.job.state == UploadState.APPROVED.value

    def test_a_draft_cannot_be_approved_into_the_public_index(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        complete_metadata(
            content_db, outcome.job, env[2], publication_state=PublicationState.DRAFT.value
        )
        problems = pipeline.approve(content_db, outcome.job, actor=env[2]["super_admin"])
        assert problems == ["upload.approve.not_public_state"]

    def test_an_internal_document_cannot_be_approved(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        complete_metadata(
            content_db,
            outcome.job,
            env[2],
            publication_state=PublicationState.INTERNAL.value,
        )
        assert pipeline.approve(content_db, outcome.job, actor=env[2]["super_admin"]) == [
            "upload.approve.not_public_state"
        ]

    def test_approval_before_metadata_is_refused(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        assert pipeline.approve(content_db, outcome.job, actor=env[2]["super_admin"]) == [
            "upload.approve.wrong_state"
        ]

    def test_approval_is_audited(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        complete_metadata(content_db, outcome.job, env[2])
        pipeline.approve(content_db, outcome.job, actor=env[2]["super_admin"])
        content_db.commit()
        assert AuditAction.DOCUMENT_APPROVED.value in audit_actions(content_db)


class TestReplacement:
    def approved(self, env, content_db):  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        complete_metadata(content_db, outcome.job, env[2])
        pipeline.approve(content_db, outcome.job, actor=env[2]["super_admin"])
        content_db.commit()
        return outcome.job

    def test_a_replacement_becomes_a_further_version_of_the_same_document(
        self, env, content_db
    ) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        first = self.approved(env, content_db)

        outcome = pipeline.replace(
            content_db,
            first,
            filename="anmeldung-2026.txt",
            declared_media_type="text/plain",
            data=ANMELDUNG_NEU,
            actor=users["content_admin"],
            settings=settings,
            store=store,
        )
        content_db.commit()

        assert outcome.accepted
        assert outcome.job.document_id == first.document_id
        assert outcome.job.replaces_id == first.id

        version = content_db.get(DocumentVersion, outcome.job.version_id)
        assert version.version_number == 2

    def test_the_previous_version_survives_a_replacement(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        """A citation issued last week has to stay explicable."""
        settings, store, users = env
        first = self.approved(env, content_db)
        old_version_id = first.version_id

        pipeline.replace(
            content_db,
            first,
            filename="anmeldung-2026.txt",
            declared_media_type="text/plain",
            data=ANMELDUNG_NEU,
            actor=users["content_admin"],
            settings=settings,
            store=store,
        )
        content_db.commit()

        old = content_db.get(DocumentVersion, old_version_id)
        assert old is not None
        assert old.extracted_text
        assert first.state == UploadState.REPLACED.value

    def test_approving_a_replacement_supersedes_the_old_version(
        self, env, content_db
    ) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        first = self.approved(env, content_db)
        old_version_id = first.version_id

        outcome = pipeline.replace(
            content_db,
            first,
            filename="anmeldung-2026.txt",
            declared_media_type="text/plain",
            data=ANMELDUNG_NEU,
            actor=users["content_admin"],
            settings=settings,
            store=store,
        )
        assert pipeline.approve(content_db, outcome.job, actor=users["super_admin"]) == []
        content_db.commit()

        old = content_db.get(DocumentVersion, old_version_id)
        document = content_db.get(Document, outcome.job.document_id)
        assert old.status == ContentStatus.SUPERSEDED.value
        assert document.current_version_id == outcome.job.version_id

    def test_a_refused_replacement_leaves_the_document_in_place(
        self, env, content_db
    ) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        first = self.approved(env, content_db)

        outcome = pipeline.replace(
            content_db,
            first,
            filename="virus.pdf",
            declared_media_type="application/pdf",
            data=b"MZ\x90\x00" + b"\x00" * 400,
            actor=users["content_admin"],
            settings=settings,
            store=store,
        )
        content_db.commit()

        assert not outcome.accepted
        assert first.state == UploadState.APPROVED.value
        document = content_db.get(Document, first.document_id)
        assert document.current_version_id == first.version_id

    def test_a_replacement_is_audited(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        first = self.approved(env, content_db)
        pipeline.replace(
            content_db,
            first,
            filename="anmeldung-2026.txt",
            declared_media_type="text/plain",
            data=ANMELDUNG_NEU,
            actor=users["content_admin"],
            settings=settings,
            store=store,
        )
        content_db.commit()
        assert AuditAction.DOCUMENT_REPLACED.value in audit_actions(content_db)


class TestWithdrawalAndDeletion:
    def approved(self, env, content_db):  # type: ignore[no-untyped-def]
        outcome = upload(env, content_db)
        complete_metadata(content_db, outcome.job, env[2])
        pipeline.approve(content_db, outcome.job, actor=env[2]["super_admin"])
        content_db.commit()
        return outcome.job

    def test_withdrawing_needs_a_reason(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        job = self.approved(env, content_db)
        assert pipeline.withdraw(
            content_db, job, actor=env[2]["super_admin"], reason="  "
        ) == ["upload.withdraw.reason_required"]

    def test_withdrawing_takes_it_out_of_the_index_and_keeps_the_file(
        self, env, content_db
    ) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        job = self.approved(env, content_db)

        assert pipeline.withdraw(
            content_db, job, actor=users["super_admin"], reason="Gebuehr aufgehoben"
        ) == []
        content_db.commit()

        document = content_db.get(Document, job.document_id)
        version = content_db.get(DocumentVersion, job.version_id)
        assert document.current_version_id is None
        assert version.status == ContentStatus.EXCLUDED.value
        assert version.review_note == "Gebuehr aufgehoben"
        assert store.exists(job.storage_path, quarantined=False)

    def test_deleting_needs_a_reason(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        job = self.approved(env, content_db)
        assert pipeline.delete_upload(
            content_db, job, actor=env[2]["super_admin"], reason="", store=env[1]
        ) == ["upload.delete.reason_required"]

    def test_deleting_removes_the_bytes_and_the_passages(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        job = self.approved(env, content_db)
        stored_path = job.storage_path

        assert pipeline.delete_upload(
            content_db, job, actor=users["super_admin"], reason="Falsch hochgeladen",
            store=store,
        ) == []
        content_db.commit()

        assert not store.exists(stored_path, quarantined=False)
        remaining = content_db.execute(
            select(Chunk).where(Chunk.version_id == job.version_id)
        ).scalars().all()
        assert remaining == []

    def test_deleting_keeps_the_version_so_old_citations_stay_explicable(
        self, env, content_db
    ) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        job = self.approved(env, content_db)

        pipeline.delete_upload(
            content_db, job, actor=users["super_admin"], reason="Falsch hochgeladen",
            store=store,
        )
        content_db.commit()

        version = content_db.get(DocumentVersion, job.version_id)
        assert version is not None
        assert version.status == ContentStatus.GONE.value
        assert version.review_note == "Falsch hochgeladen"
        assert job.state == UploadState.DELETED.value

    def test_deletion_and_withdrawal_are_audited(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        job = self.approved(env, content_db)
        pipeline.withdraw(content_db, job, actor=users["super_admin"], reason="Aufgehoben")
        pipeline.delete_upload(
            content_db, job, actor=users["super_admin"], reason="Aufgehoben", store=store
        )
        content_db.commit()

        actions = audit_actions(content_db)
        assert AuditAction.DOCUMENT_WITHDRAWN.value in actions
        assert AuditAction.DOCUMENT_DELETED.value in actions


class TestDownload:
    def test_reading_the_original_is_audited(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        """The one operation that takes content back out of the system."""
        settings, store, users = env
        outcome = upload(env, content_db)

        data = pipeline.read_original(
            content_db, outcome.job, actor=users["content_admin"], store=store
        )
        content_db.commit()

        assert data == ANMELDUNG
        assert AuditAction.DOCUMENT_DOWNLOADED.value in audit_actions(content_db)

    def test_a_deleted_upload_has_nothing_to_read(self, env, content_db) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        outcome = upload(env, content_db)
        pipeline.delete_upload(
            content_db, outcome.job, actor=users["super_admin"], reason="x", store=store
        )
        content_db.commit()

        assert pipeline.read_original(
            content_db, outcome.job, actor=users["content_admin"], store=store
        ) is None


@pytest.fixture
def client(content_db, users, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """A test client whose settings point at the temporary storage tree."""
    (tmp_path / "accepted").mkdir(exist_ok=True)
    (tmp_path / "quarantine").mkdir(exist_ok=True)
    monkeypatch.setenv("UPLOAD_STORAGE_PATH", str(tmp_path / "accepted"))
    monkeypatch.setenv("UPLOAD_QUARANTINE_PATH", str(tmp_path / "quarantine"))
    monkeypatch.setenv("MALWARE_SCANNER_COMMAND", "")

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


class TestRouteAuthorisation:
    """Authorisation is enforced by a dependency, before the handler body."""

    def test_signing_out_is_required_to_reach_the_upload_page(self, client) -> None:  # type: ignore[no-untyped-def]
        assert client.get("/admin/uploads").status_code == 401

    def test_an_auditor_cannot_open_the_upload_page(self, client) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "auditor")
        assert client.get("/admin/uploads").status_code == 403

    def test_a_content_admin_can_open_the_upload_page(self, client) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "content_admin")
        assert client.get("/admin/uploads").status_code == 200

    def test_an_upload_travels_the_whole_route(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "content_admin")
        response = client.post(
            "/admin/uploads",
            files={"file": ("anmeldung.txt", ANMELDUNG, "text/plain")},
            data={"language": "de"},
        )
        assert response.status_code == 303

        job = content_db.execute(select(UploadJob)).scalars().one()
        assert job.state == UploadState.AWAITING_METADATA.value

    def test_a_reviewer_cannot_upload(self, client, content_db) -> None:  # type: ignore[no-untyped-def]
        sign_in(client, "reviewer")
        response = client.post(
            "/admin/uploads",
            files={"file": ("anmeldung.txt", ANMELDUNG, "text/plain")},
            data={"language": "de"},
        )
        assert response.status_code == 403
        assert content_db.execute(select(UploadJob)).scalars().all() == []

    def test_a_reviewer_cannot_approve_an_upload(self, client, content_db, env) -> None:  # type: ignore[no-untyped-def]
        """Approval is a permission of its own, and a reviewer does not hold it."""
        outcome = upload(env, content_db)
        complete_metadata(content_db, outcome.job, env[2])
        content_db.commit()

        sign_in(client, "reviewer")
        response = client.post(f"/admin/uploads/{outcome.job.id}/approve", data={"note": ""})
        assert response.status_code == 403

        content_db.expire_all()
        version = content_db.get(DocumentVersion, outcome.job.version_id)
        assert version.status == ContentStatus.AWAITING_REVIEW.value

    def test_an_auditor_cannot_download_an_original(self, client, content_db, env) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        outcome = upload(env, content_db)
        content_db.commit()

        sign_in(client, "auditor")
        response = client.get(f"/admin/uploads/{outcome.job.id}/original")
        assert response.status_code == 403

    def test_an_auditor_cannot_delete_an_upload(self, client, content_db, env) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        outcome = upload(env, content_db)
        content_db.commit()

        sign_in(client, "auditor")
        response = client.post(
            f"/admin/uploads/{outcome.job.id}/delete", data={"reason": "weil"}
        )
        assert response.status_code == 403

        content_db.expire_all()
        job = content_db.get(UploadJob, outcome.job.id)
        assert job.state != UploadState.DELETED.value

    def test_a_download_is_served_as_an_attachment(self, client, content_db, env) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        outcome = upload(env, content_db, data=b"<html><body>" + ANMELDUNG + b"</body></html>",
                         name="seite.html", media_type="text/html")
        content_db.commit()

        sign_in(client, "content_admin")
        response = client.get(f"/admin/uploads/{outcome.job.id}/original")
        assert response.status_code == 200
        # Never text/html: a stored page returned as HTML would run in the
        # administrator's session.
        assert response.headers["content-type"] == "application/octet-stream"
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["x-content-type-options"] == "nosniff"

    def test_a_hostile_filename_cannot_break_out_of_the_disposition_header(
        self, client, content_db, env
    ) -> None:  # type: ignore[no-untyped-def]
        settings, store, users = env
        outcome = upload(
            env, content_db, name='a";x=1;name="b.txt', media_type="text/plain"
        )
        content_db.commit()

        sign_in(client, "content_admin")
        response = client.get(f"/admin/uploads/{outcome.job.id}/original")
        header = response.headers["content-disposition"]
        assert header.count('"') == 2

    def test_an_unknown_message_key_is_not_echoed_onto_the_page(
        self, client, content_db, env
    ) -> None:  # type: ignore[no-untyped-def]
        """t() falls back to the key, so the query string is filtered first."""
        settings, store, users = env
        outcome = upload(env, content_db)
        content_db.commit()

        sign_in(client, "content_admin")
        response = client.get(
            f"/admin/uploads/{outcome.job.id}?problems=totally-made-up-marker"
        )
        assert response.status_code == 200
        assert "totally-made-up-marker" not in response.text
