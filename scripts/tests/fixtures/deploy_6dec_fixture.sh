#!/usr/bin/env bash
# ════════════════════════════════════════════════════════════════════════════
#  6-DECIMAL FIXTURE — the two tokens the *_6 suites run against
# ════════════════════════════════════════════════════════════════════════════
#
#  deploy_clean.ts deploys every treasury token with TOKEN_DECIMALS = 18, so the
#  e2e corpus can only express 18-decimal amounts. Code that infers scale from
#  order of magnitude is therefore invisible to it — which is how a 6-decimal
#  token (AUDF on Redbelly mainnet, decimals() == 6) reached production with
#  positions inflated by 10^18. This fixture supplies the missing scale.
#
#  Creates, on the LOCAL chain only:
#    AUDFT -> token AUDFT-token, asset audft-asset   (6 decimals)
#    USDCT -> token USDCT-token, asset usdct-asset   (6 decimals)
#  and funds payer / investor / issuer with 2,000,000 of each.
#
#  Asset ids intentionally have NO "-token" infix — that is the shape the live
#  AUDF asset has (audf-asset), and the shape that broke the frontend's
#  token-id resolution. Naming them "AUDFT Token" would paper over it.
#
#  Idempotent: re-running deploys fresh token contracts and re-registers the
#  same asset ids (createAsset derives the id from the name), so the asset rows
#  repoint at the new addresses.
#
#  Usage:  ./deploy_6dec_fixture.sh
#  Needs:  hardhat on :8545, auth on :3000, payments on :3002, and a prior
#          deploy_clean.ts + setup.yaml (for the users and the access control).
# ════════════════════════════════════════════════════════════════════════════
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../../.." && pwd)"
CONTRACTS="$REPO/yieldfabric-smart-contracts"
PAY_CONFIG="$REPO/yieldfabric-payments/config/system.yaml"

RPC="${RPC_URL:-http://localhost:8545}"
AUTH="${AUTH_SERVICE_URL:-http://localhost:3000}"
PAY="${PAY_SERVICE_URL:-http://localhost:3002}"
CHAIN_ID="${CHAIN_ID:-31337}"

USERS=(
  "payer@yieldfabric.com:payer_password"
  "investor@yieldfabric.com:investor_password"
  "issuer@yieldfabric.com:issuer_password"
)

# Local access tokens are short-lived, so mint one per call rather than caching.
# Plain /auth/login yields a permission-less session; the vault/payments/keys
# services must be requested explicitly or createToken 500s on "Failed to sign
# message with vault".
tok() {
  curl -sS -m 25 -X POST "$AUTH/auth/login/with-services" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"$1\",\"password\":\"$2\",\"services\":[\"vault\",\"payments\",\"keys\"]}" \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('token',''))"
}

account_address() {
  curl -sS -m 25 "$AUTH/protected/jwt" -H "Authorization: Bearer $1" \
    | python3 -c "import sys,json;print(json.load(sys.stdin)['account_address'])"
}

echo "▶ resolving account addresses"
ADDRESSES=()
for entry in "${USERS[@]}"; do
  email="${entry%%:*}"; password="${entry##*:}"
  t="$(tok "$email" "$password")"
  [[ -z "$t" ]] && { echo "✋ login failed for $email — is auth up on $AUTH?" >&2; exit 1; }
  addr="$(account_address "$t")"
  echo "   $email -> $addr"
  ADDRESSES+=("$addr")
done

# Scrape the chain block for its access_control rather than hardcoding an
# address that would rot on the next deploy. awk keeps this dependency-free —
# note a heredoc will NOT work here, because bash parses the body of a "$( )"
# substitution and chokes on apostrophes inside it.
ACCESS_CONTROL="$(awk -v chain="\"$CHAIN_ID\":" '
  $1 == chain { inchain = 1; next }
  inchain && $1 == "access_control:" { gsub(/"/, "", $2); print $2; exit }
' "$PAY_CONFIG")"
if [[ ! "$ACCESS_CONTROL" =~ ^0x[0-9a-fA-F]{40}$ ]]; then
  echo "✋ no access_control for chain $CHAIN_ID in $PAY_CONFIG (got '${ACCESS_CONTROL:-}')" >&2
  exit 1
fi
echo "▶ access control: $ACCESS_CONTROL"

echo "▶ deploying 6-decimal tokens + funding parties"
RESULT="$(cd "$CONTRACTS" && NODE_PATH="$CONTRACTS/node_modules" \
  node "$HERE/deploy_6dec_tokens.js" "$RPC" "$ACCESS_CONTROL" "${ADDRESSES[@]}")"
echo "$RESULT"

echo "▶ registering tokens + assets"
ADMIN_TOKEN="$(tok "${USERS[0]%%:*}" "${USERS[0]##*:}")"

register() {
  local symbol="$1" address="$2" currency="$3"
  curl -sS -m 40 -X POST "$PAY/graphql" \
    -H "Authorization: Bearer $(tok "${USERS[0]%%:*}" "${USERS[0]##*:}")" \
    -H 'Content-Type: application/json' \
    -d "{\"query\":\"mutation { tokenFlow { createToken(input: { chainId: \\\"$CHAIN_ID\\\", address: \\\"$address\\\", tokenId: \\\"$symbol\\\", name: \\\"$symbol Token\\\", description: \\\"6-decimal fixture\\\" }) { success message token { id } } } }\"}" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);r=(d.get('data') or {}).get('tokenFlow',{}).get('createToken');print('   token', r['token']['id'] if r and r.get('success') else 'FAILED '+json.dumps(d)[:300])"

  # Asset NAME is the bare symbol so createAsset derives '<symbol>-asset' with
  # no '-token' infix — see the header.
  curl -sS -m 40 -X POST "$PAY/graphql" \
    -H "Authorization: Bearer $(tok "${USERS[0]%%:*}" "${USERS[0]##*:}")" \
    -H 'Content-Type: application/json' \
    -d "{\"query\":\"mutation { assetFlow { createAsset(input: { name: \\\"$symbol\\\", description: \\\"6-decimal fixture asset\\\", assetType: \\\"CASH\\\", currency: \\\"$currency\\\", tokenId: \\\"$symbol-token\\\" }) { success message asset { id } } } }\"}" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);r=(d.get('data') or {}).get('assetFlow',{}).get('createAsset');print('   asset', r['asset']['id'] if r and r.get('success') else 'FAILED '+json.dumps(d)[:300])"
}

AUDFT_ADDR="$(echo "$RESULT" | python3 -c "import sys,json;print(next(t['address'] for t in json.load(sys.stdin)['tokens'] if t['symbol']=='AUDFT'))")"
USDCT_ADDR="$(echo "$RESULT" | python3 -c "import sys,json;print(next(t['address'] for t in json.load(sys.stdin)['tokens'] if t['symbol']=='USDCT'))")"

register AUDFT "$AUDFT_ADDR" AUD
register USDCT "$USDCT_ADDR" USD

echo "✅ fixture ready — audft-asset / usdct-asset, 6 decimals"
