#!/usr/bin/env bash
# Download AI models ONCE with temporary Internet access, then go back offline.
#   ./scripts/bootstrap-models.sh
#   MOODY_COMPOSE_FILES="compose.classic.yaml" ./scripts/bootstrap-models.sh   # classic stack
#   QVAC_CONFIG=qvac.https.config.json MOODY_COMPOSE_FILES="compose.piper.yaml" ./scripts/bootstrap-models.sh
set -euo pipefail
cd "$(dirname "$0")/../deploy"
set -a; source .env; set +a

FILES=(-f compose.yaml)
for f in ${MOODY_COMPOSE_FILES:-}; do FILES+=(-f "$f"); done
[[ "${MOODY_GPU:-0}" == 1 ]] && FILES+=(-f compose.gpu.yaml)
COMPOSE=(docker compose "${FILES[@]}")

# Model services of the active stack and the internal networks each one normally uses.
declare -A NETS=([qvac]="core, ai" [ollama]="ai" [whisper]="core" [piper]="core")
mapfile -t ACTIVE < <("${COMPOSE[@]}" config --services | grep -xE 'qvac|ollama|whisper|piper' || true)
OVERRIDE="$(mktemp --suffix=.yaml)"
trap 'rm -f "$OVERRIDE"' EXIT
{
  echo "services:"
  for s in "${ACTIVE[@]}"; do echo "  $s: { networks: [${NETS[$s]}, egress] }"; done
  echo "networks: { egress: {} }"
} > "$OVERRIDE"

echo "-> starting ${ACTIVE[*]} with temporary egress"
"${COMPOSE[@]}" -f "$OVERRIDE" up -d --build "${ACTIVE[@]}"

for s in "${ACTIVE[@]}"; do
  case "$s" in
    qvac)
      echo "-> waiting for QVAC to download and load every model (can take a while the first time)"
      cid="$("${COMPOSE[@]}" ps -q qvac)"
      for _ in $(seq 1 360); do
        status="$(docker inspect -f '{{.State.Health.Status}}' "$cid" 2>/dev/null || echo starting)"
        [[ "$status" == healthy ]] && break
        if ! docker inspect -f '{{.State.Running}}' "$cid" | grep -q true; then
          echo "QVAC exited, see: docker compose logs qvac" >&2; exit 1
        fi
        sleep 10
      done
      [[ "$status" == healthy ]] || { echo "QVAC not healthy after 60 min, see logs" >&2; exit 1; }
      ;;
    ollama)
      for model in "${OLLAMA_LLM_MODEL:-qwen3:8b}" "${OLLAMA_EMBED_MODEL:-bge-m3}" "${MOODY_GUARD_MODEL:-}"; do
        [[ -n "$model" ]] && "${COMPOSE[@]}" exec -T ollama ollama pull "$model"
      done
      ;;
    whisper|piper)
      for _ in $(seq 1 120); do
        "${COMPOSE[@]}" logs "$s" 2>&1 | grep -qiE "ready|started|listening|loaded" && break
        sleep 5
      done
      ;;
  esac
done

echo "-> recreating ${ACTIVE[*]} WITHOUT Internet access"
"${COMPOSE[@]}" up -d --force-recreate "${ACTIVE[@]}"
echo "done. Models are cached in deploy/data/qvac-models (QVAC) or docker volumes (classic)."
