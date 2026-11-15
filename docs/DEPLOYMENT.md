# Deployment guide

This application is for internal networks only. Do not publish it to the Internet, and do not put it behind a
public load balancer.

## 1. What runs where

`docker compose` starts eight containers on one Docker host:

| Service | Image | Purpose | Published ports |
|---|---|---|---|
| nginx | nginx:1.29-alpine | TLS termination, network allow-list, rate limits, security headers | 443 → 8443, 80 → 8080 (redirect only) |
| frontend | built from `frontend/` | Next.js web UI (non-root) | none |
| backend | built from `backend/` | FastAPI on port 8000 (non-root); runs migrations at start | none |
| worker | same image as backend | Celery worker: polling, change jobs, backups, notifications | none |
| scheduler | same image as backend | Celery beat: schedules polling, backups, retention | none |
| postgres | timescale/timescaledb:2.32.0-pg16 | Application database and metrics | none |
| redis | redis:7.4-alpine (password required) | Celery broker, locks, cache | none |
| minio | pinned community build (see KNOWN_LIMITATIONS) | Encrypted configuration backup objects | none |

All services share the internal network `anm` (default subnet `172.31.250.0/24`). Nginx has a fixed address
(`172.31.250.10`); the API trusts `X-Forwarded-For` only from that address, so clients cannot spoof their IP.
If that subnet is routed in your network, change `ANM_DOCKER_SUBNET` and `ANM_NGINX_IP` in `.env`.

## 2. Host requirements

* Linux x86-64 host or VM, Docker Engine 24+ with the Compose plugin.
* For 50–100 switches: 4 vCPU, 8 GB RAM, 100 GB disk (metrics are kept 30–90 days and compressed).
* Network reachability from the host to every switch management address on TCP 443 (REST), UDP 161 (SNMPv3) and
  TCP 22 (SSH). The switches never connect to the application.
* An internal DNS name and a TLS certificate from your internal CA (a self-signed helper is included for labs).
* Host firewall: allow 443 (and optionally 80) only from management/IT networks.

## 3. First installation

```sh
git clone <repository> anm && cd anm

# 1. Secrets: writes .env (mode 600) with random database, Redis, MinIO, encryption and session secrets.
./deploy/scripts/init-secrets.sh
#    Copy ANM_ENCRYPTION_KEYS from .env into your password vault now. Without it, stored switch credentials,
#    MFA secrets and configuration backups cannot be decrypted, including from backups.

# 2. Edit .env: ANM_ALLOWED_CLIENT_NETWORKS (your management networks), ANM_HTTPS_BIND
#    (e.g. 10.20.30.40:443 to bind one interface), SMTP settings if you want e-mail alerts.

# 3. Nginx allow-list: same networks as ANM_ALLOWED_CLIENT_NETWORKS.
cp deploy/nginx/allowed-networks.conf.example deploy/nginx/allowed-networks.conf
vi deploy/nginx/allowed-networks.conf

# 4. TLS: install your certificate and key as deploy/certs/tls.crt and deploy/certs/tls.key,
#    or for a lab create a self-signed one:
./deploy/scripts/make-selfsigned-cert.sh anm.example.internal 10.20.30.40

# 5. Build and start.
docker compose up -d --build
docker compose ps        # every service should become "healthy" or "running" within about a minute
```

If the build host sits behind a TLS-inspecting proxy, pass the proxy's full CA bundle as a build secret
(it is not stored in the images):

```sh
docker build --secret id=build_ca,src=/etc/ssl/certs/ca-bundle.crt -t anm-backend:local backend
docker build --secret id=build_ca,src=/etc/ssl/certs/ca-bundle.crt -t anm-frontend:local frontend
docker compose up -d
```

### Create the first Super Admin

There is no default account and no default password. Create the first Super Admin on the host:

```sh
docker compose exec backend docker-entrypoint.sh cli create-superadmin <username>
# prompts twice for the password (12+ characters, three of lower/upper/digit/symbol, not a common password, not containing the username)
```

The command refuses to run once a Super Admin exists. For recovery only, see the Admin manual.
Sign in at `https://<your-host>/`, then:

1. Profile → set up two-factor authentication.
2. Settings & polling → Security: consider "Require TOTP MFA for Super Admin and Admin".
3. Device credentials → add the fleet default REST (monitoring and configuration), SNMPv3 and SSH credentials.
4. Switches → "Add switch", or "Discover" a management subnet over SNMPv3; then "Poll now" on a switch and check
   its Overview tab for the detected protocols and capabilities.

## 4. Preparing the switches

Configure on each 2540 (adapt to your standards; see SECURITY.md):

```
; read-only operator and manager accounts for REST/SSH
password operator user-name anm-monitor plaintext <secret>
password manager user-name anm-config plaintext <secret>
web-management ssl
no web-management plaintext
rest-interface
ip ssh
no telnet-server
snmpv3 enable
snmpv3 user anm-snmp auth sha <auth-passphrase> priv aes <priv-passphrase>
snmpv3 group operatorauth user anm-snmp sec-model ver3
snmpv3 only
; limit management access to the application host
ip authorized-managers <docker-host-ip> 255.255.255.255 access manager
```

The application never needs SNMP write access and never uses Telnet. Validate these commands on a lab switch
first: see [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md).

## 5. Operations

| Task | Command |
|---|---|
| Status | `docker compose ps` and Administration → System health |
| Logs | `docker compose logs -f backend worker` (secrets are redacted) |
| Stop / start | `docker compose stop` / `docker compose up -d` |
| Verify audit log integrity | `docker compose exec backend docker-entrypoint.sh cli verify-audit` |
| Read-only hardware check | `docker compose exec backend docker-entrypoint.sh cli hw-validate <switch-id>` |

### Backing up the application

```sh
./deploy/scripts/backup.sh /srv/anm-backups      # database dump + encrypted backup objects + checksums
```

Schedule it daily (cron or systemd timer) and copy the output off the host. The archive does not contain `.env`
or the encryption keys; keep those in your password vault. Restore with:

```sh
./deploy/scripts/restore.sh /srv/anm-backups/anm-<timestamp> --yes
```

`restore.sh` checks the checksums, refuses to run if `.env` lacks a key id the backup was made with, stops the
application, replaces the database and re-imports the backup objects, then starts everything again. Both scripts
were tested end to end on the Compose stack (a mutated database was restored, the audit chain verified and the
restored configuration backups decrypted and verified).

### Upgrading

```sh
./deploy/scripts/backup.sh /srv/anm-backups
git pull
docker compose up -d --build     # the backend applies database migrations before it serves requests
```

### Rotating the encryption key

1. `docker compose exec backend docker-entrypoint.sh cli generate-key` prints a new key.
2. Put it FIRST in `ANM_ENCRYPTION_KEYS` as `<new-id>:<key>,<old-id>:<old-key>` and `docker compose up -d`.
3. `docker compose exec backend docker-entrypoint.sh cli rotate-secrets` re-encrypts stored secrets.
4. Keep the old key in the ring until every configuration backup encrypted with it has expired.

## 6. Simulator (training and evaluation only)

Set `ANM_SIMULATOR_ENABLED=true` and run
`docker compose exec backend docker-entrypoint.sh cli seed-simulator 52` to create 52 simulated switches in the
reserved range 198.18.0.0/15. They are labelled SIMULATED everywhere and a banner is shown while the simulator is
on. Keep it off in production.
