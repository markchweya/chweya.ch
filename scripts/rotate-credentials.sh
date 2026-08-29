#!/usr/bin/env bash
# Print the credential rotation procedure.
#
# Deliberately does not perform the rotation. Each step needs a decision or a
# coordinated restart, and a script that half-rotates a database password
# leaves the application unable to connect.
set -euo pipefail

cat <<'PROCEDURE'
Credential rotation
===================

Rotate on a schedule, and immediately after anyone with access leaves or a
disclosure is suspected.

1. Database password
--------------------
   a. Choose a new value:
        python -c "import secrets; print(secrets.token_urlsafe(32))"
   b. Change it in PostgreSQL:
        ALTER ROLE dumi WITH PASSWORD '<new value>';
   c. Update POSTGRES_PASSWORD and the password inside DATABASE_URL in .env.
      They must match; they are two places holding one secret.
   d. Restart the application and worker:
        docker compose up -d --force-recreate app worker
   e. Confirm:
        python -m app.cli check-config
        curl -s localhost:8000/readyz

2. Application secret key
-------------------------
   SECRET_KEY signs session cookies and peppers the client-address hashes.

   Changing it logs everyone out, which is intended, and it also makes
   existing client-address hashes unlinkable to new ones. That is a privacy
   improvement, not a fault, but rate limiting and abuse history keyed on
   those hashes will start from empty.

   a. python -c "import secrets; print(secrets.token_urlsafe(48))"
   b. Replace SECRET_KEY in .env.
   c. Restart. Revoke outstanding sessions if the old key may be known:
        DELETE FROM user_sessions;

3. Administrator password
-------------------------
   Normal case: the administrator changes it in the interface.

   Lost access, no other administrator:
   a. Remove the bootstrap marker so the command will run again:
        DELETE FROM system_settings WHERE key = 'admin.bootstrapped_at';
   b. Deactivate the old account rather than deleting it, so audit events keep
      referring to a row that exists:
        UPDATE users SET is_active = false, deactivated_at = now()
         WHERE email = '<old address>';
   c. Set BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD, then:
        python -m app.cli bootstrap-admin
   d. Unset BOOTSTRAP_ADMIN_PASSWORD. The new account must change its password
      at first login regardless.

   Both steps are audited. If you did not perform them, treat it as an
   incident and follow docs/runbook-incident.md.

4. Apertus API key
------------------
   a. Issue a new token at the model server.
   b. Update APERTUS_API_KEY in .env.
   c. Restart, then confirm:  make apertus-check
   d. Revoke the old token at the model server.

After any rotation
------------------
   python -m app.cli check-config      # nothing weak or default remains
   python -m app.cli verify-audit      # the audit chain is intact
   grep -rn "<old secret>" . --exclude-dir=.git   # expect no matches
PROCEDURE
