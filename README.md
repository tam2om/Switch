# Aruba Network Manager

An internal web application for monitoring and operating a fleet of Aruba 2540 24G PoE+ switches
(AOS-Switch firmware YC.16.11.0018) from one place: inventory, live port/PoE/VLAN status, health metrics,
connected devices, LLDP topology, alerts, controlled configuration changes with approval, encrypted configuration
backups and a tamper-evident audit log.

> **Hardware status.** No physical switch was available while this was built. Every feature was exercised against
> the built-in simulator (clearly labelled **SIMULATED** in the UI). The Aruba driver follows the AOS-Switch 16.11
> REST API, MIB and CLI references, but none of it is confirmed on a real 2540 yet. See
> [docs/HARDWARE_VALIDATION.md](docs/HARDWARE_VALIDATION.md) before you connect production switches.

## Stack

| Layer | Technology |
|---|---|
| Web UI | Next.js 15 (App Router), React 19, TypeScript, Tailwind CSS 4 |
| API | FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 (Python 3.13) |
| Jobs | Celery 5 workers and beat scheduler, Redis 7 |
| Data | PostgreSQL 16 with TimescaleDB (metrics hypertables, retention and compression) |
| Backups | MinIO (S3 API); objects are AES-256-GCM encrypted by the application before upload |
| Device access | Aruba REST API v3–v7 over HTTPS, SNMPv3 (authPriv) for monitoring, SSH with an allow-listed command set as fallback. Never Telnet. |
| Delivery | Docker Compose behind Nginx (TLS 1.2/1.3, network allow-list) |

## Repository layout

```
backend/     FastAPI app, drivers (Aruba AOS-Switch + simulator), change engine, Celery tasks, tests
frontend/    Next.js UI, unit tests (Vitest) and end-to-end tests (Playwright)
deploy/      Nginx configuration, TLS/secret helpers, backup and restore scripts
docs/        Deployment, security, manuals, hardware matrix and validation, reports
docker-compose.yml, .env.example
```

## Quick start (lab)

```sh
./deploy/scripts/init-secrets.sh                       # .env with random secrets
./deploy/scripts/make-selfsigned-cert.sh anm.lab.internal
cp deploy/nginx/allowed-networks.conf.example deploy/nginx/allowed-networks.conf
docker compose up -d --build
docker compose exec backend docker-entrypoint.sh cli create-superadmin <your-username>
```

Then browse to `https://<host>/`. Full instructions: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Documentation

| Document | Contents |
|---|---|
| [DEPLOYMENT](docs/DEPLOYMENT.md) | Host preparation, first start, first Super Admin, upgrades, backups, operations |
| [SECURITY](docs/SECURITY.md) | Threat model, controls, secrets handling, hardening checklist |
| [USER_MANUAL](docs/USER_MANUAL.md) | Using the application, per role |
| [ADMIN_MANUAL](docs/ADMIN_MANUAL.md) | Users, roles, credentials, settings, approvals, integrations, recovery |
| [ARCHITECTURE](docs/ARCHITECTURE.md) | Components, data flow, technical decisions |
| [HARDWARE_COMPATIBILITY](docs/HARDWARE_COMPATIBILITY.md) | Capability matrix with evidence level |
| [HARDWARE_VALIDATION](docs/HARDWARE_VALIDATION.md) | Procedure to validate on a real lab switch |
| [KNOWN_LIMITATIONS](docs/KNOWN_LIMITATIONS.md) | What is not done, not verified, or deliberately restricted |
| [EXECUTION_CHECKLIST](docs/EXECUTION_CHECKLIST.md) | Stage-by-stage checklist with status |
| [PROGRESS](docs/PROGRESS.md) | Continuation report for whoever picks this up next |
| [FINAL_REPORT](docs/FINAL_REPORT.md) | Implemented and tested vs awaiting hardware vs deferred |

## Development

```sh
# backend (needs PostgreSQL with TimescaleDB and Redis)
cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]'
pytest && ruff check app tests
# frontend
cd frontend && npm ci && npm test && npm run build
```
