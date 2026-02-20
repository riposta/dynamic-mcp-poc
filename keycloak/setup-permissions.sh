#!/usr/bin/env bash
# Configure V1 fine-grained token exchange permissions in Keycloak.
# Runs after Keycloak starts and realm is imported.
# Idempotent: checks if already configured before creating.
#
# This configures client-level policies: only mcp-gateway can perform exchanges.
# Per-user access control (role checks) is enforced at the gateway level,
# because V1 fine-grained role policies evaluate the requesting client identity
# (mcp-gateway service account), not the subject user from the exchanged token.

set -euo pipefail

KEYCLOAK_URL="${KEYCLOAK_URL:-http://localhost:8080}"
REALM="mcp-poc"
ADMIN_USER="admin"
ADMIN_PASS="admin"

# Target clients to enable exchange for
TARGET_CLIENTS=("mcp-weather" "mcp-calculator")
GATEWAY_CLIENT_ID="mcp-gateway"

# ── Helpers ──────────────────────────────────────────────────────

get_admin_token() {
  curl -sf "${KEYCLOAK_URL}/realms/master/protocol/openid-connect/token" \
    -d "grant_type=password" \
    -d "client_id=admin-cli" \
    -d "username=${ADMIN_USER}" \
    -d "password=${ADMIN_PASS}" | jq -r '.access_token'
}

api() {
  local method="$1" path="$2"
  shift 2
  local response http_code
  response=$(curl -s -w "\n%{http_code}" -X "$method" \
    "${KEYCLOAK_URL}/admin/realms/${REALM}${path}" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    "$@")
  http_code=$(echo "$response" | tail -1)
  response=$(echo "$response" | sed '$d')
  if [ "$http_code" -ge 400 ]; then
    echo "  ERROR: ${method} ${path} returned HTTP ${http_code}" >&2
    echo "  Response: ${response}" >&2
    return 1
  fi
  echo "$response"
}

get_client_uuid() {
  api GET "/clients?clientId=$1" | jq -r '.[0].id'
}

# ── Main ─────────────────────────────────────────────────────────

echo "Getting admin token..."
TOKEN=$(get_admin_token)
if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
  echo "ERROR: Failed to get admin token"
  exit 1
fi

echo "Looking up client UUIDs..."
GATEWAY_UUID=$(get_client_uuid "$GATEWAY_CLIENT_ID")
REALM_MGMT_UUID=$(get_client_uuid "realm-management")
echo "  mcp-gateway: ${GATEWAY_UUID}"
echo "  realm-management: ${REALM_MGMT_UUID}"

for client_id in "${TARGET_CLIENTS[@]}"; do
  echo ""
  echo "=== Configuring token exchange for ${client_id} ==="

  TARGET_UUID=$(get_client_uuid "$client_id")
  echo "  ${client_id} UUID: ${TARGET_UUID}"

  # 1. Enable management permissions on target client
  echo "  Enabling management permissions..."
  api PUT "/clients/${TARGET_UUID}/management/permissions" \
    -d '{"enabled": true}' > /dev/null

  # 2. Look up auto-created authz objects
  AUTHZ_BASE="/clients/${REALM_MGMT_UUID}/authz/resource-server"

  TOKEN_EXCHANGE_SCOPE_ID=$(api GET "${AUTHZ_BASE}/scope?name=token-exchange" | jq -r '.[0].id')
  CLIENT_RESOURCE_ID=$(api GET "${AUTHZ_BASE}/resource?name=client.resource.${TARGET_UUID}" | jq -r '.[0]._id')
  PERM_NAME="token-exchange.permission.client.${TARGET_UUID}"
  PERM_ID=$(api GET "${AUTHZ_BASE}/permission?name=${PERM_NAME}" | jq -r '.[0].id')

  echo "  scope: ${TOKEN_EXCHANGE_SCOPE_ID}, resource: ${CLIENT_RESOURCE_ID}, permission: ${PERM_ID}"

  # 3. Create client policy (allows mcp-gateway to initiate exchange)
  CLIENT_POLICY_NAME="allow-gateway-for-${client_id}"
  EXISTING_POLICY=$(api GET "${AUTHZ_BASE}/policy?name=${CLIENT_POLICY_NAME}" | jq -r '.[0].id // empty')

  if [ -z "$EXISTING_POLICY" ]; then
    echo "  Creating client policy: ${CLIENT_POLICY_NAME}"
    CLIENT_POLICY_ID=$(api POST "${AUTHZ_BASE}/policy/client" \
      -d "{
        \"name\": \"${CLIENT_POLICY_NAME}\",
        \"clients\": [\"${GATEWAY_UUID}\"],
        \"logic\": \"POSITIVE\"
      }" | jq -r '.id')
  else
    CLIENT_POLICY_ID="$EXISTING_POLICY"
    echo "  Client policy already exists: ${CLIENT_POLICY_ID}"
  fi

  # 4. Update the permission to use the client policy
  echo "  Updating permission..."
  api PUT "${AUTHZ_BASE}/permission/scope/${PERM_ID}" \
    -d "{
      \"id\": \"${PERM_ID}\",
      \"name\": \"${PERM_NAME}\",
      \"type\": \"scope\",
      \"logic\": \"POSITIVE\",
      \"decisionStrategy\": \"UNANIMOUS\",
      \"resources\": [\"${CLIENT_RESOURCE_ID}\"],
      \"scopes\": [\"${TOKEN_EXCHANGE_SCOPE_ID}\"],
      \"policies\": [\"${CLIENT_POLICY_ID}\"]
    }" > /dev/null

  echo "  Done: ${client_id}"
done

echo ""
echo "Token exchange permissions configured successfully."
echo "Note: Per-user access control (role-based) is enforced at the gateway level."
