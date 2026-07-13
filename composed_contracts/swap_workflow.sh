#!/bin/bash

# Test script for the Composed Contract Swap Workflow API endpoint
# This workflow takes an EXISTING composed contract and creates a swap for all its obligations vs payment
#
# Flow:
#   1. Takes a composed contract ID (from issue_workflow.sh)
#   2. Fetches all obligations from the composed contract
#   3. Creates a swap offering those obligations for payment
#
# This is different from issue_swap_workflow.sh which CREATES new obligations.
# Use this when you already have a composed contract and want to swap its obligations.

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

list_composed_contracts() {
    local jwt_token=$1

    echo_with_color $CYAN "🔍 Listing composed contracts from workflow history..." >&2

    # Query completed composed_contract_issue workflows to list available composed contracts
    # Note: Composed contracts are stored in workflow_instances, not as regular contracts
    local url="${PAY_SERVICE_URL}/api/composed_contract/issue_workflow"
    
    # Since we can't directly query workflow_instances via REST, we'll show guidance
    echo_with_color $YELLOW "    ℹ️  Composed contracts are created by the issue_workflow" >&2
    echo_with_color $BLUE "    Run ./issue_workflow.sh first to create a composed contract" >&2
    echo_with_color $BLUE "    The workflow output will show the composed_contract_id to use" >&2
    echo ""
}

