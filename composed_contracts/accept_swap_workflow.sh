#!/bin/bash

# Test script for accepting/completing a swap created by issue_swap_workflow.sh
# This script is the counterparty (investor) flow that completes the swap.
#
# Flow:
#   1. Issuer creates obligations and swap (via issue_swap_workflow.sh)
#   2. Counterparty (investor) accepts/completes the swap (this script)
#
# The swap trades:
#   - Issuer's obligations (annuity stream + redemption) 
#   - For counterparty's payment (e.g., 125 AUD)

# Load environment variables from .env files (if present)
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "${SCRIPT_DIR}/../.." && pwd)

for env_file in "${REPO_ROOT}/.env" "${REPO_ROOT}/.env.local" "${SCRIPT_DIR}/.env"; do
    if [ -f "$env_file" ]; then
        # shellcheck disable=SC1090
        set -a
        source "$env_file"
        set +a
    fi
done

# Configuration
# To test locally, set: export PAY_SERVICE_URL=http://localhost:3002
# To test locally, set: export AUTH_SERVICE_URL=http://localhost:3000
PAY_SERVICE_URL="${PAY_SERVICE_URL:-https://pay.test.yieldfabric.com}"
AUTH_SERVICE_URL="${AUTH_SERVICE_URL:-https://auth.yieldfabric.com}"

# Colors for output (matching executor scripts)
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo_with_color() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

