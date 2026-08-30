"""Validating an uploaded file before anything else touches it.

Three independent signals must agree before a file is accepted: the extension,
the Content-Type the browser declared, and the leading bytes. Any one of them
alone is trivially wrong.

* The extension is chosen by whoever named the file.
* The Content-Type is chosen by whoever wrote the client.
* The magic bytes describe what the file actually is.

Only the third is evidence, so it decides. The other two are checked because a
disagreement is itself worth knowing about: a ZIP named `.pdf` and declared as
`application/pdf` is not a mistake somebody made by accident.

Nothing here parses the document. Validation runs before the file reaches a
parser, because handing an unknown format to a PDF library is exactly the step
this is meant to prevent.
"""

from __future__ import annotations

import re
import unicodedata
import zipfile
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO


class UploadKind(StrEnum):
    """Formats an administrator may upload.

    Deliberately short. Every entry is a format the extraction pipeline can
    actually read, because accepting a file the system cannot process only
    produces a document with no text and a reviewer wondering why.
    """

    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MARKDOWN = "markdown"
    CSV = "csv"
    HTML = "html"


@dataclass(frozen=True)
class FormatSpec:
    """What a permitted format looks like on disk and on the wire."""

    kind: UploadKind
    extensions: frozenset[str]
    media_types: frozenset[str]
    # Leading bytes that identify the format. Empty for text formats, which
    # have no signature and are validated by decoding instead.
    signatures: tuple[bytes, ...] = ()
    # True when the format is a ZIP container, which needs bomb protection.
    is_zip_container: bool = False


FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec(
        kind=UploadKind.PDF,
        extensions=frozenset({".pdf"}),
        media_types=frozenset({"application/pdf"}),
        signatures=(b"%PDF-",),
    ),
    FormatSpec(
        kind=UploadKind.DOCX,
        extensions=frozenset({".docx"}),
        media_types=frozenset(
            {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
        ),
        # DOCX is a ZIP, so the signature is ZIP's. The distinction from any
        # other ZIP is made by inspecting the archive, below.
        signatures=(b"PK\x03\x04",),
        is_zip_container=True,
    ),
    FormatSpec(
        kind=UploadKind.TXT,
        extensions=frozenset({".txt"}),
        media_types=frozenset({"text/plain"}),
    ),
    FormatSpec(
        kind=UploadKind.MARKDOWN,
        extensions=frozenset({".md", ".markdown"}),
        media_types=frozenset({"text/markdown", "text/plain"}),
    ),
    FormatSpec(
        kind=UploadKind.CSV,
        extensions=frozenset({".csv"}),
        media_types=frozenset({"text/csv", "text/plain", "application/csv"}),
    ),
    FormatSpec(
        kind=UploadKind.HTML,
        extensions=frozenset({".html", ".htm"}),
        media_types=frozenset({"text/html"}),
    ),
)

BY_EXTENSION: dict[str, FormatSpec] = {
    extension: spec for spec in FORMATS for extension in spec.extensions
}

# Formats that are never accepted, listed so a refusal can say what it saw
# rather than "unsupported". Someone uploading a .exe has made a mistake worth
# naming; someone uploading a .docm is trying to bring macros in.
DANGEROUS_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"MZ", "windows_executable"),
    (b"\x7fELF", "linux_executable"),
    (b"\xca\xfe\xba\xbe", "java_class_or_macho"),
    (b"#!", "shell_script"),
    (b"\xd0\xcf\x11\xe0", "legacy_office_document"),
    (b"\x1f\x8b", "gzip_archive"),
    (b"Rar!", "rar_archive"),
    (b"7z\xbc\xaf", "seven_zip_archive"),
)

# A DOCX must contain these. A plain ZIP renamed to .docx will not.
DOCX_REQUIRED_ENTRIES = ("[Content_Types].xml", "word/document.xml")

# Entries that make a DOCX something other than a document.
DOCX_FORBIDDEN_PATTERNS = (
    re.compile(r"vbaProject\.bin$", re.IGNORECASE),   # macros
    re.compile(r"word/embeddings/", re.IGNORECASE),   # embedded objects
    re.compile(r"\.(exe|dll|scr|bat|cmd|com|js|vbs|ps1)$", re.IGNORECASE),
)

