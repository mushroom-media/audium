# Contributing

Thanks for wanting to help. Bug reports, ideas and pull requests are all welcome.

## Issues

- **Bug:** what you did, what happened, what you expected. The version from `/api/health`, how you run audium (Docker on Linux/NAS/Windows, behind a proxy?) and the relevant lines from `docker compose logs audium` help a lot.
- **Idea:** describe the problem you want solved, not only the solution.
- **Security problems:** not as an issue, see [SECURITY.md](SECURITY.md).

## Pull requests

For anything bigger than a small fix, open an issue first, so we can agree on the direction before you spend time on it.

Development runs in Docker; see [docs/development.md](docs/development.md). Before you open the pull request:

```bash
docker compose -f docker-compose.dev.yml run --rm dev ruff check .
docker compose -f docker-compose.dev.yml run --rm dev ruff format --check .
docker compose -f docker-compose.dev.yml run --rm dev pytest
cd frontend && npm ci && npm run check && npm test
```

CI runs the same checks.

Conventions:

- **Migrations only append.** Never change a released migration; add a new one. Real installations upgrade through all of them.
- **The music is read-only.** audium never writes to `/music`, and changes must keep it that way.
- **Permissions are checked in the services** (`backend/audium/services/`), not in the routers, with tests.
- **UI texts** are German in the source and translated in `frontend/src/lib/i18n/en.ts` (server texts in `backend/audium/i18n.py`). New texts need both.
- One topic per pull request; a short explanation of the why in the description.

## Licence of contributions

audium uses two licences: the server (`backend/`, the Docker image) is AGPL-3.0-or-later, the web frontend (`frontend/`), which the audium apps are built from, is MIT.

By opening a pull request you agree that your contribution is licensed under the licence of the part it changes: AGPL-3.0-or-later for everything outside `frontend/`, MIT for `frontend/`. Only contribute what you wrote yourself or may contribute under these terms.
