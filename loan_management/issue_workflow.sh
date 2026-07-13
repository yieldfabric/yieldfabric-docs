#!/bin/bash

# Test script for the workflow-based Issue Composed Contract API endpoint
# This script processes loans from a CSV file and creates composed contracts
# Adapted to process top 10 loans from wisr_loans_20250831.csv

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

issue_composed_contract_workflow() {
    local jwt_token=$1
    local name=$2
    local description=$3
    shift 3
    local obligations_json="$1"

    echo_with_color $CYAN "🏦 Starting composed contract issuance workflow..." >&2

    local request_body
    request_body=$(cat <<EOF
{
    "name": "${name}",
    "description": "${description}",
    "obligations": ${obligations_json}
}
EOF
)

    echo_with_color $BLUE "  📋 Request body:" >&2
    echo "$request_body" | jq '.' | sed 's/^/    /' >&2

    echo_with_color $BLUE "  🌐 Making REST API request to: ${PAY_SERVICE_URL}/api/composed_contract/issue_workflow" >&2

    local temp_file
    temp_file=$(mktemp)
    local http_code
    http_code=$(curl -s -w "%{http_code}" -o "$temp_file" -X POST "${PAY_SERVICE_URL}/api/composed_contract/issue_workflow" \
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
        # Use unified workflow status endpoint - works for all workflow types
        local url="${PAY_SERVICE_URL}/api/workflows/${workflow_id}"
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
            
            local workflow_type
            workflow_type=$(echo "$response" | jq -r '.workflow_type // empty' 2>/dev/null)

            echo_with_color $BLUE "  🔎 Current workflow_status: ${workflow_status:-unknown}" >&2
            if [[ -n "$workflow_type" && "$workflow_type" != "null" ]]; then
                echo_with_color $CYAN "  📋 Workflow type: ${workflow_type}" >&2
            fi
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

# Convert currency string to wei-like format (18 decimals)
# Input: "$31,817.59" -> Output: "31817590000000000000000"
convert_currency_to_wei() {
    local currency_str="$1"
    # Remove $ and commas, keep only digits and decimal point
    local cleaned=$(echo "$currency_str" | sed 's/[\$,]//g')
    # Use awk to multiply by 10^18 (convert to wei-like units)
    echo "$cleaned" | awk '{printf "%.0f", $1 * 1000000000000000000}'
}

# Convert date from M/D/YY format to ISO format
# Input: "2/12/32" -> Output: "2032-02-12T23:59:59Z"
# Assumes 2-digit years are in 2000-2099 range for loan maturity dates
convert_date_to_iso() {
    local date_str="$1"
    # Parse M/D/YY format
    IFS='/' read -r month day year <<< "$date_str"
    
    # Convert 2-digit year to 4-digit (assume all years are 2000-2099 for loan maturities)
    # Pad single digit years with leading zero if needed
    if [[ ${#year} -eq 1 ]]; then
        year="200$year"
    elif [[ ${#year} -eq 2 ]]; then
        year="20$year"
    fi
    
    # Format with leading zeros
    month=$(printf "%02d" "$month")
    day=$(printf "%02d" "$day")
    
    echo "${year}-${month}-${day}T23:59:59Z"
}

# Parse CSV and extract loan data
# Uses a more robust approach to handle quoted fields with commas
parse_loan_from_csv() {
    local csv_line="$1"
    
    # Use Python for proper CSV parsing (handles quoted fields correctly)
    # Columns: Loan ID (0), Prin. Out (7), Maturity (4)
    python3 -c "
import csv
import sys
from io import StringIO

reader = csv.reader(StringIO(sys.argv[1]))
row = next(reader)
if len(row) > 7:
    loan_id = row[0].strip('\"')
    prin_out = row[7].strip('\"')
    maturity = row[4].strip('\"')
    print(f'{loan_id}|{prin_out}|{maturity}')
else:
    print('||')
" "$csv_line"
}

main() {
    echo_with_color $CYAN "🚀 Starting Issue Composed Contract WorkFlow API Test - Processing Loans from CSV"
    echo ""

    # Check for Python (required for CSV parsing)
    if ! command -v python3 &> /dev/null; then
        echo_with_color $RED "❌ python3 is required for CSV parsing but not found"
        echo_with_color $YELLOW "   Please install Python 3 to use this script"
        return 1
    fi

    # Parse command-line arguments for username, password, and csv_file
    # Usage: ./issue_workflow.sh [username] [password] [csv_file]
    # Or: ./issue_workflow.sh [csv_file]
    # If not provided, falls back to environment variables, then defaults
    
    # Store environment variables before we potentially overwrite them
    local env_user_email="${USER_EMAIL:-}"
    local env_password="${PASSWORD:-}"
    
    # Smart argument detection: if first arg looks like a CSV file, treat it as such
    CSV_FILE=""
    USER_EMAIL=""
    PASSWORD=""
    
    if [[ $# -ge 1 ]]; then
        # Check if first argument is a CSV file (ends with .csv or exists as file)
        if [[ "$1" == *.csv ]] || [[ -f "$1" ]]; then
            CSV_FILE="$1"
        elif [[ "$1" == *@* ]]; then
            # Looks like an email address
            USER_EMAIL="$1"
            if [[ $# -ge 2 ]]; then
                PASSWORD="$2"
                if [[ $# -ge 3 ]]; then
                    CSV_FILE="$3"
                fi
            fi
        else
            # Assume it's a username even if it doesn't look like an email
            USER_EMAIL="$1"
            if [[ $# -ge 2 ]]; then
                PASSWORD="$2"
                if [[ $# -ge 3 ]]; then
                    CSV_FILE="$3"
                fi
            fi
        fi
    fi
    
    # Set defaults if not provided (use environment variables, then hardcoded defaults)
    if [[ -z "$USER_EMAIL" ]]; then
        if [[ -n "$env_user_email" ]]; then
            USER_EMAIL="$env_user_email"
        else
            USER_EMAIL="issuer@yieldfabric.com"
        fi
    fi
    
    if [[ -z "$PASSWORD" ]]; then
        if [[ -n "$env_password" ]]; then
            PASSWORD="$env_password"
        else
            PASSWORD="issuer_password"
        fi
    fi
    
    # CSV file path - use LOANS_CSV from env, else default
    if [[ -z "$CSV_FILE" ]]; then
        CSV_FILE="${LOANS_CSV:-${SCRIPT_DIR}/wisr_loans_20250831.csv}"
    fi
    
    # Resolve relative paths
    if [[ ! "$CSV_FILE" =~ ^/ ]]; then
        # Relative path - try script directory first, then current directory
        if [[ -f "${SCRIPT_DIR}/${CSV_FILE}" ]]; then
            CSV_FILE="${SCRIPT_DIR}/${CSV_FILE}"
        elif [[ -f "$CSV_FILE" ]]; then
            CSV_FILE=$(cd "$(dirname "$CSV_FILE")" && pwd)/$(basename "$CSV_FILE")
        fi
    fi
    
    if [[ ! -f "$CSV_FILE" ]]; then
        echo_with_color $RED "❌ CSV file not found: $CSV_FILE"
        return 1
    fi

    # Test parameters
    DENOMINATION="${DENOMINATION:-aud-token-asset}"
    COUNTERPART="${COUNTERPART:-issuer@yieldfabric.com}"

    echo_with_color $BLUE "📋 Configuration:"
    echo_with_color $BLUE "  API Base URL: ${PAY_SERVICE_URL}"
    echo_with_color $BLUE "  Auth Service: ${AUTH_SERVICE_URL}"
    echo_with_color $BLUE "  User (Initiator): ${USER_EMAIL}"
    echo_with_color $BLUE "  Counterparty: ${COUNTERPART}"
    echo_with_color $BLUE "  Denomination: ${DENOMINATION}"
    echo_with_color $BLUE "  CSV File: ${CSV_FILE}"
    echo ""

    if ! check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
        echo_with_color $RED "❌ Auth service is not reachable at $AUTH_SERVICE_URL"
        return 1
    fi

    if ! check_service_running "Payments Service" "$PAY_SERVICE_URL"; then
        echo_with_color $RED "❌ Payments service is not reachable at $PAY_SERVICE_URL"
        echo_with_color $YELLOW "Please start the payments service:"
        echo "   Local: cd ../yieldfabric-payments && cargo run"
        echo_with_color $BLUE "   REST API endpoint will be available at: $PAY_SERVICE_URL/api/composed_contract/issue_workflow"
        return 1
    fi

    # Check if the endpoint exists (basic check)
    local endpoint_check
    endpoint_check=$(curl -s -o /dev/null -w "%{http_code}" "${PAY_SERVICE_URL}/api/composed_contract/issue_workflow" -X POST -H "Content-Type: application/json" -d '{}' 2>/dev/null || echo "000")
    if [[ "$endpoint_check" == "404" ]]; then
        echo_with_color $YELLOW "⚠️  Warning: Endpoint returned 404. The server may need to be restarted to pick up the new routes."
        echo_with_color $YELLOW "   Make sure the server was built with the latest code including composed_contract_issue workflow."
        echo ""
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

    # Read CSV and process top 10 loans (skip header, take rows 2-11)
    echo_with_color $CYAN "📖 Reading loans from CSV file..."
    local loan_count=0
    local success_count=0
    local fail_count=0
    
    # Read CSV lines, skip header (line 1), process lines 2-11
    local line_num=0
    while IFS= read -r csv_line && [[ $loan_count -lt 10 ]]; do
        line_num=$((line_num + 1))
        
        # Skip header row
        if [[ $line_num -eq 1 ]]; then
            continue
        fi
        
        loan_count=$((loan_count + 1))
        
        # Parse loan data
        local loan_data
        loan_data=$(parse_loan_from_csv "$csv_line")
        local loan_id=$(echo "$loan_data" | cut -d'|' -f1)
        local prin_out=$(echo "$loan_data" | cut -d'|' -f2)
        local maturity=$(echo "$loan_data" | cut -d'|' -f3)
        
        if [[ -z "$loan_id" || -z "$prin_out" || -z "$maturity" ]]; then
            echo_with_color $YELLOW "  ⚠️  Skipping loan ${loan_count}: missing data"
            fail_count=$((fail_count + 1))
            continue
        fi
        
        echo ""
        echo_with_color $PURPLE "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo_with_color $CYAN "📦 Processing Loan ${loan_count}/10: ID=${loan_id}"
        echo_with_color $PURPLE "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        echo ""
        
        # Convert currency to wei format
        local amount_wei
        amount_wei=$(convert_currency_to_wei "$prin_out")
        
        # Convert date to ISO format
        local maturity_iso
        maturity_iso=$(convert_date_to_iso "$maturity")
        
        echo_with_color $BLUE "  Loan Details:"
        echo_with_color $BLUE "    ID: ${loan_id}"
        echo_with_color $BLUE "    Principal Outstanding: ${prin_out} (${amount_wei} wei)"
        echo_with_color $BLUE "    Maturity Date: ${maturity} -> ${maturity_iso}"
        echo ""
        
        # Build single obligation JSON for this loan
        local obligation_json
        obligation_json=$(jq -n \
            --arg counterpart "$COUNTERPART" \
            --arg denomination "$DENOMINATION" \
            --arg obligor "$USER_EMAIL" \
            --arg notional "$amount_wei" \
            --arg end_date "$maturity_iso" \
            --arg name "Loan ${loan_id}" \
            --arg description "Loan obligation for loan ID ${loan_id}" \
            '{
                counterpart: $counterpart,
                denomination: $denomination,
                obligor: $obligor,
                notional: $notional,
                expiry: $end_date,
                data: {
                    name: $name,
                    description: $description
                },
                initialPayments: {
                    amount: $notional,
                    denomination: $denomination,
                    payments: [{
                        oracleAddress: null,
                        oracleOwner: null,
                        oracleKeySender: null,
                        oracleValueSenderSecret: null,
                        oracleKeyRecipient: null,
                        oracleValueRecipientSecret: null,
                        unlockSender: $end_date,
                        unlockReceiver: $end_date,
                        linearVesting: null
                    }]
                }
            }')
        
        # Create composed contract with single obligation
        local obligations_array
        obligations_array=$(jq -n --argjson ob "$obligation_json" '[$ob]')
        
        local contract_name="Loan Contract ${loan_id}"
        local contract_description="Composed contract for loan ID ${loan_id}"
        
        echo_with_color $CYAN "📤 Calling issue composed contract workflow endpoint..."
        local start_response
        start_response=$(issue_composed_contract_workflow \
            "$jwt_token" \
            "$contract_name" \
            "$contract_description" \
            "$obligations_array")
        
        local workflow_id
        workflow_id=$(echo "$start_response" | jq -r '.workflow_id // empty' 2>/dev/null)
        
        if [[ -z "$workflow_id" || "$workflow_id" == "null" ]]; then
            echo_with_color $RED "  ❌ Failed to start workflow for loan ${loan_id}"
            fail_count=$((fail_count + 1))
            continue
        fi
        
        echo_with_color $GREEN "  ✅ Workflow started with ID: ${workflow_id}"
        echo ""
        
        # Poll for completion
        local final_response
        if ! final_response=$(poll_workflow_status "$workflow_id"); then
            echo_with_color $RED "  ❌ Workflow did not complete for loan ${loan_id}"
            fail_count=$((fail_count + 1))
            continue
        fi
        
        local workflow_status
        workflow_status=$(echo "$final_response" | jq -r '.workflow_status // empty' 2>/dev/null)
        
        if [[ "$workflow_status" == "completed" ]]; then
            echo_with_color $GREEN "  ✅ Loan ${loan_id} contract created successfully!"
            local contract_id
            contract_id=$(echo "$final_response" | jq -r '.result.composed_contract_id // "N/A"')
            echo_with_color $BLUE "    Composed Contract ID: ${contract_id}"
            success_count=$((success_count + 1))
        else
            echo_with_color $RED "  ❌ Loan ${loan_id} workflow ended in status: ${workflow_status}"
            fail_count=$((fail_count + 1))
        fi
        
    done < "$CSV_FILE"
    
    echo ""
    echo_with_color $PURPLE "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo_with_color $CYAN "📊 Summary"
    echo_with_color $PURPLE "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo_with_color $BLUE "  Total loans processed: ${loan_count}"
    echo_with_color $GREEN "  Successful: ${success_count}"
    echo_with_color $RED "  Failed: ${fail_count}"
    echo ""
    
    if [[ $success_count -gt 0 ]]; then
        echo_with_color $GREEN "🎉 Successfully created ${success_count} composed contract(s)! ✨"
        return 0
    else
        echo_with_color $RED "❌ No contracts were created successfully"
        return 1
    fi
}

# Show usage if help is requested
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    echo "Usage: $0 [username] [password] [csv_file]"
    echo "   or: $0 [csv_file]"
    echo ""
    echo "Arguments:"
    echo "  username    User email for authentication (default: issuer@yieldfabric.com)"
    echo "  password    User password for authentication (default: issuer_password)"
    echo "  csv_file    Path to CSV file with loan data (default: wisr_loans_20250831.csv)"
    echo ""
    echo "Note: If the first argument is a CSV file (ends with .csv or exists as a file),"
    echo "      it will be treated as the CSV file path, and username/password will use"
    echo "      environment variables or defaults."
    echo ""
    echo "Environment variables (used as fallback if arguments not provided):"
    echo "  USER_EMAIL    User email for authentication"
    echo "  PASSWORD      User password for authentication"
    echo ""
    echo "Description:"
    echo "  Processes the top 10 loans from the CSV file and creates a composed contract"
    echo "  for each loan with a single obligation containing:"
    echo "    - Loan ID as contract identifier"
    echo "    - Principal Outstanding as payment amount"
    echo "    - Maturity date as payment due date"
    echo "    - Issuer as obligor"
    echo ""
    echo "Examples:"
    echo "  $0"
    echo "  $0 wisr_loans_20250831.csv"
    echo "  $0 user@example.com mypassword"
    echo "  $0 user@example.com mypassword /path/to/loans.csv"
    echo "  USER_EMAIL=user@example.com PASSWORD=mypassword $0"
    exit 0
fi

main "$@"

