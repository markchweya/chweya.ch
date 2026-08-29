"""Verify the audit log hash chain.

    python -m app.cli verify-audit

Exit code 0 when the chain is intact, 1 when it is broken. Intended to run
from cron or a monitoring check, so a broken chain raises an alert rather than
waiting to be noticed during an investigation.
"""

from __future__ import annotations

from app.db.session import session_scope
from app.security.audit import verify_chain


def main(argv: list[str]) -> int:
    """Walk the chain and report. Returns a process exit code."""
    with session_scope() as session:
        result = verify_chain(session)

    if result.ok:
        print(f"Audit chain intact. {result.checked} entries verified.")
        return 0

    # Deliberately loud. A broken chain means the log was altered after the
    # fact, which is a security incident, not a warning.
    print("AUDIT CHAIN BROKEN.")
    print(f"  First failing entry id: {result.broken_at}")
    print(f"  Reason: {result.reason}")
    print(f"  Entries verified before the break: {result.checked}")
    print()
    print("Follow docs/runbook-incident.md. Do not delete or repair rows: the")
    print("broken chain is the evidence.")
    return 1
