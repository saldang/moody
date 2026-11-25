# syntax=docker/dockerfile:1.7
# One image, three entrypoints: moody-gateway | moody-brain | moody-wellbeing
FROM python:3.13-slim-trixie AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml ./
COPY moody ./moody
RUN python -m venv /opt/venv && /opt/venv/bin/pip install --upgrade pip && /opt/venv/bin/pip install .

FROM python:3.13-slim-trixie
LABEL org.opencontainers.image.title="moody-server" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.description="Privacy-first open-source wellbeing voice assistant"
ENV PATH=/opt/venv/bin:$PATH PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --home /nonexistent --shell /usr/sbin/nologin moody
COPY --from=build /opt/venv /opt/venv
USER 10001
# No EXPOSE on purpose: ports are decided by compose, per service.
CMD ["moody-brain"]