start_swap_workflow() {
    local jwt_token=$1
    local composed_contract_id=$2
    local counterparty=$3
    local payment_amount=$4
    local payment_denomination=$5
    local deadline=$6

    echo_with_color $CYAN "🏦 Starting swap workflow for composed contract: $composed_contract_id..." >&2

    local request_body
    if [[ -n "$deadline" && "$deadline" != "null" ]]; then
        request_body=$(jq -n \
            --arg composed_contract_id "$composed_contract_id" \
            --arg counterparty "$counterparty" \
            --arg payment_amount "$payment_amount" \
            --arg payment_denomination "$payment_denomination" \
            --arg deadline "$deadline" \
            '{
                composed_contract_id: $composed_contract_id,
                counterparty: $counterparty,
                payment_amount: $payment_amount,
                payment_denomination: $payment_denomination,
                deadline: $deadline
            }')
    else
        request_body=$(jq -n \
            --arg composed_contract_id "$composed_contract_id" \
            --arg counterparty "$counterparty" \
            --arg payment_amount "$payment_amount" \
            --arg payment_denomination "$payment_denomination" \
            '{
                composed_contract_id: $composed_contract_id,
                counterparty: $counterparty,
                payment_amount: $payment_amount,
                payment_denomination: $payment_denomination
            }')
    fi

    echo_with_color $BLUE "  📋 Request body:" >&2
    echo "$request_body" | jq '.' | sed 's/^/    /' >&2

    echo_with_color $BLUE "  🌐 Making REST API request to: ${PAY_SERVICE_URL}/api/composed_contract/swap_workflow" >&2

    local temp_file
    temp_file=$(mktemp)
    local http_code
    http_code=$(curl -s -w "%{http_code}" -o "$temp_file" -X POST "${PAY_SERVICE_URL}/api/composed_contract/swap_workflow" \
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

    # Log the full response for debugging (especially for 422 errors)
    if [[ "$http_code" == "422" ]]; then
        echo_with_color $YELLOW "  ⚠️  Validation error - full response:" >&2
        echo "$http_response" | jq '.' 2>/dev/null | sed 's/^/    /' >&2 || echo "$http_response" | sed 's/^/    /' >&2
    fi

    echo "$http_response"
}

poll_workflow_status() {
    local workflow_id=$1
    local max_attempts=${2:-120}
    local delay_seconds=${3:-1}

    echo_with_color $CYAN "🔄 Polling workflow status for ID: ${workflow_id}" >&2

    local attempt
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        local url="${PAY_SERVICE_URL}/api/composed_contract/swap_workflow/${workflow_id}"
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

show_usage() {
    echo_with_color $CYAN "Usage: $0 [COMPOSED_CONTRACT_ID] [OPTIONS]"
    echo ""
    echo_with_color $BLUE "Arguments:"
    echo_with_color $BLUE "  COMPOSED_CONTRACT_ID    The ID of the composed contract to swap"
    echo ""
    echo_with_color $BLUE "Options:"
    echo_with_color $BLUE "  --list                  List available composed contracts"
    echo_with_color $BLUE "  -h, --help              Show this help message"
    echo ""
    echo_with_color $BLUE "Environment Variables:"
    echo_with_color $BLUE "  COMPOSED_CONTRACT_ID    Composed contract ID (alternative to argument)"
    echo_with_color $BLUE "  USER_EMAIL              Issuer email (default: issuer@yieldfabric.com)"
    echo_with_color $BLUE "  PASSWORD                Issuer password (default: issuer_password)"
    echo_with_color $BLUE "  COUNTERPART             Swap counterparty (default: investor@yieldfabric.com)"
    echo_with_color $BLUE "  PAYMENT_AMOUNT          Expected payment amount (default: 125)"
    echo_with_color $BLUE "  PAYMENT_DENOMINATION    Payment denomination (default: aud-token-asset)"
    echo_with_color $BLUE "  DEADLINE                Swap deadline (default: 2025-12-31T23:59:59Z)"
    echo_with_color $BLUE "  PAY_SERVICE_URL         Payments service URL"
    echo_with_color $BLUE "  AUTH_SERVICE_URL        Auth service URL"
    echo ""
    echo_with_color $PURPLE "Examples:"
    echo_with_color $BLUE "  # Swap a specific composed contract"
    echo_with_color $BLUE "  ./swap_workflow.sh 123456789"
    echo ""
    echo_with_color $BLUE "  # List available composed contracts"
    echo_with_color $BLUE "  ./swap_workflow.sh --list"
    echo ""
    echo_with_color $BLUE "  # Swap with custom parameters"
    echo_with_color $BLUE "  PAYMENT_AMOUNT=200 COUNTERPART=buyer@example.com ./swap_workflow.sh 123456789"
    echo ""
    echo_with_color $PURPLE "Workflow:"
    echo_with_color $BLUE "  1. First create a composed contract with: ./issue_workflow.sh"
    echo_with_color $BLUE "  2. Note the composed_contract_id from the output"
    echo_with_color $BLUE "  3. Run this script with that ID: ./swap_workflow.sh <ID>"
    echo_with_color $BLUE "  4. Counterparty accepts the swap with: ./accept_swap_workflow.sh"
}

main() {
    echo_with_color $CYAN "🚀 Starting Composed Contract Swap Workflow"
    echo ""

    # Check for help flag
    if [[ "$1" == "-h" || "$1" == "--help" ]]; then
        show_usage
        return 0
    fi

    # Test parameters
    USER_EMAIL="${USER_EMAIL:-issuer@yieldfabric.com}"
    PASSWORD="${PASSWORD:-issuer_password}"
    COUNTERPART="${COUNTERPART:-investor@yieldfabric.com}"
    DENOMINATION="${DENOMINATION:-aud-token-asset}"
    
    # Swap parameters
    PAYMENT_AMOUNT="${PAYMENT_AMOUNT:-125}"
    PAYMENT_DENOMINATION="${PAYMENT_DENOMINATION:-$DENOMINATION}"
    DEADLINE="${DEADLINE:-2025-12-31T23:59:59Z}"
    
    # Composed contract ID from argument or environment
    COMPOSED_CONTRACT_ID="${1:-${COMPOSED_CONTRACT_ID:-}}"
    LIST_ONLY="${LIST_ONLY:-false}"
    
    if [[ "$1" == "--list" ]]; then
        LIST_ONLY="true"
        COMPOSED_CONTRACT_ID=""
    fi

    echo_with_color $PURPLE "📋 Configuration:"
    echo_with_color $BLUE "  🌐 Payment Service URL: $PAY_SERVICE_URL"
    echo_with_color $BLUE "  🌐 Auth Service URL: $AUTH_SERVICE_URL"
    echo_with_color $BLUE "  👤 User (Initiator): $USER_EMAIL"
    echo_with_color $BLUE "  👥 Counterparty: $COUNTERPART"
    echo_with_color $BLUE "  💰 Payment Amount: $PAYMENT_AMOUNT $PAYMENT_DENOMINATION"
    echo_with_color $BLUE "  ⏰ Deadline: $DEADLINE"
    if [[ -n "$COMPOSED_CONTRACT_ID" ]]; then
        echo_with_color $BLUE "  📄 Composed Contract ID: $COMPOSED_CONTRACT_ID"
    else
        echo_with_color $YELLOW "  📄 Composed Contract ID: (will list available contracts)"
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

    echo_with_color $CYAN "🔐 Step 1: Authenticating..."
    echo ""

    local jwt_token
    jwt_token=$(login_user "$USER_EMAIL" "$PASSWORD")
    if [[ -z "$jwt_token" ]]; then
        echo_with_color $RED "❌ Failed to get JWT token for user: $USER_EMAIL"
        return 1
    fi

    echo_with_color $GREEN "  ✅ JWT token obtained (first 50 chars): ${jwt_token:0:50}..."
    echo ""

    # If no composed contract ID provided, show help
    if [[ -z "$COMPOSED_CONTRACT_ID" ]]; then
        echo_with_color $CYAN "🔍 Step 2: No composed contract ID provided"
        echo ""

        list_composed_contracts "$jwt_token"

        if [[ "$LIST_ONLY" == "true" ]]; then
            echo_with_color $CYAN "💡 To swap a composed contract, run:"
            echo_with_color $BLUE "    ./swap_workflow.sh <COMPOSED_CONTRACT_ID>"
            echo ""
            echo_with_color $PURPLE "Example composed contract ID format:"
            echo_with_color $BLUE "    COMPOSED-CONTRACT-1764332654035"
            return 0
        fi

        echo_with_color $YELLOW "⚠️  Please provide a composed contract ID:"
        echo_with_color $BLUE "    ./swap_workflow.sh <COMPOSED_CONTRACT_ID>"
        echo ""
        echo_with_color $PURPLE "Example:"
        echo_with_color $BLUE "    ./swap_workflow.sh COMPOSED-CONTRACT-1764332654035"
        return 1
    fi

    echo_with_color $CYAN "🏦 Step 2: Starting swap workflow..."
    echo ""

    local start_response
    start_response=$(start_swap_workflow \
        "$jwt_token" \
        "$COMPOSED_CONTRACT_ID" \
        "$COUNTERPART" \
        "$PAYMENT_AMOUNT" \
        "$PAYMENT_DENOMINATION" \
        "$DEADLINE")

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
        
        # Check if we got a 404 (route not found)
        if echo "$start_response" | grep -qi "404\|not found" || [[ -z "$start_response" ]]; then
            echo_with_color $YELLOW "    ⚠️  Received 404 or empty response - the endpoint may not be registered"
            echo_with_color $YELLOW "    This usually means the server needs to be restarted with the latest code"
            echo_with_color $BLUE "    Please ensure:"
            echo_with_color $BLUE "      1. The server was built with: cd yieldfabric-payments && cargo build"
            echo_with_color $BLUE "      2. The server was restarted after adding the composed_contract_swap workflow"
            echo_with_color $BLUE "      3. The route is registered at: /api/composed_contract/swap_workflow"
        else
            local error_msg
            error_msg=$(echo "$start_response" | jq -r '.error // .message // "Unknown error"' 2>/dev/null)
            if [[ -z "$error_msg" || "$error_msg" == "null" ]]; then
                echo_with_color $RED "    Error: Invalid request (HTTP 422 - Unprocessable Entity)"
                echo_with_color $YELLOW "    Full response:"
                echo "$start_response" | jq '.' 2>/dev/null | sed 's/^/      /' || echo "$start_response" | sed 's/^/      /'
            else
                echo_with_color $RED "    Error: ${error_msg}"
            fi
        fi
        return 1
    fi

    echo_with_color $GREEN "  ✅ Workflow started with ID: ${workflow_id}"
    echo ""

    echo_with_color $CYAN "⏳ Step 3: Polling workflow status..."
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
        echo_with_color $GREEN "    ✅ Swap workflow completed successfully!"
        echo ""
        echo_with_color $BLUE "  📋 Result Details:"
        echo_with_color $BLUE "      Composed Contract ID: $COMPOSED_CONTRACT_ID"
        echo_with_color $BLUE "      Swap ID: $(echo "$final_response" | jq -r '.result.swap_id // "N/A"')"
        echo_with_color $BLUE "      Swap Message ID: $(echo "$final_response" | jq -r '.result.swap_message_id // "N/A"')"
        echo_with_color $BLUE "      Obligation IDs: $(echo "$final_response" | jq -r '.result.obligation_ids // "N/A"')"
        echo ""
        echo_with_color $GREEN "🎉 Swap workflow completed successfully! ✨"
        echo ""
        echo_with_color $CYAN "📝 Summary:"
        echo_with_color $BLUE "   • Composed Contract: $COMPOSED_CONTRACT_ID"
        echo_with_color $BLUE "   • Obligations swapped: $(echo "$final_response" | jq -r '.result.obligation_ids | length // "N/A"')"
        echo_with_color $BLUE "   • Swap offer: all obligations vs ${PAYMENT_AMOUNT} ${PAYMENT_DENOMINATION}"
        echo_with_color $BLUE "   • Counterparty: ${COUNTERPART}"
        echo ""
        echo_with_color $CYAN "💡 Next Steps:"
        echo_with_color $BLUE "   The counterparty ($COUNTERPART) can now accept the swap:"
        local swap_id
        swap_id=$(echo "$final_response" | jq -r '.result.swap_id // ""')
        if [[ -n "$swap_id" && "$swap_id" != "N/A" ]]; then
            echo_with_color $BLUE "   ./accept_swap_workflow.sh $swap_id"
        else
            echo_with_color $BLUE "   ./accept_swap_workflow.sh <SWAP_ID>"
        fi
        return 0
    else
        echo_with_color $RED "    ❌ Swap workflow ended in status: ${workflow_status}"
        local error_msg
        error_msg=$(echo "$final_response" | jq -r '.error // "Unknown error"' 2>/dev/null)
        echo_with_color $RED "    Error: ${error_msg}"
        echo_with_color $BLUE "    Full response:"
        echo "$final_response" | sed 's/^/      /'
        return 1
    fi
}

main "$@"

