# Known limitations

Listed honestly so nobody assumes more than has been shown.

## Awaiting hardware

* **No physical switch has been tested.** The Aruba AOS-Switch driver (REST, SNMPv3, SSH, SFTP) was written from the
  AOS-Switch 16.11 references and tested only against the simulator and recorded/constructed device responses.
  Field names, REST resource availability, CLI syntax of the security operations, temperature support and REST
  session limits may differ on YC.16.11.0018. Every capability is marked "documented", none "verified". Follow
  [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md) before managing production switches.
* Performance figures (each polling category for 100 switches / 2,800 ports finishing within 60 s in the test, the
  dashboard answering in under 3 s) come from the simulator scale test, not from real devices and network latency.

## Integrations

* Zabbix and AirWave clients are tested against mocked API responses only, not live servers.
* E-mail notifications are tested with a fake SMTP client only, not a real mail server.

## Deliberate restrictions

* No free-form CLI, by design. Only the typed operations listed in HARDWARE_COMPATIBILITY.md can change a switch.
* The application never reloads a switch. A configuration restore writes the startup configuration; the reload is
  done by an engineer in a maintenance window.
* Firmware upgrades are not part of this release.
* No LDAP/RADIUS sign-in to the application: local accounts only, as specified. (Switches can be pointed at RADIUS
  or TACACS+ through the AAA server operation.)
* English only. Arabic/RTL was removed from scope at the owner's request.
* SNMP is read-only; MD5 and DES are not accepted. Telnet is never used.

## Platform and dependencies

* **MinIO image**: the upstream MinIO project stopped publishing container images. The Compose file uses a pinned
  community build (`pgsty/minio:RELEASE.2026-08-04T00-00-00Z`). Before production, either vet and mirror that image
  in your registry (set `MINIO_IMAGE`), or point the application at an existing S3-compatible service. Backup
  objects are encrypted by the application, so the storage service never sees plaintext.
* **Content-Security-Policy** allows `'unsafe-inline'` scripts and styles. Next.js inlines bootstrap scripts and the
  theme is applied before first paint; nonce-based CSP was not implemented. Other CSP directives are strict
  (`default-src 'self'`, no framing, no external connections).
* The HTTP→HTTPS redirect on port 80 uses the request host without a port; if HTTPS is published on a port other
  than 443, users must use the HTTPS address directly.
* Rate limits are per client address. Many users behind one NAT address share the login limit (10 per minute per
  address in Nginx).
* The interactive API documentation is disabled in production; it can be enabled with `ANM_API_DOCS_ENABLED=true`
  for a short troubleshooting window, but Swagger UI loads assets from a CDN that the CSP blocks.
* Encryption keys live in `.env` on the Docker host. There is no HSM or external KMS integration.
* Single-host deployment. There is no clustering or automatic failover; recovery is by `restore.sh`.

## Testing coverage

* Backend: unit and integration tests run against PostgreSQL/TimescaleDB and Redis with the simulator.
* Frontend: component tests (Vitest) and 10 end-to-end scenarios (Playwright) against the running stack, including
  through Nginx in the Compose deployment.
* Not done: load testing of the UI, accessibility audit with assistive technology, penetration test by a third party.
