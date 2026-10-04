# Local container deployment

The Compose stack runs PostgreSQL, a one-shot migration job, the API, and a
background worker. It is a local deployment exercise, not a public deployment
template. Both published ports bind to `127.0.0.1`; the database and API have
development credentials unless you replace them.

## Start

Copy `.env.example` to `.env` if it does not exist. Set long random values for
`API_ACCESS_KEY` and `APPROVAL_API_KEY` before allowing anyone else to use this
machine. Leave `DECISION_PROVIDER=deterministic` for the reproducible demo.

```bash
docker compose up --build -d
docker compose ps
curl -i http://127.0.0.1:8000/ready
```

The first startup builds the same application Dockerfile for the API, migration
job, and worker. The
database health check gates migrations; the migration job must finish
successfully before the API and worker start. Compose overrides the host-side
`DATABASE_URL` with `postgres:5432` inside the container network. The API's
readiness probe checks PostgreSQL. A worker has no HTTP health endpoint; inspect
its logs and jobs to confirm progress. The worker immediately claims any queued
jobs already present in this database. Inspect or back up existing development
data before starting the full stack; use an empty database for a clean demo.

```bash
docker compose logs --tail=100 api worker migrate
docker compose exec api alembic current
docker compose stop api worker
docker compose start api worker
```

`docker compose down` removes containers and their network but preserves the
named `postgres_data` volume. Do not add `-v` unless you explicitly intend to
delete the database. The same volume is used by the development PostgreSQL
service, so existing local data is not reset by starting this stack.

If a host-side Uvicorn process is already using port 8000, stop it before
starting the Compose API. If another PostgreSQL service already uses 5433,
stop it or change the host binding. Model URLs such as `127.0.0.1:8001` refer to
the API container itself when used inside Compose; configure a reachable model
host deliberately. The image does not include a GPU model server.

## Release and security boundary

The image is built from the lockfile and contains application code and
migrations, not `.env` or the Git history. Compose supplies secrets at runtime.
For a real deployment, use a managed secret store, private network, TLS and
per-user identity; replace fixed database credentials; restrict `/docs` and
the model service; and run migration compatibility checks before rolling out.
The approval and API shared keys are local-development controls, not complete
authentication or multi-tenant authorization. Review
[security](security.md), [failure model](failure-model.md), and
[self-hosted model](self-hosted-model.md) before any exposure.

The worker finishes its current step on SIGTERM, but an external side effect
and its persistence cannot be committed atomically. Stale write intent becomes
uncertain and requires operator review; it is not automatically replayed.
Rollback of an application image does not undo a database migration, so schema
changes need a separately planned compatibility and recovery procedure.

## Isolated smoke test

`compose.smoke.yml` starts the same application components with a fresh,
separate PostgreSQL volume and no host-published ports. It does not read the
development `.env` or share the development job queue. CI runs this stack and
checks `/ready` inside the API container. Use a unique Compose project name
when running it manually; only remove a project and volume you created for
this test. The smoke volume is disposable, unlike `postgres_data` above.
