# Development

Everything runs in Docker; no local Python is needed.

```bash
docker compose -f docker-compose.dev.yml build dev
docker compose -f docker-compose.dev.yml run --rm dev pytest          # tests
docker compose -f docker-compose.dev.yml run --rm dev ruff check .    # lint
docker compose -f docker-compose.dev.yml run --rm dev ruff format .   # format
docker compose -f docker-compose.dev.yml up app                       # run audium on :8080
```

The `dev` image contains the dependencies; the source in `backend/` is mounted, so code changes need no rebuild. The `app` service creates the admin `admin` / `admin-dev-password` (development only).

## Layout

```
backend/audium/
  api/         HTTP routers (FastAPI). No business logic; they call services.
  services/    business logic and permission checks (users, auth, roots, library)
  db/          schema (SQLAlchemy Core), engine, migrations, pagination, search (FTS5), dialect helpers
  scanner/     walking, tag reading (mutagen), covers, incremental scan, scan jobs
  jobs/        DB job queue and worker loop
  devtools/    test library generator, load test, audio fixtures
  supervisor.py  runs API + workers in one container
```

## Database migrations

Schema lives in `audium/db/schema.py`. After changing it, generate a migration in the container and review it:

```bash
docker compose -f docker-compose.dev.yml run --rm dev python -c "
from alembic import command; from audium.db.migrate import alembic_config
command.revision(alembic_config('sqlite:////tmp/gen.db'), message='describe change', autogenerate=True, rev_id='0002')"
```

(Upgrade `/tmp/gen.db` to the previous head first if it already exists.) Migrations run automatically at startup; a copy of the SQLite file is saved to `/data/backups` before an upgrade.

## Dependencies

`backend/requirements.lock` (runtime) and `backend/requirements-dev.lock` pin exact versions for reproducible images. To update: install `backend/` into a fresh `python:3.12-slim-bookworm` venv, `pip freeze`, and copy the result.

## Performance testing

```bash
# 100k real audio files (~1-2 GB, takes a while) in a Docker volume
docker volume create audium-testmusic
docker run --rm -v audium-testmusic:/music audium:dev python -m audium gen-testlib --mode files --tracks 100000 --out /music/testlib

# or: 100k rows directly in the database (seconds; no files, nothing to stream)
docker compose -f docker-compose.dev.yml run --rm dev python -m audium gen-testlib --mode db --tracks 100000

# latency against a running instance
docker exec audium audium loadtest --user admin --password ... --requests 3000 --concurrency 4
```

The load test fails (exit code 1) if search p95 exceeds 200 ms or more than 1 % of requests fail.
