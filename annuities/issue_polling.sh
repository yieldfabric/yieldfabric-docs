#!/bin/bash

# Lightweight script to poll the status of an existing annuity workflow.
# Usage:
#   ./issue_polling.sh WORKFLOW_ID
#
# Optionally uses PAY_SERVICE_URL from environment; defaults to https://pay.test.yieldfabric.com

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

PAY_SERVICE_URL="${PAY_SERVICE_URL:-https://pay.test.yieldfabric.com}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo_with_color() {
    local color=$1
    local message=$2
    echo -e "${color}${message}${NC}"
}

poll_workflow_status() {
    local workflow_id=$1
    local max_attempts=${2:-60}
    local delay_seconds=${3:-5}

    echo_with_color $CYAN "🔄 Polling annuity workflow status for ID: ${workflow_id}"

    local attempt
    for ((attempt=1; attempt<=max_attempts; attempt++)); do
        local url="${PAY_SERVICE_URL}/api/annuity/issue_workflow/${workflow_id}"
        echo_with_color $BLUE "  📡 Attempt ${attempt}/${max_attempts}: GET ${url}"

        local response
        response=$(curl -s "$url")

        if [[ -z "$response" ]]; then
            echo_with_color $YELLOW "  ⚠️  Empty response from status endpoint"
        else
            local workflow_status
            workflow_status=$(echo "$response" | jq -r '.workflow_status // empty' 2>/dev/null)
            
            local current_step
            current_step=$(echo "$response" | jq -r '.current_step // empty' 2>/dev/null)

            echo_with_color $BLUE "  🔎 Current workflow_status: ${workflow_status:-unknown}"
            if [[ -n "$current_step" && "$current_step" != "unknown" ]]; then
                echo_with_color $CYAN "  📍 Current step: ${current_step}"
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

    echo_with_color $RED "  ❌ Workflow did not complete within ${max_attempts} attempts"
    return 1
}

main() {
    if [[ -z "$1" ]]; then
        echo_with_color $RED "Usage: $0 WORKFLOW_ID [MAX_ATTEMPTS] [DELAY_SECONDS]"
        exit 1
    fi

    local workflow_id=$1
    local max_attempts=${2:-60}
    local delay_seconds=${3:-5}

    echo_with_color $BLUE "📋 Configuration:"
    echo_with_color $BLUE "  API Base URL: ${PAY_SERVICE_URL}"
    echo_with_color $BLUE "  Workflow ID: ${workflow_id}"
    echo_with_color $BLUE "  Max Attempts: ${max_attempts}"
    echo_with_color $BLUE "  Delay Seconds: ${delay_seconds}"
    echo ""

    local final_response
    if ! final_response=$(poll_workflow_status "$workflow_id" "$max_attempts" "$delay_seconds"); then
        echo_with_color $RED "❌ Polling failed or timed out"
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
        echo_with_color $GREEN "🎉 Polling test completed successfully! ✨"
        exit 0
    else
        echo_with_color $RED "    ❌ Annuity workflow ended in status: ${workflow_status}"
        local error_msg
        error_msg=$(echo "$final_response" | jq -r '.error // "Unknown error"' 2>/dev/null)
        echo_with_color $RED "    Error: ${error_msg}"
        echo_with_color $BLUE "    Full response:"
        echo "$final_response" | sed 's/^/      /'
        exit 1
    fi
}

main "$@"


