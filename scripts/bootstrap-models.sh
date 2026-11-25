#!/usr/bin/env bash
# Download AI models ONCE with temporary Internet access, then go back offline.
set -euo pipefail
cd "$(dirname "$0")/../deploy"
set -a; source .env; set +a

COMPOSE=(docker compose -f compose.yaml)
[[ "${MOODY_GPU:-0}" == 1 ]] && COMPOSE+=(-f compose.gpu.yaml)

echo "-> starting model containers with temporary egress"
"${COMPOSE[@]}" -f compose.bootstrap.yaml up -d ollama whisper piper

for model in "$MOODY_LLM_MODEL" "${MOODY_EMBED_MODEL:-}" "${MOODY_GUARD_MODEL:-}"; do
  [[ -z "$model" ]] && continue
  echo "-> pulling $model"
  "${COMPOSE[@]}" exec -T ollama ollama pull "$model"
done

echo "-> waiting for whisper/piper to download their models (first start only)"
for svc in whisper piper; do
  for _ in $(seq 1 120); do
    if "${COMPOSE[@]}" logs "$svc" 2>&1 | grep -qiE "ready|started|listening|Loaded"; then break; fi
    sleep 5
  done
done

echo "-> recreating containers WITHOUT Internet access"
"${COMPOSE[@]}" up -d --force-recreate ollama whisper piper
echo "done. Models stored in docker volumes: ollama, whisper, piper"
