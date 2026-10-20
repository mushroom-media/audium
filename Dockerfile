# syntax=docker/dockerfile:1.7
#
# Stages:
#   base     Python + ffmpeg + tini (shared by everything below)
#   builder  installs audium and its dependencies into /opt/venv
#   dev      builder venv + test tools; source is mounted at /src (see docker-compose.dev.yml)
#   runtime  the published image (default target)

ARG PYTHON_VERSION=3.12

FROM python:${PYTHON_VERSION}-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg tini \
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
ENV PATH=/opt/venv/bin:$PATH \
    AUDIUM_DATA_DIR=/data \
    AUDIUM_MUSIC_DIR=/music
USER audium
EXPOSE 8080
VOLUME ["/data"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD ["audium", "healthcheck"]
ENTRYPOINT ["tini", "--", "audium"]
CMD ["serve"]