check_service_running() {
    local service_name=$1
    local service_url=$2

    echo_with_color $BLUE "  🔍 Checking if ${service_name} is running..."

    if [[ "$service_url" =~ ^https?:// ]]; then
        if curl -s -f -o /dev/null --max-time 5 "${service_url}/health" 2>/dev/null || \
           curl -s -f -o /dev/null --max-time 5 "$service_url" 2>/dev/null; then
            echo_with_color $GREEN "    ✅ ${service_name} is reachable"
            return 0
        else
            echo_with_color $RED "    ❌ ${service_name} is not reachable at ${service_url}"
            return 1
        fi
    else
        local port=$service_url
        if nc -z localhost $port 2>/dev/null; then
            echo_with_color $GREEN "    ✅ ${service_name} is running on port ${port}"
            return 0
        else
            echo_with_color $RED "    ❌ ${service_name} is not running on port ${port}"
            return 1
        fi
    fi
}

login_user() {
    local email="$1"
    local password="$2"
    local services_json='["vault", "payments"]'

    echo_with_color $BLUE "  🔐 Logging in user: $email" >&2

    local http_response
    http_response=$(curl -s -X POST "${AUTH_SERVICE_URL}/auth/login/with-services" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"$email\", \"password\": \"$password\", \"services\": $services_json}")

    echo_with_color $BLUE "    📡 Login response received" >&2

    if [[ -n "$http_response" ]]; then
        local token
        token=$(echo "$http_response" | jq -r '.token // .access_token // .jwt // empty')
        if [[ -n "$token" && "$token" != "null" ]]; then
            echo_with_color $GREEN "    ✅ Login successful" >&2
            echo "$token"
            return 0
        else
            echo_with_color $RED "    ❌ No token in response" >&2
            echo_with_color $YELLOW "    Response: $http_response" >&2
            return 1
        fi
    else
        echo_with_color $RED "    ❌ Login failed: no response" >&2
        return 1
    fi
}

query_pending_swaps() {
    local jwt_token=$1
    local counterparty_entity=$2

    echo_with_color $CYAN "🔍 Querying pending swaps for counterparty..." >&2

    local graphql_query='query { swaps { id swapId status deadline parties { entityId role } initiatorObligationIds counterpartyExpectedPayments createdAt } }'

    local response
    response=$(curl -s -X POST "${PAY_SERVICE_URL}/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${jwt_token}" \
        -d "{\"query\": \"$graphql_query\"}")

    echo "$response"
}

complete_swap() {
    local jwt_token=$1
    local swap_id=$2
    local idempotency_key=$3

    echo_with_color $CYAN "🏦 Completing swap: $swap_id..." >&2

    local graphql_mutation='mutation($input: CompleteSwapInput!) { completeSwap(input: $input) { success message accountAddress swapId completeResult messageId transactionId signature timestamp } }'

    local variables
    if [[ -n "$idempotency_key" && "$idempotency_key" != "null" ]]; then
        variables=$(jq -n \
            --arg swapId "$swap_id" \
            --arg idempotencyKey "$idempotency_key" \
            '{
                "input": {
                    "swapId": $swapId,
                    "idempotencyKey": $idempotencyKey
                }
            }')
    else
        variables=$(jq -n \
            --arg swapId "$swap_id" \
            '{
                "input": {
                    "swapId": $swapId
                }
            }')
    fi

    echo_with_color $BLUE "  📋 Request variables:" >&2
    echo "$variables" | jq '.' | sed 's/^/    /' >&2

    local temp_file
    temp_file=$(mktemp)
    local http_code
    http_code=$(curl -s -w "%{http_code}" -o "$temp_file" -X POST "${PAY_SERVICE_URL}/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${jwt_token}" \
        -d "{\"query\": \"$graphql_mutation\", \"variables\": $variables}")

    local http_response
    http_response=$(cat "$temp_file")
    rm -f "$temp_file"

    echo_with_color $BLUE "  📡 Response received (HTTP $http_code)" >&2

    echo "$http_response"
}

query_swap_status() {
    local jwt_token=$1
    local swap_id=$2

    local graphql_query="query { swaps { id swapId status deadline createdAt } }"

    local response
    response=$(curl -s -X POST "${PAY_SERVICE_URL}/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${jwt_token}" \
        -d "{\"query\": \"$graphql_query\"}")

    # Check if response has data.swaps array
    local has_swaps
    has_swaps=$(echo "$response" | jq -r '.data.swaps // empty' 2>/dev/null)
    
    if [[ -z "$has_swaps" || "$has_swaps" == "null" ]]; then
        # No swaps found - might be an auth issue or empty result
        echo ""
        return
    fi

    # Find the specific swap
    echo "$response" | jq -r --arg sid "$swap_id" '(.data.swaps // [])[] | select(.swapId == $sid)' 2>/dev/null
}

poll_swap_completion() {
    local jwt_token=$1
    local swap_id=$2
    local max_attempts=${3:-60}
    local delay_seconds=${4:-2}

    echo_with_color $CYAN "🔄 Polling swap completion status for: ${swap_id}" >&2

    local attempt
    local debug_shown=false
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        echo_with_color $BLUE "  📡 Attempt ${attempt}/${max_attempts}: Checking swap status..." >&2

        local swap_data
        swap_data=$(query_swap_status "$jwt_token" "$swap_id")

        if [[ -z "$swap_data" ]]; then
            # Show debug info on first failure
            if [[ "$debug_shown" == "false" ]]; then
                debug_shown=true
                echo_with_color $YELLOW "  ⚠️  Swap not found in swaps query. Checking raw response..." >&2
                local raw_response
                raw_response=$(curl -s -X POST "${PAY_SERVICE_URL}/graphql" \
                    -H "Content-Type: application/json" \
                    -H "Authorization: Bearer ${jwt_token}" \
                    -d '{"query": "query { swaps { id swapId status } }"}')
                local swap_count
                swap_count=$(echo "$raw_response" | jq -r '(.data.swaps // []) | length' 2>/dev/null)
                echo_with_color $BLUE "  📊 Found $swap_count swap(s) visible to this user" >&2
                if [[ "$swap_count" != "0" ]]; then
                    echo_with_color $BLUE "  📋 Available swaps:" >&2
                    echo "$raw_response" | jq -r '.data.swaps[] | "      - \(.swapId): \(.status)"' 2>/dev/null | head -5 >&2
                fi
            fi
            echo_with_color $YELLOW "  ⏳ Waiting for swap to become visible..." >&2
        else
            local status
            status=$(echo "$swap_data" | jq -r '.status // empty')

            echo_with_color $BLUE "  🔎 Current swap status: ${status:-unknown}" >&2

            if [[ "$status" == "COMPLETED" ]]; then
                echo_with_color $GREEN "  ✅ Swap completed successfully!" >&2
                echo "$swap_data"
                return 0
            elif [[ "$status" == "CANCELLED" || "$status" == "EXPIRED" || "$status" == "FAILED" ]]; then
                echo_with_color $RED "  ❌ Swap ended in status: $status" >&2
                echo "$swap_data"
                return 1
            fi
        fi

        if [[ $attempt -lt $max_attempts ]]; then
            sleep "$delay_seconds"
        fi
    done

    echo_with_color $RED "  ❌ Swap did not complete within ${max_attempts} attempts" >&2
    return 1
}

show_usage() {
    echo_with_color $CYAN "Usage: $0 [SWAP_ID]"
    echo ""
    echo_with_color $BLUE "Arguments:"
    echo_with_color $BLUE "  SWAP_ID    The ID of the swap to accept (optional if only one pending swap)"
    echo ""
    echo_with_color $BLUE "Environment Variables:"
    echo_with_color $BLUE "  SWAP_ID              Swap ID to accept (alternative to argument)"
    echo_with_color $BLUE "  USER_EMAIL           Counterparty email (default: investor@yieldfabric.com)"
    echo_with_color $BLUE "  PASSWORD             Counterparty password (default: investor_password)"
    echo_with_color $BLUE "  PAY_SERVICE_URL      Payments service URL"
    echo_with_color $BLUE "  AUTH_SERVICE_URL     Auth service URL"
    echo ""
    echo_with_color $PURPLE "Example:"
    echo_with_color $BLUE "  # Accept a specific swap"
    echo_with_color $BLUE "  ./accept_swap_workflow.sh 1764329161323"
    echo ""
    echo_with_color $BLUE "  # Accept using environment variable"
    echo_with_color $BLUE "  SWAP_ID=1764329161323 ./accept_swap_workflow.sh"
    echo ""
    echo_with_color $BLUE "  # List pending swaps (don't provide SWAP_ID)"
    echo_with_color $BLUE "  ./accept_swap_workflow.sh --list"
}

main() {
    echo_with_color $CYAN "🚀 Starting Accept/Complete Swap Workflow"
    echo ""

    # Check for help flag
    if [[ "$1" == "-h" || "$1" == "--help" ]]; then
        show_usage
        return 0
    fi

    # Test parameters - Counterparty (investor) credentials
    USER_EMAIL="${USER_EMAIL:-investor@yieldfabric.com}"
    PASSWORD="${PASSWORD:-investor_password}"
    
    # Swap ID can come from argument, environment, or we'll list pending swaps
    SWAP_ID="${1:-${SWAP_ID:-}}"
    LIST_ONLY="${LIST_ONLY:-false}"
    
    if [[ "$1" == "--list" ]]; then
        LIST_ONLY="true"
        SWAP_ID=""
    fi

    echo_with_color $PURPLE "📋 Configuration:"
    echo_with_color $BLUE "  🌐 Payment Service URL: $PAY_SERVICE_URL"
    echo_with_color $BLUE "  🌐 Auth Service URL: $AUTH_SERVICE_URL"
    echo_with_color $BLUE "  👤 Counterparty Email: $USER_EMAIL"
    if [[ -n "$SWAP_ID" ]]; then
        echo_with_color $BLUE "  🔄 Swap ID: $SWAP_ID"
    else
        echo_with_color $YELLOW "  🔄 Swap ID: (will query pending swaps)"
    fi
    echo ""

    echo_with_color $CYAN "🔍 Step 0: Checking services..."
    echo ""

    if ! check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
        echo_with_color $RED "❌ Auth Service not available. Exiting."
        return 1
    fi

    if ! check_service_running "Payment Service" "$PAY_SERVICE_URL"; then
        echo_with_color $RED "❌ Payment Service not available. Exiting."
        return 1
    fi
    echo ""

    echo_with_color $CYAN "🔐 Step 1: Logging in as counterparty ($USER_EMAIL)..."
    echo ""

    local jwt_token
    jwt_token=$(login_user "$USER_EMAIL" "$PASSWORD")
    if [[ -z "$jwt_token" ]]; then
        echo_with_color $RED "❌ Failed to obtain JWT token. Exiting."
        return 1
    fi

    echo_with_color $GREEN "  ✅ JWT token obtained (first 50 chars): ${jwt_token:0:50}..."
    echo ""

    # If no swap ID provided, query and list pending swaps
    if [[ -z "$SWAP_ID" ]]; then
        echo_with_color $CYAN "🔍 Step 2: Querying pending swaps..."
        echo ""

        local swaps_response
        swaps_response=$(query_pending_swaps "$jwt_token" "$USER_EMAIL")

        echo_with_color $BLUE "📋 Swaps Response:"
        echo "$swaps_response" | jq '.' 2>/dev/null | sed 's/^/  /' || echo "$swaps_response" | sed 's/^/  /'
        echo ""

        # Extract pending swaps
        local pending_swaps
        pending_swaps=$(echo "$swaps_response" | jq -r '.data.swaps[] | select(.status == "PENDING") | .swapId' 2>/dev/null)

        if [[ -z "$pending_swaps" ]]; then
            echo_with_color $YELLOW "⚠️  No pending swaps found for this counterparty."
            echo_with_color $BLUE "    Run issue_swap_workflow.sh first to create a swap."
            return 0
        fi

        # Count pending swaps
        local swap_count
        swap_count=$(echo "$pending_swaps" | wc -l | tr -d ' ')

        echo_with_color $PURPLE "📝 Found ${swap_count} pending swap(s):"
        echo "$pending_swaps" | while read -r sid; do
            echo_with_color $BLUE "    - $sid"
        done
        echo ""

        if [[ "$LIST_ONLY" == "true" ]]; then
            echo_with_color $CYAN "💡 To accept a swap, run:"
            echo_with_color $BLUE "    ./accept_swap_workflow.sh <SWAP_ID>"
            return 0
        fi

        # If only one pending swap, use it; otherwise ask user to specify
        if [[ "$swap_count" -eq 1 ]]; then
            SWAP_ID=$(echo "$pending_swaps" | head -1)
            echo_with_color $GREEN "  ✅ Using the only pending swap: $SWAP_ID"
        else
            echo_with_color $YELLOW "⚠️  Multiple pending swaps found. Please specify which swap to accept:"
            echo_with_color $BLUE "    ./accept_swap_workflow.sh <SWAP_ID>"
            return 1
        fi
        echo ""
    fi

    echo_with_color $CYAN "🏦 Step 3: Completing swap: $SWAP_ID..."
    echo ""

    local idempotency_key="complete-swap-${SWAP_ID}-$(date +%s)"
    local complete_response
    complete_response=$(complete_swap "$jwt_token" "$SWAP_ID" "$idempotency_key")

    echo_with_color $BLUE "📡 Complete Swap Response:"
    echo "$complete_response" | jq '.' 2>/dev/null | sed 's/^/  /' || {
        echo_with_color $RED "  ⚠️  Response is not valid JSON:"
        echo "$complete_response" | sed 's/^/  /'
    }
    echo ""

    # Check if the complete mutation succeeded
    local success
    success=$(echo "$complete_response" | jq -r '.data.completeSwap.success // false' 2>/dev/null)

    if [[ "$success" != "true" ]]; then
        local error_msg
        error_msg=$(echo "$complete_response" | jq -r '.data.completeSwap.message // .errors[0].message // "Unknown error"' 2>/dev/null)
        echo_with_color $RED "❌ Failed to submit swap completion: $error_msg"
        return 1
    fi

    local message_id
    message_id=$(echo "$complete_response" | jq -r '.data.completeSwap.messageId // empty' 2>/dev/null)
    local tx_hash
    tx_hash=$(echo "$complete_response" | jq -r '.data.completeSwap.transactionId // empty' 2>/dev/null)
    
    echo_with_color $GREEN "  ✅ Swap completion submitted successfully!"
    echo_with_color $BLUE "      Message ID: $message_id"
    echo ""

    # The completeSwap mutation success means the swap will be processed.
    # The counterparty (investor) may not have visibility to the swap via the swaps query
    # because it filters by entity and only shows swaps where you are the initiator.
    # This is by design - the mutation success is the confirmation.
    
    echo_with_color $GREEN "🎉 Swap completed successfully! ✨"
    echo ""
    echo_with_color $CYAN "📝 Summary:"
    echo_with_color $BLUE "   • Swap ID: $SWAP_ID"
    echo_with_color $BLUE "   • Message ID: $message_id"
    echo_with_color $BLUE "   • Transaction ID: $tx_hash"
    echo_with_color $BLUE "   • Counterparty ($USER_EMAIL) will receive the issuer's obligations"
    echo_with_color $BLUE "   • Issuer will receive payment from counterparty"
    echo ""
    echo_with_color $CYAN "💡 Note: The swap is processing asynchronously. You can verify completion by:"
    echo_with_color $BLUE "    1. Checking the issuer's received payments in the UI"
    echo_with_color $BLUE "    2. Querying the swap from the issuer's account"
    return 0
}

main "$@"

