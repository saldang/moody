# QVAC by Tether - local AI runtime exposing an OpenAI-compatible API (qvac serve --openai).
# Serves Moody's LLM, embeddings, speech-to-text and text-to-speech. See docs/13-qvac.md
# Licenses: @qvac/cli and @qvac/sdk Apache-2.0, QVAC Fabric (llama.cpp fork) MIT.
FROM node:24.22.3-trixie-slim

ARG QVAC_CLI_VERSION=0.20.0
# libatomic1: required by the QVAC worker on minimal images. No ffmpeg: Moody uses native WAV only.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libatomic1 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && npm install -g --omit=dev --no-audit --no-fund "@qvac/cli@${QVAC_CLI_VERSION}" \
 && npm cache clean --force

LABEL org.opencontainers.image.title="moody-qvac" \
      org.opencontainers.image.description="QVAC (Tether) OpenAI-compatible local AI server for Moody" \
      org.opencontainers.image.licenses="Apache-2.0"

# HOME holds ~/.qvac/kv-cache (conversation-derived KV state): compose mounts it as tmpfs (RAM only).
ENV HOME=/qvac-home NODE_ENV=production
WORKDIR /qvac-home
USER node
ENTRYPOINT ["qvac", "serve", "--openai", "--no-default"]
CMD ["--config", "/config/qvac.config.json", "--host", "0.0.0.0", "--port", "11435", \
     "--api-key-file", "/run/secrets/qvac_api_key", "--allowed-host", "qvac"]
