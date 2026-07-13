#!/bin/bash

# Test script for the Settle Annuity API endpoint
# This script demonstrates how to use the /api/settle-annuity endpoint
# Follows executor script conventions

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

# Function to call the settle annuity endpoint
settle_annuity() {
    local jwt_token=$1
    local annuity_id=$2
    local accept_payments=$3

    # Build request body
    local request_body=$(cat <<EOF
{
    "annuity_id": "$annuity_id",
    "accept_payments": $accept_payments
}
EOF
)
    
    echo_with_color $BLUE "  📋 Request body:" >&2
    echo "$request_body" | jq '.' | sed 's/^/    /' >&2
    
    echo_with_color $BLUE "  🌐 Making REST API request to: ${PAY_SERVICE_URL}/api/annuity/settle" >&2
    
    # Use -w to get HTTP status code
    local temp_file=$(mktemp)
    local http_code=$(curl -s -w "%{http_code}" -o "$temp_file" -X POST "${PAY_SERVICE_URL}/api/annuity/settle" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${jwt_token}" \
        -d "$request_body")
    
    local http_response=$(cat "$temp_file")
    rm -f "$temp_file"
    
    echo_with_color $BLUE "    📡 HTTP Status: $http_code" >&2
    echo_with_color $BLUE "    📥 Response:" >&2
    echo "$http_response" | jq '.' | sed 's/^/    /' >&2
    
    # Return the response to stdout
    echo "$http_response"
}

# Main test execution
main() {
    echo_with_color $CYAN "🚀 Starting Settle Annuity API Test"
    echo ""
    
    # Test parameters
    USER_EMAIL="${USER_EMAIL:-investor@yieldfabric.com}"
    PASSWORD="${PASSWORD:-investor_password}"
    ANNUITY_ID="${ANNUITY_ID:-1763180898558}"
    ACCEPT_PAYMENTS="${ACCEPT_PAYMENTS:-true}"
    
    echo_with_color $PURPLE "📋 Test Configuration:"
    echo_with_color $BLUE "  🌐 Payment Service URL: $PAY_SERVICE_URL"
    echo_with_color $BLUE "  🌐 Auth Service URL: $AUTH_SERVICE_URL"
    echo_with_color $BLUE "  👤 User Email: $USER_EMAIL"
    echo_with_color $BLUE "  🔄 Annuity ID: $ANNUITY_ID"
    echo_with_color $BLUE "  ✅ Accept Payments: $ACCEPT_PAYMENTS"
    echo ""
    
    # Step 0: Check services are running
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
    
    # Step 1: Login and get JWT token
    echo_with_color $CYAN "🔐 Step 1: Logging in as $USER_EMAIL..."
    echo ""
    
    local jwt_token=$(login_user "$USER_EMAIL" "$PASSWORD")
    if [[ -z "$jwt_token" ]]; then
        echo_with_color $RED "❌ Failed to obtain JWT token. Exiting."
        exit 1
    fi
    
    echo_with_color $GREEN "  ✅ JWT token obtained (first 50 chars): ${jwt_token:0:50}..."
    echo ""
    
    # Step 2: Call settle annuity endpoint
    echo_with_color $CYAN "📤 Step 2: Calling settle annuity endpoint..."
    echo ""
    local response=$(settle_annuity \
        "$jwt_token" \
        "$ANNUITY_ID" \
        "$ACCEPT_PAYMENTS")
    
    # Parse response
    local status=$(echo "$response" | jq -r '.status // empty')
    local result=$(echo "$response" | jq -r '.result // empty')
    local error=$(echo "$response" | jq -r '.error // empty')
    
    echo ""
    echo_with_color $CYAN "📊 Step 3: Analyzing results..."
    echo ""
    
    if [[ "$status" == "success" ]]; then
        echo_with_color $GREEN "✅ Settlement successful!"
        echo ""
        echo_with_color $PURPLE "📦 Settlement Details:"
        echo "$result" | jq '.' | sed 's/^/  /'
        
        # Extract specific fields
        local complete_swap_message_id=$(echo "$result" | jq -r '.complete_swap_message_id // empty')
        local counterparty_accept_message_id=$(echo "$result" | jq -r '.counterparty_accept_message_id // empty')
        
        echo ""
        echo_with_color $BLUE "  🔄 Annuity ID: $ANNUITY_ID"
        echo_with_color $BLUE "  📨 Complete Swap Message ID: $complete_swap_message_id"
        if [[ -n "$counterparty_accept_message_id" && "$counterparty_accept_message_id" != "null" ]]; then
            echo_with_color $BLUE "  📨 Counterparty Accept Message ID: $counterparty_accept_message_id"
        fi
        
        echo ""
        echo_with_color $GREEN "🎉 Settle Annuity API Test Completed Successfully!"
        return 0
    else
        echo_with_color $RED "❌ Settlement failed!"
        echo ""
        echo_with_color $YELLOW "Error: $error"
        echo ""
        echo_with_color $RED "❌ Settle Annuity API Test Failed"
        return 1
    fi
}

# Run the main function
main "$@"

