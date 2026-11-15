#!/bin/sh
# Create a self-signed TLS certificate for first start or a lab. Use a certificate from your internal CA in production.
# Usage: make-selfsigned-cert.sh <dns-name> [ip-address]
set -eu
[ $# -ge 1 ] || { echo "usage: $0 <dns-name> [ip-address]" >&2; exit 2; }
cd "$(dirname "$0")/../certs"
SAN="DNS:$1"
[ $# -ge 2 ] && SAN="$SAN,IP:$2"
umask 077
openssl req -x509 -newkey rsa:3072 -sha256 -days 397 -nodes \
  -keyout tls.key -out tls.crt -subj "/CN=$1" -addext "subjectAltName=$SAN" 2>/dev/null
chmod 0644 tls.crt
# Nginx reads the key as root before dropping privileges; keep it unreadable for other host users.
echo "Wrote deploy/certs/tls.crt and tls.key for $SAN (valid 397 days)."
