#!/bin/sh
# Container entrypoint: api | worker | scheduler | migrate | cli <args>
set -eu

case "${1:-api}" in
  api)
    # Apply schema migrations and reference data before serving. Safe to run repeatedly.
    alembic upgrade head
    python -m app.cli init
    # Client IPs are derived by the application from X-Forwarded-For sent by trusted proxies only
    # (ANM_TRUSTED_PROXIES), so uvicorn's own proxy-header rewriting is disabled.
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-proxy-headers --no-server-header \
      --workers "${ANM_API_WORKERS:-2}"
    ;;
  worker)
    exec celery -A app.workers.celery_app worker -Q default,polling,changes \
      --concurrency "${ANM_WORKER_CONCURRENCY:-4}" --loglevel INFO --without-mingle --without-gossip
    ;;
  scheduler)
    exec celery -A app.workers.celery_app beat --loglevel INFO --schedule /tmp/celerybeat-schedule
    ;;
  migrate)
    alembic upgrade head
    exec python -m app.cli init
    ;;
  cli)
    shift
    exec python -m app.cli "$@"
    ;;
  *)
    exec "$@"
    ;;
esac
