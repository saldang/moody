#!/usr/bin/env bash
# Create ntfy accounts: a write-only publisher for Moody and a read-only subscriber
# for the person(s) who receive help requests (family member, night staff).
set -euo pipefail
cd "$(dirname "$0")/../deploy"
set -a; source .env; set +a
SUBSCRIBER="${1:-caregiver}"
C=(docker compose -f compose.yaml)

"${C[@]}" up -d ntfy
sleep 2
if ! "${C[@]}" exec -T ntfy ntfy user list 2>/dev/null | grep -q "moody-publisher"; then
  NTFY_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')" \
    "${C[@]}" exec -T -e NTFY_PASSWORD ntfy ntfy user add moody-publisher
fi
"${C[@]}" exec -T ntfy ntfy access moody-publisher "$MOODY_NTFY_TOPIC" write-only
token="$("${C[@]}" exec -T ntfy ntfy token add moody-publisher | grep -o 'tk_[A-Za-z0-9]*')"
umask 077; printf '%s' "$token" > secrets/ntfy_token
echo "-> publisher token stored in deploy/secrets/ntfy_token"

echo "-> creating subscriber '$SUBSCRIBER' (you will be asked for a password)"
"${C[@]}" exec ntfy ntfy user add "$SUBSCRIBER" || true
"${C[@]}" exec -T ntfy ntfy access "$SUBSCRIBER" "$MOODY_NTFY_TOPIC" read-only
echo
echo "Subscribe from the ntfy app: server http://<server>:8088, topic $MOODY_NTFY_TOPIC, user $SUBSCRIBER"
echo "Then restart the tools service: docker compose -f deploy/compose.yaml restart wellbeing"
