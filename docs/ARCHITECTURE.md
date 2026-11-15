# Architecture and technical decisions

## Components

```
 browser ──HTTPS──▶ nginx ──▶ frontend (Next.js, static UI shell)
                      │
                      └────▶ backend (FastAPI /api/v1) ──▶ PostgreSQL + TimescaleDB
                                   │                   ──▶ Redis (broker, locks, simulator state)
                                   │                   ──▶ MinIO (encrypted config backups)
                                   ▼
                     worker (Celery) ◀── scheduler (Celery beat)
                                   │
                                   ▼  REST/HTTPS · SNMPv3 · SSH/SFTP (never Telnet)
                         Aruba 2540 switches  (or the simulator, 198.18.0.0/15)
```

* **frontend**: client-rendered React pages. All data comes from `/api/v1`; there is no server-side data access in
  the UI and no mock data in production code.
* **backend**: REST API, authentication, RBAC, validation, risk assessment and audit. Long-running work is handed to
  Celery; the API never talks to switches for change jobs itself.
* **worker**: three queues: `polling` (monitoring), `changes` (change jobs), `default`
  (backups, notifications, retention, integrations).
* **scheduler**: beat schedule that dispatches polling per category according to the configured intervals,
  scheduled backups, retention and recovery of lost job dispatches.

## Backend layout (`backend/app`)

| Package | Responsibility |
|---|---|
| `core` | settings, AES-256-GCM key ring, Argon2id, permissions catalogue, log redaction, network allow-list |
| `models`, `alembic` | SQLAlchemy models and the schema migration (hypertables, retention, compression, audit trigger) |
| `api/v1` | routers: auth, users, switches, inventory, vlans, monitoring, jobs, backups, alerts, topology, admin, integrations, simulator |
| `drivers/base.py` | the device abstraction (`SwitchDriver`) used by everything above it |
| `drivers/aruba/aos_switch` | AOS-Switch 16.11 driver: REST client, SNMPv3 client, SSH/SFTP client, CLI generator, capability registry |
| `drivers/simulator` | simulator implementing the same REST/SNMP/SSH behaviour with shared state in Redis |
| `services` | polling, alerts, backups, credentials, change engine (`jobs/engine.py`) and operations (`jobs/operations.py`), hardware validation harness |
| `integrations` | optional Zabbix and AirWave clients |
| `workers` | Celery app and tasks |

## Change engine

1. **Preview**: the operation's typed parameters are validated (Pydantic), the per-switch risk is assessed
   (uplinks, management VLAN, PoE impact, number of switches) and the exact plan is returned.
2. **Submit**: the job is stored with sealed secret parameters. If its risk is at or above the approval threshold
   it waits in `pending_approval`; critical jobs also require the requester's acknowledgement.
3. **Approve**: a Super Admin other than the requester approves (four-eyes) or rejects.
4. **Run**: per switch: pre-change backup → apply (REST first, allow-listed SSH fallback) →
   read-back verification → write memory. Batches run in parallel only for low/medium risk; high/critical run one
   switch at a time; canary first and stop-after-N-failures are honoured; cancellation stops before the next switch.
5. Every step is recorded per switch and in the audit log. Failed switches can be retried as a new job.

## Monitoring

Polling categories (availability, counters, health, PoE, temperature, MAC, LLDP, inventory) each have their own
interval. A poll uses the cheapest protocol available (SNMP for counters and health, REST for structured data, SNMP
fallback for reads when a REST resource is missing). Concurrency is bounded (`ANM_POLL_CONCURRENCY`) and a Redis lock per
(switch, category) prevents overlapping polls of a slow switch. Metrics go to TimescaleDB hypertables with retention (90/30/30 days) and
compression. Measurements carry a timestamp so the UI can mark stale values; nothing is filled in when a value is
unavailable.

## Decisions

| Decision | Reason |
|---|---|
| REST for configuration, SNMPv3 for monitoring, SSH only as allow-listed fallback | REST gives structured, verifiable writes; SNMP is the lightest way to poll counters for 50–100 switches; SSH covers features REST does not expose without allowing free-form CLI |
| Capability registry with evidence levels plus runtime probing | Firmware behaviour is not assumed; unverified items are visible as such |
| Application-side encryption of backups and secrets (AES-256-GCM with AAD) | Storage, database dumps and backups never hold plaintext; key rotation through a key ring |
| Server-side sessions with SameSite=Strict cookies and double-submit CSRF | Revocable sessions; no tokens in browser storage |
| Hash-chained audit log with a database trigger | Tampering is detectable; rows cannot be updated |
| Celery + Redis | Mature, simple to operate; separate queues isolate polling from changes |
| TimescaleDB | Time-series retention and compression in the same PostgreSQL |
| Simulator speaking the same protocols | The whole stack, including the driver code paths, can be tested without hardware |
| Fixed Docker subnet with a static Nginx address | Only Nginx can set the client address the API trusts |
| English only | Arabic/RTL removed from scope by the owner |
| Community MinIO image, pinned | Upstream no longer publishes images; documented in KNOWN_LIMITATIONS |
