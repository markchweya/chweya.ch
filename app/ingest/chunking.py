"""Splitting extracted content into retrievable passages.

A chunk is the unit that retrieval returns and that a citation points at, so
the split has to respect two things at once.

Meaning: a chunk that ends halfway through a requirements list, or that
separates a fee from the service it belongs to, produces an answer that is
technically sourced and practically wrong. Splits are therefore made at
structural boundaries first and only fall back to sentence boundaries.

Citability: every chunk carries the heading trail and, for PDFs, the page
number of the content it holds. A chunk spanning two PDF pages is attributed
to the page where it starts, because a citation has to name one page and the
first is where a reader begins looking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingest.extract_html import ExtractedBlock, ExtractedPage
from app.ingest.extract_pdf import ExtractedPdf

# Target size in characters. Chosen so several chunks fit an 8k context window
# alongside the system instruction and the question, with room for the answer.
TARGET_CHUNK_CHARACTERS = 1400
MAX_CHUNK_CHARACTERS = 2200
# Below this a chunk carries too little context to be useful on its own.
MIN_CHUNK_CHARACTERS = 120

# A PDF page below this is effectively blank. Much lower than the chunk
# minimum, because a short page still has to reach the index.
MIN_PDF_PAGE_CHARACTERS = 25

# Overlap between adjacent chunks, so a sentence spanning a boundary is
# retrievable from both sides.
OVERLAP_CHARACTERS = 150

# Sentence boundary for German, French, Italian and English. Avoids splitting
# on abbreviations common in Swiss administrative German such as "Art." and
# "Abs.", and on decimal numbers.
SENTENCE_BOUNDARY = re.compile(
    r"(?<![A-Z][a-z]\.)(?<!\bArt\.)(?<!\bAbs\.)(?<!\bBst\.)(?<!\bZiff\.)(?<!\bNr\.)"
    r"(?<!\blit\.)(?<!\bbzw\.)(?<!\bca\.)(?<!\bd\.h\.)(?<!\bz\.B\.)(?<!\bevtl\.)"
    r"(?<!\d)\.\s+(?=[A-ZÄÖÜ])"
)

# Rough characters-per-token, used only to populate token_estimate. Kept
# pessimistic for the same reason as in the Apertus provider.
CHARS_PER_TOKEN = 3.0


@dataclass
class TextChunk:
    """One retrievable passage with everything a citation needs."""

    text: str
    ordinal: int
    section_path: tuple[str, ...] = ()
    page_number: int | None = None
    anchor: str | None = None
    language: str = "de"
    extra: dict = field(default_factory=dict)

    @property
    def token_estimate(self) -> int:
        return int(len(self.text) / CHARS_PER_TOKEN) + 1


def _split_long_text(text: str) -> list[str]:
    """Split text that exceeds the maximum at sentence boundaries.

    Falls back to a hard character split only when a single sentence is longer
    than the maximum, which happens with badly extracted tables.
    """
    if len(text) <= MAX_CHUNK_CHARACTERS:
        return [text]

    sentences = SENTENCE_BOUNDARY.split(text)
    pieces: list[str] = []
    current = ""

    for sentence in sentences:
        candidate = f"{current} {sentence}".strip() if current else sentence
        if len(candidate) > TARGET_CHUNK_CHARACTERS and current:
            pieces.append(current)
            current = sentence
        else:
            current = candidate

    if current:
        pieces.append(current)

    # A single sentence longer than the maximum still has to be broken.
    final: list[str] = []
    for piece in pieces:
        while len(piece) > MAX_CHUNK_CHARACTERS:
            final.append(piece[:MAX_CHUNK_CHARACTERS])
            piece = piece[MAX_CHUNK_CHARACTERS - OVERLAP_CHARACTERS :]
        if piece:
            final.append(piece)

    return final


def chunk_blocks(blocks: list[ExtractedBlock], *, language: str = "de") -> list[TextChunk]:
    """Group extracted HTML blocks into chunks.

    Blocks are accumulated until the target size is reached, and a new chunk is
    started whenever the heading trail changes. Keeping a section together
    matters more than filling a chunk evenly: a fee and the service it applies
    to belong in the same passage.
    """
    chunks: list[TextChunk] = []
    buffer: list[ExtractedBlock] = []
    buffer_length = 0

    def flush() -> None:
        nonlocal buffer, buffer_length
        if not buffer:
            return
        text = "\n".join(block.text for block in buffer).strip()
        head_path = buffer[0].section_path
        # Merge a short run into the previous chunk only when it belongs to the
        # same section. Merging across sections relabels the text with the
        # wrong heading trail, and a citation naming the wrong section of a
        # long page is worse than a short chunk naming the right one.
        if (
            len(text) < MIN_CHUNK_CHARACTERS
            and chunks
            and chunks[-1].section_path == head_path
        ):
            previous = chunks[-1]
            if len(previous.text) + len(text) <= MAX_CHUNK_CHARACTERS:
                chunks[-1] = TextChunk(
                    text=f"{previous.text}\n{text}",
                    ordinal=previous.ordinal,
                    section_path=previous.section_path,
                    page_number=previous.page_number,
                    anchor=previous.anchor,
                    language=previous.language,
                )
                buffer, buffer_length = [], 0
                return

        # The heading trail and anchor come from the first block, which is
        # where a reader following the citation arrives.
        head = buffer[0]
        anchor = next((b.anchor for b in buffer if b.anchor), None)
        for piece in _split_long_text(text):
            chunks.append(
                TextChunk(
                    text=piece,
                    ordinal=len(chunks),
                    section_path=head.section_path,
                    anchor=anchor,
                    language=language,
                )
            )
        buffer, buffer_length = [], 0

    previous_path: tuple[str, ...] | None = None

    for block in blocks:
        # A new section always starts a new chunk. There is deliberately no
        # size condition here: gating the flush on buffer length made every
        # section of a short page collapse into one chunk carrying the h1 as
        # its heading trail, so a fee under "Gebuehren" cited as though it sat
        # directly under the page title.
        if previous_path is not None and block.section_path != previous_path and buffer:
            flush()

        buffer.append(block)
        buffer_length += len(block.text) + 1
        previous_path = block.section_path

        if buffer_length >= TARGET_CHUNK_CHARACTERS:
            flush()
            previous_path = block.section_path

    flush()
    return chunks


def chunk_pdf(document: ExtractedPdf, *, language: str = "de") -> list[TextChunk]:
    """Split a PDF into chunks, each attributed to the page it starts on.

    Page boundaries are respected: a chunk never silently merges text from two
    pages under one page number, because that would make the citation point at
    a page that does not contain half of what was quoted.
    """
    chunks: list[TextChunk] = []

    for page in document.pages:
        text = page.text.strip()
        # Deliberately not MIN_CHUNK_CHARACTERS. A page holding 118 characters
        # is short, not empty, and dropping it removes its content from the
        # index entirely. The floor here only skips pages that are effectively
        # blank, matching the extractor's own threshold.
        if len(text) < MIN_PDF_PAGE_CHARACTERS:
            continue
        for piece in _split_long_text(text):
            chunks.append(
                TextChunk(
                    text=piece,
                    ordinal=len(chunks),
                    section_path=page.section_path,
                    page_number=page.number,
                    language=language,
                )
            )

    return chunks


def chunk_page(page: ExtractedPage, *, language: str | None = None) -> list[TextChunk]:
    """Chunk an extracted HTML page."""
    return chunk_blocks(page.blocks, language=language or page.language or "de")
