# Backup and disaster recovery

## What must survive

| Data | Lose it and |
|---|---|
| Audit log | Accountability is gone and cannot be reconstructed |
| Users and roles | Nobody can administer the system |
| Document versions | Past citations become inexplicable |
| Crawled content | Recoverable by re-crawling, at a cost |
| Embeddings | Recoverable by re-embedding, at a cost |
| Uploaded documents | Gone unless the uploader still has them |

Uploads and the audit log are the two that cannot be regenerated.

## Taking a backup

```bash
make backup
```

`pg_dump`, gzip, then age encryption when `BACKUP_AGE_RECIPIENT` is set. It
warns loudly when it is not, because an unencrypted dump contains
administrator password hashes and the full audit history.

Uploaded files live outside the database in `UPLOAD_STORAGE_PATH` and are
**not** included. They need their own backup.

## Restoring

```bash
make restore f=backups/dumi-20260101T000000Z.sql.gz.age
```

It asks for the database name as confirmation, because the most common way to
lose data during an incident is restoring over the wrong database.

Afterwards:

```bash
.venv/bin/alembic current       # expected revision
python -m app.cli verify-audit  # chain survived the round trip
```

## Restore drills

**A backup that has never been restored is a hope, not a backup.**

Monthly, restore the most recent backup into a scratch database and confirm:
the schema is at the expected revision, the audit chain verifies, document and
chunk counts are plausible, and an administrator row exists.

Record the date and the outcome. A drill nobody logged did not happen.

## Objectives

Proposed, not guaranteed. See `docs/sla-proposal.md`.

| Objective | Proposed | Basis |
|---|---|---|
| Backup frequency | Daily, retained 30 days | Content changes slowly |
| RPO | 24 hours | Crawled content is re-derivable; audit and uploads are not |
| RTO | 4 hours | Restore plus re-index |
| Drill frequency | Monthly | |

An RPO of 24 hours means up to a day of audit entries and uploads could be
lost. If that is unacceptable, continuous archiving is the answer and it is
not configured.

## Total loss

1. Provision infrastructure.
2. Restore the database.
3. Restore upload storage.
4. `alembic upgrade head`.
5. Verify the audit chain.
6. Point `APERTUS_BASE_URL` at a working endpoint; `make apertus-check`.
7. Re-embed if the model or its version changed.
8. `make evaluate` before going public.

Step 8 is not optional. A restored system that fails an adversarial case
should not take questions.

## Not implemented

Continuous archiving, off-host audit shipping, automated drills, and
cross-region replication. All are production requirements and none is
configured.
