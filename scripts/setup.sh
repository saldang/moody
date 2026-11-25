#!/usr/bin/env bash
# First-time setup of a Moody server: config, secrets, private PKI.
#   ./scripts/setup.sh --hostname moody.lan --ip 192.168.10.5 [--enterprise]
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEPLOY="$ROOT/deploy"
HOSTNAME_FQDN="moody.lan"
IP=""
ENTERPRISE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --hostname) HOSTNAME_FQDN="$2"; shift 2 ;;
    --ip) IP="$2"; shift 2 ;;
    --enterprise) ENTERPRISE=1; shift ;;
    -h|--help) sed -n '2,3p' "$0"; exit 0 ;;
    *) echo "unknown option $1" >&2; exit 1 ;;
  esac
done

command -v docker >/dev/null || { echo "docker not found (see docs/03-setup-ambiente.md)"; exit 1; }
command -v python3 >/dev/null || { echo "python3 not found"; exit 1; }
if [[ -z "$IP" ]]; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo "-> using detected IP $IP (override with --ip)"
fi

# 1. local virtualenv with the PKI/provisioning tooling (cryptography, pyserial)
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -q --upgrade pip
  "$ROOT/.venv/bin/pip" install -q -e "$ROOT/server[pki]"
fi
PY="$ROOT/.venv/bin/python"

# 2. .env
if [[ ! -f "$DEPLOY/.env" ]]; then
  cp "$DEPLOY/.env.example" "$DEPLOY/.env"
  sed -i "s/^MOODY_UID=.*/MOODY_UID=$(id -u)/; s/^MOODY_GID=.*/MOODY_GID=$(id -g)/" "$DEPLOY/.env"
  topic="moody-help-$("$PY" -c 'import secrets; print(secrets.token_hex(8))')"
  sed -i "s/^MOODY_NTFY_TOPIC=.*/MOODY_NTFY_TOPIC=$topic/" "$DEPLOY/.env"
  sed -i "s#^base-url:.*#base-url: \"http://$HOSTNAME_FQDN:8088\"#" "$DEPLOY/config/ntfy/server.yml"
  echo "-> created deploy/.env"
fi

# 3. runtime folders and secrets (files, never env vars)
mkdir -p "$DEPLOY/data/brain" "$DEPLOY/data/wellbeing" "$DEPLOY/data/qvac-models" "$DEPLOY/secrets"
[[ -s "$DEPLOY/secrets/data_key" ]] || \
  "$PY" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' > "$DEPLOY/secrets/data_key"
# Bearer key between brain/gateway and the QVAC server (internal network only)
[[ -s "$DEPLOY/secrets/qvac_api_key" ]] || \
  "$PY" -c 'import secrets; print(secrets.token_urlsafe(32), end="")' > "$DEPLOY/secrets/qvac_api_key"
touch "$DEPLOY/secrets/ntfy_token" "$DEPLOY/secrets/ha_token"
chmod 600 "$DEPLOY/secrets/"*

if [[ $ENTERPRISE -eq 1 ]]; then
  gen() { "$PY" -c 'import secrets; print(secrets.token_urlsafe(32))'; }
  for var in KEYCLOAK_ADMIN_PASSWORD KEYCLOAK_DB_PASSWORD MOODY_GATEWAY_CLIENT_SECRET; do
    if grep -q "^$var=$" "$DEPLOY/.env"; then
      value="$(gen)"
      sed -i "s#^$var=.*#$var=$value#" "$DEPLOY/.env"
      [[ $var == MOODY_GATEWAY_CLIENT_SECRET ]] && printf '%s' "$value" > "$DEPLOY/secrets/gateway_client_secret"
    fi
  done
  chmod 600 "$DEPLOY/secrets/"* "$DEPLOY/.env"
fi

# 4. private PKI: two separate CAs + one certificate per service
export MOODY_PKI_DIR="$DEPLOY/pki"
"$PY" -m moody.pki init
for svc in gateway brain wellbeing; do
  [[ -f "$DEPLOY/pki/services/$svc/tls.pem" ]] && continue
  if [[ $svc == gateway ]]; then
    "$PY" -m moody.pki service gateway --dns "$HOSTNAME_FQDN" --ip "$IP"
  else
    "$PY" -m moody.pki service "$svc"
  fi
done
if [[ $ENTERPRISE -eq 1 && ! -f "$DEPLOY/pki/services/keycloak/tls.pem" ]]; then
  "$PY" -m moody.pki service keycloak --dns localhost
fi

# 5. device registry
[[ -f "$DEPLOY/config/devices.yaml" ]] || printf 'devices: {}\nrevoked_serials: []\n' > "$DEPLOY/config/devices.yaml"

cat <<MSG

Setup complete.
  Gateway URL for devices : wss://$HOSTNAME_FQDN:8443/v1/ws  (or wss://$IP:8443/v1/ws)
  CA keys                 : deploy/pki/*/ca.key  -> BACK THEM UP OFFLINE, then consider removing
                            device-ca/ca.key from the server (docs/04-pki-identita.md)
Next steps:
  1. ./scripts/bootstrap-models.sh          # one-off model download
  2. ./scripts/ntfy-setup.sh                # help-request notifications
  3. docker compose -f deploy/compose.yaml up -d
  4. provision devices: docs/05-setup-device.md
MSG
