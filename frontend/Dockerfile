# syntax=docker/dockerfile:1
# Aruba Network Manager - web frontend (Next.js standalone server).
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# Behind a TLS-inspecting proxy, pass the full CA bundle as a build secret (never baked into the image):
#   docker build --secret id=build_ca,src=/path/to/ca-bundle.pem ...
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -s /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi; \
    npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 anm && adduser -S -u 10001 -G anm anm
COPY --from=build --chown=anm:anm /app/.next/standalone ./
COPY --from=build --chown=anm:anm /app/.next/static ./.next/static
COPY --from=build --chown=anm:anm /app/public ./public
USER anm
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:3000/login >/dev/null || exit 1
CMD ["node", "server.js"]
