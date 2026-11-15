#!/bin/sh
# Create .env from .env.example with freshly generated random secrets. Refuses to overwrite an existing .env.
set -eu
cd "$(dirname "$0")/../.."
if [ -e .env ]; then
  echo ".env already exists; not overwriting. Delete it first if you really want new secrets" >&2
  echo "(changing ANM_ENCRYPTION_KEYS makes existing encrypted data unreadable)." >&2
  exit 1
fi
rand() { openssl rand -base64 48 | tr -d '\n/+=' | cut -c1-"$1"; }
key() { openssl rand 32 | openssl base64 -A | tr '+/' '-_' | tr -d '='; }
umask 077
sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(rand 40)|" \
    -e "s|^REDIS_PASSWORD=.*|REDIS_PASSWORD=$(rand 40)|" \
    -e "s|^MINIO_ROOT_PASSWORD=.*|MINIO_ROOT_PASSWORD=$(rand 40)|" \
    -e "s|^ANM_ENCRYPTION_KEYS=.*|ANM_ENCRYPTION_KEYS=k$(date +%Y%m%d):$(key)|" \
    -e "s|^ANM_SESSION_SECRET=.*|ANM_SESSION_SECRET=$(rand 64)|" \
    .env.example > .env
echo "Wrote .env (mode 600). Store a copy of ANM_ENCRYPTION_KEYS in your password vault now."
