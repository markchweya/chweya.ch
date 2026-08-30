"""Contradiction detection.

Precision matters more than recall here. Every finding costs a reviewer's
attention, and a queue full of false positives is a queue nobody reads, which
is worse than no queue at all.

The detector must never decide which passage is right. Section 9 prohibits it,
and a system that picked a winner would put a wrong fee in front of residents
with its own confidence behind it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text as sql

from app.db.models.review import ContradictionKind, ReviewState
from app.ingest.contradictions import (
    detect,
    extract_amounts,
    extract_deadlines,
    extract_hours,
    extract_phones,
)


class TestExtraction:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Die Anmeldung kostet CHF 20.-- pro Person.", {20.0}),
            ("Die Gebuehr betraegt CHF 20.00.", {20.0}),
            ("Es kostet Fr. 35.- pro Stunde.", {35.0}),
            ("Die Gebuehr betraegt 40 Franken.", {40.0}),
            ("Der Betrag ist CHF 1'250.00.", {1250.0}),
            ("Le montant est de CHF 85.00.", {85.0}),
        ],
    )
    def test_swiss_money_formats(self, text: str, expected: set[float]) -> None:
        assert extract_amounts(text) == expected

    def test_apostrophe_thousands_separator(self) -> None:
        """Swiss formatting uses both the straight and typographic apostrophe."""
        assert extract_amounts("CHF 1'250.00") == extract_amounts("CHF 1’250.00")

    def test_implausible_amounts_are_ignored(self) -> None:
        """A year or a reference number is not a fee."""
        assert 2026.0 not in extract_amounts("Gueltig ab CHF 2000000.00 im Jahr 2026")

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Sie muessen sich innert 14 Tagen anmelden.", {(14, "days")}),
            ("innerhalb von 30 Tagen", {(30, "days")}),
            ("You must register within 14 days.", {(14, "days")}),
            ("dans un delai de 3 mois", {(3, "months")}),
            ("entro 30 giorni", {(30, "days")}),
            ("innert 2 Wochen", {(2, "weeks")}),
        ],
    )
    def test_deadlines_in_four_languages(self, text: str, expected: set) -> None:
        assert extract_deadlines(text) == expected

    def test_phone_formatting_differences_collapse(self) -> None:
        """The same number written two ways must not look like a conflict."""
        assert extract_phones("041 728 33 11") == extract_phones("041/728 33 11")

    def test_opening_hours_are_canonicalised(self) -> None:
        assert extract_hours("08.00 - 11.30") == extract_hours("8:00 bis 11:30")


def seed_pair(db, first_text: str, second_text: str) -> None:  # type: ignore[no-untyped-def]
    """Insert two approved passages in two different documents."""
    db.execute(sql("TRUNCATE contradiction_findings, chunks, document_versions, documents CASCADE"))
    for index, text in enumerate((first_text, second_text)):
        doc_id, version_id = uuid.uuid4(), uuid.uuid4()
        db.execute(
            sql(
                "INSERT INTO documents (id, kind, title, media_type, language,"
                " publication_state, current_version_id) "
                "VALUES (:d, 'crawled_page', :t, 'text/html', 'de', 'official', :v)"
            ),
            {"d": doc_id, "t": f"Seite {index}", "v": version_id},
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


class TestDetection:
    def test_conflicting_fees_are_found(self, db) -> None:  # type: ignore[no-untyped-def]
        seed_pair(
            db,
            "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 20.-- pro Person.",
            "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 35.-- pro Person.",
        )
        findings = detect(db)
        assert any(f.kind == ContradictionKind.FEE.value for f in findings)

    def test_conflicting_deadlines_are_found(self, db) -> None:  # type: ignore[no-untyped-def]
        seed_pair(
            db,
            "Anmeldung bei der Einwohnerkontrolle innert 14 Tagen nach Zuzug erforderlich.",
            "Anmeldung bei der Einwohnerkontrolle innert 30 Tagen nach Zuzug erforderlich.",
        )
        findings = detect(db)
        assert any(f.kind == ContradictionKind.DEADLINE.value for f in findings)

    def test_a_deadline_outranks_a_fee(self, db) -> None:  # type: ignore[no-untyped-def]
        """Missing a registration deadline has consequences a resident cannot
        undo; paying the wrong fee is corrected at the counter."""
        seed_pair(
            db,
            "Anmeldung Einwohnerkontrolle innert 14 Tagen, Gebuehr CHF 20.--.",
            "Anmeldung Einwohnerkontrolle innert 30 Tagen, Gebuehr CHF 35.--.",
        )
        findings = detect(db)
        by_kind = {f.kind: f.priority for f in findings}
        assert by_kind[ContradictionKind.DEADLINE.value] > by_kind[ContradictionKind.FEE.value]

    def test_a_finding_records_both_values_and_never_a_verdict(self, db) -> None:  # type: ignore[no-untyped-def]
        seed_pair(
            db,
            "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 20.-- pro Person.",
            "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 35.-- pro Person.",
        )
        finding = next(f for f in detect(db) if f.kind == ContradictionKind.FEE.value)
        assert finding.first_value and finding.second_value
        assert finding.state == ReviewState.OPEN.value
        # The explanation describes; it does not conclude.
        lowered = finding.explanation.lower()
        assert "may" in lowered or "different" in lowered
        assert "correct" not in lowered and "wrong" not in lowered

    def test_unrelated_passages_are_not_compared(self, db) -> None:  # type: ignore[no-untyped-def]
        """Two different services legitimately charging different fees is not
        a contradiction, and filling the queue with those makes it useless."""
        seed_pair(
            db,
            "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 20.-- pro Person.",
            "Die Abholung von Sperrgut kostet CHF 40.-- pro Kubikmeter.",
        )
        assert detect(db) == []

    def test_identical_values_produce_nothing(self, db) -> None:  # type: ignore[no-untyped-def]
        seed_pair(
            db,
            "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 20.-- pro Person.",
            "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 20.-- pro Person.",
        )
        assert detect(db) == []

    def test_passages_in_one_document_are_not_compared(self, db) -> None:  # type: ignore[no-untyped-def]
        """A page listing several fees is a price list, not a contradiction."""
        db.execute(sql("TRUNCATE contradiction_findings, chunks, document_versions, documents CASCADE"))
        doc_id, version_id = uuid.uuid4(), uuid.uuid4()
        db.execute(
            sql(
                "INSERT INTO documents (id, kind, title, media_type, language,"
                " publication_state, current_version_id) "
                "VALUES (:d, 'crawled_page', 'Tarife', 'text/html', 'de', 'official', :v)"
            ),
            {"d": doc_id, "v": version_id},
        )
        db.execute(
            sql(
                "INSERT INTO document_versions (id, document_id, version_number, content_hash,"
                " status, extracted_text) VALUES (:v, :d, 1, 'h', 'approved', '')"
            ),
            {"v": version_id, "d": doc_id},
        )
        for ordinal, text in enumerate(
            [
                "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 20.-- pro Person.",
                "Die Anmeldung bei der Einwohnerkontrolle kostet CHF 35.-- pro Familie.",
            ]
        ):
            db.execute(
                sql(
                    "INSERT INTO chunks (id, version_id, document_id, ordinal, text, language)"
                    " VALUES (:c, :v, :d, :o, :t, 'de')"
                ),
                {"c": uuid.uuid4(), "v": version_id, "d": doc_id, "o": ordinal, "t": text},
            )
        db.commit()
        assert detect(db) == []


class TestReviewStates:
    def test_open_states_are_the_ones_that_lower_confidence(self) -> None:
        assert ReviewState.OPEN.is_open
        assert ReviewState.IN_REVIEW.is_open
        assert ReviewState.UNRESOLVED.is_open
        assert not ReviewState.RESOLVED_FIRST_CURRENT.is_open
        assert not ReviewState.NOT_A_CONTRADICTION.is_open

    def test_not_a_contradiction_exists_as_an_outcome(self) -> None:
        """Most findings will be exactly that: two services that legitimately
        differ. Without it a reviewer must force a real distinction into a
        resolution implying one page is wrong."""
        assert ReviewState.NOT_A_CONTRADICTION in set(ReviewState)
