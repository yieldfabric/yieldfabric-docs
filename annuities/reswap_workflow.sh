#!/bin/bash

# Test script for the workflow-based Annuity Reswap API endpoint
# This script extracts obligations from an existing swap and creates a new swap
# Uses the asynchronous /api/annuity/reswap_workflow + status endpoints.

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

annuity_reswap_workflow() {
    local jwt_token=$1
    local annuity_id=$2
    local counterpart=$3
    local value=$4
    local denomination=$5
    local deadline=$6

    local request_body
    request_body=$(cat <<EOF
{
    "annuity_id": "$annuity_id",
    "counterpart": "$counterpart",
    "value": "$value",
    "denomination": "$denomination",
    "deadline": "$deadline"
}
EOF
)

    echo_with_color $BLUE "  📋 Request body:" >&2
    echo "$request_body" | jq '.' | sed 's/^/    /' >&2

    echo_with_color $BLUE "  🌐 Making REST API request to: ${PAY_SERVICE_URL}/api/annuity/reswap_workflow" >&2

    local temp_file
    temp_file=$(mktemp)
    local http_code
    http_code=$(curl -s -w "%{http_code}" -o "$temp_file" -X POST "${PAY_SERVICE_URL}/api/annuity/reswap_workflow" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${jwt_token}" \
        -d "$request_body")

    local http_response
    http_response=$(cat "$temp_file")
    rm -f "$temp_file"

    echo_with_color $BLUE "    📡 HTTP Status: $http_code" >&2
    echo_with_color $BLUE "    📥 Response:" >&2
    echo "$http_response" | jq '.' | sed 's/^/    /' >&2

    echo "$http_response"
}

poll_workflow_status() {
    local workflow_id=$1
    local max_attempts=${2:-60}
    local delay_seconds=${3:-5}

    echo_with_color $CYAN "🔄 Polling annuity reswap workflow status for ID: ${workflow_id}" >&2

    local attempt
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        local url="${PAY_SERVICE_URL}/api/annuity/reswap_workflow/${workflow_id}"
        echo_with_color $BLUE "  📡 Attempt ${attempt}/${max_attempts}: GET ${url}" >&2

        local response
        response=$(curl -s "$url")

        if [[ -z "$response" ]]; then
            echo_with_color $YELLOW "  ⚠️  Empty response from status endpoint" >&2
        else
            local workflow_status
            workflow_status=$(echo "$response" | jq -r '.workflow_status // empty' 2>/dev/null)
            
            local current_step
            current_step=$(echo "$response" | jq -r '.current_step // empty' 2>/dev/null)

            echo_with_color $BLUE "  🔎 Current workflow_status: ${workflow_status:-unknown}" >&2
            if [[ -n "$current_step" && "$current_step" != "unknown" ]]; then
                echo_with_color $CYAN "  📍 Current step: ${current_step}" >&2
            fi

            if [[ "$workflow_status" == "completed" || "$workflow_status" == "failed" || "$workflow_status" == "cancelled" ]]; then
                echo "$response"
                return 0
            fi
        fi

        if [[ $attempt -lt $max_attempts ]]; then
            sleep "$delay_seconds"
        fi
    done

    echo_with_color $RED "  ❌ Workflow did not complete within ${max_attempts} attempts" >&2
    return 1
}

main() {
    echo_with_color $CYAN "🚀 Starting Annuity Reswap WorkFlow API Test"
    echo ""

    # Test parameters
    USER_EMAIL="${USER_EMAIL:-investor@yieldfabric.com}"
    PASSWORD="${PASSWORD:-investor_password}"
    ANNUITY_ID="${ANNUITY_ID:-1765256221319}"  # Source swap_id to extract obligations from
    COUNTERPART="${COUNTERPART:-collateral@yieldfabric.com}"  # Counterparty for new swap
    VALUE="${VALUE:-10000000000000000000000}"  # Value for counterparty expected payments
    DENOMINATION="${DENOMINATION:-audm-token-asset}"  # Denomination for new swap
    # Default deadline: 1 year from now (ISO 8601 format)
    DEADLINE="${DEADLINE:-$(date -u -v+1y +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || date -u -d "+1 year" +"%Y-%m-%dT%H:%M:%SZ" 2>/dev/null || echo "2025-12-31T23:59:59Z")}"

    echo_with_color $PURPLE "📋 Test Configuration:"
    echo_with_color $BLUE "  🌐 Payment Service URL: $PAY_SERVICE_URL"
    echo_with_color $BLUE "  🌐 Auth Service URL: $AUTH_SERVICE_URL"
    echo_with_color $BLUE "  👤 User Email: $USER_EMAIL"
    echo_with_color $BLUE "  🔄 Source Annuity ID (swap_id): $ANNUITY_ID"
    echo_with_color $BLUE "  👥 Counterpart: $COUNTERPART"
    echo_with_color $BLUE "  💰 Value: $VALUE"
    echo_with_color $BLUE "  💵 Denomination: $DENOMINATION"
    echo_with_color $BLUE "  📅 Deadline: $DEADLINE"
    echo ""

    echo_with_color $CYAN "🔍 Step 0: Checking services..."
    echo ""

    if ! check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
        echo_with_color $RED "❌ Auth Service not available. Exiting."
        exit 1
    fi

    if ! check_service_running "Payment Service" "$PAY_SERVICE_URL"; then
        echo_with_color $RED "❌ Payment Service not available. Exiting."
        exit 1
    fi
    echo ""

    echo_with_color $CYAN "🔐 Step 1: Logging in as $USER_EMAIL..."
    echo ""

    local jwt_token
    jwt_token=$(login_user "$USER_EMAIL" "$PASSWORD")
    if [[ -z "$jwt_token" ]]; then
        echo_with_color $RED "❌ Failed to obtain JWT token. Exiting."
        exit 1
    fi

    echo_with_color $GREEN "  ✅ JWT token obtained (first 50 chars): ${jwt_token:0:50}..."
    echo ""

    echo_with_color $CYAN "📤 Step 2: Calling annuity reswap workflow endpoint..."
    echo ""
    local start_response
    start_response=$(annuity_reswap_workflow \
        "$jwt_token" \
        "$ANNUITY_ID" \
        "$COUNTERPART" \
        "$VALUE" \
        "$DENOMINATION" \
        "$DEADLINE")

    local workflow_id
    workflow_id=$(echo "$start_response" | jq -r '.workflow_id // empty' 2>/dev/null)

    if [[ -z "$workflow_id" || "$workflow_id" == "null" ]]; then
        echo_with_color $RED "❌ No workflow_id returned from start endpoint"
        local error_msg
        error_msg=$(echo "$start_response" | jq -r '.error // "Unknown error"' 2>/dev/null)
        echo_with_color $RED "    Error: ${error_msg}"
        exit 1
    fi

    echo_with_color $GREEN "  ✅ Reswap workflow started with ID: ${workflow_id}"
    echo ""

    local final_response
    if ! final_response=$(poll_workflow_status "$workflow_id"); then
        echo_with_color $RED "❌ Workflow did not complete successfully"
        exit 1
    fi

    echo_with_color $BLUE "📡 Final Workflow Status Response:"
    echo "$final_response" | jq '.' 2>/dev/null | sed 's/^/  /' || {
        echo_with_color $RED "  ⚠️  Final response is not valid JSON:"
        echo "$final_response" | sed 's/^/  /'
    }
    echo ""

    local workflow_status
    workflow_status=$(echo "$final_response" | jq -r '.workflow_status // empty' 2>/dev/null)

    if [[ "$workflow_status" == "completed" ]]; then
        echo_with_color $GREEN "✅ Reswap workflow completed successfully!"
        echo ""
        echo_with_color $PURPLE "📦 Reswap Details:"
        echo "$final_response" | jq -r '.result // empty' | jq '.' | sed 's/^/  /'

        echo ""
        echo_with_color $GREEN "🎉 Annuity Reswap WorkFlow API Test Completed Successfully!"
        exit 0
    else
        echo_with_color $RED "❌ Reswap workflow ended in status: ${workflow_status}"
        local error_msg
        error_msg=$(echo "$final_response" | jq -r '.error // "Unknown error"' 2>/dev/null)
        echo_with_color $RED "    Error: ${error_msg}"
        echo_with_color $BLUE "    Full response:"
        echo "$final_response" | sed 's/^/      /'
        exit 1
    fi
}

main "$@"
