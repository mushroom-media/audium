# syntax=docker/dockerfile:1.7
#
# Stages:
#   frontend builds the Svelte app (static files only, no Node.js in the final image)
#   base     Python + ffmpeg + tini (shared by everything below)
#   builder  installs audium and its dependencies into /opt/venv
#   dev      builder venv + test tools; source is mounted at /src (see docker-compose.dev.yml)
#   runtime  the published image (default target)

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=24

FROM node:${NODE_VERSION}-bookworm-slim AS frontend
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:${PYTHON_VERSION}-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
# Timeouts + retries: a stalled mirror connection fails and retries instead of hanging the build.
RUN apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 update \
 && apt-get -o Acquire::Retries=3 -o Acquire::http::Timeout=30 install -y --no-install-recommends ffmpeg tini \
 && rm -rf /var/lib/apt/lists/*

FROM base AS builder
WORKDIR /build
RUN python -m venv /opt/venv
COPY backend/requirements.lock ./requirements.lock
RUN /opt/venv/bin/pip install -r requirements.lock
COPY backend/ ./backend/
RUN /opt/venv/bin/pip install --no-deps ./backend

FROM base AS dev
COPY --from=builder /opt/venv /opt/venv
COPY backend/requirements-dev.lock /tmp/requirements-dev.lock
RUN /opt/venv/bin/pip install -r /tmp/requirements-dev.lock
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/src/backend
WORKDIR /src/backend
CMD ["pytest"]

FROM base AS runtime
ARG VERSION=dev
LABEL org.opencontainers.image.title="audium" \
      org.opencontainers.image.description="Self-hosted music streaming server" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.version="${VERSION}"
RUN useradd --uid 1000 --user-group --no-create-home --shell /usr/sbin/nologin audium \
 && mkdir -p /data /music \
 && chown audium:audium /data
COPY --from=builder /opt/venv /opt/venv
COPY --from=frontend /web/dist /opt/audium/web
ENV PATH=/opt/venv/bin:$PATH \
    AUDIUM_WEB_DIR=/opt/audium/web \
    AUDIUM_DATA_DIR=/data \
    AUDIUM_MUSIC_DIR=/music
USER audium
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD ["audium", "healthcheck"]
ENTRYPOINT ["tini", "--", "audium"]
CMD ["serve"]
