# Phase 6 report: production readiness

Final phase of the six the brief defines. 422 tests passing, lint clean, zero
schema drift.

## What Phase 6 produced

All 23 documents section 25 requires, plus a privacy notice placeholder, a
support runbook, and phase reports for each phase.

The documents are written to be argued with rather than filed. Every target in
the SLA carries its basis. Every policy names what needs human review. Every
report separates what was verified against a running system from what was not.

## Security review

`docs/threat-model.md` and `docs/security-controls.md` list controls against
where they live and what tests them, and list absent controls explicitly: no
MFA, no CSRF tokens, no distributed rate limiting, no malware scanning
execution, no off-host audit shipping, no penetration test.

One finding during this phase: the development bootstrap passwords were
committed in a test file. The brief prohibits committing them with no
exception for tests. They now come from the environment and no tracked file
contains either. They remain in this branch's earlier history and should be
rotated.

## Accessibility

`docs/accessibility.md` lists implementation against specific WCAG 2.2
criteria and then states that this is not a conformance claim. No
screen-reader testing, no keyboard walkthrough by a person, no axe run, no
contrast measurement. Two of those cannot be substituted with tooling.

## Privacy

Three documents, each marked for what it is. The privacy notice is a
placeholder. The DPIA is a template with eight open questions and no
conclusion, because the controller is undetermined and the deployment does not
exist. Neither has been reviewed by a qualified Swiss privacy professional,
and both say so.

## Backup and restore

Documented, scripted, and **never performed**. `make backup` and `make
restore` exist. No restore has been run, which the recovery document states
rather than implying the capability is proven.

## Proposed SLA and maintenance

Drafts for negotiation. No agreement exists. Availability is proposed at 99.5%
rather than 99.9%, because the honest constraint is a single Apertus server
and promising three nines without redundant inference would be promising
something not built.

## Production readiness

About twenty blocking items, none ticked. The three needing most lead time
because they need other people: the penetration test, the DPIA review, and the
zug.ch terms review.

The three easiest to overlook: the semantic distance threshold is calibrated
against nothing and controls how often the assistant refuses; the German,
French and Italian interface strings are unreviewed machine output; and no
restore has ever been performed.

## Definition of done, honestly assessed

| Requirement | State |
|---|---|
| Existing UI works with the backend | Yes, the Dumi design system is served unchanged and drives the interface |
| A question can be asked in four languages | Yes |
| Apertus answers from retrieved Zug sources | Untested against a real endpoint |
| Every supported answer carries citations | Yes, enforced and tested |
| Unsupported questions get a safe response | Yes, without calling the model |
| An administrator can log in securely | Yes |
| The bootstrap password must be changed | Yes, enforced and tested |
| Administrator can inspect ingestion status | Yes, dashboard shows live counts |
| Administrator can upload, review, approve documents | **No.** Not implemented |
| The crawler safely ingests approved content | Yes, against a stand-in site |
| PDFs retain page-aware citations | Yes |
| Content versions are retained | Yes |
| Contradictions enter a review queue | Detection yes, review interface no |
| Synchronisation updates the index without downtime | **No.** No scheduling, no index versioning |
| Local database and UI password protected | Yes |
| Database UI localhost only | Yes, verified by parsing the resolved config |
| Production refuses the development passwords | Yes, by digest |
| Documentation exists | Yes, all 23 required |
| Automated tests pass | Yes, 422 |
| Known limitations disclosed honestly | Yes |

**Four of twenty are not met.** Document upload, the contradiction review
interface, scheduled synchronisation with index versioning, and a verified
Apertus answer. They are listed as gaps rather than described as done.
