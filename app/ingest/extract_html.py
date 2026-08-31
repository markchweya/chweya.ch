"""HTML extraction and cleaning.

Turns a fetched page into text worth retrieving over, plus the structure a
citation needs.

Two constraints shape everything here.

First, the text must not be rewritten. Section 8 forbids changing meaning
during ingestion, so this module removes and preserves; it never rephrases,
summarises or normalises wording. A fee of "CHF 20.-" stays exactly that.

Second, the structure has to survive. A resident asking about a deadline needs
the deadline, and a deadline usually lives in a list or a table under a
specific heading. Flattening a page into a wall of prose destroys the section
trail that makes a citation useful and often destroys the answer with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from selectolax.parser import HTMLParser, Node

# Elements that never carry content worth indexing. Removed outright.
DISCARD_TAGS = frozenset(
    {
        "script", "style", "noscript", "template", "svg", "canvas",
        "iframe", "object", "embed", "form", "button", "input", "select",
        "textarea", "label", "video", "audio", "picture", "source",
    }
)

# Structural chrome that repeats on every page. Removing it stops the same
# navigation text being indexed hundreds of times and drowning the content.
CHROME_TAGS = frozenset({"nav", "header", "footer", "aside"})

# Class and id fragments that mark chrome on typical government sites. Matched
# case-insensitively as substrings, which is blunt but effective; a false
# positive costs one block of text, a false negative costs the same boilerplate
# on every page in the index.
CHROME_PATTERNS = (
    "cookie", "consent", "datenschutzhinweis", "navigation", "navbar", "menu",
    "breadcrumb", "sidebar", "skip-link", "skiplink", "sprachwahl",
    "language-switch", "langnav", "social", "share", "teilen", "footer",
    "header", "banner", "advert", "werbung", "newsletter", "search-form",
    "suchformular", "accessibility-toolbar", "toolbar", "back-to-top",
    "pagination", "pager", "print-only", "screen-reader-only", "sr-only",
    "visually-hidden",
)

# Elements whose text is kept as a block, in document order.
BLOCK_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dt", "dd", "pre", "blockquote")
HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# A block shorter than this is almost always a fragment of chrome that escaped
# the filters: a single word in a menu, a stray label.
MIN_BLOCK_CHARACTERS = 3

# Below this, a page has no useful content. Recorded as low quality rather
# than indexed, so retrieval never returns an empty citation.
MIN_DOCUMENT_CHARACTERS = 120


@dataclass
class ExtractedBlock:
    """One block of text with the heading trail above it."""

    text: str
    tag: str
    # The h1..h6 chain in force at this point, outermost first. This is what a
    # citation shows as "Steuern > Natuerliche Personen > Fristen".
    section_path: tuple[str, ...] = ()
    # The nearest usable id attribute, so a citation link can land on the
    # passage instead of the top of the page.
    anchor: str | None = None

    @property
    def is_heading(self) -> bool:
        return self.tag in HEADING_TAGS


@dataclass
class ExtractedPage:
    """Everything pulled out of one HTML document."""

    title: str = ""
    blocks: list[ExtractedBlock] = field(default_factory=list)
    breadcrumbs: tuple[str, ...] = ()
    canonical_url: str | None = None
    language: str | None = None
    published_at_text: str | None = None
    # Set when the page is too thin to index.
    quality_note: str = ""

    @property
    def text(self) -> str:
        """The blocks joined for indexing and language detection."""
        return "\n\n".join(block.text for block in self.blocks)

    @property
    def is_usable(self) -> bool:
        return len(self.text) >= MIN_DOCUMENT_CHARACTERS


def _looks_like_chrome(node: Node) -> bool:
    """Return True when a node's class or id marks it as page furniture."""
    attributes = node.attributes or {}
    haystack = " ".join(
        str(attributes.get(name) or "") for name in ("class", "id", "role", "data-testid")
    ).lower()
    if not haystack:
        return False
    return any(pattern in haystack for pattern in CHROME_PATTERNS)


def _inside_table(node: Node) -> bool:
    """Whether a node sits inside a table, whose text the row handling owns."""
    parent = node.parent
    while parent is not None:
        if parent.tag == "table":
            return True
        parent = parent.parent
    return False


def _table_rows(table: Node) -> list[str]:
    """Render a table's rows as text, one line per row.

    Cells are joined with " | ", which keeps a row's values together through
    chunking and retrieval. A holiday calendar or a fee schedule lives in a
    table, and flattening it cell by cell into prose destroys exactly the
    answer a resident asked for.
    """
    rows: list[str] = []
    for row in table.css("tr"):
        cells = [
            _collapse_whitespace(cell.text()) for cell in row.css("th, td")
        ]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(" | ".join(cells))
        elif cells and len(cells[0]) >= MIN_BLOCK_CHARACTERS:
            rows.append(cells[0])
    return rows


def _collapse_whitespace(value: str) -> str:
    """Collapse runs of whitespace without touching the words themselves.

    Non-breaking spaces become ordinary ones, because a fee written with a
    non-breaking space would otherwise not match a query written with a normal
    one.
    """
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def _extract_breadcrumbs(tree: HTMLParser) -> tuple[str, ...]:
    """Pull the breadcrumb trail, which names the responsible area of the site."""
    for selector in (
        '[class*="breadcrumb"]',
        '[id*="breadcrumb"]',
        'nav[aria-label*="readcrumb"]',
        '[typeof="BreadcrumbList"]',
    ):
        node = tree.css_first(selector)
        if node is None:
            continue
        parts = [
            _collapse_whitespace(link.text())
            for link in node.css("a, li, span")
            if _collapse_whitespace(link.text())
        ]
        # Deduplicate while preserving order: markup often nests a span inside
        # each list item, which yields every label twice.
        seen: list[str] = []
        for part in parts:
            if part not in seen and len(part) < 120:
                seen.append(part)
        if len(seen) >= 2:
            return tuple(seen)
    return ()


