# Security

## Scope and threat model

The application can change the configuration of every access switch in the estate. It is therefore treated as
a privileged administrative system. The threats addressed are:

* Network exposure: access from outside the management networks, or from the Internet.
* Account takeover: password guessing, credential stuffing, session theft, CSRF.
* Privilege misuse: a user doing more than the role allows; one administrator making a high-impact change alone.
* Secret leakage: switch credentials, SNMP keys and configuration backups read from the database, object
  storage, logs, API responses or backups.
* Device-side abuse: arbitrary CLI execution through the application, man-in-the-middle on device sessions.
* Repudiation and tampering: changes without a trace, or an edited audit trail.

## Controls

### Network
* Only Nginx publishes ports. Database, Redis, MinIO, API and UI are reachable only on the internal Docker network.
* Two independent allow-lists: the Nginx `geo` list (`deploy/nginx/allowed-networks.conf`) and the API's
  `ANM_ALLOWED_CLIENT_NETWORKS`. Requests from other addresses get HTTP 403.
* The API trusts `X-Forwarded-For` only from Nginx's fixed address, so clients cannot spoof their source address
  to pass the allow-list or to dodge rate limits. Uvicorn's own proxy-header handling is turned off.
* HTTPS only (TLS 1.2/1.3); port 80 only redirects. HSTS, `X-Frame-Options: DENY`, `nosniff`,
  `Referrer-Policy: no-referrer` and a restrictive Permissions-Policy are set by Nginx. Pages get a per-request Content-Security-Policy with a
  script nonce (no inline scripts allowed); API responses get `default-src 'none'`.
* The interactive API documentation is disabled in production (`ANM_API_DOCS_ENABLED=false`).

### Authentication
* Local accounts only. Passwords are hashed with Argon2id (time cost 3, 64 MiB, parallelism 4).
* Password policy: at least 12 characters, three character classes, not a common password, not containing the
  username. Optional maximum age.
* Lockout after 5 failed attempts for 15 minutes (configurable), per-IP login throttling in the API and a second
  rate limit in Nginx (10 per minute per address on the login, MFA and reset endpoints).
* Optional TOTP two-factor authentication (RFC 6238), enforceable for Super Admin and Admin.
* There is no default account and no default password. The first Super Admin is created on the host with the CLI.
* Password resets use single-use, time-limited tokens issued by an administrator; changing a password signs out
  the user's other sessions.

### Sessions and CSRF
* Server-side sessions with an idle timeout (30 min) and an absolute lifetime (12 h). Users can see their sessions
  and sign out the others. Disabling a user, changing their role or setting their password ends their sessions.
* Session cookie: `HttpOnly`, `Secure`, `SameSite=Strict`. Every state-changing request also needs the
  double-submit CSRF header `X-CSRF-Token`.

### Authorization
* Exactly four roles: Super Admin, Admin, Monitor, Viewer. Every API endpoint checks a named permission on the
  server; the UI hides what a role cannot use but is never the control. See the Admin manual for the matrix.
* Admins can manage only Monitor and Viewer users. Only a Super Admin can manage Super Admins, security settings,
  device credentials and integrations, or approve changes. The last active Super Admin cannot be removed or demoted.
* Change control: every change is risk-scored. Changes at or above the approval threshold (default: high) wait
  for a Super Admin's approval, and the requester cannot approve their own change unless a Super Admin turns that
  on explicitly. Critical changes (for example disabling an uplink port) also need an explicit risk acknowledgement
  from the requester. Changes to 10 or more switches are raised to at least medium risk, and high and critical
  changes run one switch at a time.

### Device access
* Telnet is never used. REST runs over HTTPS with certificate verification on by default (`ANM_REST_CA_BUNDLE`
  for an internal CA). SNMP is v3 authPriv only (SHA/SHA-2 and AES); MD5 and DES are rejected. SNMP is read-only.
* SSH host keys are fetched and must be explicitly trusted by an administrator before any SSH session; a changed
  key blocks SSH until it is reviewed.
* There is no free-form CLI. Configuration over SSH is generated from typed operations; every command is built from
  validated parameters and checked against an allow-list (`cli_commands.py`). Read commands are allow-listed too.
* Separate monitoring (read-only) and configuration credentials per switch or as fleet defaults. Monitoring never
  makes changes with the configuration account. The one exception to keeping them apart: when no monitoring SSH
  account is set, configuration reads (scheduled backups, the hardware harness) use the configuration SSH
  account through a session that can only run the allow-listed show commands and refuses configuration commands
  and file uploads.
* Every change takes a pre-change backup, reads the result back to verify it, and stops a rollout after the
  configured number of failures. Canary-first and batched rollout are supported.

### Secrets and data at rest
* Switch credentials, SNMP keys, TOTP secrets and integration tokens are encrypted with AES-256-GCM, bound to their
  purpose with associated data, under a key ring that supports rotation (`ANM_ENCRYPTION_KEYS`).
* Secrets are write-only through the API: responses show `********`. Secret parameters of change jobs and templates
  are sealed in the database and masked in job views and the audit log.
* Configuration backups are encrypted by the application before they are written to MinIO, carry a SHA-256 of the
  plaintext and can be verified at any time.
* Logs pass through a redaction filter for passwords, keys, tokens and cookies.
* No credentials are in the repository; `.env` is generated on the host and ignored by git.

### Audit
* Security and operational events (sign-in, failures, lockouts, user and role changes, settings, credential
  changes, every change request, approval, run and result, backups, exports) are written to an append-only audit
  log. Each row includes the hash of the previous row, a database trigger blocks UPDATE and DELETE (except the
  retention job), and `cli verify-audit` checks the chain. Retention is at least 365 days (default 730).

### Containers
* Application containers run as an unprivileged user (uid 10001) and ship no OS packages beyond the base image.
  Python dependencies are pinned in `requirements.lock`; npm dependencies are locked in `package-lock.json`
  (`npm audit` reported 0 vulnerabilities at release).

## Hardening checklist for operators

- [ ] Restrict `allowed-networks.conf` and `ANM_ALLOWED_CLIENT_NETWORKS` to the management/IT networks only.
- [ ] Bind Nginx to the management interface (`ANM_HTTPS_BIND=<ip>:443`) and firewall the host.
- [ ] Use a certificate from the internal CA; replace the self-signed lab certificate.
- [ ] Store `ANM_ENCRYPTION_KEYS` in the password vault; keep `.env` mode 600, owned by root.
- [ ] Enable "Require TOTP MFA for Super Admin and Admin".
- [ ] Use dedicated switch accounts: an operator account for monitoring, a manager account for changes.
- [ ] On the switches: `no telnet-server`, `snmpv3 only`, `no web-management plaintext`, and
      `ip authorized-managers` limited to the application host and your jump hosts.
- [ ] Trust each switch's SSH host key only after comparing its fingerprint with the console.
- [ ] Schedule `deploy/scripts/backup.sh` and test a restore.
- [ ] Keep `ANM_SIMULATOR_ENABLED=false` in production.
- [ ] Review the audit log and the "Configuration drift" tab regularly.

## Known residual risks

See [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md): CSP still allows inline styles (scripts need a per-request nonce),
the MinIO image is a community build, and device behaviour has not been validated on real hardware yet.

## Reporting a vulnerability

Report suspected vulnerabilities to the internal network/security team that owns this deployment; do not file
them in a public tracker.
