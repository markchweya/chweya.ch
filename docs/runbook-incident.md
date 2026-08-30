# Incident response runbook

## Severity

| Level | Meaning | Response |
|---|---|---|
| 1 | Wrong information affecting a legal deadline or obligation, or a data breach | Immediately |
| 2 | Administrative access compromised, audit chain broken | Within the hour |
| 3 | Service down | Same working day |
| 4 | Degraded quality, single wrong answer | Next working day |

Severity 1 is deliberately first. Downtime is visible and recoverable; a
confidently wrong deadline is neither.

## First five minutes, any incident

1. Note the time and what you observed.
2. Do not delete anything. Broken state is evidence.
3. If residents may be acting on wrong information, take the assistant offline.
   An unavailable assistant is safer than a wrong one.
4. Start a log with timestamps.

## Wrong information published

1. Find the answer's citation and the passage behind it.
2. Set `is_excluded` on the passage's URL with a reason, or move the version to
   `excluded`. Effective immediately; retrieval only returns approved current
   versions.
3. Determine how it got in: canton content error, extraction fault, or a
   retrieval fault that surfaced an unrelated passage.
4. If the canton's own page is wrong, tell them. Do not correct their content
   in the index.
5. Add a grounded evaluation case.

## Administrative account compromised

1. Revoke every session for the account:
   `UPDATE user_sessions SET revoked_at = now(), revoked_reason = 'incident'
    WHERE user_id = '<id>';` Effective immediately.
2. Deactivate the account. Do not delete it: audit events reference it.
3. `python -m app.cli verify-audit`.
4. Read the audit log for that user: approvals, source changes, exports.
5. Rotate `SECRET_KEY`, which invalidates every session everywhere.
6. Reverse anything the account did.

## Audit chain broken

`verify-audit` names the first failing entry.

1. **Do not repair or delete rows.** The break is the evidence.
2. Snapshot the database immediately.
3. Entries before the break are still trustworthy; entries after it are not.
4. Establish who has database write access. If the application role holds
   UPDATE on `audit_events`, that is a misconfiguration and part of the finding.
5. Treat as severity 2 until shown otherwise.

## Suspected prompt injection

1. Find the flagged document: `SELECT * FROM document_versions WHERE
   injection_flags != '[]'`.
2. Move it to `excluded`.
3. Check whether it ever reached an answer.
4. If the canton's page was altered, tell them at once. That is a compromise of
   their site, which matters far more than our index.

## Data breach

1. Establish what was actually stored. The answer is usually "less than
   feared": no transcripts, no raw addresses, no accounts for public users.
2. Preserve logs.
3. **Notification is a legal decision.** Involve a qualified Swiss privacy
   professional. Nothing in this repository is legal advice.
4. Swiss notification duties are time-bound. Escalate early rather than
   investigating first.

## After any incident

Write it up within two working days: what happened, what was affected, what
was done, what would have caught it earlier. Add a test or an evaluation case.
An incident without one will happen again.
