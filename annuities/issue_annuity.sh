#!/bin/bash

# Test script for the Issue Annuity API endpoint
# This script demonstrates how to use the /api/issue-annuity endpoint
# Follows patterns from yieldfabric-docs/scripts/executors.sh

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

# Helper function to print colored output (matching executor scripts)
echo_with_color() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

# Function to check if a service is running
check_service_running() {
    local service_name=$1
    local service_url=$2
    
    echo_with_color $BLUE "  🔍 Checking if ${service_name} is running..."
    
    # If URL is provided (remote service), check with curl
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
        # Legacy: port-based check for localhost
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

# Function to login user and get JWT token (matching auth.sh pattern)
login_user() {
    local email="$1"
    local password="$2"
    local services_json='["vault", "payments"]'

    # All informational output goes to stderr
    echo_with_color $BLUE "  🔐 Logging in user: $email" >&2
    
    local http_response=$(curl -s -X POST "${AUTH_SERVICE_URL}/auth/login/with-services" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"$email\", \"password\": \"$password\", \"services\": $services_json}")

    echo_with_color $BLUE "    📡 Login response received" >&2
    
    if [[ -n "$http_response" ]]; then
        local token=$(echo "$http_response" | jq -r '.token // .access_token // .jwt // empty')
        if [[ -n "$token" && "$token" != "null" ]]; then
            echo_with_color $GREEN "    ✅ Login successful" >&2
            # Only the token goes to stdout
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

# Function to call the issue annuity endpoint
issue_annuity() {
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
    
    # All informational output goes to stderr so it doesn't get captured
    echo_with_color $CYAN "🏦 Creating annuity settlement..." >&2
    
    # Build coupon_dates JSON array
    local coupon_dates_json="["
    for i in "${!coupon_dates[@]}"; do
        if [ $i -gt 0 ]; then
            coupon_dates_json+=","
        fi
        coupon_dates_json+="\"${coupon_dates[$i]}\""
    done
    coupon_dates_json+="]"
    
    local request_body=$(cat <<EOF
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
    
    echo_with_color $BLUE "  🌐 Making REST API request to: ${PAY_SERVICE_URL}/api/annuity/issue" >&2
    
    # Use -w to get HTTP status code
    local temp_file=$(mktemp)
    local http_code=$(curl -s -w "%{http_code}" -o "$temp_file" -X POST "${PAY_SERVICE_URL}/api/annuity/issue" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${jwt_token}" \
        -d "$request_body")
    
    local http_response=$(cat "$temp_file")
    rm -f "$temp_file"
    
    echo_with_color $BLUE "  📡 Response received (HTTP $http_code)" >&2
    
    if [[ -z "$http_response" ]]; then
        echo_with_color $YELLOW "  ⚠️  Warning: Empty response body" >&2
    fi
    
    # Only the actual response goes to stdout
    echo "$http_response"
}

# Main test execution
main() {
    echo_with_color $CYAN "🚀 Starting Issue Annuity API Test"
    echo ""
    
    # Test parameters (matching issue_annuity.yaml)
    USER_EMAIL="${USER_EMAIL:-issuer@yieldfabric.com}"
    PASSWORD="${PASSWORD:-issuer_password}"
    DENOMINATION="${DENOMINATION:-aud-token-asset}"
    COUNTERPART="${COUNTERPART:-investor@yieldfabric.com}"
    START_DATE="${START_DATE:-2025-12-20}"
    END_DATE="${END_DATE:-2025-12-24}"
    COUPON_AMOUNT="${COUPON_AMOUNT:-2000000000000000000}"
    INITIAL_AMOUNT="${INITIAL_AMOUNT:-10000000000000000000000}"
    REDEMPTION_AMOUNT="${REDEMPTION_AMOUNT:-10000000000000000000000}"
    
    # Coupon dates (matching issue_annuity.yaml)
    COUPON_DATES=(
        "2025-12-20T00:00:00Z"
        "2025-12-21T00:00:00Z"
        "2025-12-22T00:00:00Z"
        "2025-12-23T00:00:00Z"
        "2025-12-24T00:00:00Z"
    )
    
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
    
    # Check service health (matching executor scripts)
    if ! check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
        echo_with_color $RED "❌ Auth service is not reachable at $AUTH_SERVICE_URL"
        echo_with_color $YELLOW "Please check your connection or start the auth service:"
        echo "   Local: cd ../yieldfabric-auth && cargo run"
        echo "   Remote: Verify $AUTH_SERVICE_URL is accessible"
        return 1
    fi
    
    if ! check_service_running "Payments Service" "$PAY_SERVICE_URL"; then
        echo_with_color $RED "❌ Payments service is not reachable at $PAY_SERVICE_URL"
        echo_with_color $YELLOW "Please check your connection or start the payments service:"
        echo "   Local: cd ../yieldfabric-payments && cargo run"
        echo_with_color $BLUE "   REST API endpoint will be available at: $PAY_SERVICE_URL/api/annuity/issue"
        return 1
    fi
    
    echo ""
    
    # Step 1: Login (using auth.sh pattern)
    echo_with_color $CYAN "🔐 Authenticating..."
    local jwt_token=$(login_user "$USER_EMAIL" "$PASSWORD")
    if [[ -z "$jwt_token" ]]; then
        echo_with_color $RED "❌ Failed to get JWT token for user: $USER_EMAIL"
        return 1
    fi
    
    echo_with_color $GREEN "  ✅ JWT token obtained (first 50 chars): ${jwt_token:0:50}..."
    echo ""
    
    # Step 2: Call issue annuity endpoint
    echo_with_color $CYAN "📤 Calling issue annuity endpoint..."
    echo ""
    local response=$(issue_annuity \
        "$jwt_token" \
        "$DENOMINATION" \
        "$COUNTERPART" \
        "$START_DATE" \
        "$END_DATE" \
        "$COUPON_AMOUNT" \
        "$INITIAL_AMOUNT" \
        "$REDEMPTION_AMOUNT" \
        "${COUPON_DATES[@]}")
    
    echo ""
    echo_with_color $BLUE "📡 Raw API Response:"
    
    if [[ -z "$response" ]]; then
        echo_with_color $RED "  ❌ Empty response received from server!"
        echo_with_color $YELLOW "  This usually means:"
        echo_with_color $YELLOW "    - The server needs to be restarted with the new handler code"
        echo_with_color $YELLOW "    - JSON deserialization failed (check request format)"
        echo_with_color $YELLOW "    - The endpoint handler returned an error"
        echo ""
        echo_with_color $CYAN "  💡 Troubleshooting steps:"
        echo_with_color $CYAN "    1. Restart the payments service:"
        echo_with_color $CYAN "       cd ../yieldfabric-payments && cargo run"
        echo_with_color $CYAN "    2. Check server logs for deserialization errors"
        echo_with_color $CYAN "    3. Verify the route is registered:"
        echo_with_color $CYAN "       grep 'issue-annuity' src/main.rs"
        echo_with_color $CYAN "    4. Test with verbose curl:"
        echo_with_color $CYAN "       curl -v -X POST http://localhost:3002/api/annuity/issue \\"
        echo_with_color $CYAN "         -H 'Content-Type: application/json' \\"
        echo_with_color $CYAN "         -H 'Authorization: Bearer YOUR_TOKEN' \\"
        echo_with_color $CYAN "         -d '{\"denomination\":\"test\",\"counterpart\":\"test\",...}'"
        return 1
    fi
    
    echo "$response" | jq '.' 2>/dev/null | sed 's/^/  /' || {
        echo_with_color $RED "  ⚠️  Response is not valid JSON:"
        echo "$response" | sed 's/^/  /'
    }
    echo ""
    
    # Check response status
    local status=$(echo "$response" | jq -r '.status // empty' 2>/dev/null)
    
    if [[ "$status" == "success" ]]; then
        echo_with_color $GREEN "    ✅ Annuity settlement created successfully!"
        echo ""
        echo_with_color $BLUE "  📋 Settlement Details:"
        echo_with_color $BLUE "      Annuity Contract ID: $(echo "$response" | jq -r '.result.annuity_contract_id // "N/A"')"
        echo_with_color $BLUE "      Annuity Message ID: $(echo "$response" | jq -r '.result.annuity_message_id // "N/A"')"
        echo_with_color $BLUE "      Annuity Accept Message ID: $(echo "$response" | jq -r '.result.annuity_accept_message_id // "N/A"')"
        echo_with_color $BLUE "      Redemption Contract ID: $(echo "$response" | jq -r '.result.redemption_contract_id // "N/A"')"
        echo_with_color $BLUE "      Redemption Message ID: $(echo "$response" | jq -r '.result.redemption_message_id // "N/A"')"
        echo_with_color $BLUE "      Redemption Accept Message ID: $(echo "$response" | jq -r '.result.redemption_accept_message_id // "N/A"')"
        echo_with_color $BLUE "      Annuity ID: $(echo "$response" | jq -r '.result.annuity_id // "N/A"')"
        echo ""
        echo_with_color $GREEN "🎉 Test completed successfully! ✨"
        return 0
    else
        echo_with_color $RED "    ❌ Annuity settlement failed"
        local error_msg=$(echo "$response" | jq -r '.error // "Unknown error"')
        echo_with_color $RED "    Error: ${error_msg}"
        echo_with_color $BLUE "    Full response: $response"
        return 1
    fi
}

# Run the test
main "$@"

