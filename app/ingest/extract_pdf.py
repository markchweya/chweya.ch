"""PDF extraction with page-aware citation anchors.

Section 7 requires that a PDF citation carries a page number. Without one, a
resident is told the answer is "in this fifty-page document somewhere", which
is barely better than no citation at all.

Safety. A PDF is a container format that can hold JavaScript, embedded files,
launch actions and form submission targets. None of it is executed here:
pypdf parses structure and text and does not run anything. What this module
adds is detection, so a document carrying active content is flagged for a
reviewer rather than indexed quietly. The brief also requires this to run in
an isolated worker, which is what the separate worker container is for.

Quality. A scanned PDF with no text layer yields nothing, which is obvious. A
badly OCRed one yields text that looks plausible and is wrong, which is worse,
because it reaches retrieval and gets cited. Both are detected and reported
rather than indexed silently.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.db.models.content import ExtractionQuality
from app.observability import get_logger

logger = get_logger(__name__)

# Bounds. A document beyond these is either not what it claims or not
# something to process in a request-adjacent worker.
MAX_PAGES = 2000
MAX_TEXT_CHARACTERS = 8_000_000

# Below this, a page carries no usable text. Usually a scan with no text layer.
MIN_PAGE_CHARACTERS = 20

# Proportion of pages that must yield text before the document counts as
# properly extracted.
GOOD_EXTRACTION_RATIO = 0.8
PARTIAL_EXTRACTION_RATIO = 0.4

# Text that suggests OCR produced nonsense: long runs with no vowels, or a
# high proportion of isolated single characters. Latin-script languages do not
# look like this, and all four supported languages are Latin script.
GIBBERISH_PATTERNS = (
    re.compile(r"[bcdfghjklmnpqrstvwxz]{7,}", re.IGNORECASE),
    re.compile(r"(?:\b\w\b[\s.,]{0,2}){12,}"),
)

# Titles that PDF producers write when the author set none. They are truthy
# but useless as a citation label, so they are treated as absent and the
# filename is used instead. "Microsoft Word - Gebuehren.docx" is deliberately
# not in this list: the part after the dash is a real name.
PLACEHOLDER_TITLES = frozenset(
    {"untitled", "unknown", "document", "dokument", "no title", "sans titre", "senza titolo"}
)


def _usable_title(raw: str) -> str:
    """Return a title worth showing beside a citation, or an empty string."""
    cleaned = raw.strip()
    if not cleaned or cleaned.lower() in PLACEHOLDER_TITLES:
        return ""
    # Some producers prefix the source application. The real name follows.
    for prefix in ("Microsoft Word - ", "Microsoft PowerPoint - ", "Adobe Acrobat - "):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix) :].strip()
    return cleaned


# Heading heuristics. A PDF has no heading elements, so structure is inferred:
# a short line, not ending in sentence punctuation, that is either numbered or
# largely upper case.
NUMBERED_HEADING = re.compile(r"^\s*(\d+(?:\.\d+)*)[.)\s]\s*(\S.{0,90})$")
MAX_HEADING_LENGTH = 100


@dataclass
class PdfPage:
    """Text extracted from one page, with its page number."""

    # One-based, matching what a PDF reader shows the resident.
    number: int
    text: str = ""
    section_path: tuple[str, ...] = ()

    @property
    def has_text(self) -> bool:
        return len(self.text.strip()) >= MIN_PAGE_CHARACTERS


@dataclass
class ExtractedPdf:
    """Everything pulled out of one PDF."""

    title: str = ""
    author: str | None = None
    subject: str | None = None
    created_text: str | None = None
    page_count: int = 0
    pages: list[PdfPage] = field(default_factory=list)
    quality: ExtractionQuality = ExtractionQuality.GOOD
    notes: list[str] = field(default_factory=list)
    # Active content found in the file. Non-empty means a reviewer looks
    # before this reaches the public index.
    active_content: list[str] = field(default_factory=list)
    encrypted: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())

    @property
    def pages_with_text(self) -> int:
        return sum(1 for page in self.pages if page.has_text)

    @property
    def needs_ocr(self) -> bool:
        """True when the document is probably a scan with no text layer."""
        if not self.pages:
            return False
        return self.pages_with_text == 0


def _detect_active_content(reader: PdfReader) -> list[str]:
    """Report active content without executing or resolving any of it.

    Reads catalogue keys only. Nothing here follows a URL, opens an embedded
    file or evaluates a script.
    """
    findings: list[str] = []
    try:
        catalog = reader.trailer.get("/Root", {})
    except Exception:  # noqa: BLE001 - a malformed trailer is a finding, not a crash
        return ["unreadable_catalog"]

    try:
        names = catalog.get("/Names", {}) or {}
        if "/JavaScript" in names:
            findings.append("javascript")
        if "/EmbeddedFiles" in names:
            findings.append("embedded_files")

        if "/OpenAction" in catalog:
            findings.append("open_action")
        if "/AA" in catalog:
            findings.append("additional_actions")

        acroform = catalog.get("/AcroForm", {}) or {}
        if acroform:
            findings.append("form_fields")
            if "/XFA" in acroform:
                findings.append("xfa_form")

        for page in reader.pages:
            annotations = page.get("/Annots") or []
            for annotation in annotations:
                try:
                    resolved = annotation.get_object()
                except Exception as exc:  # noqa: BLE001
                    # A broken annotation reference is itself worth knowing
                    # about: it can mean a deliberately malformed file.
                    logger.debug("pdf.unresolvable_annotation", error=type(exc).__name__)
                    if "malformed_annotation" not in findings:
                        findings.append("malformed_annotation")
                    continue
                action = resolved.get("/A") or {}
                action_type = str(action.get("/S", ""))
                if action_type == "/Launch" and "launch_action" not in findings:
                    findings.append("launch_action")
                if action_type == "/SubmitForm" and "submit_form" not in findings:
                    findings.append("submit_form")
                if action_type == "/JavaScript" and "annotation_javascript" not in findings:
                    findings.append("annotation_javascript")
    except Exception:  # noqa: BLE001 - detection is best effort, never fatal
        findings.append("active_content_scan_incomplete")

    return findings


def _looks_like_gibberish(text: str) -> bool:
    """Return True when text looks like a failed OCR pass."""
    sample = text[:4000]
    if len(sample) < 200:
        return False
    return any(pattern.search(sample) for pattern in GIBBERISH_PATTERNS)


def _headings_in(text: str) -> list[str]:
    """Return the lines in a page that look like headings.

    A PDF carries no heading elements, so this is inference. It is used only
    to enrich a citation, never to decide what a passage means, so being
    approximately right is acceptable.
    """
    headings: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or len(line) > MAX_HEADING_LENGTH:
            continue
        if line.endswith((".", ",", ";", ":")):
            continue

        numbered = NUMBERED_HEADING.match(line)
        if numbered:
            headings.append(line)
            continue

        letters = [c for c in line if c.isalpha()]
        if len(letters) >= 4 and sum(1 for c in letters if c.isupper()) / len(letters) > 0.7:
            headings.append(line)

    return headings


def extract_pdf(data: bytes, *, filename: str | None = None) -> ExtractedPdf:
    """Extract text, page numbers and metadata from PDF bytes.

    Never raises for a malformed document. A PDF that cannot be parsed is a
    condition to record against the source, and an exception escaping into a
    crawl run would stop the run over one bad file.
    """
    result = ExtractedPdf()

    if not data.startswith(b"%PDF-"):
        result.quality = ExtractionQuality.FAILED
        result.notes.append("not_a_pdf: missing %PDF- signature")
        return result

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
    except (PdfReadError, ValueError, OSError) as exc:
        result.quality = ExtractionQuality.FAILED
        result.notes.append(f"unreadable_pdf: {type(exc).__name__}")
        return result

    if getattr(reader, "is_encrypted", False):
        # An empty-password PDF is common and decrypts silently. Anything else
        # is left alone rather than attacked.
        try:
            if reader.decrypt("") == 0:
                result.encrypted = True
                result.quality = ExtractionQuality.FAILED
                result.notes.append("encrypted_pdf: a password is required")
                return result
            result.notes.append("empty_password_encryption_removed")
        except (PdfReadError, NotImplementedError) as exc:
            result.encrypted = True
            result.quality = ExtractionQuality.FAILED
            result.notes.append(f"undecryptable_pdf: {type(exc).__name__}")
            return result

    result.active_content = _detect_active_content(reader)
    if result.active_content:
        logger.warning(
            "pdf.active_content_detected",
            findings=",".join(result.active_content),
            filename=filename or "(none)",
        )

    metadata = reader.metadata or {}
    result.title = _usable_title(str(metadata.get("/Title") or ""))
    result.author = str(metadata.get("/Author") or "").strip() or None
    result.subject = str(metadata.get("/Subject") or "").strip() or None
    created = metadata.get("/CreationDate")
    result.created_text = str(created).strip() if created else None

    try:
        page_objects = reader.pages
        result.page_count = len(page_objects)
    except Exception as exc:  # noqa: BLE001 - a broken page tree is a finding
        result.quality = ExtractionQuality.FAILED
        result.notes.append(f"unreadable_page_tree: {type(exc).__name__}")
        return result

    if result.page_count > MAX_PAGES:
        result.quality = ExtractionQuality.FAILED
        result.notes.append(f"too_many_pages: {result.page_count} exceeds {MAX_PAGES}")
        return result

    total_characters = 0
    section_path: tuple[str, ...] = ()

    for index, page in enumerate(page_objects, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # noqa: BLE001 - one bad page must not stop the rest
            result.notes.append(f"page_{index}_extraction_failed: {type(exc).__name__}")
            result.pages.append(PdfPage(number=index, text=""))
            continue

        text = text.replace("\xa0", " ").strip()
        total_characters += len(text)
        if total_characters > MAX_TEXT_CHARACTERS:
            result.notes.append("text_limit_reached: remaining pages were not extracted")
            break

        headings = _headings_in(text)
        if headings:
            # The last heading on a page carries into the next one, so a
            # passage on page 5 under a heading introduced on page 4 still
            # cites the right section.
            section_path = (headings[-1],)

        result.pages.append(PdfPage(number=index, text=text, section_path=section_path))

    # Quality assessment.
    if not result.pages:
        result.quality = ExtractionQuality.FAILED
        result.notes.append("no_pages_extracted")
        return result

    ratio = result.pages_with_text / len(result.pages)
    if result.pages_with_text == 0:
        result.quality = ExtractionQuality.FAILED
        result.notes.append("no_text_layer: probably a scan, OCR required")
    elif _looks_like_gibberish(result.text):
        # Deliberately harsher than a low ratio. Plausible-looking nonsense
        # reaches retrieval and gets cited; missing text does not.
        result.quality = ExtractionQuality.LOW
        result.notes.append("text_looks_like_failed_ocr")
    elif ratio >= GOOD_EXTRACTION_RATIO:
        result.quality = ExtractionQuality.GOOD
    elif ratio >= PARTIAL_EXTRACTION_RATIO:
        result.quality = ExtractionQuality.PARTIAL
        result.notes.append(f"only_{result.pages_with_text}_of_{len(result.pages)}_pages_had_text")
    else:
        result.quality = ExtractionQuality.LOW
        result.notes.append(f"only_{result.pages_with_text}_of_{len(result.pages)}_pages_had_text")

    if not result.title and filename:
        # A filename is a poor title, but it beats an empty citation label.
        result.title = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0].replace("_", " ").strip()

    return result
