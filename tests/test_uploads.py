"""Validation, storage and scanning of uploaded files.

These tests build real bytes rather than mocking the checks. A test that
asserts validate_upload refuses a file because a mock said so proves nothing
about what happens when somebody uploads an actual executable named
report.pdf, which is the case the code exists for.
"""

from __future__ import annotations

import io
import os
import pathlib
import zipfile

import pytest

from app.config import Settings
from app.ingest.extract_document import (
    extract_csv,
    extract_docx,
    extract_markdown,
    extract_text,
)
from app.uploads.scanning import ScanOutcome, scan_file
from app.uploads.storage import DocumentStore
from app.uploads.validation import (
    UploadKind,
    refusal_message_key,
    sanitise_filename,
    validate_upload,
)

MAX_BYTES = 10 * 1024 * 1024

# A minimal but genuine PDF. Written out rather than loaded, so the test states
# what it is testing against.
PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

GERMAN_TEXT = (
    b"Anmeldung bei der Einwohnerkontrolle\n\n"
    b"Sie muessen sich innert 14 Tagen nach dem Zuzug bei der Einwohnerkontrolle "
    b"anmelden. Bringen Sie den Heimatschein und einen gueltigen Ausweis mit.\n\n"
    b"Die Anmeldung kostet CHF 20.-- pro Person und ist vor Ort zu entrichten."
)


