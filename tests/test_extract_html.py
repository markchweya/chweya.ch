"""HTML extraction and cleaning.

Two properties matter more than the rest: boilerplate must not reach the
index, and the wording of what does reach it must be unchanged. A paraphrased
fee or deadline is worse than no answer.
"""

from __future__ import annotations

from app.ingest.extract_html import extract_html, extract_links

PAGE = """<!DOCTYPE html>
<html lang="de-CH">
<head>
  <title>Adresse anmelden - Kanton Zug</title>
  <meta property="og:title" content="Adresse anmelden">
  <link rel="canonical" href="https://www.zug.ch/behoerden/anmeldung">
  <meta name="date" content="2026-01-15">
  <script>var tracking = 1;</script>
  <style>.x { color: red }</style>
</head>
<body>
  <div class="cookie-consent">Wir verwenden Cookies. Alle akzeptieren.</div>
  <header class="site-header">Kanton Zug</header>
  <nav class="main-navigation"><a href="/steuern">Steuern</a><a href="/bauen">Bauen</a></nav>
  <nav class="breadcrumb"><a href="/">Start</a><a href="/behoerden">Behoerden</a><a href="/behoerden/anmeldung">Anmeldung</a></nav>

  <main>
    <h1>Adresse anmelden</h1>
    <p>Sie muessen sich innert 14 Tagen nach dem Zuzug anmelden.</p>

    <h2 id="unterlagen">Erforderliche Unterlagen</h2>
    <ul>
      <li>Identitaetskarte oder Reisepass</li>
      <li>Mietvertrag</li>
      <li>Krankenversicherungsnachweis</li>
    </ul>

    <h2>Gebuehren</h2>
    <p>Die Anmeldung kostet CHF 20.-- pro Person.</p>

    <h3>Ermaessigung</h3>
    <p>Fuer Studierende betraegt die Gebuehr CHF 10.--.</p>
  </main>

  <aside class="sidebar"><p>Verwandte Themen</p></aside>
  <footer class="site-footer">Impressum | Datenschutz</footer>
  <div class="social-share">Auf Facebook teilen</div>
</body>
</html>"""


class TestBoilerplateRemoval:
    def test_scripts_and_styles_are_gone(self) -> None:
        text = extract_html(PAGE).text
        assert "tracking" not in text
        assert "color: red" not in text

    def test_cookie_notice_is_removed(self) -> None:
        assert "Cookies" not in extract_html(PAGE).text

    def test_navigation_is_removed(self) -> None:
        """Otherwise the same menu is indexed on every page and drowns content."""
        text = extract_html(PAGE).text
        assert "Bauen" not in text

    def test_header_footer_and_sidebar_are_removed(self) -> None:
        text = extract_html(PAGE).text
        assert "Impressum" not in text
        assert "Verwandte Themen" not in text
        assert "Facebook" not in text


class TestContentPreservation:
    def test_the_deadline_survives_verbatim(self) -> None:
        """Section 8 forbids rewriting. The wording must be exactly as published."""
        assert "innert 14 Tagen nach dem Zuzug" in extract_html(PAGE).text

    def test_fees_survive_verbatim(self) -> None:
        text = extract_html(PAGE).text
        assert "CHF 20.-- pro Person" in text
        assert "CHF 10.--" in text

    def test_list_items_are_kept_as_separate_blocks(self) -> None:
        """A requirements list flattened into prose loses which items are which."""
        blocks = [b.text for b in extract_html(PAGE).blocks]
        assert "Identitaetskarte oder Reisepass" in blocks
        assert "Mietvertrag" in blocks
        assert "Krankenversicherungsnachweis" in blocks


