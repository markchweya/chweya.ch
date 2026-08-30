# Known limitations

Everything below is honest. Nothing here is a plan described as a feature.

## Never exercised in this environment

**No Apertus endpoint has been contacted.** Apertus is on the developer's
desktop; this was built in a remote container. The provider is verified
against a recorded wire contract by 16 tests. It has never spoken to a model.

**No embedding model has run.** The network policy permits PyPI and blocks
huggingface.co, so weights could not be downloaded. All retrieval testing used
a non-semantic hashing provider that matches on shared vocabulary rather than
meaning. It is refused in production.

**No request has been made to zug.ch.** Every crawler test runs against a
stand-in site. The boilerplate filters encode assumptions about cantonal
markup that have never met the real thing.

**Docker never ran.** The compose stack is validated by parsing, not by
starting.

**Consequence:** `MAX_SEMANTIC_DISTANCE`, which controls how often the
assistant says it cannot verify something, is set to 0.62 and calibrated
against nothing.

## Not implemented

### Ingestion
- Scheduled synchronisation. Crawls are manual.
- Multi-level link following. One level within a source's base path.
- OCR. Scanned PDFs are detected and flagged, never read.
- Concurrency. URLs are crawled one at a time; `CRAWLER_MAX_CONCURRENCY` is
  read and unused.
- Nothing transitions a removed page to `gone`. A deleted canton page keeps
  its last approved version and stays retrievable.

### Retrieval and answering
- Streaming. The provider supports it; the endpoint returns complete answers.
  The live region and stop control are built for it and untested.
- Reranking.
- Conversation memory. Each question is answered independently, so a follow-up
  referring to a previous answer will not resolve.

### Administration
- The contradiction review interface. Detection works; resolving needs SQL.
- The specified effect of an open contradiction on answer confidence is
  documented and not wired in.
- Index versioning, atomic promotion and rollback.
- User management.
- Feedback capture.

### Security
- Multi-factor authentication.
- CSRF synchroniser tokens. `SameSite` covers the common case.
- Distributed rate limiting. Per process, so N processes allow N times the rate.
- Off-host audit shipping. A database superuser can rewrite both rows and chain.
- No penetration test.

### Accessibility
- No screen-reader testing, no keyboard-only walkthrough by a person, no axe
  run, no contrast measurement, no testing with assistive technology users.

## Known weaknesses in what is built

**Injection detection misses novel phrasing.** It is a flag, not the defence.
The architectural controls carry it and have not been tested against a real
model.

**Contradiction detection is deliberately narrow.** It compares extracted
numbers and contacts. Conflicting eligibility rules expressed in prose are not
detected at all.

**Boilerplate removal is blunt**, matching class and id substrings. A false
positive drops a block of real content, and it has never met real cantonal
markup.

**Interface strings in German, French and Italian were written by a model.**
They need review by native speakers. A mistranslated deadline is a real
problem for a real person.

**The confidence thresholds are judgement, not evidence.** They encode a view
about when a public body should answer and when it should defer.

**No malware scanner has run against an uploaded file.** The invocation is
tested with stand-in commands that exit 0, 1 and 7, which establishes that the
outcomes are handled and that a filename cannot become a command. It does not
establish that ClamAV works, because ClamAV is not installed here.
`MALWARE_SCANNER_COMMAND` is unset in development, so a file is promoted out of
quarantine unscanned; production refuses to start without it.

**An approved upload is searchable by keyword before it is searchable by
meaning.** Approval populates the text search vector in the request. Embeddings
are filled in by the indexing run, which loads a model and does not belong in a
request, so a newly approved document is found by wording until that run
happens.

**Deleting an upload leaves its version row.** The bytes, the extracted text
and the passages go; the version stays with status `gone` so a citation issued
before the deletion can still be explained. Anyone reading that as a full
erasure would be wrong, and a subject-access deletion needs the version row
handled too.

## What must not be claimed

- Not Swiss-hosted. Nothing has been deployed anywhere.
- Not endorsed by the Canton of Zug.
- Not compliant with anything. No qualified professional has reviewed it.
- No service level exists.
- Not accessible-conformant. Automated checks cover a minority of criteria and
  none has run.
