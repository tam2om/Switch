#!/bin/sh
# Back up the application data: the PostgreSQL database and the (already encrypted) configuration backup
# objects in MinIO. Run it from cron, e.g. daily, and copy the output to separate storage.
# Usage: backup.sh [output-directory]   (default ./anm-backups)
#
# The archive does NOT contain .env or the encryption key ring. Store ANM_ENCRYPTION_KEYS separately
# (password vault); without it, switch credentials, TOTP secrets and configuration backups cannot be decrypted.
set -eu
cd "$(dirname "$0")/../.."
OUT_ROOT="${1:-./anm-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$OUT_ROOT/anm-$STAMP"
umask 077
mkdir -p "$OUT"
echo "Dumping database..."
docker compose exec -T postgres pg_dump -U anm -d anm -Fc --no-owner > "$OUT/database.dump"

echo "Exporting encrypted configuration backup objects..."
docker compose exec -T backend docker-entrypoint.sh cli export-objects > "$OUT/objects.tar"

REV="$(docker compose exec -T postgres psql -U anm -d anm -tAc 'SELECT version_num FROM alembic_version' | tr -d '\r')"
{
  echo "created_utc=$STAMP"
  echo "schema_revision=$REV"
  echo "key_ids=$(grep -E '^ANM_ENCRYPTION_KEYS=' .env 2>/dev/null | cut -d= -f2- | tr ',' '\n' | cut -d: -f1 | paste -sd, -)"
} > "$OUT/manifest.txt"
(cd "$OUT" && sha256sum database.dump objects.tar manifest.txt > SHA256SUMS)
echo "Backup written to $OUT"
cat "$OUT/manifest.txt"