def _meta(tree: HTMLParser, **attrs: str) -> str | None:
    """Return the content of the first matching meta element."""
    selector = "meta" + "".join(f'[{k}="{v}"]' for k, v in attrs.items())
    node = tree.css_first(selector)
    if node is None:
        return None
    value = (node.attributes or {}).get("content")
    return _collapse_whitespace(value) if value else None


def extract_html(html: str, *, url: str | None = None) -> ExtractedPage:
    """Extract readable content and structure from an HTML document.

    ``url`` is used only for diagnostics. Nothing about the extraction depends
    on it, so a page can be re-extracted from stored bytes later.
    """
    tree = HTMLParser(html)

    page = ExtractedPage()

    title_node = tree.css_first("title")
    if title_node is not None:
        page.title = _collapse_whitespace(title_node.text())
    # og:title is usually cleaner, lacking the site name suffix.
    og_title = _meta(tree, property="og:title")
    if og_title and len(og_title) > 3:
        page.title = og_title

    canonical = tree.css_first('link[rel="canonical"]')
    if canonical is not None:
        href = (canonical.attributes or {}).get("href")
        if href:
            page.canonical_url = href.strip()

    html_node = tree.css_first("html")
    if html_node is not None:
        lang = (html_node.attributes or {}).get("lang")
        if lang:
            # "de-CH" and "de" mean the same thing for our purposes.
            page.language = lang.strip().lower().split("-")[0][:5] or None

    page.published_at_text = (
        _meta(tree, property="article:published_time")
        or _meta(tree, name="date")
        or _meta(tree, name="dcterms.date")
    )

    page.breadcrumbs = _extract_breadcrumbs(tree)

    # Remove everything that cannot contribute before walking the tree, so the
    # walk does not have to keep re-checking ancestry.
    for tag in DISCARD_TAGS | CHROME_TAGS:
        for node in tree.css(tag):
            node.decompose()

    body = tree.css_first("body") or tree.root
    if body is None:
        page.quality_note = "no_body_element"
        return page

    for node in body.css("*"):
        if _looks_like_chrome(node):
            node.decompose()

    # Prefer the main content region when the page marks one. Government sites
    # usually do, and it removes a whole class of stray blocks.
    container = body
    for selector in ("main", '[role="main"]', "article", "#content", ".content"):
        found = body.css_first(selector)
        if found is not None and len(found.text() or "") > MIN_DOCUMENT_CHARACTERS:
            container = found
            break

    section_path: list[str] = []
    seen_blocks: set[str] = set()

    # Walked with traverse() rather than a grouped CSS selector. selectolax
    # returns a comma-separated selector grouped by selector, so
    # css("h1, h2, p") yields every heading and then every paragraph. That
    # destroys the heading trail: each paragraph would inherit whichever
    # heading happened to come last in the document, not the one above it.
    block_tags = set(BLOCK_TAGS)
    for node in container.traverse(include_text=False):
        tag = node.tag

        # Tables are handled as rows, and anything inside one belongs to its
        # row: without the guard a paragraph in a cell would appear twice,
        # once in the row and once on its own.
        if tag == "table":
            if _inside_table(node):
                continue
            anchor = (node.attributes or {}).get("id")
            for row_text in _table_rows(node):
                page.blocks.append(
                    ExtractedBlock(
                        text=row_text,
                        tag="tr",
                        section_path=tuple(part for part in section_path if part),
                        anchor=anchor or None,
                    )
                )
            continue
        if tag not in block_tags:
            continue
        if _inside_table(node):
            continue
        text = _collapse_whitespace(node.text())
        if len(text) < MIN_BLOCK_CHARACTERS:
            continue

        if tag in HEADING_TAGS:
            level = int(tag[1])
            # Pop deeper or equal headings, then push this one, so the trail
            # reflects nesting rather than document order.
            del section_path[level - 1 :]
            while len(section_path) < level - 1:
                section_path.append("")
            section_path.append(text)

        # The same string twice in one page is boilerplate that survived the
        # filters, or a summary repeated as a teaser.
        fingerprint = text.lower()
        if fingerprint in seen_blocks:
            continue
        seen_blocks.add(fingerprint)

        anchor = (node.attributes or {}).get("id")

        page.blocks.append(
            ExtractedBlock(
                text=text,
                tag=tag,
                section_path=tuple(part for part in section_path if part),
                anchor=anchor or None,
            )
        )

    # A page with no title element still needs a citation label, and its own
    # h1 is the best available one. An untitled citation gives a resident a
    # bare URL to judge, which defeats the point of citing at all.
    if not page.title:
        first_heading = next((b for b in page.blocks if b.tag == "h1"), None)
        if first_heading is not None:
            page.title = first_heading.text

    if not page.is_usable:
        page.quality_note = "insufficient_text"

    return page


def extract_links(html: str, base_url: str) -> list[str]:
    """Return the absolute links found in a document.

    Returned unfiltered. The caller passes each through the allowlist, because
    deciding what may be fetched is that module's job and duplicating the rule
    here would let the two drift apart.
    """
    tree = HTMLParser(html)
    from app.ingest.urls import normalise

    found: list[str] = []
    seen: set[str] = set()

    for node in tree.css("a[href]"):
        href = (node.attributes or {}).get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        try:
            absolute = normalise(href, base=base_url)
        except ValueError:
            continue
        if absolute not in seen:
            seen.add(absolute)
            found.append(absolute)

    return found
