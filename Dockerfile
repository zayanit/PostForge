FROM node:20-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS frontend-build

WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

RUN npm run build \
    && npm prune --omit=dev


FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS backend-dependencies

WORKDIR /build/backend

COPY backend/requirements.lock ./requirements.lock
RUN python -m pip install \
    --no-cache-dir \
    --require-hashes \
    --prefix=/install \
    -r requirements.lock


FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS runtime

ARG NODEJS_VERSION=20.19.2+dfsg-1+deb13u2
ARG TINI_VERSION=0.19.0-3+b7
ARG CURL_VERSION=8.14.1-2+deb13u4

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        "nodejs=${NODEJS_VERSION}" \
        "tini=${TINI_VERSION}" \
        "curl=${CURL_VERSION}" \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 appuser \
    && useradd --system --uid 10001 --gid appuser --create-home appuser

WORKDIR /app

COPY --from=backend-dependencies /install/ /usr/local/
COPY --chown=appuser:appuser backend/app/ ./backend/app/

COPY --from=frontend-build --chown=appuser:appuser /build/frontend/.next/ ./frontend/.next/
COPY --from=frontend-build --chown=appuser:appuser /build/frontend/node_modules/ ./frontend/node_modules/
COPY --from=frontend-build --chown=appuser:appuser /build/frontend/public/ ./frontend/public/
COPY --from=frontend-build --chown=appuser:appuser /build/frontend/package.json ./frontend/package.json
COPY --from=frontend-build --chown=appuser:appuser /build/frontend/next.config.js ./frontend/next.config.js
COPY --chown=appuser:appuser scripts/container-entrypoint.sh /scripts/container-entrypoint.sh

ENV PATH="/app/frontend/node_modules/.bin:${PATH}"

EXPOSE 3000

USER appuser

ENTRYPOINT ["tini", "--", "/scripts/container-entrypoint.sh"]
