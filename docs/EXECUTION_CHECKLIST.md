# Execution checklist

Status legend: ✅ done and tested · ⏳ implemented, awaiting physical switch · ⛔ blocked · ➖ out of scope / deferred

## Stage 0: repository and environment audit
- ✅ Repository inspected: it was empty (no code, tests, deployment or documentation to preserve). Built from scratch.
- ✅ Tools available: Python 3.13, Node 22, Docker with Compose, PostgreSQL 16 + TimescaleDB, Redis 7, Chromium/Playwright.
- ✅ No physical Aruba switch available: simulator-first plan, hardware items tracked as pending.
- ✅ This checklist.

## Stage 1: hardware integration
- ✅ Device abstraction (`drivers/base.py`) and AOS-Switch 16.11 driver (REST, SNMPv3, SSH/SFTP).
- ✅ Simulator speaking the same REST, SNMPv3 and SSH behaviour; 52-switch and 100-switch fleets.
- ✅ Read-only hardware validation harness (`cli hw-validate`), tested on the simulator.
- ⏳ REST authentication, resource availability, SNMPv3, SSH, ports, VLANs, PoE, MAC table and configuration retrieval
  on a real 2540 running YC.16.11.0018: procedure in HARDWARE_VALIDATION.md, not run.

## Stage 2: database and backend
- ✅ Schema and Alembic migration (hypertables, retention, compression, append-only audit trigger).
- ✅ Authentication (Argon2id, lockout, TOTP, sessions, CSRF), four roles, server-side authorization.
- ✅ Audit framework (hash chain, verification CLI, CSV export).
- ✅ Inventory APIs, discovery, monitoring engine, configuration job engine.

## Stage 3: frontend
- ✅ All modules A–N connected to real endpoints; dark/light themes; Simple/Pro modes.
- ➖ Arabic and RTL: removed from scope by the owner.

## Stage 4: configuration and automation
- ✅ Port, VLAN, PoE and security operations; backups, verification, drift detection, restore; bulk operations with
  batches, canary, stop-after-failures, cancel and retry; approval workflow with four-eyes and risk acknowledgement;
  templates; one change at a time per switch.
- ⏳ All of the above on real hardware.

## Stage 5: integrations
- ✅ Zabbix and AirWave (test, preview, link, import) against mocked APIs.
- ⏳ Against live Zabbix/AirWave servers.

## Stage 6: testing and hardening
- ✅ Backend: 148 tests pass (pytest) including all four roles and a 100-switch simulated workload; ruff clean.
- ✅ Frontend: 31 unit tests (Vitest), TypeScript clean, production build succeeds.
- ✅ End to end: 10 Playwright scenarios pass against the dev stack and against the Compose stack through Nginx.
- ✅ CI (GitHub Actions): backend, frontend, end-to-end and Compose deploy/backup/restore jobs on every push.
- ✅ Deployment and recovery: Compose stack started from scratch; backup.sh and restore.sh round trip tested.
- ✅ Dependency audit: `npm audit` 0 vulnerabilities; `pip-audit` no known vulnerabilities.

## Stage 7: production deployment preparation
- ✅ Dockerfiles (non-root), docker-compose.yml, Nginx, `.env.example`, secret and certificate scripts.
- ✅ Database and object backup/restore scripts (tested).
- ✅ Deployment, security, user and administrator documentation; hardware matrix; known limitations.

## Stage 8: final audit
- ✅ No TODO/FIXME or placeholder code; the remaining `NotImplementedError`s are abstract base methods.
- ✅ No hardcoded credentials (secrets come from `.env`; the e2e suite reads its password from the environment).
- ✅ Every API route requires a signed-in user with a named permission, except health checks, setup status and the
  sign-in, MFA and password-reset endpoints (checked by enumerating the routes); RBAC tests cover all four roles.
- ✅ Defects found and fixed during the audit: concurrent changes could target the same switch (now serialised per
  switch); deleting a switch left its encrypted backup objects in storage (now removed); storage keys accepted a
  leading slash (now rejected); duplicate security headers through Nginx (now single source).
- ✅ Final implementation report (FINAL_REPORT.md).
