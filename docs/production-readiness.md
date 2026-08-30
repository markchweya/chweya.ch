# Production readiness checklist

Nothing here is ticked. The system has never been deployed, and a checklist
with pre-ticked boxes is worse than none.

Items marked **blocking** must be done before any public exposure. Items
marked **required** must be done before the canton is asked to consider it.

## Security

- [ ] **blocking** Penetration test by an independent party, findings closed
- [ ] **blocking** TLS terminated in front of the application, HSTS confirmed
- [ ] **blocking** Secrets from a secret manager, not a `.env` file
- [ ] **blocking** Two database roles: owner for migrations, separate app role,
      with `DATABASE_APP_ROLE` set so the audit grants apply
- [ ] **blocking** Rate limiting moved to Redis; the current limiter is per
      process
- [ ] **blocking** `MALWARE_SCANNER_COMMAND` set to a real scanner and proven
      against the EICAR test file. The upload pipeline invokes it and handles
      every outcome; no actual scanner has ever run
- [ ] **blocking** The upload storage directory mounted `noexec` and `nosuid`,
      and excluded from any path a web server can serve directly
- [ ] **required** Multi-factor authentication for administrators
- [ ] **required** CSRF synchroniser tokens on administrative forms
- [ ] **required** Audit log shipped off-host
- [ ] **required** `pip-audit` enforced in CI
- [ ] `python -m app.cli check-config` passes with `ENVIRONMENT=production`

## Privacy

- [ ] **blocking** DPIA completed and reviewed by a qualified Swiss privacy
      professional
- [ ] **blocking** Privacy notice reviewed and published at a real URL
- [ ] **blocking** Data residency verified for the application, database,
      backups and Apertus. Verified, not assumed
- [ ] **required** Audit retention period decided, with a person accountable
- [ ] **required** Decision recorded on whether the hashed client address is
      necessary
- [ ] Controller identified in writing

## Content and legal

- [ ] **blocking** zug.ch terms of use reviewed against `docs/crawler-policy.md`
      by someone with authority to accept the risk
- [ ] **blocking** `CRAWLER_CONTACT` set to a monitored address
- [ ] **blocking** Path exclusions checked against the real site
- [ ] **required** Canton informed before a first full crawl
- [ ] **required** A named person accountable for approving uploaded documents.
      The system requires an approval; it cannot require that the approver
      checked anything
- [ ] **required** Permission obtained before using the canton's name, arms or
      branding anywhere

## Retrieval quality

- [ ] **blocking** A real embedding model configured; the hashing provider is
      refused in production
- [ ] **blocking** `MAX_SEMANTIC_DISTANCE` calibrated against that model and
      real content. It currently controls refusal behaviour and is calibrated
      against nothing
- [ ] **blocking** Grounded evaluation cases written from captured official
      content, covering the common topics in all four languages
- [ ] **blocking** `make evaluate` passes, adversarial cases included
- [ ] **required** Boilerplate filters tuned against real cantonal markup
- [ ] **required** Interface strings in German, French and Italian reviewed by
      native speakers

## Apertus

- [ ] **blocking** A real endpoint reachable; `make apertus-check` reports
      healthy
- [ ] **blocking** Running on infrastructure whose location is verified
- [ ] **required** Capacity sized against expected load. No load test has run

## Operations

- [ ] **blocking** Backups running and encrypted
- [ ] **blocking** A restore actually performed into a scratch database
- [ ] **blocking** `/readyz` monitored with alerting
- [ ] **required** `verify-audit` scheduled with alerting
- [ ] **required** Scheduled synchronisation
- [ ] **required** On-call arrangement matching the proposed severity levels
- [ ] Index versioning with promotion and rollback

## Accessibility

- [ ] **blocking** Manual screen-reader testing: NVDA/Firefox, JAWS/Chrome,
      VoiceOver/Safari
- [ ] **blocking** Keyboard-only walkthrough of every flow
- [ ] **required** Automated axe-core check in CI
- [ ] **required** Contrast measured for every token pair in both themes
- [ ] **required** A session with at least one person who uses assistive
      technology daily
- [ ] Streaming announcement tested once streaming is implemented

## Product

- [ ] **blocking** The unofficial-prototype notice present and non-dismissible
      on every public surface, in all four languages
- [ ] **blocking** No canton arms, flag or wordmark anywhere without permission
- [ ] **required** Emergency numbers verified as current
- [ ] **required** Someone named as accountable for answer quality

## The honest summary

Roughly twenty blocking items. The three that need the most lead time, because
they need other people, are the penetration test, the DPIA review, and the
zug.ch terms review.

The three easiest to overlook are that the semantic distance threshold is
uncalibrated, that the German, French and Italian strings are unreviewed
machine output, and that no restore has ever been performed.