# Archive bomb limits. A DOCX of a few hundred pages stays well inside these.
MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED_BYTES = 300 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200

# Bytes read for signature detection. More than any signature needs, and
# enough for python-magic to work with.
SNIFF_BYTES = 4096

MAX_FILENAME_LENGTH = 255

# Refusal reasons are fine-grained so that they can be counted by cause. The
# messages shown to a person are not: someone who uploaded a RAR archive does
# not need to be told which of eight signatures matched. This maps the reasons
# onto the smaller set of message keys the string table carries.
REFUSAL_MESSAGE_KEYS: dict[str, str] = {
    "refused_windows_executable": "upload.refused.executable",
    "refused_linux_executable": "upload.refused.executable",
    "refused_java_class_or_macho": "upload.refused.executable",
    "refused_shell_script": "upload.refused.executable",
    "refused_gzip_archive": "upload.refused.archive",
    "refused_rar_archive": "upload.refused.archive",
    "refused_seven_zip_archive": "upload.refused.archive",
    "zip_too_many_entries": "upload.refused.zip_suspicious",
    "zip_uncompressed_too_large": "upload.refused.zip_suspicious",
    "zip_compression_ratio_suspicious": "upload.refused.zip_suspicious",
    "zip_entry_path_traversal": "upload.refused.zip_suspicious",
}


def refusal_message_key(reason: str) -> str:
    """Return the message key for a refusal reason."""
    return REFUSAL_MESSAGE_KEYS.get(reason, f"upload.refused.{reason}")


@dataclass(frozen=True)
class ValidationResult:
    """Whether a file may be accepted, and what it actually is."""

    ok: bool
    # A machine-readable reason, so refusals can be counted by cause and
    # localised for the person who uploaded.
    reason: str = ""
    kind: UploadKind | None = None
    detected_media_type: str = ""
    # A filename safe to display. Never used to build a path.
    safe_display_name: str = ""

    def __bool__(self) -> bool:
        return self.ok


def sanitise_filename(raw: str) -> str:
    """Return a filename safe to store as a label and show to a person.

    This value is never used to build a path. Storage names are generated
    server-side, so directory traversal is not defended against here; it is
    made impossible in app.uploads.storage. What this protects is the display
    surface: a filename is attacker-controlled text that ends up in an audit
    entry, an interface and a log line.
    """
    # Strip any path component a browser or a client may have sent.
    name = raw.replace("\\", "/").rsplit("/", 1)[-1]
    # Normalise so visually identical names cannot differ invisibly, and drop
    # control characters and bidi overrides, which can make a .exe display as
    # a .pdf.
    name = unicodedata.normalize("NFKC", name)
    name = "".join(character for character in name if character.isprintable())
    name = re.sub(r"[​-‏‪-‮⁦-⁩]", "", name)
    name = name.strip().strip(".")
    if not name:
        return "unnamed"
    return name[:MAX_FILENAME_LENGTH]


def extension_of(filename: str) -> str:
    """Return the lower-case extension, including the dot."""
    name = sanitise_filename(filename).lower()
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[1]


def detect_media_type(data: bytes) -> str:
    """Identify content from its leading bytes.

    Uses libmagic when available and falls back to signature matching. The
    fallback matters: an environment without libmagic must still refuse a
    disguised executable, rather than silently losing the check.
    """
    try:
        import magic

        return str(magic.from_buffer(data[:SNIFF_BYTES], mime=True))
    except Exception:  # noqa: BLE001 - a missing or broken libmagic is not fatal
        for spec in FORMATS:
            for signature in spec.signatures:
                if data.startswith(signature):
                    return next(iter(sorted(spec.media_types)))
        return "application/octet-stream"


