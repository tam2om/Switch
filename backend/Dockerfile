# syntax=docker/dockerfile:1
# Aruba Network Manager - backend image (API, Celery worker and scheduler share this image).
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# No OS packages are installed. Docker Compose runs the containers with "init: true", so signals are
# forwarded and zombie processes are reaped without a separate init binary in the image.
RUN groupadd --system --gid 10001 anm \
 && useradd --system --uid 10001 --gid anm --home-dir /app --shell /usr/sbin/nologin anm

WORKDIR /app
COPY requirements.lock ./
# Behind a TLS-inspecting proxy, pass the full CA bundle as a build secret (never baked into the image):
#   docker build --secret id=build_ca,src=/path/to/ca-bundle.pem ...
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-deps -r requirements.lock

COPY alembic.ini pyproject.toml ./
COPY alembic ./alembic
COPY app ./app
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p /var/lib/anm/backups \
 && chown -R anm:anm /var/lib/anm

USER anm
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["api"]