def make_docx(*, extra_entries: dict[str, bytes] | None = None) -> bytes:
    """Build a DOCX that satisfies the container checks."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", "<document/>")
        for name, payload in (extra_entries or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


class TestValidation:
    """The three signals, and what happens when they disagree."""

    def test_a_real_pdf_is_accepted(self) -> None:
        result = validate_upload("merkblatt.pdf", "application/pdf", PDF, max_bytes=MAX_BYTES)
        assert result.ok
        assert result.kind is UploadKind.PDF

    def test_an_executable_named_pdf_is_refused(self) -> None:
        """The extension says PDF, the bytes say Windows executable."""
        data = b"MZ\x90\x00" + b"\x00" * 512
        result = validate_upload("report.pdf", "application/pdf", data, max_bytes=MAX_BYTES)
        assert not result.ok
        assert result.reason == "refused_windows_executable"

    def test_a_shell_script_named_txt_is_refused(self) -> None:
        data = b"#!/bin/sh\nrm -rf /\n" + b"x" * 200
        result = validate_upload("notes.txt", "text/plain", data, max_bytes=MAX_BYTES)
        assert not result.ok
        assert result.reason == "refused_shell_script"

    def test_a_legacy_office_document_is_refused_by_name(self) -> None:
        """Named as its own format rather than lumped in with executables."""
        data = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 512
        result = validate_upload("gebuehren.doc", "application/msword", data, max_bytes=MAX_BYTES)
        assert not result.ok
        assert result.reason == "refused_legacy_office_document"

    def test_a_pdf_renamed_txt_is_refused(self) -> None:
        """A .txt whose bytes are a PDF does not decode as text."""
        result = validate_upload("merkblatt.txt", "text/plain", PDF, max_bytes=MAX_BYTES)
        assert not result.ok
        assert result.reason == "content_does_not_match_extension"

    def test_a_plain_zip_named_docx_is_refused(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("holiday.jpg", b"not a document")
        result = validate_upload(
            "merkblatt.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            buffer.getvalue(),
            max_bytes=MAX_BYTES,
        )
        assert not result.ok
        assert result.reason == "not_a_word_document"

    def test_a_docx_carrying_macros_is_refused(self) -> None:
        data = make_docx(extra_entries={"word/vbaProject.bin": b"macro"})
        result = validate_upload(
            "formular.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            data,
            max_bytes=MAX_BYTES,
        )
        assert not result.ok
        assert result.reason == "document_contains_macros_or_executables"

    def test_a_zip_entry_with_a_traversal_path_is_refused(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
            archive.writestr("../../etc/passwd", b"root:x:0:0")
        result = validate_upload(
            "formular.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            buffer.getvalue(),
            max_bytes=MAX_BYTES,
        )
        assert not result.ok
        assert result.reason == "zip_entry_path_traversal"

    def test_a_zip_bomb_is_refused_before_it_is_read(self) -> None:
        """One highly compressible entry, refused on its compression ratio."""
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", "<document/>")
            archive.writestr("word/media/big.bin", b"\x00" * (60 * 1024 * 1024))
        result = validate_upload(
            "formular.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            buffer.getvalue(),
            max_bytes=MAX_BYTES * 20,
        )
        assert not result.ok
        assert result.reason in (
            "zip_compression_ratio_suspicious",
            "zip_uncompressed_too_large",
        )

    def test_an_empty_file_is_refused(self) -> None:
        result = validate_upload("leer.pdf", "application/pdf", b"", max_bytes=MAX_BYTES)
        assert result.reason == "empty_file"

    def test_an_oversized_file_is_refused(self) -> None:
        result = validate_upload("gross.pdf", "application/pdf", PDF, max_bytes=10)
        assert result.reason == "file_too_large"

    def test_an_unsupported_extension_is_refused(self) -> None:
        result = validate_upload("tabelle.xlsx", "", b"PK\x03\x04rest", max_bytes=MAX_BYTES)
        assert result.reason == "extension_not_allowed"

    def test_every_refusal_reason_has_a_message_key(self) -> None:
        """A refusal with no localised message would show a bare identifier."""
        from app.i18n import STRINGS

        reasons = [
            "empty_file",
            "file_too_large",
            "refused_windows_executable",
            "refused_linux_executable",
            "refused_java_class_or_macho",
            "refused_shell_script",
            "refused_legacy_office_document",
            "refused_gzip_archive",
            "refused_rar_archive",
            "refused_seven_zip_archive",
            "extension_not_allowed",
            "content_does_not_match_extension",
            "declared_type_does_not_match_content",
            "malformed_zip_container",
            "zip_too_many_entries",
            "zip_entry_path_traversal",
            "zip_uncompressed_too_large",
            "zip_compression_ratio_suspicious",
            "document_contains_macros_or_executables",
            "not_a_word_document",
        ]
        assert [r for r in reasons if refusal_message_key(r) not in STRINGS] == []


class TestFilenames:
    """The filename is attacker-controlled text that ends up on a page."""

    def test_a_bidi_override_is_stripped(self) -> None:
        """U+202E makes "invoice<RLO>fdp.exe" display as "invoiceexe.pdf"."""
        assert sanitise_filename("invoice\u202efdp.exe") == "invoicefdp.exe"

    def test_a_path_is_reduced_to_its_last_component(self) -> None:
        assert sanitise_filename("../../etc/passwd") == "passwd"
        assert sanitise_filename("C:\\Users\\x\\merkblatt.pdf") == "merkblatt.pdf"

    def test_control_characters_are_dropped(self) -> None:
        assert sanitise_filename("merk\x00blatt\n.pdf") == "merkblatt.pdf"

    def test_an_empty_name_gets_a_placeholder(self) -> None:
        assert sanitise_filename("   ...  ") == "unnamed"

    def test_a_very_long_name_is_truncated(self) -> None:
        assert len(sanitise_filename("a" * 900 + ".pdf")) == 255


def make_store(tmp_path: pathlib.Path) -> DocumentStore:
    settings = Settings(
        _env_file=None,
        secret_key="test-secret-key-of-adequate-length-000000",
        database_url="postgresql+psycopg://u:p@localhost:5432/d",
        upload_storage_path=str(tmp_path / "accepted"),
        upload_quarantine_path=str(tmp_path / "quarantine"),
    )
    (tmp_path / "accepted").mkdir()
    (tmp_path / "quarantine").mkdir()
    return DocumentStore(settings)


class TestStorage:
    def test_new_uploads_land_in_quarantine(self, tmp_path: pathlib.Path) -> None:
        store = make_store(tmp_path)
        stored = store.write(PDF)
        assert stored.quarantined
        assert store.exists(stored.relative_path, quarantined=True)
        assert not store.exists(stored.relative_path, quarantined=False)

    def test_the_stored_name_carries_nothing_from_the_upload(
        self, tmp_path: pathlib.Path
    ) -> None:
        """Traversal is impossible because there is no attacker-controlled part."""
        store = make_store(tmp_path)
        first = store.write(PDF)
        second = store.write(PDF)
        assert first.relative_path != second.relative_path
        assert first.relative_path.count("/") == 1
        # Sharded by the first two characters of the generated token.
        shard, name = first.relative_path.split("/")
        assert len(shard) == 2 and name.startswith(shard)

    def test_files_are_written_owner_only(self, tmp_path: pathlib.Path) -> None:
        store = make_store(tmp_path)
        stored = store.write(PDF)
        mode = os.stat(store.path_of(stored.relative_path, quarantined=True)).st_mode
        assert mode & 0o777 == 0o600

    def test_promotion_moves_the_file_out_of_quarantine(
        self, tmp_path: pathlib.Path
    ) -> None:
        store = make_store(tmp_path)
        stored = store.write(PDF)
        promoted = store.promote(stored.relative_path)
        assert not promoted.quarantined
        assert not store.exists(stored.relative_path, quarantined=True)
        assert store.read(promoted.relative_path, quarantined=False) == PDF

    def test_a_path_outside_the_root_is_refused(self, tmp_path: pathlib.Path) -> None:
        """A tampered database row must not make the store read anywhere."""
        store = make_store(tmp_path)
        with pytest.raises(ValueError):
            store.read("../../etc/passwd", quarantined=True)
        with pytest.raises(ValueError):
            store.path_of("../../../etc/shadow", quarantined=False)

    def test_deleting_a_missing_file_reports_rather_than_raises(
        self, tmp_path: pathlib.Path
    ) -> None:
        store = make_store(tmp_path)
        assert store.delete("ab/abcdef", quarantined=True) is False


def scanner_settings(command: str) -> Settings:
    return Settings(
        _env_file=None,
        secret_key="test-secret-key-of-adequate-length-000000",
        database_url="postgresql+psycopg://u:p@localhost:5432/d",
        malware_scanner_command=command,
    )


class TestScanning:
    def test_exit_zero_is_clean(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "file.pdf"
        target.write_bytes(PDF)
        result = scan_file(str(target), scanner_settings("/bin/true"))
        assert result.outcome is ScanOutcome.CLEAN

    def test_exit_one_is_a_detection(self, tmp_path: pathlib.Path) -> None:
        target = tmp_path / "file.pdf"
        target.write_bytes(PDF)
        result = scan_file(str(target), scanner_settings("/bin/false"))
        assert result.outcome is ScanOutcome.INFECTED
        assert not result.clean

    def test_a_missing_scanner_fails_rather_than_passing(
        self, tmp_path: pathlib.Path
    ) -> None:
        """A scanner that is not installed must not read as clean."""
        target = tmp_path / "file.pdf"
        target.write_bytes(PDF)
        result = scan_file(str(target), scanner_settings("/nonexistent/clamscan"))
        assert result.outcome is ScanOutcome.FAILED
        assert not result.outcome.may_promote

    def test_an_unexpected_exit_code_fails(self, tmp_path: pathlib.Path) -> None:
        script = tmp_path / "scanner.sh"
        script.write_text("#!/bin/sh\nexit 7\n")
        script.chmod(0o755)
        target = tmp_path / "file.pdf"
        target.write_bytes(PDF)
        result = scan_file(str(target), scanner_settings(str(script)))
        assert result.outcome is ScanOutcome.FAILED

    def test_a_filename_cannot_become_a_command(self, tmp_path: pathlib.Path) -> None:
        """The path is one argv entry, so no shell metacharacter is interpreted."""
        script = tmp_path / "scanner.sh"
        report = tmp_path / "argv.txt"
        script.write_text(f'#!/bin/sh\nprintf "%s\\n" "$@" > {report}\nexit 0\n')
        script.chmod(0o755)

        # A shell would read the semicolon as a command separator and create
        # the marker file. subprocess with an argv list does not.
        marker = tmp_path / "pwned.txt"
        hostile = tmp_path / f"a; touch {marker.name}"
        hostile.write_bytes(PDF)

        result = scan_file(str(hostile), scanner_settings(str(script)))
        assert result.outcome is ScanOutcome.CLEAN
        assert report.read_text().strip() == str(hostile)
        assert not marker.exists()
        assert not (pathlib.Path.cwd() / marker.name).exists()

    def test_no_scanner_configured_is_permitted_outside_production(
        self, tmp_path: pathlib.Path
    ) -> None:
        target = tmp_path / "file.pdf"
        target.write_bytes(PDF)
        result = scan_file(str(target), scanner_settings(""))
        assert result.outcome is ScanOutcome.NOT_CONFIGURED
        assert result.outcome.may_promote


class TestExtraction:
    def test_plain_text_becomes_paragraphs(self) -> None:
        document = extract_text(GERMAN_TEXT, filename="anmeldung.txt")
        assert document.is_usable
        assert "CHF 20.--" in document.text
        assert document.title == "Anmeldung bei der Einwohnerkontrolle"

    def test_a_fee_is_never_reformatted(self) -> None:
        """Section 11: amounts are quoted, not normalised into something else."""
        document = extract_text(GERMAN_TEXT)
        assert "CHF 20.--" in document.text
        assert "CHF 20.00" not in document.text

    def test_markdown_headings_build_a_section_path(self) -> None:
        source = (
            b"# Anmeldung\n\n"
            b"Einleitender Absatz mit genuegend Text, damit das Dokument als "
            b"brauchbar gilt und nicht als zu duenn verworfen wird.\n\n"
            b"## Fristen\n\n"
            b"Die Frist betraegt 14 Tage nach dem Zuzug in die Gemeinde.\n"
        )
        document = extract_markdown(source, filename="anmeldung.md")
        paths = [block.section_path for block in document.blocks]
        assert ("Anmeldung", "Fristen") in paths
        assert document.title == "Anmeldung"

    def test_a_semicolon_separated_csv_is_read_as_columns(self) -> None:
        """A German-locale Excel export uses semicolons, not commas."""
        source = (
            b"Leistung;Gebuehr;Zustaendig\n"
            b"Anmeldung;CHF 20.--;Einwohnerkontrolle\n"
            b"Abmeldung;CHF 20.--;Einwohnerkontrolle\n"
            b"Ausweis;CHF 65.--;Passbuero\n"
            b"Umzug innerhalb der Gemeinde;CHF 20.--;Einwohnerkontrolle\n"
        )
        document = extract_csv(source, filename="gebuehren.csv")
        assert "Leistung: Anmeldung; Gebuehr: CHF 20.--" in document.text

    def test_a_csv_row_keeps_its_column_labels(self) -> None:
        """A bare row of values is meaningless once retrieved on its own."""
        source = b"Leistung;Gebuehr\nAnmeldung;CHF 20.--\n" + b"Abmeldung;CHF 20.--\n" * 8
        document = extract_csv(source)
        assert all(
            "Leistung:" in block.text for block in document.blocks if block.tag == "li"
        )

    def test_a_docx_is_read_with_its_headings(self) -> None:
        docx = pytest.importorskip("docx")

        document = docx.Document()
        document.add_heading("Anmeldung bei der Einwohnerkontrolle", level=1)
        document.add_paragraph(
            "Sie muessen sich innert 14 Tagen nach dem Zuzug anmelden. Bringen Sie "
            "den Heimatschein und einen gueltigen Ausweis mit."
        )
        document.add_heading("Gebuehren", level=2)
        document.add_paragraph("Die Anmeldung kostet CHF 20.-- pro Person.")
        buffer = io.BytesIO()
        document.save(buffer)

        extracted = extract_docx(buffer.getvalue(), filename="anmeldung.docx")
        assert extracted.is_usable
        assert "CHF 20.--" in extracted.text
        assert any(
            block.section_path
            and block.section_path[-1] == "Gebuehren"
            for block in extracted.blocks
        )

    def test_a_docx_table_keeps_its_header_labels(self) -> None:
        docx = pytest.importorskip("docx")

        document = docx.Document()
        table = document.add_table(rows=3, cols=2)
        table.cell(0, 0).text = "Leistung"
        table.cell(0, 1).text = "Gebuehr"
        table.cell(1, 0).text = "Anmeldung"
        table.cell(1, 1).text = "CHF 20.--"
        table.cell(2, 0).text = "Ausweis"
        table.cell(2, 1).text = "CHF 65.--"
        buffer = io.BytesIO()
        document.save(buffer)

        extracted = extract_docx(buffer.getvalue(), filename="gebuehren.docx")
        assert "Leistung: Anmeldung; Gebuehr: CHF 20.--" in extracted.text

    def test_an_unreadable_docx_fails_rather_than_producing_empty_text(self) -> None:
        extracted = extract_docx(make_docx(), filename="kaputt.docx")
        assert extracted.quality.value == "failed"
