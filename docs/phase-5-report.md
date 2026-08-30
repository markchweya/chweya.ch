# Phase 5 report: administration and quality

Status at commit after the evaluation suite. 422 tests passing.

## Verified working

**Authentication.** An administrator logs in, and the bootstrap password must
be changed before any other route is reachable. Sessions are server-side, so
logout takes effect immediately and a retained cookie is useless. Cookies are
HttpOnly, SameSite, and Secure in production.

**Lockout and throttling.** Repeated failures lock the account for a bounded
time. Failures count in the database, so flushing a cache cannot reset an
attacker's budget. An unknown account and a wrong password return the same
error and spend the same time.

**Authorisation.** Enforced by a dependency before the handler body, and a
denial is audited as a security event. An unknown role name grants nothing.
The auditor role holds only read permissions.

**Password change.** Requires the current password even when forced, and
revokes every other session.

**The dashboard** shows live counts only. Nothing on it is a placeholder.

**Contradiction detection.** Finds conflicting fees, deadlines, contacts and
opening hours between documents, files a finding with both values and a
review priority, and never decides which is correct. Two different services
legitimately charging different fees produce nothing, and a price list within
one document produces nothing.

**The evaluation suite.** Eleven adversarial cases covering instruction
override, prompt and credential disclosure, a false premise asserted as fact,
a request for a binding decision, out-of-scope questions, a plausible but
non-existent topic, case-specific personal data, legal advice and an
emergency. Runnable with `make evaluate`, exit code 1 on any failure.

## Findings

**Thirty-five NOT NULL columns had no server default.** Their values came from
Python, so any insert outside the ORM failed. Section 5 requires a local
database interface, and an administrator correcting a row through Adminer hits
exactly this. Fixed in migration `0006_defaults`; schema drift is now zero.

## Not implemented

- **Document upload.** The schema, publication states and quarantine state
  exist. There is no upload endpoint, no magic-byte validation in the request
  path, and no malware scanner invocation. Production configuration already
  refuses to start without a scanner configured, so this cannot be shipped by
  accident.
- **The contradiction review interface.** Detection files findings and the
  states exist; there is no page for resolving them.
- **Index versioning and atomic promotion.** Content is approved on ingest.
  There is no index version to promote or roll back.
- **User management.** Users are created by the bootstrap command or by SQL.
- **Feedback capture.** No thumbs control, no feedback table.
- **Scheduled synchronisation.** Still manual.
- **Grounded evaluation cases.** The file is deliberately empty. Writing one
  before a crawl would mean inventing what the canton says.

## Environment limitations

Unchanged from Phase 4: no embedding model has run, and no Apertus endpoint
has been contacted. The evaluation suite has therefore never been executed
against a real model. It is tested at the level of its own grader, with
deliberately bad answers fed in to confirm it reports them.

## Requires human review

- The contradiction priority ordering encodes a judgement that a deadline
  conflict matters more than a fee conflict. Reasonable, and not mine to
  settle.
- The permission-to-role mapping should be checked against how the canton
  actually divides these duties.
- The adversarial cases are a starting set, not a complete threat model.
