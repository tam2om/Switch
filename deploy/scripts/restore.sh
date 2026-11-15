#!/bin/sh
# Restore a backup made by backup.sh. This REPLACES the current database and bucket contents.
# Usage: restore.sh <backup-directory> --yes
#
# The .env in this directory must hold the same ANM_ENCRYPTION_KEYS (or a key ring containing those key ids)
# that were in use when the backup was taken.
set -eu
cd "$(dirname "$0")/../.."
[ $# -eq 2 ] && [ "$2" = "--yes" ] || { echo "usage: $0 <backup-directory> --yes" >&2; exit 2; }
SRC="$1"
[ -f "$SRC/database.dump" ] && [ -f "$SRC/objects.tar" ] || { echo "not a backup directory: $SRC" >&2; exit 2; }
(cd "$SRC" && sha256sum -c SHA256SUMS) || { echo "checksum mismatch; refusing to restore" >&2; exit 1; }
NEED="$(grep -E '^key_ids=' "$SRC/manifest.txt" | cut -d= -f2-)"
HAVE="$(grep -E '^ANM_ENCRYPTION_KEYS=' .env | cut -d= -f2- | tr ',' '\n' | cut -d: -f1 | paste -sd, -)"
for k in $(echo "$NEED" | tr ',' ' '); do
  case ",$HAVE," in *",$k,"*) ;; *) echo "key '$k' from the backup is missing in .env ANM_ENCRYPTION_KEYS" >&2; exit 1;; esac
done

echo "Stopping application services..."
docker compose stop nginx frontend scheduler worker backend
docker compose up -d postgres redis minio
docker compose exec -T postgres sh -c 'until pg_isready -U anm -d postgres >/dev/null; do sleep 1; done'

echo "Restoring database..."
docker compose exec -T postgres psql -U anm -d postgres -v ON_ERROR_STOP=1 \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='anm' AND pid<>pg_backend_pid();" \
  -c "DROP DATABASE IF EXISTS anm;" -c "CREATE DATABASE anm OWNER anm;" >/dev/null
docker compose exec -T postgres psql -U anm -d anm -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION IF NOT EXISTS timescaledb;" -c "SELECT timescaledb_pre_restore();" >/dev/null
docker compose exec -T postgres pg_restore -U anm -d anm --no-owner --exit-on-error < "$SRC/database.dump"
docker compose exec -T postgres psql -U anm -d anm -v ON_ERROR_STOP=1 -c "SELECT timescaledb_post_restore();" >/dev/null

echo "Restoring configuration backup objects..."
docker compose run --rm --no-deps -T backend cli import-objects < "$SRC/objects.tar"

echo "Starting application..."
docker compose up -d
echo "Restore complete. Sign in and check Administration > System, then verify a few backups."
