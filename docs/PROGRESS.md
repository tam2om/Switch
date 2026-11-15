# Progress and continuation report

Last updated: 2026-11-15 (2930F and 5406R zl2 support added). Branch: `claude/project-thread-zsgro2`.

## Completed stages

All stages 0–8 are complete for work that does not need hardware. See [EXECUTION_CHECKLIST.md](EXECUTION_CHECKLIST.md)
and [FINAL_REPORT.md](FINAL_REPORT.md).

| Commit | Content |
|---|---|
| Backend foundation | settings, crypto, RBAC catalogue, models, AOS-Switch driver, simulator |
| Backend services | REST API, Celery workers, integrations, first tests |
| Backend test suite | auth, RBAC, drivers, monitoring, change engine, backups, audit, integrations, 100-switch scale |
| Web frontend | Next.js UI for all modules wired to the real API, unit and e2e tests |
| Deployment | Docker images, Compose, Nginx, backup/restore scripts, hardware validation harness |
| Docs and final audit | documentation set, per-switch change lock, backup object cleanup on switch delete, SMTP test |

## Remaining (blocked on external dependencies)

1. Hardware validation on a lab Aruba 2540 with YC.16.11.0018 ([HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md)).
2. Fix any driver mismatches found there, with tests reproducing the real responses; then mark capabilities verified.
3. Test Zabbix/AirWave against live servers and e-mail against the internal SMTP relay.
4. Mirror or replace the MinIO image.

## Tests

* Passing: backend 137, frontend unit 28, end-to-end 10 (dev stack and Compose stack), backup/restore round trip.
* Failing: none.

## Known issues

None open in code. Limitations are listed in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md).

## Commands to resume development

```sh
# services for development
docker run -d --name anm-pg -e POSTGRES_USER=anm -e POSTGRES_PASSWORD=devpass -p 5432:5432 timescale/timescaledb:2.32.0-pg16
docker exec anm-pg createdb -U anm anm_test
redis-server --daemonize yes

# backend
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
export ANM_ENVIRONMENT=development ANM_DATABASE_URL=postgresql+psycopg://anm:devpass@localhost:5432/anm \
       ANM_ENCRYPTION_KEYS=dev:$(python -m app.cli generate-key) ANM_SESSION_SECRET=$(openssl rand -hex 32) \
       ANM_STORAGE_BACKEND=filesystem ANM_STORAGE_PATH=/tmp/anm-backups ANM_SIMULATOR_ENABLED=true \
       ANM_COOKIE_SECURE=false ANM_API_DOCS_ENABLED=true
alembic upgrade head && python -m app.cli init && python -m app.cli create-superadmin <user>
python -m app.cli seed-simulator 52
uvicorn app.main:app --reload --port 8000 &
celery -A app.workers.celery_app worker -Q default,polling,changes &
celery -A app.workers.celery_app beat &
pytest && ruff check app tests

# frontend
cd frontend && npm ci && npm run dev          # http://127.0.0.1:3000, proxies /api to :8000
npm test && npx tsc --noEmit && npm run build
E2E_SUPERADMIN_USER=<user> E2E_SUPERADMIN_PASSWORD=<password> npx playwright test

# full stack
see DEPLOYMENT.md
```
