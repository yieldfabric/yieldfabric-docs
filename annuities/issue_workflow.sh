#!/bin/bash

# Test script for the workflow-based Issue Annuity API endpoint
# This script is modeled on issue_annuity.sh but uses the asynchronous
# /api/annuity/issue_workflow + status endpoints.

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

issue_annuity_workflow() {
    local jwt_token=$1
    local denomination=$2
    local counterpart=$3
    local start_date=$4
    local end_date=$5
    local coupon_amount=$6
    local initial_amount=$7
    local redemption_amount=$8
    shift 8
    local coupon_dates=("$@")

    echo_with_color $CYAN "🏦 Starting annuity issuance workflow..." >&2

    # Build coupon_dates JSON array
    local coupon_dates_json="["
    local i
    for i in "${!coupon_dates[@]}"; do
        if [ "$i" -gt 0 ]; then
            coupon_dates_json+=","
        fi
        coupon_dates_json+="\"${coupon_dates[$i]}\""
    done
    coupon_dates_json+="]"

    local request_body
    request_body=$(cat <<EOF
{
    "denomination": "${denomination}",
    "counterpart": "${counterpart}",
    "start_date": "${start_date}",
    "end_date": "${end_date}",
    "coupon_amount": "${coupon_amount}",
    "coupon_dates": ${coupon_dates_json},
    "initial_amount": "${initial_amount}",
    "redemption_amount": "${redemption_amount}"
}
EOF
)

    echo_with_color $BLUE "  📋 Request body:" >&2
    echo "$request_body" | jq '.' | sed 's/^/    /' >&2

    echo_with_color $BLUE "  🌐 Making REST API request to: ${PAY_SERVICE_URL}/api/annuity/issue_workflow" >&2

    local temp_file
    temp_file=$(mktemp)
    local http_code
    http_code=$(curl -s -w "%{http_code}" -o "$temp_file" -X POST "${PAY_SERVICE_URL}/api/annuity/issue_workflow" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${jwt_token}" \
        -d "$request_body")

    local http_response
    http_response=$(cat "$temp_file")
    rm -f "$temp_file"

    echo_with_color $BLUE "  📡 Response received (HTTP $http_code)" >&2

    if [[ -z "$http_response" ]]; then
        echo_with_color $YELLOW "  ⚠️  Warning: Empty response body" >&2
    fi

    echo "$http_response"
}

poll_workflow_status() {
    local workflow_id=$1
    local max_attempts=${2:-120}
    local delay_seconds=${3:-5}

    echo_with_color $CYAN "🔄 Polling workflow status for ID: ${workflow_id}" >&2

    local attempt
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        local url="${PAY_SERVICE_URL}/api/annuity/issue_workflow/${workflow_id}"
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
    echo_with_color $CYAN "🚀 Starting Issue Annuity WorkFlow API Test"
    echo ""

    # Test parameters (aligned with issue_annuity.sh)
    USER_EMAIL="${USER_EMAIL:-issuer@yieldfabric.com}"
    PASSWORD="${PASSWORD:-issuer_password}"
    DENOMINATION="${DENOMINATION:-aud-token-asset}"
    COUNTERPART="${COUNTERPART:-investor@yieldfabric.com}"
    # Calculate dates relative to current UTC time
    # Using epoch seconds for portability across different date implementations
    NOW_EPOCH=$(date -u +%s)
    
    # START_DATE = now UTC + 1 minute
    START_DATE="${START_DATE:-$(date -u -r $((NOW_EPOCH + 60)) +"%Y-%m-%dT%H:%M:%SZ")}"
    
    # END_DATE = now UTC + 5 minutes
    END_DATE="${END_DATE:-$(date -u -r $((NOW_EPOCH + 300)) +"%Y-%m-%dT%H:%M:%SZ")}"
    
    # START_DATE="${START_DATE:-2025-11-30T13:00:00.000Z}"
    # END_DATE="${END_DATE:-2025-12-19T12:59:59.000Z}"
    COUPON_AMOUNT="${COUPON_AMOUNT:-2000000000000000000}"
    INITIAL_AMOUNT="${INITIAL_AMOUNT:-10000000000000000000000}"
    REDEMPTION_AMOUNT="${REDEMPTION_AMOUNT:-10000000000000000000000}"
    # COUPON_AMOUNT="${COUPON_AMOUNT:-2 000000000000000000}"
    # INITIAL_AMOUNT="${INITIAL_AMOUNT:-10000 000000000000000000}"
    # REDEMPTION_AMOUNT="${REDEMPTION_AMOUNT:-10000 000000000000000000}"

    # COUPON_DATES = (now UTC + 1min 30sec, 2min, 3min, 4min, 5min)
    if [ -z "${COUPON_DATES[*]}" ]; then
        COUPON_DATES=(
            "$(date -u -r $((NOW_EPOCH + 90)) +"%Y-%m-%dT%H:%M:%SZ")"   # +1min 30sec
            "$(date -u -r $((NOW_EPOCH + 120)) +"%Y-%m-%dT%H:%M:%SZ")"  # +2min
            "$(date -u -r $((NOW_EPOCH + 180)) +"%Y-%m-%dT%H:%M:%SZ")"  # +3min
            "$(date -u -r $((NOW_EPOCH + 240)) +"%Y-%m-%dT%H:%M:%SZ")"  # +4min
            "$(date -u -r $((NOW_EPOCH + 300)) +"%Y-%m-%dT%H:%M:%SZ")"  # +5min
        )
    fi
    # Old commented coupon dates:
    # "2025-12-02T00:00:00+11:00"
    # "2025-12-03T00:00:00+11:00"
    # "2025-12-04T00:00:00+11:00"
    # "2025-12-05T00:00:00+11:00"
    # "2025-12-08T00:00:00+11:00"
    # "2025-12-09T00:00:00+11:00"
    # "2025-12-10T00:00:00+11:00"
    # "2025-12-11T00:00:00+11:00"
    # "2025-12-12T00:00:00+11:00"
    # "2025-12-15T00:00:00+11:00"
    # "2025-12-16T00:00:00+11:00"
    # "2025-12-17T00:00:00+11:00"
    # "2025-12-18T00:00:00+11:00"
    # "2025-12-19T23:59:59+11:00"

    echo_with_color $BLUE "📋 Configuration:"
    echo_with_color $BLUE "  API Base URL: ${PAY_SERVICE_URL}"
    echo_with_color $BLUE "  Auth Service: ${AUTH_SERVICE_URL}"
    echo_with_color $BLUE "  User: ${USER_EMAIL}"
    echo_with_color $BLUE "  Denomination: ${DENOMINATION}"
    echo_with_color $BLUE "  Counterpart: ${COUNTERPART}"
    echo_with_color $BLUE "  Date Range: ${START_DATE} to ${END_DATE}"
    echo_with_color $BLUE "  Coupon Amount: ${COUPON_AMOUNT}"
    echo_with_color $BLUE "  Initial Amount: ${INITIAL_AMOUNT}"
    echo_with_color $BLUE "  Redemption Amount: ${REDEMPTION_AMOUNT}"
    echo_with_color $BLUE "  Number of Coupons: ${#COUPON_DATES[@]}"
    echo ""

    if ! check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
        echo_with_color $RED "❌ Auth service is not reachable at $AUTH_SERVICE_URL"
        return 1
    fi

    if ! check_service_running "Payments Service" "$PAY_SERVICE_URL"; then
        echo_with_color $RED "❌ Payments service is not reachable at $PAY_SERVICE_URL"
        echo_with_color $YELLOW "Please start the payments service:"
        echo "   Local: cd ../yieldfabric-payments && cargo run"
        echo_with_color $BLUE "   REST API endpoint will be available at: $PAY_SERVICE_URL/api/annuity/issue_workflow"
        return 1
    fi

    echo ""

    echo_with_color $CYAN "🔐 Authenticating..."
    local jwt_token
    jwt_token=$(login_user "$USER_EMAIL" "$PASSWORD")
    if [[ -z "$jwt_token" ]]; then
        echo_with_color $RED "❌ Failed to get JWT token for user: $USER_EMAIL"
        return 1
    fi

    echo_with_color $GREEN "  ✅ JWT token obtained (first 50 chars): ${jwt_token:0:50}..."
    echo ""

    echo_with_color $CYAN "📤 Calling issue annuity workflow endpoint..."
    echo ""

    local start_response
    start_response=$(issue_annuity_workflow \
        "$jwt_token" \
        "$DENOMINATION" \
        "$COUNTERPART" \
        "$START_DATE" \
        "$END_DATE" \
        "$COUPON_AMOUNT" \
        "$INITIAL_AMOUNT" \
        "$REDEMPTION_AMOUNT" \
        "${COUPON_DATES[@]}")

    echo_with_color $BLUE "📡 Start API Response:"
    echo "$start_response" | jq '.' 2>/dev/null | sed 's/^/  /' || {
        echo_with_color $RED "  ⚠️  Start response is not valid JSON:"
        echo "$start_response" | sed 's/^/  /'
    }
    echo ""

    local workflow_id
    workflow_id=$(echo "$start_response" | jq -r '.workflow_id // empty' 2>/dev/null)

    if [[ -z "$workflow_id" || "$workflow_id" == "null" ]]; then
        echo_with_color $RED "❌ No workflow_id returned from start endpoint"
        local error_msg
        error_msg=$(echo "$start_response" | jq -r '.error // "Unknown error"' 2>/dev/null)
        echo_with_color $RED "    Error: ${error_msg}"
        return 1
    fi

    echo_with_color $GREEN "  ✅ Workflow started with ID: ${workflow_id}"
    echo ""

    local final_response
    if ! final_response=$(poll_workflow_status "$workflow_id"); then
        echo_with_color $RED "❌ Workflow did not complete successfully"
        return 1
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
        echo_with_color $GREEN "    ✅ Annuity workflow completed successfully!"
        echo ""
        echo_with_color $BLUE "  📋 Annuity Details:"
        echo_with_color $BLUE "      Annuity Contract ID: $(echo "$final_response" | jq -r '.result.annuity_contract_id // "N/A"')"
        echo_with_color $BLUE "      Annuity Message ID: $(echo "$final_response" | jq -r '.result.annuity_message_id // "N/A"')"
        echo_with_color $BLUE "      Annuity Accept Message ID: $(echo "$final_response" | jq -r '.result.annuity_accept_message_id // "N/A"')"
        echo_with_color $BLUE "      Redemption Contract ID: $(echo "$final_response" | jq -r '.result.redemption_contract_id // "N/A"')"
        echo_with_color $BLUE "      Redemption Message ID: $(echo "$final_response" | jq -r '.result.redemption_message_id // "N/A"')"
        echo_with_color $BLUE "      Redemption Accept Message ID: $(echo "$final_response" | jq -r '.result.redemption_accept_message_id // "N/A"')"
        echo_with_color $BLUE "      Annuity ID: $(echo "$final_response" | jq -r '.result.annuity_id // "N/A"')"
        echo ""
        echo_with_color $GREEN "🎉 Workflow test completed successfully! ✨"
        return 0
    else
        echo_with_color $RED "    ❌ Annuity workflow ended in status: ${workflow_status}"
        local error_msg
        error_msg=$(echo "$final_response" | jq -r '.error // "Unknown error"' 2>/dev/null)
        echo_with_color $RED "    Error: ${error_msg}"
        echo_with_color $BLUE "    Full response:"
        echo "$final_response" | sed 's/^/      /'
        return 1
    fi
}

main "$@"


