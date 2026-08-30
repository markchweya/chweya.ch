# Threat model

Who might attack this system, what they would want, and what stops them.

Written against what is built at the time of writing. Controls marked **not
implemented** are gaps, not plans that count as coverage.

## What is worth protecting

1. **The integrity of answers.** The worst outcome is not downtime. It is a
   resident acting on a wrong deadline or fee that carried a citation and
   looked official.
2. **Administrator credentials and sessions.** They allow content into the
   public index.
3. **Resident questions.** Not stored by default, and that default is the
   control.
4. **The audit trail.** Its value is that it cannot be quietly rewritten.
5. **The canton's reputation.** The canton's name is adjacent to every answer
   even though the prototype is unofficial.

## Actors

| Actor | Capability | Wants |
|---|---|---|
| Anonymous user | Sends questions | Free answers, or to make the system say something wrong |
| Content author on zug.ch | Edits a page the crawler reads | Usually nothing; the risk is a compromised CMS account |
| Attacker with an admin credential | Full administrative access | Publish false content, exfiltrate data |
| Network attacker | Sees or alters traffic | Session theft, content injection |
| Insider | Legitimate access | Alter history, remove evidence of a decision |
| Automated scanner | Mass probing | Any exposed service |

## Attacks and controls

### Indirect prompt injection

An instruction hidden in a crawled page or an uploaded PDF that changes what
the assistant does.

**Why it matters most here:** the system's whole value is that it reads
canton pages. A compromised CMS account turns that into an instruction
channel.

Controls: untrusted content never occupies the system role; the evidence
delimiter is random per request so it cannot be pre-written into a page; the
model is given no tools; answers must cite, so an instruction to ignore the
sources produces an answer failing its own requirement; instruction-shaped
text flags a document for review rather than being indexed silently; and the
answer's citations are validated against the passages actually supplied.

Residual risk: pattern detection misses novel phrasing. The architectural
controls are what carry this, and they have not been tested against a real
model.

### Server-side request forgery

Making the crawler fetch something internal. An administrator can add a source
URL, and every crawled page contains links.

Controls: a hostname allowlist checked before DNS; resolved addresses
validated against loopback, private, link-local, carrier-grade NAT, reserved
and cloud metadata ranges; the connection pinned to the validated address, so
the name cannot resolve to something else between check and connect; every
redirect hop revalidated through both gates; HTTP and HTTPS only; redirect
count bounded; blocked attempts logged by cause.

### Credential and session attacks

Controls: Argon2id at 64 MiB; a policy rejecting known and weak values; the
same error and the same response time whether or not an account exists;
lockout after repeated failures, counted in the database; server-side sessions
so revocation is immediate; HttpOnly, Secure and SameSite cookies; forced
password change on first login; every other session revoked on password
change.

Not implemented: multi-factor authentication. The schema does not carry a
second factor.

### Cross-site scripting

The interface renders text extracted from crawled pages and uploaded PDFs.

Controls: Jinja autoescaping, pinned by test including an `img` tag with an
`onerror` handler; a Content-Security-Policy with no `unsafe-inline` for
scripts; active markup stripped during extraction; `X-Content-Type-Options:
nosniff`.

### Cross-site request forgery

Controls: `SameSite` on the session cookie, which is the defence for
cookie-based state change.

Not implemented: synchroniser tokens on administrative forms. `SameSite=lax`
covers the common case and is not equivalent to a token. Recorded in the
production checklist.

### Audit tampering

Controls: a hash chain, so an edit, deletion, reordering or forged insert
breaks verification and the break can be located; `UPDATE` and `DELETE`
revoked from the application role where it is not the table owner;
`verify-audit` runnable from cron.

Residual risk: a database superuser can rewrite both the rows and the chain.
Off-host shipping is the answer and is not implemented.

### Denial of service

Controls: per-host crawl politeness; response size caps; statement timeouts;
request rate limiting; bounded question length; a bounded context budget.

Residual risk: rate limiting is per process, so N processes allow N times the
configured rate. Redis-backed limiting is required before public exposure.

### Data disclosure through answers

Controls: only approved content in the current version of a document whose
publication state is official or supplementary is retrievable, enforced in
SQL; draft and internal documents can never be returned; the crawler never
visits authenticated or administrative paths.

### Personal data accumulation

Controls: no account for public use; transcripts off by default; client
addresses and user agents HMACed under a key held outside the database;
question text, answers and passage content dropped from logs by key name;
audit entries record an email domain rather than an address.

## Assumptions

- The Canton of Zug's website is not hostile, but individual pages may be
  compromised. The design assumes the second.
- The Apertus deployment is trusted infrastructure. A compromised model server
  can return anything, and citation validation limits but does not eliminate
  the damage.
- The database is not shared with untrusted tenants.
- TLS terminates in front of the application in production. Nothing here
  implements TLS.

## What has not been tested

No penetration test. No red-team exercise against a live model. No load test.
The controls above are implemented and unit-tested; that is not the same as
proven under attack.
