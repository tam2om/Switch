# Administrator manual

For installation and host operations see [DEPLOYMENT.md](DEPLOYMENT.md). This manual covers administration inside
the application.

## Roles and permissions

There are exactly four roles. They cannot be edited, so every installation behaves the same.

| Permission | Viewer | Monitor | Admin | Super Admin |
|---|:-:|:-:|:-:|:-:|
| dashboard, switch, port, VLAN, PoE, topology, metrics, report view | ✓ | ✓ | ✓ | ✓ |
| device.view (MAC tables), alert.view, alert.ack, event.view, report.export | | ✓ | ✓ | ✓ |
| switch.manage, switch.delete, port/vlan/poe.manage, netsec.manage, bulk.execute | | | ✓ | ✓ |
| job.view, backup.view/manage/export, config.restore, template.manage, alert_rule.manage | | | ✓ | ✓ |
| user.view, user.manage (Monitor/Viewer only), audit.view_operational | | | ✓ | ✓ |
| settings.view, settings.operational (polling, backups, thresholds), system.health | | | ✓ | ✓ |
| change.approve, user.manage_superadmin, audit.view_all | | | | ✓ |
| settings.manage (security settings), credential.manage, integration.manage | | | | ✓ |

The source of truth is `backend/app/core/permissions.py`; every API endpoint checks one of these permissions.

## Users

**Users** (Admin and Super Admin):

* **Add user**: username (3–64 characters: lowercase letters, digits, `.`, `_`, `-`), name, e-mail, role and an
  initial password. The user must change it at first sign-in.
* **Edit**: name, e-mail, role, enabled. Changing the role or disabling the account ends the user's sessions.
* **Reset password**: set a temporary password, or create a one-time reset link (valid for a limited time) to pass
  to the user through a trusted channel.
* **Unlock**: clear a lockout after failed sign-ins.
* **Reset two-factor**: for a user who lost their authenticator device; they set it up again at next sign-in.
* Admins can manage only Monitor and Viewer accounts. The last active Super Admin cannot be disabled, deleted or
  demoted.

### Super Admin recovery

If every Super Admin is locked out, create a recovery account on the host and disable it afterwards:

```sh
docker compose exec -e ANM_ALLOW_ADDITIONAL_SUPERADMIN=1 backend docker-entrypoint.sh cli create-superadmin recovery-admin
```

The action is recorded in the audit log.

## Device credentials (Super Admin)

Credentials are stored encrypted and never shown again after saving. Set **fleet defaults** first; a credential
set on one switch overrides the default for that switch.

| Protocol | Purpose | Use |
|---|---|---|
| REST API | Monitoring (read) | Read-only operator account; inventory, ports, VLANs, PoE, MAC, LLDP |
| REST API | Configuration (write) | Manager account; only used by change jobs and backups |
| SNMPv3 | Monitoring only | authPriv with SHA/SHA-256/SHA-512 and AES-128/192/256; counters, health, fallback reads |
| SSH | Monitoring / configuration | Fallback for configuration text and allow-listed CLI changes; requires a trusted host key |

**SSH host keys**: on a switch's Security tab, fetch the host key, compare the fingerprint with the switch console
(`show crypto host-public-key fingerprint`), then trust it. Until then the application refuses SSH to that switch.

## Inventory

* **Switches → Add switch**: hostname, management IP, site, groups, which protocols to use. Inventory data such as
  model, serial and firmware is read from the device on the next poll; nothing is assumed.
* **Discover**: give a management subnet (for example `10.20.30.0/24`); the application queries it with the
  default SNMPv3 credential and lists the Aruba AOS-Switch devices that answer. Tick "add" to add them.
* **Sites & groups**: organise switches; groups are used to select targets for bulk changes and reports.
* **Monitoring toggle**: pause polling for a switch during maintenance.
* **Delete**: removes the switch together with its metrics, events and configuration backups. Download any backup
  you need first.

## Settings & polling

**Security** (Super Admin): session idle timeout and lifetime, lockout threshold and duration, require MFA for
Super Admin and Admin, password maximum age, approval threshold (lowest risk needing approval, default high),
allow self-approval (off by default, not recommended), audit retention (minimum 365 days).

**Operational** (Admin and Super Admin): polling intervals (availability 30 s, counters, health and PoE 60 s,
temperature, MAC and LLDP 5 min, inventory 1 h), scheduled backups (on, 02:00, keep 60 per switch; pre-change
backups are kept 90 days), default batch size, alert thresholds (CPU 85 %, memory 90 %, PoE 85 %, errors 10/min,
flapping 4 changes in 10 min), dashboard refresh and the age after which values are shown as stale.

Metrics are kept 90 days (switch metrics) and 30 days (port and PoE metrics); port metrics are compressed after 3
days. Every settings change is audited with the old and new value.

## Alert rules and notifications

Each alert type (switch offline or recovered, port down, flapping, high errors, high CPU, memory or PoE, PoE fault,
new device, unexpected configuration change, failed configuration operation) can be enabled or disabled, given a
severity and a threshold, and sent by e-mail to a list of recipients. E-mail needs the `ANM_SMTP_*` settings in
`.env`.

## Approvals (Super Admin)

Changes at or above the approval threshold appear under **Changes & approvals** with the status "pending
approval". Open one, review the risk reasons, parameters and target switches, then **Approve and run** or
**Reject** with a comment. Approval runs the change immediately with the requester's settings. Requesters cannot
approve their own changes unless self-approval is enabled.

## Templates

A template saves a change (operation and parameters, including sealed secrets such as an SNMPv3 passphrase) to
apply it again later to other switches. Applying a template goes through the same preview, risk and approval steps.

## Integrations (Super Admin)

Optional and read-only towards the other system:

* **Zabbix** (5.4+, API token): test the connection, preview Zabbix hosts that look like switches, link them to
  inventory by IP or name, optionally import new ones.
* **Aruba AirWave**: same flow using the AMP XML API.

The application works fully without them. Both were developed against recorded API behaviour, not a live server
(see KNOWN_LIMITATIONS.md).

## Audit log

**Audit log** shows who did what, when, from which address, and the result. Admins see operational events; Super
Admins see everything, including security events. Filter by user, action, category, target or time and export as
CSV (the export itself is audited). The log is append-only and hash-chained; check its integrity with
`cli verify-audit`.

## System health

Shows database (including the migration revision and TimescaleDB), Redis and queue lengths, object storage, the
Celery workers and their active tasks, the polling schedule (which can be paused per category), the application
version and whether the simulator is on.
