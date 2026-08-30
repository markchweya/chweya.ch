"""URL normalisation, canonicalisation and the crawl allowlist.

Two jobs that have to agree with each other:

* Deciding whether a URL may be fetched at all. That decision is made here,
  before any DNS lookup, and again in app.ingest.netguard against the resolved
  address.
* Reducing URLs that name the same page to one string, so the same content is
  not crawled, stored and cited several times under different spellings.

Normalisation is deliberately conservative. Two URLs are only collapsed when
they are the same page under the HTTP specification. Stripping a query
parameter that the site actually uses would make the crawler fetch the wrong
page and cite it as the right one, which is worse than crawling a duplicate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Only these schemes are ever fetched. file:, ftp:, gopher: and data: are all
# ways to reach something that is not a public web page.
ALLOWED_SCHEMES = frozenset({"http", "https"})

DEFAULT_PORTS = {"http": 80, "https": 443}

# Query parameters that never change which page is returned. Removing them
# collapses the same page arriving from different campaigns and referrers.
# Kept short on purpose: anything not obviously a tracker stays.
TRACKING_PARAMETERS = frozenset(
    {
        "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
        "utm_id", "gclid", "fbclid", "msclkid", "mc_cid", "mc_eid",
        "_ga", "_gl", "ref", "referrer",
    }
)

# Path segments that indicate a page which is not informational content.
# Search result pages and calendar views generate unbounded URL spaces, and
# the brief excludes them unless an administrator approves them explicitly.
# A segment ends at "/", "?" or the end of the string. Requiring only "/"
# or end-of-string let "/suche?q=steuern" through, so search pages were
# being crawled despite the exclusion.
SEGMENT_END = r"(?=[/?]|$)"

EXCLUDED_PATH_PATTERNS = (
    re.compile(r"/suche" + SEGMENT_END, re.IGNORECASE),
    re.compile(r"/search" + SEGMENT_END, re.IGNORECASE),
    re.compile(r"/recherche" + SEGMENT_END, re.IGNORECASE),
    re.compile(r"/ricerca" + SEGMENT_END, re.IGNORECASE),
    # Calendar and archive views, which paginate forever.
    re.compile(r"/kalender" + SEGMENT_END, re.IGNORECASE),
    re.compile(r"/calendar" + SEGMENT_END, re.IGNORECASE),
    re.compile(r"/\d{4}/\d{2}/\d{2}(/|$)"),
    # Authenticated and administrative areas. The crawler must never touch
    # these, and following such a link would be an attempt to reach content
    # that is not public.
    re.compile(r"/(login|logout|admin|intern|internal|myaccount|konto)" + SEGMENT_END, re.IGNORECASE),
    # Print and share endpoints, which duplicate a page we already have.
    re.compile(r"[?&](print|share)=", re.IGNORECASE),
    # Content-management view endpoints. "@@" is the CMS view namespace on
    # zg.ch, and the *_view and export_pdf paths serve the page we already
    # crawled again, as a widget or a generated download. Each one fetched
    # spends page budget on a duplicate.
    re.compile(r"@@"),
    re.compile(r"/[\w-]*_view" + SEGMENT_END, re.IGNORECASE),
    re.compile(r"/export_pdf" + SEGMENT_END, re.IGNORECASE),
    # Interactive form endpoints, which are applications, not content.
    re.compile(r"/aforms-formular" + SEGMENT_END, re.IGNORECASE),
)

# Query parameters that create an unbounded space of near-identical pages.
PAGINATION_PARAMETERS = frozenset({"page", "seite", "p", "start", "offset", "from", "tx_news_pi1"})

MAX_URL_LENGTH = 2048
MAX_PATH_SEGMENTS = 24
MAX_QUERY_PARAMETERS = 8


@dataclass(frozen=True)
class UrlDecision:
    """Whether a URL may be crawled, and why not when it may not."""

    allowed: bool
    # A machine-readable reason, so blocked attempts can be counted by cause
    # in the administration dashboard rather than only logged as prose.
    reason: str = ""
    normalised: str = ""

    def __bool__(self) -> bool:
        return self.allowed


def normalise(url: str, *, base: str | None = None) -> str:
    """Return a canonical form of ``url``.

    Applies only transformations that the HTTP specification says preserve
    identity, plus removal of known tracking parameters:

    * Scheme and host lower-cased. Both are case-insensitive.
    * The default port for the scheme removed.
    * Fragment removed. It is never sent to the server.
    * An empty path becomes "/".
    * Query parameters sorted, so ordering does not create duplicates.

    Path case is preserved, because paths are case-sensitive on many servers
    and lower-casing one would produce a URL that 404s.
    """
    if base:
        from urllib.parse import urljoin

        url = urljoin(base, url)

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    host = parts.hostname.lower() if parts.hostname else ""

    # Drop the default port. https://zug.ch:443/x and https://zug.ch/x are
    # the same resource.
    port = parts.port
    netloc = host
    if port is not None and port != DEFAULT_PORTS.get(scheme):
        netloc = f"{host}:{port}"

    path = parts.path or "/"
    # Collapse repeated slashes, which servers treat as one.
    path = re.sub(r"/{2,}", "/", path)

    query = ""
    if parts.query:
        kept = [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.lower() not in TRACKING_PARAMETERS
        ]
        # Sorted so ?a=1&b=2 and ?b=2&a=1 collapse to one URL.
        query = urlencode(sorted(kept))

    # Fragment dropped: it is a client-side anchor and never reaches the server.
    return urlunsplit((scheme, netloc, path, query, ""))


def host_matches_allowlist(host: str, allowed: tuple[str, ...]) -> bool:
    """Return True if ``host`` is on the allowlist, or is a subdomain of one.

    Matching is on label boundaries. A naive ``endswith`` check would accept
    ``evil-zug.ch`` and ``zug.ch.attacker.example`` for an allowlist entry of
    ``zug.ch``, which is how allowlists usually fail.
    """
    host = host.lower().rstrip(".")
    for entry in allowed:
        entry = entry.lower().rstrip(".")
        if host == entry:
            return True
        if host.endswith("." + entry):
            return True
    return False


def evaluate(url: str, allowed_hosts: tuple[str, ...], *, base: str | None = None) -> UrlDecision:
    """Decide whether ``url`` may be crawled.

    This is the first of two gates. It runs before any DNS lookup and rejects
    on the URL alone. The second gate, in app.ingest.netguard, validates the
    address the hostname resolves to, because a name on the allowlist can
    still resolve to a private address.
    """
    if not url or len(url) > MAX_URL_LENGTH:
        return UrlDecision(False, "url_too_long_or_empty")

    try:
        # Inspected before normalisation. normalise() rebuilds the netloc from
        # the hostname alone, which silently discards any userinfo, so a check
        # made afterwards would never fire.
        raw_parts = urlsplit(url.strip())
        candidate = normalise(url, base=base)
        parts = urlsplit(candidate)
    except ValueError:
        # urlsplit raises on malformed IPv6 literals and bad ports.
        return UrlDecision(False, "malformed_url")

    # Credentials in a URL are a redirect-phishing pattern and have no place in
    # a crawl target.
    if raw_parts.username or raw_parts.password:
        return UrlDecision(False, "credentials_in_url")

    if parts.scheme not in ALLOWED_SCHEMES:
        return UrlDecision(False, "scheme_not_allowed")

    host = parts.hostname or ""
    if not host:
        return UrlDecision(False, "no_hostname")

    if not host_matches_allowlist(host, allowed_hosts):
        return UrlDecision(False, "host_not_on_allowlist")

    path_and_query = parts.path + ("?" + parts.query if parts.query else "")
    for pattern in EXCLUDED_PATH_PATTERNS:
        if pattern.search(path_and_query):
            return UrlDecision(False, "excluded_path")

    # Bound the shapes that create unbounded URL spaces.
    if parts.path.count("/") > MAX_PATH_SEGMENTS:
        return UrlDecision(False, "path_too_deep")

    if parts.query:
        params = parse_qsl(parts.query, keep_blank_values=True)
        if len(params) > MAX_QUERY_PARAMETERS:
            return UrlDecision(False, "too_many_query_parameters")
        # One pagination parameter is fine. Two means a filter matrix, which
        # multiplies out into thousands of near-identical pages.
        pagination = sum(1 for key, _ in params if key.lower() in PAGINATION_PARAMETERS)
        if pagination > 1:
            return UrlDecision(False, "pagination_matrix")

    return UrlDecision(True, "", candidate)
