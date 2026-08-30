"""Chunking.

A chunk is what retrieval returns and what a citation points at, so two
properties matter: the passage must carry the heading trail of the content it
actually holds, and no content may be silently dropped.

Both of these were broken in the first implementation and are pinned here.
"""

from __future__ import annotations

import pathlib

from app.ingest.chunking import chunk_page, chunk_pdf
from app.ingest.extract_html import extract_html
from app.ingest.extract_pdf import extract_pdf

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

PAGE = """<html lang="de"><body><main>
<h1>Adresse anmelden</h1>
<p>Sie muessen sich innert 14 Tagen nach dem Zuzug anmelden.</p>
<h2 id="unterlagen">Erforderliche Unterlagen</h2>
<ul><li>Identitaetskarte oder Reisepass</li><li>Mietvertrag</li></ul>
<h2>Gebuehren</h2>
<p>Die Anmeldung kostet CHF 20.-- pro Person.</p>
<h3>Ermaessigung</h3>
<p>Fuer Studierende betraegt die Gebuehr CHF 10.--.</p>
</main></body></html>"""


class TestSectionAttribution:
    def test_each_section_becomes_its_own_chunk(self) -> None:
        """A short page must not collapse into one chunk under the h1.

        The first implementation gated the section flush on buffer length, so
        on a short page every section merged into one chunk carrying the page
        title as its heading trail.
        """
        chunks = chunk_page(extract_html(PAGE))
        assert len(chunks) >= 4

    def test_the_fee_cites_its_own_section(self) -> None:
        """This is the failure the gating bug produced: a fee cited as though
        it sat directly under the page title rather than under Gebuehren."""
        chunks = chunk_page(extract_html(PAGE))
        fee = next(c for c in chunks if "CHF 20" in c.text)
        assert fee.section_path == ("Adresse anmelden", "Gebuehren")

    def test_nested_sections_keep_the_full_trail(self) -> None:
        chunks = chunk_page(extract_html(PAGE))
        reduction = next(c for c in chunks if "CHF 10" in c.text)
        assert reduction.section_path == ("Adresse anmelden", "Gebuehren", "Ermaessigung")

    def test_a_short_section_is_not_merged_into_a_different_one(self) -> None:
        """Merging across sections relabels text with the wrong heading."""
        chunks = chunk_page(extract_html(PAGE))
        for chunk in chunks:
            if "CHF 10" in chunk.text:
                assert "CHF 20" not in chunk.text, "two fees merged under one heading"

    def test_anchors_are_carried_for_deep_linking(self) -> None:
        chunks = chunk_page(extract_html(PAGE))
        documents = next(c for c in chunks if "Identitaetskarte" in c.text)
        assert documents.anchor == "unterlagen"

    def test_ordinals_are_sequential(self) -> None:
        chunks = chunk_page(extract_html(PAGE))
        assert [c.ordinal for c in chunks] == list(range(len(chunks)))


class TestPdfChunking:
    def test_every_page_with_text_produces_a_chunk(self) -> None:
        """A page holding 118 characters is short, not empty.

        The first implementation used the chunk minimum as the page floor, so
        the second page of the fixture fell just under it and its content was
        dropped from the index entirely.
        """
        document = extract_pdf((FIXTURES / "merkblatt.pdf").read_bytes())
        chunks = chunk_pdf(document)
        assert {c.page_number for c in chunks} == {1, 2}

    def test_content_is_attributed_to_the_page_it_is_on(self) -> None:
        document = extract_pdf((FIXTURES / "merkblatt.pdf").read_bytes())
        chunks = chunk_pdf(document)
        fee = next(c for c in chunks if "CHF 20" in c.text)
        assert fee.page_number == 1

    def test_chunks_never_span_two_pages(self) -> None:
        """A citation names one page, so a chunk must not straddle two."""
        document = extract_pdf((FIXTURES / "merkblatt.pdf").read_bytes())
        for chunk in chunk_pdf(document):
            assert chunk.page_number is not None


class TestSizeHandling:
    def test_long_text_is_split(self) -> None:
        long_paragraph = "Die Gebuehr betraegt CHF 20 pro Person. " * 200
        html = f"<html><body><main><h1>T</h1><p>{long_paragraph}</p></main></body></html>"
        chunks = chunk_page(extract_html(html))
        assert len(chunks) > 1
        assert all(len(c.text) <= 2200 for c in chunks)

    def test_swiss_legal_abbreviations_do_not_split_sentences(self) -> None:
        """Art. and Abs. end in a full stop but not a sentence."""
        text = "Gemaess Art. 12 Abs. 3 lit. b des Gesetzes gilt die Frist. " * 60
        html = f"<html><body><main><h1>T</h1><p>{text}</p></main></body></html>"
        for chunk in chunk_page(extract_html(html)):
            assert not chunk.text.strip().endswith("Art."), "split inside a legal reference"
            assert not chunk.text.strip().endswith("Abs.")

    def test_token_estimate_is_populated(self) -> None:
        chunks = chunk_page(extract_html(PAGE))
        assert all(c.token_estimate > 0 for c in chunks)

    def test_an_empty_page_yields_no_chunks(self) -> None:
        assert chunk_page(extract_html("<html><body></body></html>")) == []
