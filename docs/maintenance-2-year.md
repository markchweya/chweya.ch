# Two-year maintenance plan

A proposal, not an agreement. Costs depend on infrastructure and usage and are
not estimated here.

## What maintenance actually means for this system

Three things decay independently:

1. **Content.** The canton edits pages. Handled by synchronisation, and it is
   the one that degrades fastest.
2. **Dependencies.** Security patches, and eventually a Python or PostgreSQL
   major version.
3. **The model.** Apertus will release new versions. Each needs evaluation
   before promotion.

## Year 1

**Quarter 1: stabilisation.** The first crawl of the real site will surface
boilerplate the filters have not seen; tuning that is the main work. Calibrate
`MAX_SEMANTIC_DISTANCE` against a real embedding model, which has never been
done. Build the grounded evaluation set, which cannot exist before a crawl.
Close the Phase 5 gaps: upload workflow, contradiction review interface, user
management.

**Quarter 2: hardening.** Penetration test and remediation. Manual
accessibility testing with screen readers. Add MFA and CSRF tokens. Move rate
limiting to Redis. Complete the DPIA with a qualified professional.

**Quarter 3: operational maturity.** Scheduled synchronisation. Index
versioning with atomic promotion and rollback. Off-host audit shipping.
Monitoring and alert thresholds. First restore drill under real conditions.

**Quarter 4: quality.** Expand grounded evaluation coverage across all four
languages. Review answer quality against real reported problems. Consider a
reranker. Review the confidence thresholds against a year of evidence.

## Year 2

**Ongoing, monthly:** dependency updates and vulnerability review; restore
drill; evaluation suite; contradiction queue review; a report against the
proposed service levels.

**Quarterly:** review the source allowlist and exclusions; review answer
quality and add evaluation cases for anything that went wrong; review access
and revoke what is no longer needed.

**Annually:** re-run the penetration test; re-run manual accessibility
testing; review the DPIA; review retention and delete what policy says to
delete.

**As needed:** Apertus version upgrades, each gated on the evaluation suite;
embedding model upgrades, which require re-embedding the corpus and a
migration if dimensions change; PostgreSQL minor upgrades.

## Effort

A rough shape rather than a quote. Year 1 is dominated by closing gaps and by
the first real-content work, and is not a maintenance year. Year 2 is
maintenance: content and contradiction review is the steady cost, and it grows
with the corpus rather than with usage.

## What ends the plan

If the canton adopts the assistant, the unofficial notice comes off, the
controller changes, and the agreement is renegotiated. That is a different
engagement, not a continuation.
