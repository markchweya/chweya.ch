# Phase 3 report: ingestion

Status at commit `d530149`. Written to the rule in section 26: report what
works, report what does not, and do not claim completion for anything
unverified.

## Verified working

Exercised against a real PostgreSQL 16 database and a stand-in canton site,
not inferred from the code.

**The two-gate URL policy.** `app.ingest.urls` decides whether a name may be
fetched, before any DNS lookup. `app.ingest.netguard` decides whether the
address it resolves to may be connected to. Both are needed: a hostname on the
allowlist can still resolve to a private address.

**Allowlist matching on label boundaries.** `evil-zug.ch`,
`zug.ch.attacker.example` and `notzug.ch` are all refused for an allowlist
entry of `zug.ch`. A plain `endswith` accepts all three, which is how
allowlists usually fail.

**SSRF address validation.** Loopback, private, link-local, multicast,
reserved, carrier-grade NAT, broadcast and unspecified addresses are refused,
and the cloud metadata addresses are named specifically so a blocked attempt
records which rule stopped it. `::ffff:127.0.0.1` is unwrapped and refused as
loopback.

**DNS rebinding closed by pinning.** The request URL carries the validated IP,
the `Host` header carries the name so the server serves the right virtual
host, and `sni_hostname` carries it so TLS still verifies against the real
certificate. A test asserts all three.

**Redirect revalidation.** Every hop goes back through both gates. Tested: a
redirect off the allowlist, a redirect to a name resolving to loopback, a
redirect to `file://`, an unbounded chain, and a two-URL loop. The private
address case asserts the second hop opens no connection.

**robots.txt obedience, failing closed.** 404 allows everything. 5xx, timeout,
transport failure and 403 disallow the whole host until robots.txt can be
read.

**Sitemap discovery.** Indexes are walked, cycles terminate, a `DOCTYPE` is
refused outright, and a malformed sitemap is recorded against the source
rather than aborting the run.

**HTML extraction.** Boilerplate removed, wording preserved verbatim, heading
trail and element anchors captured for citations.

**PDF extraction with page numbers.** Text is attributed to the page it is on.
Encrypted documents are refused rather than attacked. Active content is
detected and never executed.

**Chunking.** Sections stay together, chunks carry their heading trail and PDF
page number, and Swiss legal abbreviations do not split sentences.

**End-to-end crawl.** A source with a sitemap produces documents, versions and
chunks with correct section paths. A second run over unchanged content creates
no new version.

**Tests.** 274 passing. 26 need `TEST_DATABASE_URL`.

## Defects found by testing

Recorded because each shows where reading the code was not enough.

**Search pages were being crawled.** The exclusion patterns required `/` or
end-of-string after the segment, so `/suche` matched but `/suche?q=steuern`
did not, and that is the form a search page actually takes.

**The credentials-in-URL check was dead code.** `normalise()` rebuilds the
netloc from the hostname alone, silently discarding userinfo, so the check
never fired. It now inspects the raw URL.

**Every citation's section path would have been wrong.** The HTML block walk
used a grouped CSS selector, and selectolax returns those grouped by selector
rather than in document order: every heading, then every paragraph. The
heading trail was built from whichever heading came last in the document.
Silent, plausible, and wrong on every page.

**Sections collapsed on short pages.** The section-change flush was gated on
buffer size, so a page whose sections are a sentence each merged into one
chunk carrying the `h1`. A fee under "Gebühren" was cited as though it sat
directly under the page title.

**PDF pages were silently dropped.** `chunk_pdf` used the chunk minimum as its
page floor. The second page of the test fixture holds 118 characters against a
120 floor, so its content never reached the index.

**Soft hyphens would have flagged half the site.** German CMSes emit them
throughout compound words for hyphenation, and they were being counted as
suspicious invisible characters. Invisible characters are now split into a
benign class and a suspicious one.

**Autogenerate proposed dropping a security-relevant index.** It wanted to
replace the functional unique index on `lower(email)` with one on `email`,
which removes case-insensitive uniqueness and lets one person hold two
accounts. Fixed in the models so it stops proposing it.

## Not implemented

- **Scheduled synchronisation.** A crawl runs when called. Nothing schedules
  it, and the `sync` Make target still exits non-zero.
- **Multi-level link following.** One level within the source's base path.
  Deeper needs a persisted frontier with its own loop control.
- **OCR.** The pipeline detects that a PDF needs it and records
  `no_text_layer`. Nothing runs OCR.
- **DOCX, CSV and administrator uploads.** Schema and lifecycle states exist;
  the upload path does not.
- **Source management endpoints.** Sources are rows. There is no interface to
  create, pause or trigger them.
- **Concurrency.** URLs are crawled one at a time. `CRAWLER_MAX_CONCURRENCY`
  is read and not used.
- **Contradiction detection.** Phase 5.

## Environment limitations

**No request has been made to `zug.ch`.** Every test runs against a stand-in
site. The allowlist, robots handling and extraction are verified against
constructed input, not against the real site's markup. Real cantonal HTML will
have chrome patterns this has not seen, and the boilerplate filters will need
tuning against it. That tuning is a first-run task, not a code change.

**The politeness delay defaults to one second per host and has never been
exercised against a real server.**

## Requires human review before any real crawl

- The crawler policy and its reading of the `zug.ch` terms of use need review
  by someone with authority to accept the legal risk.
- `CRAWLER_CONTACT` must name a reachable address before the crawler runs
  against a site the project does not own. Production refuses to start
  without it.
- The exclusion list encodes assumptions about which paths are not public
  content. Those should be checked against the real site.
