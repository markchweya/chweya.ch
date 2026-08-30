# Operations runbook

## Daily

```bash
curl -s localhost:8000/readyz | jq        # every check ok
python -m app.cli verify-audit            # chain intact
```

A broken audit chain is a security incident, not a warning. Follow
`docs/runbook-incident.md` and do not repair rows: the broken chain is the
evidence.

## Weekly

- Review the contradiction queue, highest priority first.
- Review documents in `awaiting_review`.
- Check crawl run blocked-reason counts for a new cause.
- Run `make evaluate` and read the failures.
- Run `make security`.

## After any content or model change

`make evaluate`. The adversarial cases are the ones that matter; a new model
that fails an injection case is not an upgrade.

## Common situations

### Answers stopped appearing

1. `curl localhost:8000/readyz` — which dependency is down?
2. Database unavailable: check the container, check `DATABASE_URL`.
3. Migrations unavailable: `make migrate`.
4. Apertus unavailable: `make apertus-check`, then check the model server.

The chat surface says the assistant is unavailable rather than answering
badly. That is correct behaviour, not a failure to fix in a hurry.

### The assistant refuses everything

Usually nothing is embedded. Check the dashboard: passages embedded against
passages total. If zero, the embedding run has not happened or the model
failed to load.

If embeddings exist, `MAX_SEMANTIC_DISTANCE` may be too strict for the model
in use. It has never been calibrated against a real model.

### A crawl fetches nothing

1. Is the source paused?
2. Does robots.txt now disallow us? An unreadable robots.txt disallows the
   whole host by design.
3. Check `blocked_reasons` on the run: it names the cause.
4. `host_not_on_allowlist` means the sitemap points somewhere else.

### The canton asks us to stop crawling

Pause every source and remove the hostnames from `CRAWLER_ALLOWED_HOSTS`. Both
take effect immediately. Neither needs a deployment. Then talk to them.

### A wrong answer was reported

1. Reproduce it and note the request id.
2. Find the cited passage in the administration interface.
3. If the source is wrong, that is a canton content issue; exclude the passage
   and tell them.
4. If the source is right and the answer is wrong, the model misread it. Add a
   grounded evaluation case so it cannot regress silently.
5. If the answer had no citations, that is a bug: the system should have
   refused.

### Backups

```bash
make backup
make restore f=backups/dumi-....sql.gz.age
```

Restore into a scratch database on a schedule. A backup that has never been
restored is a hope, not a backup.

### Credential rotation

`make rotate-credentials` prints the procedure. It does not perform it: each
step needs a decision or a coordinated restart, and a script that half-rotates
a database password leaves the application unable to connect.