def _inspect_zip(data: bytes) -> tuple[bool, str]:
    """Check a ZIP container for bombs, macros and non-document entries."""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return False, "malformed_zip_container"

    entries = archive.infolist()
    if len(entries) > MAX_ZIP_ENTRIES:
        return False, "zip_too_many_entries"

    total_uncompressed = 0
    for entry in entries:
        # An entry name with a path component or an absolute path is a zip-slip
        # attempt. Nothing here extracts to disk, but a container built that
        # way is not a document somebody made in Word.
        if entry.filename.startswith("/") or ".." in entry.filename.split("/"):
            return False, "zip_entry_path_traversal"

        for pattern in DOCX_FORBIDDEN_PATTERNS:
            if pattern.search(entry.filename):
                return False, "document_contains_macros_or_executables"

        total_uncompressed += entry.file_size
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            return False, "zip_uncompressed_too_large"

        if entry.compress_size > 0:
            ratio = entry.file_size / entry.compress_size
            if ratio > MAX_ZIP_COMPRESSION_RATIO:
                return False, "zip_compression_ratio_suspicious"

    names = {entry.filename for entry in entries}
    if not all(required in names for required in DOCX_REQUIRED_ENTRIES):
        return False, "not_a_word_document"

    return True, ""


def _matches_another_format(data: bytes, spec: FormatSpec) -> bool:
    """Whether the bytes carry the signature of a different permitted format.

    Text formats have no signature of their own, so decoding is the only
    positive test available, and a PDF happens to decode: its header and object
    dictionaries are ASCII. That means a PDF renamed to .txt would pass as text
    and be indexed as the mangled remains of a binary file.

    Looking for the other formats' signatures closes it. A .txt beginning
    "%PDF-" is a PDF whatever it is called.
    """
    for other in FORMATS:
        if other.kind is spec.kind:
            continue
        for signature in other.signatures:
            if data.startswith(signature):
                return True
    return False


def _looks_like_text(data: bytes) -> bool:
    """Whether the bytes decode as text without control characters.

    A file claiming to be plain text that contains NUL bytes is not plain
    text, whatever its extension says.
    """
    sample = data[:SNIFF_BYTES]
    if b"\x00" in sample:
        return False
    for encoding in ("utf-8", "utf-16", "cp1252"):
        try:
            sample.decode(encoding)
        except UnicodeDecodeError:
            continue
        else:
            return True
    return False


def validate_upload(
    filename: str,
    declared_media_type: str,
    data: bytes,
    *,
    max_bytes: int,
) -> ValidationResult:
    """Decide whether an uploaded file may be accepted.

    Checks run cheapest first, so an oversized or obviously hostile file is
    refused before anything expensive touches it.
    """
    safe_name = sanitise_filename(filename)

    if not data:
        return ValidationResult(False, "empty_file", safe_display_name=safe_name)
    if len(data) > max_bytes:
        return ValidationResult(False, "file_too_large", safe_display_name=safe_name)

    # Refuse known-dangerous content before consulting the extension, so a
    # .pdf that is really an executable is named as such.
    for signature, label in DANGEROUS_SIGNATURES:
        if data.startswith(signature):
            # The legacy Office signature is also a real format, so it is
            # refused with its own reason rather than as an executable.
            return ValidationResult(False, f"refused_{label}", safe_display_name=safe_name)

    extension = extension_of(filename)
    spec = BY_EXTENSION.get(extension)
    if spec is None:
        return ValidationResult(
            False, "extension_not_allowed", safe_display_name=safe_name
        )

    detected = detect_media_type(data)

    if spec.signatures:
        if not any(data.startswith(signature) for signature in spec.signatures):
            # The extension says one thing and the bytes say another. The bytes
            # decide, and the disagreement is the finding.
            return ValidationResult(
                False,
                "content_does_not_match_extension",
                detected_media_type=detected,
                safe_display_name=safe_name,
            )
    elif not _looks_like_text(data) or _matches_another_format(data, spec):
        return ValidationResult(
            False,
            "content_does_not_match_extension",
            detected_media_type=detected,
            safe_display_name=safe_name,
        )

    if spec.is_zip_container:
        ok, reason = _inspect_zip(data)
        if not ok:
            return ValidationResult(
                False, reason, detected_media_type=detected, safe_display_name=safe_name
            )

    # The declared type is checked last and is advisory. It is chosen by the
    # client, so a mismatch is recorded rather than treated as authoritative.
    declared = (declared_media_type or "").split(";", 1)[0].strip().lower()
    if declared and declared not in spec.media_types and declared != detected:
        return ValidationResult(
            False,
            "declared_type_does_not_match_content",
            kind=spec.kind,
            detected_media_type=detected,
            safe_display_name=safe_name,
        )

    return ValidationResult(
        True,
        kind=spec.kind,
        detected_media_type=detected,
        safe_display_name=safe_name,
    )
