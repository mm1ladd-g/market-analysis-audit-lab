FROM python:3.14.6-slim-trixie@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS base

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/auditlab

LABEL org.opencontainers.image.title="Market Analysis Audit Lab" \
      org.opencontainers.image.description="Local-first evidence pipeline for market-analysis video audits" \
      org.opencontainers.image.licenses="Apache-2.0"

# The timestamped Debian repositories and requested package versions make APT
# resolution reviewable and repeatable instead of silently following a moving mirror.
RUN rm -f /etc/apt/sources.list.d/debian.sources \
    && printf '%s\n' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260715T000000Z trixie main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/20260715T000000Z trixie-updates main' \
      'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/20260715T000000Z trixie-security main' \
      > /etc/apt/sources.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
      ca-certificates=20250419 \
      ffmpeg=7:7.1.5-0+deb13u1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid "${APP_GID}" auditlab \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --shell /usr/sbin/nologin auditlab

WORKDIR /app

COPY requirements.txt requirements.lock ./
RUN python -m pip install --require-hashes --requirement requirements.lock \
    && python -m pip check

COPY --chown=auditlab:auditlab audit_lab ./audit_lab
COPY --chown=auditlab:auditlab scripts ./scripts
COPY --chown=auditlab:auditlab configs ./configs
COPY --chown=auditlab:auditlab examples ./examples
COPY --chown=auditlab:auditlab docs ./docs
COPY --chown=auditlab:auditlab tests ./tests
COPY --chown=auditlab:auditlab \
  README.md README.fa.md LICENSE NOTICE pyproject.toml Makefile .env.example \
  Dockerfile docker-compose.yml ./
COPY --chown=auditlab:auditlab \
  SECURITY.md SECURITY.fa.md PRIVACY.md PRIVACY.fa.md \
  CONTRIBUTING.md CONTRIBUTING.fa.md CODE_OF_CONDUCT.md CODE_OF_CONDUCT.fa.md \
  GOVERNANCE.md GOVERNANCE.fa.md SUPPORT.md SUPPORT.fa.md ROADMAP.md CHANGELOG.md \
  THIRD_PARTY_NOTICES.md ASSET_LICENSES.yml CITATION.cff DCO .gitignore .dockerignore ./

RUN mkdir -p /workspace && chown auditlab:auditlab /workspace

FROM base AS development

COPY --chown=auditlab:auditlab requirements-dev.lock ./
RUN python -m pip install --require-hashes --requirement requirements-dev.lock \
    && python -m pip check

USER auditlab

FROM base AS runtime

# Package installers are build-time tooling, not part of the application runtime.
RUN python -m pip uninstall --yes pip setuptools wheel

USER auditlab

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).read()" || exit 1

CMD ["uvicorn", "audit_lab.web:app", "--host", "0.0.0.0", "--port", "8080", "--no-server-header"]