class TestCitationAnchors:
    def test_section_path_tracks_heading_nesting(self) -> None:
        page = extract_html(PAGE)
        reduction = next(b for b in page.blocks if "CHF 10" in b.text)
        assert reduction.section_path == ("Adresse anmelden", "Gebuehren", "Ermaessigung")

    def test_section_path_pops_when_a_heading_closes(self) -> None:
        """A later h2 must not inherit the previous h3."""
        page = extract_html(PAGE)
        fees = next(b for b in page.blocks if "CHF 20" in b.text)
        assert fees.section_path == ("Adresse anmelden", "Gebuehren")

    def test_element_ids_become_anchors(self) -> None:
        page = extract_html(PAGE)
        heading = next(b for b in page.blocks if b.text == "Erforderliche Unterlagen")
        assert heading.anchor == "unterlagen"

    def test_breadcrumbs_are_captured(self) -> None:
        assert extract_html(PAGE).breadcrumbs == ("Start", "Behoerden", "Anmeldung")


class TestMetadata:
    def test_og_title_is_preferred_over_the_title_element(self) -> None:
        """The title element usually carries a site-name suffix."""
        assert extract_html(PAGE).title == "Adresse anmelden"

    def test_canonical_url_is_read(self) -> None:
        assert extract_html(PAGE).canonical_url == "https://www.zug.ch/behoerden/anmeldung"

    def test_language_is_read_and_normalised(self) -> None:
        """de-CH and de mean the same thing here."""
        assert extract_html(PAGE).language == "de"

    def test_publication_date_text_is_captured(self) -> None:
        assert extract_html(PAGE).published_at_text == "2026-01-15"

    def test_h1_is_used_when_the_page_has_no_title_element(self) -> None:
        """An untitled citation gives a resident a bare URL to judge."""
        html = "<html><body><main><h1>Bulky waste collection</h1>" + (
            "<p>Collections take place on the first Monday of each month in "
            "every municipality of the canton.</p>"
        ) + "</main></body></html>"
        assert extract_html(html).title == "Bulky waste collection"


class TestQuality:
    def test_a_thin_page_is_flagged_rather_than_indexed(self) -> None:
        """An empty citation is worse than no answer."""
        page = extract_html("<html><body><main><p>Kurz.</p></main></body></html>")
        assert not page.is_usable
        assert page.quality_note == "insufficient_text"

    def test_repeated_blocks_are_deduplicated(self) -> None:
        html = (
            "<html><body><main>"
            + "<p>Die Anmeldung erfolgt bei der Einwohnerkontrolle Ihrer Gemeinde.</p>" * 3
            + "</main></body></html>"
        )
        assert len(extract_html(html).blocks) == 1

    def test_missing_body_is_reported(self) -> None:
        page = extract_html("")
        assert page.quality_note in {"no_body_element", "insufficient_text"}


class TestLinkExtraction:
    def test_relative_links_are_resolved(self) -> None:
        html = '<a href="/steuern">S</a><a href="../bauen">B</a>'
        links = extract_links(html, "https://www.zug.ch/behoerden/anmeldung")
        assert "https://www.zug.ch/steuern" in links
        assert "https://www.zug.ch/bauen" in links

    def test_non_navigational_schemes_are_skipped(self) -> None:
        html = (
            '<a href="mailto:x@zug.ch">m</a>'
            '<a href="tel:+41">t</a>'
            '<a href="javascript:alert(1)">j</a>'
            '<a href="#top">a</a>'
        )
        assert extract_links(html, "https://www.zug.ch/") == []

    def test_duplicates_are_collapsed(self) -> None:
        html = '<a href="/a">1</a><a href="/a?utm_source=x">2</a><a href="/a#frag">3</a>'
        assert extract_links(html, "https://www.zug.ch/") == ["https://www.zug.ch/a"]

    def test_off_site_links_are_returned_for_the_caller_to_filter(self) -> None:
        """Deciding what may be fetched belongs to the allowlist, not here."""
        links = extract_links('<a href="https://example.com/x">x</a>', "https://www.zug.ch/")
        assert links == ["https://example.com/x"]
