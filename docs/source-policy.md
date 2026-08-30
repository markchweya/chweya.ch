# Source allowlist and exclusion policy

## The allowlist

`CRAWLER_ALLOWED_HOSTS`, currently `www.zug.ch,zug.ch,www.zg.ch,zg.ch`.
zg.ch is the Canton of Zug, zug.ch is the City of Zug; the cantonal
content lives on zg.ch.

Matching is on label boundaries, so `zug.ch` admits `zug.ch` and
`steuern.zug.ch` and refuses `evil-zug.ch` and `zug.ch.attacker.example`. A
plain suffix check accepts both of those, which is how allowlists usually
fail, and there are tests for each shape.

### Adding a hostname

A policy decision requiring: the host is operated by the Canton of Zug or a
body it names; its content is public; its robots.txt permits crawling; and a
person accepts the widening. Change the setting, restart, add a source, run a
crawl, then read what came back before approving anything.

## Path exclusions

Two layers.

**Global**, in `app/ingest/urls.py`, applied before any DNS lookup: search
pages, calendar and dated archive views, `login`, `logout`, `admin`, `intern`,
`internal`, `myaccount`, `konto`, print and share endpoints, paths deeper than
24 segments, and query strings with more than one pagination parameter.

These encode an assumption about which paths are not public content. **They
should be checked against the real site before a first full crawl.**

**Per source**, in `sources.excluded_paths`, one prefix per line, for areas a
particular source should not include.

## Publication states

A document's publication state is independent of its review status, and both
must permit retrieval.

| State | Reaches the public index |
|---|---|
| `official` | Yes, once approved |
| `supplementary` | Yes, once approved |
| `draft` | Never |
| `internal` | Never |

A draft a reviewer approved is still a draft. Section 16 requires that
separation, and it is enforced in the retrieval query rather than by a filter
applied afterwards.

## Excluding content already indexed

Set `crawled_urls.is_excluded` with a reason. The URL is skipped on every
future run and the exclusion is counted in the run summary, so it does not
look like the URL simply vanished.

Excluding does not delete. Version history is retained so a citation issued
earlier stays explicable.
