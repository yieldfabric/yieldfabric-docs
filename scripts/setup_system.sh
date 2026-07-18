#!/bin/bash

# YieldFabric System Setup Script
# Reads setup.yaml and creates users, groups, and relationships
# Integrates with yieldfabric-auth.sh for authentication management

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SETUP_FILE="$SCRIPT_DIR/setup.yaml"
AUTH_SCRIPT="$SCRIPT_DIR/yieldfabric-auth.sh"
TOKENS_DIR="$SCRIPT_DIR/tokens"

# Load .env file if it exists
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    echo "Loading environment variables from .env file..."
    set -a
    source "$SCRIPT_DIR/.env"
    set +a
fi

# Ensure tokens directory exists
mkdir -p "$TOKENS_DIR"

# Service URLs - can be overridden by environment variables
# PAY_SERVICE_URL="${PAY_SERVICE_URL:-http://localhost:3002}"
# AUTH_SERVICE_URL="${AUTH_SERVICE_URL:-http://localhost:3000}"

PAY_SERVICE_URL="${PAY_SERVICE_URL:-https://pay.yieldfabric.io}"
AUTH_SERVICE_URL="${AUTH_SERVICE_URL:-https://auth.yieldfabric.io}"

# Colors for output
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

# Function to check if a service is running
check_service_running() {
    local service_name=$1
    local service_url=$2
    
    # If URL is provided (remote service), check with curl
    if [[ "$service_url" =~ ^https?:// ]]; then
        if curl -s -f -o /dev/null --max-time 5 "$service_url/health" 2>/dev/null || \
           curl -s -f -o /dev/null --max-time 5 "$service_url" 2>/dev/null; then
            return 0
        else
            return 1
        fi
    else
        # Legacy: port-based check for localhost
        local port=$service_url
        if nc -z localhost $port 2>/dev/null; then
            return 0
        else
            return 1
        fi
    fi
}

# Function to check if token service is running
check_token_service_running() {
    if check_service_running "Token Service" "$PAY_SERVICE_URL"; then
        return 0
    else
        return 1
    fi
}

# Function to check if yq is available for YAML parsing
check_yq_available() {
    if command -v yq &> /dev/null; then
        return 0
    else
        return 1
    fi
}

# Function to parse YAML using yq
parse_yaml() {
    local yaml_file="$1"
    local query="$2"
    
    if ! check_yq_available; then
        echo_with_color $RED "yq is required for YAML parsing but not installed"
        echo_with_color $YELLOW "Install yq: brew install yq (macOS) or see https://github.com/mikefarah/yq"
        return 1
    fi
    
    yq eval "$query" "$yaml_file" 2>/dev/null
}

# Function to login with services and return JWT token
login_with_services() {
    local email="$1"
    local password="$2"
    local services_json='["vault", "payments"]'

    local http_response=$(curl -s -w "HTTP_STATUS:%{http_code}" -X POST "${AUTH_SERVICE_URL}/auth/login/with-services" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"$email\", \"password\": \"$password\", \"services\": $services_json}")

    local http_status=$(echo "$http_response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)
    local response_body=$(echo "$http_response" | sed 's/HTTP_STATUS:[0-9]*//')

    if [[ "$http_status" == "200" ]]; then
        echo "$response_body" | jq -r '.token // .access_token // .jwt // empty'
        return 0
    else
        echo "" # no token
        return 1
    fi
}

# ── Deployed account-address reporting ──────────────────────────────────
# Login is intentionally off-chain. Setup explicitly activates each user's
# JWT-selected chain because later phases fund/use those accounts. Group
# creation retains its existing explicit deployment lifecycle.

jwt_default_chain_id() {
    python3 -c 'import base64,json,sys; p=sys.argv[1].split(".")[1]; p += "=" * (-len(p) % 4); print(json.loads(base64.urlsafe_b64decode(p)).get("default_chain_id", ""))' "$1" 2>/dev/null
}

# Print a USER's deployed default account address.
# Logs in as the user and explicitly activates the active chain with their OWN
# token — activation forbids preparing another user's account.
print_user_account_address() {
    local user_id="$1" email="$2" password="$3"
    local token
    token=$(login_with_services "$email" "$password")
    if [[ -z "$token" || "$token" == "null" ]]; then
        echo_with_color $YELLOW "      🏦 account: (login failed; cannot read address)"
        return 1
    fi
    local chain
    chain=$(jwt_default_chain_id "$token")
    if [[ -z "$chain" || "$chain" == "null" ]]; then
        echo_with_color $YELLOW "      🏦 account: (session has no active chain)"
        return 1
    fi

    local attempt resp addr status
    resp=$(curl -s -X POST "${AUTH_SERVICE_URL}/entities/user/${user_id}/chain-accounts/${chain}/activation" \
        -H "Content-Type: application/json" \
        -d '{}' \
        -H "Authorization: Bearer ${token}")
    for ((attempt=1; attempt<=60; attempt++)); do
        status=$(echo "$resp" | jq -r '.status // empty' 2>/dev/null)
        addr=$(echo "$resp" | jq -r '.account_address // empty' 2>/dev/null)
        if [[ -n "$addr" && "$addr" != "null" ]]; then
            echo_with_color $PURPLE "      🏦 account: ${addr} (chain ${chain})"
            return 0
        fi
        if [[ "$status" == "failed_retryable" ]]; then
            local activation_error
            activation_error=$(echo "$resp" | jq -r '.error // "unknown error"' 2>/dev/null)
            echo_with_color $YELLOW "      🏦 activation failed; retrying: ${activation_error}"
        fi
        [[ "$attempt" -ge 60 ]] && break
        sleep 2
        # Poll with GET normally. Re-POST terminal failures immediately and
        # every third observation so auth can reconcile a completed MQ message
        # whose original response was ambiguous.
        if [[ "$status" == "failed_retryable" || $((attempt % 3)) -eq 0 ]]; then
            resp=$(curl -s -X POST "${AUTH_SERVICE_URL}/entities/user/${user_id}/chain-accounts/${chain}/activation" \
                -H "Content-Type: application/json" \
                -d '{}' \
                -H "Authorization: Bearer ${token}")
        else
            resp=$(curl -s -X GET "${AUTH_SERVICE_URL}/entities/user/${user_id}/chain-accounts/${chain}/activation" \
                -H "Authorization: Bearer ${token}")
        fi
    done
    echo_with_color $YELLOW "      🏦 account: (not on chain yet after ~120s of reconciliation)"
    return 1
}

# Print a GROUP's account from the canonical chain-qualified activation
# resource. The creator's owner token is required.
print_group_account_address() {
    local group_id="$1" token="$2"
    local chain
    chain=$(jwt_default_chain_id "$token")
    if [[ -z "$chain" || "$chain" == "null" ]]; then
        echo_with_color $YELLOW "      🏦 account: (session has no active chain)"
        return 1
    fi
    local attempt resp addr status
    for ((attempt=1; attempt<=60; attempt++)); do
        resp=$(curl -s -X GET "${AUTH_SERVICE_URL}/entities/group/${group_id}/chain-accounts/${chain}/activation" \
            -H "Authorization: Bearer ${token}")
        status=$(echo "$resp" | jq -r '.status // empty' 2>/dev/null)
        addr=$(echo "$resp" | jq -r '.account_address // empty' 2>/dev/null)
        if [[ -n "$addr" && "$addr" != "null" && "$addr" != "0x0000000000000000000000000000000000000000" ]]; then
            echo_with_color $PURPLE "      🏦 account: ${addr} (chain ${chain}${status:+, ${status}})"
            return 0
        fi
        [[ "$attempt" -lt 60 ]] && sleep 2
    done
    echo_with_color $YELLOW "      🏦 account: (not on chain yet after ~120s of reconciliation)"
    return 1
}

# Helper to fetch first user's credentials from setup.yaml
get_first_user_credentials() {
    local email=$(parse_yaml "$SETUP_FILE" '.users[0].id')
    local password=$(parse_yaml "$SETUP_FILE" '.users[0].password')
    if [[ -n "$email" && -n "$password" ]]; then
        echo "$email $password"
        return 0
    fi
    return 1
}

# Helper to find a group's DB id by its name
get_group_id_by_name() {
    local token="$1"
    local name="$2"
    local groups_json=$(curl -s -X GET "${AUTH_SERVICE_URL}/auth/groups" -H "Authorization: Bearer $token")
    local group_id=$(echo "$groups_json" | jq -r ".[] | select(.name == \"$name\") | .id" 2>/dev/null)
    echo "$group_id"
}

# Helper to get user ID by email from stored user IDs
get_user_id_by_email() {
    local email="$1"
    local user_count=$(parse_yaml "$SETUP_FILE" '.users | length')
    
    for ((i=0; i<$user_count; i++)); do
        local stored_email=$(parse_yaml "$SETUP_FILE" ".users[$i].id")
        if [[ "$stored_email" == "$email" ]]; then
            # Get the stored user ID
            local user_id_var="USER_ID_${i}"
            local user_id="${!user_id_var}"
            if [[ -n "$user_id" ]]; then
                echo "$user_id"
                return 0
            fi
        fi
    done
    
    return 1
}

# Helper function to get group ID by name from auth service
get_group_id_by_name_for_delegation() {
    local token="$1"
    local group_name="$2"
    
    echo_with_color $BLUE "  🔍 Looking up group ID for delegation: $group_name" >&2
    
    local groups_json=$(curl -s -X GET "${AUTH_SERVICE_URL}/auth/groups" \
        -H "Authorization: Bearer $token")
    
    if [[ -n "$groups_json" ]]; then
        local group_id=$(echo "$groups_json" | jq -r ".[] | select(.name == \"$group_name\") | .id" 2>/dev/null)
        if [[ -n "$group_id" && "$group_id" != "null" ]]; then
            echo_with_color $GREEN "    ✅ Found group ID for delegation: ${group_id:0:8}..." >&2
            echo "$group_id"
            return 0
        else
            echo_with_color $RED "    ❌ Group not found for delegation: $group_name" >&2
            return 1
        fi
    else
        echo_with_color $RED "    ❌ Failed to retrieve groups list for delegation" >&2
        return 1
    fi
}

# Helper function to create delegation JWT token for a specific group
create_delegation_token_for_fiat() {
    local user_token="$1"
    local group_id="$2"
    local group_name="$3"
    
    echo_with_color $BLUE "  🎫 Creating delegation JWT for fiat account creation: $group_name" >&2
    echo_with_color $BLUE "    Group ID: ${group_id:0:8}..." >&2
    
    # Create delegation JWT with comprehensive scope for payments operations
    local delegation_response=$(curl -s -X POST "${AUTH_SERVICE_URL}/auth/delegation/jwt" \
        -H "Authorization: Bearer $user_token" \
        -H "Content-Type: application/json" \
        -d "{\"group_id\": \"$group_id\", \"delegation_scope\": [\"CryptoOperations\", \"ReadGroup\", \"UpdateGroup\", \"ManageGroupMembers\"], \"expiry_seconds\": 3600}")
    
    echo_with_color $BLUE "    Delegation response: $delegation_response" >&2
    
    local delegation_token=$(echo "$delegation_response" | jq -r '.delegation_jwt // .token // .delegation_token // .jwt // empty' 2>/dev/null)
    
    if [[ -n "$delegation_token" && "$delegation_token" != "null" ]]; then
        echo_with_color $GREEN "    ✅ Delegation JWT created successfully for fiat account creation" >&2
        echo "$delegation_token"
        return 0
    else
        echo_with_color $RED "    ❌ Failed to create delegation JWT for fiat account creation" >&2
        echo_with_color $YELLOW "    Response: $delegation_response" >&2
        return 1
    fi
}

# Function to login user and get JWT token (with optional group delegation for fiat accounts)
login_user_for_fiat_account() {
    local email="$1"
    local password="$2"
    local group_name="$3"  # Optional group name for delegation
    
    echo_with_color $BLUE "  🔐 Logging in user for fiat account creation: $email" >&2
    
    local services_json='["vault", "payments"]'
    local http_response=$(curl -s -X POST "${AUTH_SERVICE_URL}/auth/login/with-services" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"$email\", \"password\": \"$password\", \"services\": $services_json}")
    
    echo_with_color $BLUE "    📡 Login response: $http_response" >&2
    
    if [[ -n "$http_response" ]]; then
        local token=$(echo "$http_response" | jq -r '.token // .access_token // .jwt // empty')
        if [[ -n "$token" && "$token" != "null" ]]; then
            echo_with_color $GREEN "    ✅ Login successful for fiat account creation" >&2
            
            # If group name is specified, create delegation token
            if [[ -n "$group_name" && "$group_name" != "null" ]]; then
                echo_with_color $CYAN "  🏢 Group delegation requested for fiat account creation: $group_name" >&2
                
                # Get group ID by name
                local group_id=$(get_group_id_by_name_for_delegation "$token" "$group_name")
                if [[ $? -eq 0 && -n "$group_id" ]]; then
                    # Create delegation token
                    local delegation_token=$(create_delegation_token_for_fiat "$token" "$group_id" "$group_name")
                    if [[ $? -eq 0 && -n "$delegation_token" ]]; then
                        echo_with_color $GREEN "    ✅ Group delegation successful for fiat account creation" >&2
                        echo "$delegation_token"
                        return 0
                    else
                        echo_with_color $YELLOW "    ⚠️  Delegation failed, using regular token for fiat account creation" >&2
                        echo "$token"
                        return 0
                    fi
                else
                    echo_with_color $YELLOW "    ⚠️  Group not found, using regular token for fiat account creation" >&2
                    echo "$token"
                    return 0
                fi
            else
                echo "$token"
                return 0
            fi
        else
            echo_with_color $RED "    ❌ No token in response for fiat account creation" >&2
            return 1
        fi
    else
        echo_with_color $RED "    ❌ Login failed for fiat account creation: no response" >&2
        return 1
    fi
}

# Ensure we have a working auth token for group operations
ensure_auth_token() {
    # 1) Try logging in with the first user from setup.yaml
    local creds
    creds=$(get_first_user_credentials)
    if [[ -n "$creds" ]]; then
        local email password
        email=$(echo "$creds" | awk '{print $1}')
        password=$(echo "$creds" | awk '{print $2}')
        local token
        token=$(login_with_services "$email" "$password")
        if [[ -n "$token" && "$token" != "null" ]]; then
            echo "$token"
            return 0
        fi
    fi

    # 2) Try test token via helper script
    if [[ -x "$AUTH_SCRIPT" ]]; then
        local test_token
        test_token=$($AUTH_SCRIPT test 2>/dev/null)
        if [[ -n "$test_token" && "$test_token" != "null" ]]; then
            echo "$test_token"
            return 0
        fi
        # 3) Fallback to admin helper
        local admin_token
        admin_token=$($AUTH_SCRIPT admin 2>/dev/null)
        if [[ -n "$admin_token" && "$admin_token" != "null" ]]; then
            echo "$admin_token"
            return 0
        fi
    fi

    echo ""
    return 1
}

# Function to create user (requires admin token)
create_user() {
    local email="$1"
    local password="$2"
    local role="$3"
    local admin_token="$4"
    
    echo_with_color $BLUE "  📧 $email ($role)"
    
    local user_payload="{\"email\": \"$email\", \"password\": \"$password\", \"role\": \"$role\"}"
    
    # Get HTTP status code along with response
    local http_response=$(curl -s -w "HTTP_STATUS:%{http_code}" -X POST "${AUTH_SERVICE_URL}/auth/users" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $admin_token" \
        -d "$user_payload")
    
    local http_status=$(echo "$http_response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)
    local response_body=$(echo "$http_response" | sed 's/HTTP_STATUS:[0-9]*//')
    
    if [[ "$http_status" == "200" ]]; then
        local user_id=$(echo "$response_body" | jq -r '.user.id // .id // empty' 2>/dev/null)
        if [[ -n "$user_id" && "$user_id" != "null" ]]; then
            echo_with_color $GREEN "    ✅ Created (ID: ${user_id:0:8}...)"
            return 0
        else
            echo_with_color $RED "    ❌ Failed: invalid response"
            return 1
        fi
    elif [[ "$http_status" == "409" ]]; then
        echo_with_color $YELLOW "    ⚠️  Already exists"
        return 0
    else
        echo_with_color $RED "    ❌ Failed (HTTP $http_status)"
        return 1
    fi
}

# Function to check if user exists and return user ID
check_user_exists() {
    local email="$1"
    
    # Since there's no GET /auth/users endpoint, we need to try to get user info
    # by attempting to login and extract user ID from the response
    local login_response=$(curl -s -X POST "${AUTH_SERVICE_URL}/auth/login/with-services" \
        -H "Content-Type: application/json" \
        -d "{\"email\": \"$email\", \"password\": \"$(parse_yaml "$SETUP_FILE" ".users[] | select(.id == \"$email\") | .password")\", \"services\": [\"vault\", \"payments\"]}")
    
    if [[ -n "$login_response" ]]; then
        local user_id=$(echo "$login_response" | jq -r '.user.id // empty' 2>/dev/null)
        if [[ -n "$user_id" && "$user_id" != "null" ]]; then
            echo "$user_id"
            return 0
        fi
    fi
    
    return 1
}

# Function to create initial users (without admin token)
create_initial_users() {
    echo_with_color $CYAN "👥 Creating initial users from $(basename "$SETUP_FILE")..."
    
    local success_count=0
    local total_count=0
    
    # Get user count
    local user_count=$(parse_yaml "$SETUP_FILE" '.users | length')
    
    for ((i=0; i<$user_count; i++)); do
        local email=$(parse_yaml "$SETUP_FILE" ".users[$i].id")
        local password=$(parse_yaml "$SETUP_FILE" ".users[$i].password")
        local role=$(parse_yaml "$SETUP_FILE" ".users[$i].role")
        
        if [[ -n "$email" && -n "$password" && -n "$role" ]]; then
            total_count=$((total_count + 1))
            
            # Check if user already exists
            local existing_user_id=$(check_user_exists "$email")
            if [[ -n "$existing_user_id" ]]; then
                echo_with_color $YELLOW "  📧 $email - ⚠️  Already exists (ID: ${existing_user_id:0:8}...)"
                # Store user ID for later use
                eval "USER_ID_${i}=\"$existing_user_id\""
                if print_user_account_address "$existing_user_id" "$email" "$password"; then
                    success_count=$((success_count + 1))
                else
                    echo_with_color $RED "  📧 $email - ❌ Account activation did not become ready"
                fi
                continue
            fi
            
            # Create user without admin token (direct API call)
            local user_payload="{\"email\": \"$email\", \"password\": \"$password\", \"role\": \"$role\"}"
            
            # Add a small delay to prevent race conditions
            sleep 1
            
            # Get HTTP status code along with response
            local http_response=$(curl -s -w "HTTP_STATUS:%{http_code}" -X POST "${AUTH_SERVICE_URL}/auth/users" \
                -H "Content-Type: application/json" \
                -d "$user_payload")
            
            local http_status=$(echo "$http_response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)
            local response_body=$(echo "$http_response" | sed 's/HTTP_STATUS:[0-9]*//')
            
            if [[ "$http_status" == "200" ]]; then
                local user_id=$(echo "$response_body" | jq -r '.user.id // .id // empty' 2>/dev/null)
                if [[ -n "$user_id" && "$user_id" != "null" ]]; then
                    echo_with_color $GREEN "  📧 $email - ✅ Created (ID: ${user_id:0:8}...)"
                    # Store user ID for later use
                    eval "USER_ID_${i}=\"$user_id\""
                    # Wait a moment for the user to be fully registered
                    sleep 2
                    # Explicitly activate the setup chain and print the account address.
                    if print_user_account_address "$user_id" "$email" "$password"; then
                        success_count=$((success_count + 1))
                    else
                        echo_with_color $RED "  📧 $email - ❌ Account activation did not become ready"
                    fi
                else
                    echo_with_color $RED "  📧 $email - ❌ Failed: invalid response"
                fi
            elif [[ "$http_status" == "409" ]]; then
                echo_with_color $YELLOW "  📧 $email - ⚠️  Already exists"
                success_count=$((success_count + 1))
            else
                echo_with_color $RED "  📧 $email - ❌ Failed (HTTP $http_status)"
            fi
        else
            echo_with_color $RED "  ❌ Invalid user data at index $i"
        fi
    done
    
    echo_with_color $GREEN "✅ Users setup completed: $success_count/$total_count successful"
    return $((success_count == total_count ? 0 : 1))
}

# Function to create group
create_group() {
    local group_id="$1"
    local name="$2"
    local description="$3"
    local group_type="$4"
    local creator_token="$5"
    
    echo_with_color $BLUE "  🏢 $name ($group_type)"
    
    local group_payload="{\"name\": \"$name\", \"description\": \"$description\", \"group_type\": \"$group_type\"}"
    
    # Get HTTP status code along with response
    local http_response=$(curl -s -w "HTTP_STATUS:%{http_code}" -X POST "${AUTH_SERVICE_URL}/auth/groups" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $creator_token" \
        -d "$group_payload")
    
    local http_status=$(echo "$http_response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)
    local response_body=$(echo "$http_response" | sed 's/HTTP_STATUS:[0-9]*//')
    
    if [[ "$http_status" == "200" || "$http_status" == "202" ]]; then
        local created_group_id=$(echo "$response_body" | jq -r '.id // empty' 2>/dev/null)
        if [[ -n "$created_group_id" && "$created_group_id" != "null" ]]; then
            echo_with_color $GREEN "    ✅ Created (ID: ${created_group_id:0:8}...)"
            if ! deploy_group_account_if_needed "$created_group_id" "$creator_token"; then
                return 1
            fi
            print_group_account_address "$created_group_id" "$creator_token"
            return 0
        else
            echo_with_color $RED "    ❌ Failed: invalid response"
            return 1
        fi
    elif [[ "$http_status" == "409" ]]; then
        echo_with_color $YELLOW "    ⚠️  Already exists"
        local existing_gid=$(get_group_id_by_name_for_delegation "$creator_token" "$name")
        if [[ -n "$existing_gid" && "$existing_gid" != "null" ]]; then
            if ! deploy_group_account_if_needed "$existing_gid" "$creator_token"; then
                return 1
            fi
            print_group_account_address "$existing_gid" "$creator_token"
        fi
        return 0
    else
        echo_with_color $RED "    ❌ Failed (HTTP $http_status)"
        return 1
    fi
}

# Function to check if user is already a member of a group
check_user_in_group() {
    local group_id="$1"
    local user_email="$2"
    local admin_token="$3"
    
    # Get the user ID
    local user_id
    user_id=$(get_user_id_by_email "$user_email")
    
    if [[ -z "$user_id" ]]; then
        return 1
    fi
    
    # Check if user is already a member
    local http_response=$(curl -s -w "HTTP_STATUS:%{http_code}" -X GET "${AUTH_SERVICE_URL}/auth/groups/$group_id/members" \
        -H "Authorization: Bearer $admin_token")
    
    local http_status=$(echo "$http_response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)
    local members_response=$(echo "$http_response" | sed 's/HTTP_STATUS:[0-9]*//')
    
    if [[ "$http_status" == "200" && -n "$members_response" ]]; then
        local is_member=$(echo "$members_response" | jq -r ".[] | select(.user_id == \"$user_id\") | .user_id" 2>/dev/null)
        if [[ -n "$is_member" && "$is_member" != "null" ]]; then
            return 0  # User is already a member
        fi
    fi
    
    return 1  # User is not a member
}

# Function to add user to group with specified role
add_user_to_group() {
    local group_id="$1"
    local user_email="$2"
    local role="$3"
    local admin_token="$4"
    
    # Validate role
    case "$role" in
        "owner"|"admin"|"member"|"viewer")
            ;;
        *)
            echo_with_color $RED "❌ Invalid role: '$role'. Must be one of: owner, admin, member, viewer"
            return 1
            ;;
    esac
    
    # Check if user is already a member
    if check_user_in_group "$group_id" "$user_email" "$admin_token"; then
        echo_with_color $YELLOW "    ⚠️  Already a member"
        return 0
    fi
    
    # Get the user ID from stored user IDs (since there's no GET /auth/users endpoint)
    local user_id
    user_id=$(get_user_id_by_email "$user_email")
    
    if [[ -z "$user_id" ]]; then
        echo_with_color $RED "    ❌ User not found in stored user IDs: $user_email"
        return 1
    fi
    
    # Add user to group with the specified role
    local member_payload="{\"user_id\": \"$user_id\", \"role\": \"$role\"}"
    
    # Get HTTP status code along with response
    local http_response=$(curl -s -w "HTTP_STATUS:%{http_code}" -X POST "${AUTH_SERVICE_URL}/auth/groups/$group_id/members" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $admin_token" \
        -d "$member_payload")
    
    local http_status=$(echo "$http_response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)
    local response_body=$(echo "$http_response" | sed 's/HTTP_STATUS:[0-9]*//')
    
    if [[ "$http_status" == "200" ]]; then
        echo_with_color $GREEN "    ✅ Added as $role"
        return 0
    elif [[ "$http_status" == "409" ]]; then
        echo_with_color $YELLOW "    ⚠️  Already a member"
        return 0
    else
        echo_with_color $RED "    ❌ Failed to add (HTTP $http_status)"
        echo_with_color $YELLOW "    Response: $response_body"
        return 1
    fi
}

# Function to create token
create_token() {
    local token_id="$1"
    local name="$2"
    local description="$3"
    local token_id_param="$4"
    local chain_id="$5"
    local address="$6"
    local admin_token="$7"
    
    echo_with_color $BLUE "  🪙 $name ($token_id)"
    
    # Create token using GraphQL API with input object
    local create_token_query="{\"query\": \"mutation { tokenFlow { createToken(input: { chainId: \\\"$chain_id\\\", address: \\\"$address\\\", tokenId: \\\"$token_id_param\\\", name: \\\"$name\\\", description: \\\"$description\\\" }) { success message token { id chainId address } transactionId signature timestamp } } }\"}"
    
    local response=$(curl -s -X POST "${PAY_SERVICE_URL}/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $admin_token" \
        -d "$create_token_query")
    
    if [[ -n "$response" ]]; then
        # Check if token was created successfully
        local success=$(echo "$response" | jq -r '.data.tokenFlow.createToken.success // false' 2>/dev/null)
        if [[ "$success" == "true" ]]; then
            local created_token_id=$(echo "$response" | jq -r '.data.tokenFlow.createToken.token.id // empty' 2>/dev/null)
            local message=$(echo "$response" | jq -r '.data.tokenFlow.createToken.message // empty' 2>/dev/null)
            if [[ -n "$created_token_id" && "$created_token_id" != "null" ]]; then
                echo_with_color $GREEN "    ✅ Created (ID: ${created_token_id:0:8}...) - $message"
                return 0
            else
                echo_with_color $GREEN "    ✅ Created - $message"
                return 0
            fi
        else
            # Check for errors
            local error_msg=$(echo "$response" | jq -r '.errors[0].message // empty' 2>/dev/null)
            if [[ -n "$error_msg" ]]; then
                if [[ "$error_msg" == *"already exists"* ]]; then
                    echo_with_color $YELLOW "    ⚠️  Already exists"
                    return 0
                else
                    echo_with_color $RED "    ❌ Failed: $(echo "$error_msg" | head -c 50)..."
                    return 1
                fi
            else
                echo_with_color $RED "    ❌ Failed: unknown error"
                return 1
            fi
        fi
    else
        echo_with_color $RED "    ❌ Failed: no response"
        return 1
    fi
}

# Function to create asset
create_asset() {
    local asset_id="$1"
    local name="$2"
    local asset_type="$3"
    local currency="$4"
    local description="$5"
    local token_id="$6"
    local admin_token="$7"
    
    echo_with_color $BLUE "  💎 $name ($asset_id)"
    
    # Create asset using GraphQL API with input object
    local create_asset_query="{\"query\": \"mutation { assetFlow { createAsset(input: { name: \\\"$name\\\", description: \\\"$description\\\", assetType: \\\"$asset_type\\\", currency: \\\"$currency\\\", tokenId: \\\"$token_id\\\" }) { success message asset { id name description assetType currency tokenId obligorId createdAt deleted transactionId } transactionId signature timestamp } } }\"}"
    
    local response=$(curl -s -X POST "${PAY_SERVICE_URL}/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $admin_token" \
        -d "$create_asset_query")
    
    if [[ -n "$response" ]]; then
        # Check if asset was created successfully
        local success=$(echo "$response" | jq -r '.data.assetFlow.createAsset.success // false' 2>/dev/null)
        if [[ "$success" == "true" ]]; then
            local created_asset_id=$(echo "$response" | jq -r '.data.assetFlow.createAsset.asset.id // empty' 2>/dev/null)
            local message=$(echo "$response" | jq -r '.data.assetFlow.createAsset.message // empty' 2>/dev/null)
            if [[ -n "$created_asset_id" && "$created_asset_id" != "null" ]]; then
                echo_with_color $GREEN "    ✅ Created (ID: ${created_asset_id:0:8}...) - $message"
                return 0
            else
                echo_with_color $GREEN "    ✅ Created - $message"
                return 0
            fi
        else
            # Check for errors
            local error_msg=$(echo "$response" | jq -r '.errors[0].message // empty' 2>/dev/null)
            if [[ -n "$error_msg" ]]; then
                if [[ "$error_msg" == *"already exists"* ]]; then
                    echo_with_color $YELLOW "    ⚠️  Already exists"
                    return 0
                else
                    echo_with_color $RED "    ❌ Failed: $(echo "$error_msg" | head -c 50)..."
                    return 1
                fi
            else
                echo_with_color $RED "    ❌ Failed: unknown error"
                return 1
            fi
        fi
    else
        echo_with_color $RED "    ❌ Failed: no response"
        return 1
    fi
}

# Function to create US bank account
create_us_bank_account() {
    local account_id="$1"
    local asset_id="$2"
    local country="$3"
    local currency="$4"
    local account_holder_name="$5"
    local iban="$6"
    local routing_number="$7"
    local account_number="$8"
    local admin_token="$9"
    local user_email="${10}"  # Optional user email for delegation
    local user_password="${11}"  # Optional user password for delegation
    local group_name="${12}"  # Optional group name for delegation
    
    echo_with_color $BLUE "  🏦 US Bank Account: $account_holder_name ($account_id)"
    
    # Determine which token to use - delegation if group specified, otherwise admin token
    local effective_token="$admin_token"
    if [[ -n "$user_email" && -n "$user_password" && -n "$group_name" ]]; then
        echo_with_color $CYAN "  🏢 Using delegation JWT for group: $group_name"
        effective_token=$(login_user_for_fiat_account "$user_email" "$user_password" "$group_name")
        if [[ -z "$effective_token" ]]; then
            echo_with_color $YELLOW "  ⚠️  Delegation failed, falling back to admin token"
            effective_token="$admin_token"
        fi
    fi
    
    # Create US bank account using GraphQL API
    local create_fiat_account_query="{\"query\": \"mutation { fiatAccountFlow { createUsBankAccount(input: { accountId: \\\"$account_id\\\", assetId: \\\"$asset_id\\\", country: \\\"$country\\\", currency: \\\"$currency\\\", accountHolderName: \\\"$account_holder_name\\\", iban: \\\"$iban\\\", status: ACTIVE, routingNumber: \\\"$routing_number\\\", accountNumber: \\\"$account_number\\\" }) { success message bankAccount { id assetId country currency accountHolderName iban status } transactionId signature timestamp } } }\"}"
    
    local response=$(curl -s -X POST "${PAY_SERVICE_URL}/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $effective_token" \
        -d "$create_fiat_account_query")
    
    if [[ -n "$response" ]]; then
        # Check if fiat account was created successfully
        local success=$(echo "$response" | jq -r '.data.fiatAccountFlow.createUsBankAccount.success // false' 2>/dev/null)
        if [[ "$success" == "true" ]]; then
            local created_account_id=$(echo "$response" | jq -r '.data.fiatAccountFlow.createUsBankAccount.bankAccount.id // empty' 2>/dev/null)
            local message=$(echo "$response" | jq -r '.data.fiatAccountFlow.createUsBankAccount.message // empty' 2>/dev/null)
            if [[ -n "$created_account_id" && "$created_account_id" != "null" ]]; then
                echo_with_color $GREEN "    ✅ Created (ID: ${created_account_id:0:8}...) - $message"
                return 0
            else
                echo_with_color $GREEN "    ✅ Created - $message"
                return 0
            fi
        else
            # Check for errors
            local error_msg=$(echo "$response" | jq -r '.errors[0].message // empty' 2>/dev/null)
            if [[ -n "$error_msg" ]]; then
                if [[ "$error_msg" == *"already exists"* ]]; then
                    echo_with_color $YELLOW "    ⚠️  Already exists"
                    return 0
                else
                    echo_with_color $RED "    ❌ Failed: $(echo "$error_msg" | head -c 50)..."
                    return 1
                fi
            else
                echo_with_color $RED "    ❌ Failed: unknown error"
                return 1
            fi
        fi
    else
        echo_with_color $RED "    ❌ Failed: no response"
        return 1
    fi
}

# Function to create UK bank account
create_uk_bank_account() {
    local account_id="$1"
    local asset_id="$2"
    local country="$3"
    local currency="$4"
    local account_holder_name="$5"
    local iban="$6"
    local sort_code="$7"
    local account_number="$8"
    local admin_token="$9"
    local user_email="${10}"  # Optional user email for delegation
    local user_password="${11}"  # Optional user password for delegation
    local group_name="${12}"  # Optional group name for delegation
    
    echo_with_color $BLUE "  🏦 UK Bank Account: $account_holder_name ($account_id)"
    
    # Determine which token to use - delegation if group specified, otherwise admin token
    local effective_token="$admin_token"
    if [[ -n "$user_email" && -n "$user_password" && -n "$group_name" ]]; then
        echo_with_color $CYAN "  🏢 Using delegation JWT for group: $group_name"
        effective_token=$(login_user_for_fiat_account "$user_email" "$user_password" "$group_name")
        if [[ -z "$effective_token" ]]; then
            echo_with_color $YELLOW "  ⚠️  Delegation failed, falling back to admin token"
            effective_token="$admin_token"
        fi
    fi
    
    # Create UK bank account using GraphQL API
    local create_fiat_account_query="{\"query\": \"mutation { fiatAccountFlow { createUkBankAccount(input: { accountId: \\\"$account_id\\\", assetId: \\\"$asset_id\\\", country: \\\"$country\\\", currency: \\\"$currency\\\", accountHolderName: \\\"$account_holder_name\\\", iban: \\\"$iban\\\", status: ACTIVE, sortCode: \\\"$sort_code\\\", accountNumber: \\\"$account_number\\\" }) { success message bankAccount { id assetId country currency accountHolderName iban status } transactionId signature timestamp } } }\"}"
    
    local response=$(curl -s -X POST "${PAY_SERVICE_URL}/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $effective_token" \
        -d "$create_fiat_account_query")
    
    if [[ -n "$response" ]]; then
        # Check if fiat account was created successfully
        local success=$(echo "$response" | jq -r '.data.fiatAccountFlow.createUkBankAccount.success // false' 2>/dev/null)
        if [[ "$success" == "true" ]]; then
            local created_account_id=$(echo "$response" | jq -r '.data.fiatAccountFlow.createUkBankAccount.bankAccount.id // empty' 2>/dev/null)
            local message=$(echo "$response" | jq -r '.data.fiatAccountFlow.createUkBankAccount.message // empty' 2>/dev/null)
            if [[ -n "$created_account_id" && "$created_account_id" != "null" ]]; then
                echo_with_color $GREEN "    ✅ Created (ID: ${created_account_id:0:8}...) - $message"
                return 0
            else
                echo_with_color $GREEN "    ✅ Created - $message"
                return 0
            fi
        else
            # Check for errors
            local error_msg=$(echo "$response" | jq -r '.errors[0].message // empty' 2>/dev/null)
            if [[ -n "$error_msg" ]]; then
                if [[ "$error_msg" == *"already exists"* ]]; then
                    echo_with_color $YELLOW "    ⚠️  Already exists"
                    return 0
                else
                    echo_with_color $RED "    ❌ Failed: $(echo "$error_msg" | head -c 50)..."
                    return 1
                fi
            else
                echo_with_color $RED "    ❌ Failed: unknown error"
                return 1
            fi
        fi
    else
        echo_with_color $RED "    ❌ Failed: no response"
        return 1
    fi
}

# Function to create AU bank account
create_au_bank_account() {
    local account_id="$1"
    local asset_id="$2"
    local country="$3"
    local currency="$4"
    local account_holder_name="$5"
    local iban="$6"
    local bsb="$7"
    local account_number="$8"
    local admin_token="$9"
    local user_email="${10}"  # Optional user email for delegation
    local user_password="${11}"  # Optional user password for delegation
    local group_name="${12}"  # Optional group name for delegation
    
    echo_with_color $BLUE "  🏦 AU Bank Account: $account_holder_name ($account_id)"
    
    # Determine which token to use - delegation if group specified, otherwise admin token
    local effective_token="$admin_token"
    if [[ -n "$user_email" && -n "$user_password" && -n "$group_name" ]]; then
        echo_with_color $CYAN "  🏢 Using delegation JWT for group: $group_name"
        effective_token=$(login_user_for_fiat_account "$user_email" "$user_password" "$group_name")
        if [[ -z "$effective_token" ]]; then
            echo_with_color $YELLOW "  ⚠️  Delegation failed, falling back to admin token"
            effective_token="$admin_token"
        fi
    fi
    
    # Create AU bank account using GraphQL API
    local create_fiat_account_query="{\"query\": \"mutation { fiatAccountFlow { createAuBankAccount(input: { accountId: \\\"$account_id\\\", assetId: \\\"$asset_id\\\", country: \\\"$country\\\", currency: \\\"$currency\\\", accountHolderName: \\\"$account_holder_name\\\", iban: \\\"$iban\\\", status: ACTIVE, bsb: \\\"$bsb\\\", accountNumber: \\\"$account_number\\\" }) { success message bankAccount { id assetId country currency accountHolderName iban status } transactionId signature timestamp } } }\"}"
    
    local response=$(curl -s -X POST "${PAY_SERVICE_URL}/graphql" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $effective_token" \
        -d "$create_fiat_account_query")
    
    if [[ -n "$response" ]]; then
        # Check if fiat account was created successfully
        local success=$(echo "$response" | jq -r '.data.fiatAccountFlow.createAuBankAccount.success // false' 2>/dev/null)
        if [[ "$success" == "true" ]]; then
            local created_account_id=$(echo "$response" | jq -r '.data.fiatAccountFlow.createAuBankAccount.bankAccount.id // empty' 2>/dev/null)
            local message=$(echo "$response" | jq -r '.data.fiatAccountFlow.createAuBankAccount.message // empty' 2>/dev/null)
            if [[ -n "$created_account_id" && "$created_account_id" != "null" ]]; then
                echo_with_color $GREEN "    ✅ Created (ID: ${created_account_id:0:8}...) - $message"
                return 0
            else
                echo_with_color $GREEN "    ✅ Created - $message"
                return 0
            fi
        else
            # Check for errors
            local error_msg=$(echo "$response" | jq -r '.errors[0].message // empty' 2>/dev/null)
            if [[ -n "$error_msg" ]]; then
                if [[ "$error_msg" == *"already exists"* ]]; then
                    echo_with_color $YELLOW "    ⚠️  Already exists"
                    return 0
                else
                    echo_with_color $RED "    ❌ Failed: $(echo "$error_msg" | head -c 50)..."
                    return 1
                fi
            else
                echo_with_color $RED "    ❌ Failed: unknown error"
                return 1
            fi
        fi
    else
        echo_with_color $RED "    ❌ Failed: no response"
        return 1
    fi
}





# Function to setup users (requires admin token)
setup_users() {
    echo_with_color $CYAN "Setting up users from $(basename "$SETUP_FILE")..."
    
    local admin_token="$1"
    local success_count=0
    local total_count=0
    
    # Get user count
    local user_count=$(parse_yaml "$SETUP_FILE" '.users | length')
    
    for ((i=0; i<$user_count; i++)); do
        local email=$(parse_yaml "$SETUP_FILE" ".users[$i].id")
        local password=$(parse_yaml "$SETUP_FILE" ".users[$i].password")
        local role=$(parse_yaml "$SETUP_FILE" ".users[$i].role")
        
        if [[ -n "$email" && -n "$password" && -n "$role" ]]; then
            total_count=$((total_count + 1))
            if create_user "$email" "$password" "$role" "$admin_token"; then
                local user_id
                user_id=$(check_user_exists "$email")
                if [[ -n "$user_id" ]] && print_user_account_address "$user_id" "$email" "$password"; then
                    success_count=$((success_count + 1))
                else
                    echo_with_color $RED "  ❌ $email account activation did not become ready"
                fi
            fi
        else
            echo_with_color $RED "Invalid user data at index $i"
        fi
    done
    
    echo_with_color $GREEN "Users setup completed: $success_count/$total_count successful"
    return $((success_count == total_count ? 0 : 1))
}

# Function to setup groups
setup_groups() {
    echo_with_color $CYAN "🏢 Setting up groups from $(basename "$SETUP_FILE")..."
    
    # Always use a fresh token from the first user (which has SuperAdmin role)
    echo_with_color $BLUE "🔑 Getting fresh token for group operations..."
    local effective_token
    effective_token=$(ensure_auth_token)
    if [[ -z "$effective_token" ]]; then
        echo_with_color $RED "❌ Failed to obtain a valid token for group operations"
        return 1
    fi
    
    echo_with_color $GREEN "✅ Using fresh token for group operations"
    
    local success_count=0
    local total_count=0
    
    # Get group count
    local group_count=$(parse_yaml "$SETUP_FILE" '.groups | length')
    
    for ((i=0; i<$group_count; i++)); do
        local group_id=$(parse_yaml "$SETUP_FILE" ".groups[$i].id")
        local name=$(parse_yaml "$SETUP_FILE" ".groups[$i].name")
        local description=$(parse_yaml "$SETUP_FILE" ".groups[$i].description")
        local group_type=$(parse_yaml "$SETUP_FILE" ".groups[$i].group_type")
        
        # Parse the user field to determine who should create the group
        local creator_email=$(parse_yaml "$SETUP_FILE" ".groups[$i].user.id")
        local creator_password=$(parse_yaml "$SETUP_FILE" ".groups[$i].user.password")
        
        if [[ -n "$group_id" && -n "$name" && -n "$description" && -n "$group_type" ]]; then
            total_count=$((total_count + 1))
            
            # Get token for the group creator
            local creator_token=""
            if [[ -n "$creator_email" && -n "$creator_password" ]]; then
                echo_with_color $BLUE "  🔑 Getting token for group creator: $creator_email"
                creator_token=$(login_with_services "$creator_email" "$creator_password")
                if [[ -z "$creator_token" || "$creator_token" == "null" ]]; then
                    echo_with_color $RED "  ❌ Failed to get token for group creator: $creator_email"
                    continue
                fi
                echo_with_color $GREEN "  ✅ Got token for group creator: $creator_email"
            else
                echo_with_color $YELLOW "  ⚠️  No creator specified, using admin token"
                creator_token="$effective_token"
            fi
            
            if create_group "$group_id" "$name" "$description" "$group_type" "$creator_token"; then
                success_count=$((success_count + 1))
            fi
        else
            echo_with_color $RED "  ❌ Invalid group data at index $i"
        fi
    done
    
    echo_with_color $GREEN "✅ Groups setup completed: $success_count/$total_count successful"
    return $((success_count == total_count ? 0 : 1))
}

# Explicitly activate a group account on the creator JWT's selected chain.
# POST is idempotent within a durable attempt; GET is the normal poll, while a
# periodic POST lets auth reconcile an ambiguous MQ handoff.
deploy_group_account_if_needed() {
    local group_id="$1"
    local creator_token="$2"
    local chain
    chain=$(jwt_default_chain_id "$creator_token")
    if [[ -z "$chain" || "$chain" == "null" ]]; then
        echo_with_color $RED "    ❌ Creator session has no active chain"
        return 1
    fi

    local url="${AUTH_SERVICE_URL}/entities/group/${group_id}/chain-accounts/${chain}/activation"
    local resp status addr activation_error attempt
    echo_with_color $BLUE "    🚀 Activating group account on chain ${chain}..."
    resp=$(curl -s -X POST "$url" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer ${creator_token}" \
        -d '{}')

    for ((attempt=1; attempt<=60; attempt++)); do
        status=$(echo "$resp" | jq -r '.status // empty' 2>/dev/null)
        addr=$(echo "$resp" | jq -r '.account_address // empty' 2>/dev/null)
        if [[ "$status" == "ready" && -n "$addr" && "$addr" != "null" ]]; then
            echo_with_color $GREEN "    ✅ Group account ready: ${addr}"
            return 0
        fi
        if [[ "$status" == "pending_signature" ]]; then
            echo_with_color $YELLOW "    ⚠️  Group activation awaits a wallet signature"
            return 1
        fi
        if [[ "$status" == "failed_retryable" ]]; then
            activation_error=$(echo "$resp" | jq -r '.error // "unknown error"' 2>/dev/null)
            echo_with_color $YELLOW "    ⚠️  Activation failed; retrying: ${activation_error}"
        fi
        [[ "$attempt" -ge 60 ]] && break
        sleep 2
        if [[ "$status" == "failed_retryable" || $((attempt % 3)) -eq 0 ]]; then
            resp=$(curl -s -X POST "$url" \
                -H "Content-Type: application/json" \
                -H "Authorization: Bearer ${creator_token}" \
                -d '{}')
        else
            resp=$(curl -s -X GET "$url" \
                -H "Authorization: Bearer ${creator_token}")
        fi
    done

    echo_with_color $RED "    ❌ Group activation did not become ready: ${resp}"
    return 1
}

# Function to create delegation JWT for group management
create_delegation_jwt() {
    local group_id="$1"
    local admin_token="$2"
    
    echo_with_color $BLUE "    🔑 Creating delegation JWT for group: $group_id" >&2
    
    local delegation_response=$(curl -s -X POST "${AUTH_SERVICE_URL}/auth/delegation/jwt" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $admin_token" \
        -d "{\"group_id\": \"$group_id\", \"delegation_scope\": [\"CryptoOperations\", \"ReadGroup\", \"UpdateGroup\", \"ManageGroupMembers\"], \"expiry_seconds\": 3600}")
    
    local delegation_token=$(echo "$delegation_response" | jq -r '.delegation_jwt // .token // .delegation_token // .jwt // empty' 2>/dev/null)
    
    if [[ -n "$delegation_token" && "$delegation_token" != "null" ]]; then
        echo_with_color $GREEN "    ✅ Delegation JWT created successfully" >&2
        echo "$delegation_token"
        return 0
    else
        echo_with_color $RED "    ❌ Failed to create delegation JWT" >&2
        echo_with_color $YELLOW "    Response: $delegation_response" >&2
        return 1
    fi
}

# Function to add member as owner to group account
add_member_as_owner() {
    local group_id="$1"
    local member_email="$2"
    local actor_token="$3"
    
    echo_with_color $BLUE "    🔍 Looking up user ID for: $member_email"
    
    # Get the user ID from stored user IDs
    local user_id
    user_id=$(get_user_id_by_email "$member_email")
    
    if [[ -z "$user_id" ]]; then
        echo_with_color $RED "    ❌ User not found in stored user IDs: $member_email"
        return 1
    fi
    
    echo_with_color $BLUE "    ✅ Found user ID: ${user_id:0:8}..."
    
    # Create delegation JWT for group management
    echo_with_color $BLUE "    🔍 DEBUG: About to create delegation JWT"
    local delegation_token
    delegation_token=$(create_delegation_jwt "$group_id" "$actor_token")
    local delegation_result=$?
    echo_with_color $BLUE "    🔍 DEBUG: Delegation JWT creation result: $delegation_result"
    if [[ $delegation_result -ne 0 ]]; then
        echo_with_color $RED "    ❌ Failed to create delegation JWT"
        return 1
    fi
    echo_with_color $BLUE "    🔍 DEBUG: Delegation JWT created successfully: ${delegation_token:0:50}..."
    
    local chain
    chain=$(jwt_default_chain_id "$actor_token")
    if [[ -z "$chain" || "$chain" == "null" ]]; then
        echo_with_color $RED "    ❌ Group actor session has no active chain"
        return 1
    fi
    echo_with_color $BLUE "    🔍 Checking group activation on chain $chain"

    local account_status_response=$(curl -s -X GET \
        "${AUTH_SERVICE_URL}/entities/group/${group_id}/chain-accounts/${chain}/activation" \
        -H "Authorization: Bearer $actor_token")
    
    echo_with_color $BLUE "    📥 Account status response: $account_status_response"
    
    if [[ -n "$account_status_response" ]]; then
        local account_address=$(echo "$account_status_response" | jq -r '.account_address // empty' 2>/dev/null)
        local status=$(echo "$account_status_response" | jq -r '.status // empty' 2>/dev/null)
        
        echo_with_color $BLUE "    📊 Parsed status: '$status'"
        echo_with_color $BLUE "    📊 Parsed account_address: '$account_address'"
        
        if [[ "$status" == "ready" && -n "$account_address" && "$account_address" != "null" ]]; then
            echo_with_color $BLUE "    🔑 Adding $member_email as owner to account: ${account_address:0:10}..."
            echo_with_color $BLUE "    📡 Making API call to: /auth/groups/$group_id/add-owner"
            echo_with_color $BLUE "    📦 Payload: {\"new_owner\": \"$user_id\"}"
            
            # Add the user as an owner to the group's account using delegation JWT
            local add_owner_payload="{\"new_owner\": \"$user_id\"}"
            
            local add_owner_response=$(curl -s -w "HTTP_STATUS:%{http_code}" -X POST "${AUTH_SERVICE_URL}/auth/groups/$group_id/add-owner" \
                -H "Content-Type: application/json" \
                -H "Authorization: Bearer $delegation_token" \
                -d "$add_owner_payload")
            
            local http_status=$(echo "$add_owner_response" | grep -o 'HTTP_STATUS:[0-9]*' | cut -d: -f2)
            local response_body=$(echo "$add_owner_response" | sed 's/HTTP_STATUS:[0-9]*//')
            
            echo_with_color $BLUE "    📥 Response status: $http_status"
            echo_with_color $BLUE "    📥 Response body: $response_body"
            
            if [[ "$http_status" == "200" ]]; then
                local success=$(echo "$response_body" | jq -r '.status // empty' 2>/dev/null)
                if [[ "$success" == "success" ]]; then
                    echo_with_color $GREEN "    ✅ Added as owner"
                    return 0
                else
                    echo_with_color $YELLOW "    ⚠️  Owner addition initiated"
                    return 0
                fi
            else
                echo_with_color $RED "    ❌ Failed to add owner (HTTP $http_status)"
                return 1
            fi
        else
            echo_with_color $YELLOW "    ⚠️  Group account not deployed yet, skipping owner addition"
            return 0
        fi
    else
        echo_with_color $RED "    ❌ Failed to get group account status"
        return 1
    fi
}

# Function to setup group relationships
setup_group_relationships() {
    echo_with_color $CYAN "🔗 Setting up group relationships from $(basename "$SETUP_FILE")..."
    
    # Always use a fresh token from the first user (which has SuperAdmin role)
    echo_with_color $BLUE "🔑 Getting fresh token for group operations..."
    local effective_token
    effective_token=$(ensure_auth_token)
    if [[ -z "$effective_token" ]]; then
        echo_with_color $RED "❌ Failed to obtain a valid token for group operations"
        return 1
    fi
    
    echo_with_color $GREEN "✅ Using fresh token for group operations"
    
    local success_count=0
    local total_count=0
    
    # Get group count
    local group_count=$(parse_yaml "$SETUP_FILE" '.groups | length')
    
    for ((i=0; i<$group_count; i++)); do
        local group_id=$(parse_yaml "$SETUP_FILE" ".groups[$i].id")
        local group_name=$(parse_yaml "$SETUP_FILE" ".groups[$i].name")
        
        echo_with_color $BLUE "🏢 Setting up relationships for: $group_name"
        echo_with_color $BLUE "    📋 Original group ID from YAML: '$group_id'"

        # The group creator is its initial owner. Use that same principal for
        # creation, activation, and membership changes; the bootstrap/API-key
        # token may represent a different entity.
        local creator_email=$(parse_yaml "$SETUP_FILE" ".groups[$i].user.id")
        local creator_password=$(parse_yaml "$SETUP_FILE" ".groups[$i].user.password")
        local creator_token=""
        if [[ -n "$creator_email" && -n "$creator_password" ]]; then
            echo_with_color $BLUE "    🔑 Getting token for group creator: $creator_email"
            creator_token=$(login_with_services "$creator_email" "$creator_password")
            if [[ -z "$creator_token" || "$creator_token" == "null" ]]; then
                echo_with_color $RED "    ❌ Failed to get token for group creator: $creator_email"
                continue
            fi
            echo_with_color $GREEN "    ✅ Got token for group creator: $creator_email"
        else
            echo_with_color $YELLOW "    ⚠️  No creator specified, using admin principal"
            creator_token="$effective_token"
        fi
        
        # Always resolve group id by name since YAML IDs are not UUIDs
        echo_with_color $BLUE "    🔍 Looking up group by name to get actual UUID..."
        local resolved_group_id=$(get_group_id_by_name "$effective_token" "$group_name")
        echo_with_color $BLUE "    📋 Resolved group ID by name: '$resolved_group_id'"
        if [[ -z "$resolved_group_id" || "$resolved_group_id" == "null" ]]; then
            # Attempt to create the group quickly if it doesn't exist
            local description=$(parse_yaml "$SETUP_FILE" ".groups[$i].description")
            local group_type=$(parse_yaml "$SETUP_FILE" ".groups[$i].group_type")
            if create_group "$group_id" "$group_name" "$description" "$group_type" "$creator_token"; then
                resolved_group_id=$(get_group_id_by_name "$effective_token" "$group_name")
            fi
        fi
        if [[ -z "$resolved_group_id" || "$resolved_group_id" == "null" ]]; then
            echo_with_color $RED "❌ Could not resolve group id for: $group_name"
            continue
        fi
        
        # Ensure group account is deployed before adding owners
        echo_with_color $BLUE "    🏦 Checking group account deployment for group ID: $resolved_group_id..."
        if ! deploy_group_account_if_needed "$resolved_group_id" "$creator_token"; then
            echo_with_color $RED "    ❌ Group account is not ready; skipping on-chain owner setup"
            continue
        fi
        
        # Handle members with their specific roles
        local member_count=$(parse_yaml "$SETUP_FILE" ".groups[$i].members | length" 2>/dev/null)
        if [[ -n "$member_count" && "$member_count" != "0" ]]; then
            for ((j=0; j<$member_count; j++)); do
                local member_email=$(parse_yaml "$SETUP_FILE" ".groups[$i].members[$j].id" 2>/dev/null)
                local member_role=$(parse_yaml "$SETUP_FILE" ".groups[$i].members[$j].role" 2>/dev/null)
                
                if [[ -n "$member_email" && -n "$member_role" ]]; then
                    total_count=$((total_count + 1))
                    echo_with_color $BLUE "    👤 $member_email ($member_role)"
                    if add_user_to_group "$resolved_group_id" "$member_email" "$member_role" "$creator_token"; then
                        success_count=$((success_count + 1))
                        
                        # Add member as owner to group account
                        echo_with_color $BLUE "    🔑 Adding as account owner..."
                        if add_member_as_owner "$resolved_group_id" "$member_email" "$creator_token"; then
                            echo_with_color $GREEN "    ✅ Successfully added as owner"
                        else
                            echo_with_color $YELLOW "    ⚠️  Owner addition had issues"
                        fi
                    fi
                else
                    echo_with_color $RED "    ❌ Invalid member data at index $j"
                fi
            done
        fi
    done
    
    echo_with_color $GREEN "✅ Group relationships setup completed: $success_count/$total_count successful"
    return $((success_count == total_count ? 0 : 1))
}

# Function to setup tokens
setup_tokens() {
    echo_with_color $CYAN "🪙 Setting up tokens from $(basename "$SETUP_FILE")..."
    
    # Check if token service is running
    if ! check_token_service_running; then
        echo_with_color $YELLOW "⚠️  Token service not running on port 3002, skipping token setup"
        echo_with_color $BLUE "   Start the token service first: cd ../yieldfabric-services && cargo run"
        return 0
    fi
    
    # Get admin token for token operations
    echo_with_color $BLUE "🔑 Getting admin token for token operations..."
    local admin_token
    admin_token=$(ensure_auth_token)
    if [[ -z "$admin_token" ]]; then
        echo_with_color $RED "❌ Failed to obtain a valid token for token operations"
        return 1
    fi
    
    echo_with_color $GREEN "✅ Using admin token for token operations"
    
    local success_count=0
    local total_count=0
    
    # Get token count
    local token_count=$(parse_yaml "$SETUP_FILE" '.tokens | length' 2>/dev/null)
    
    if [[ -z "$token_count" || "$token_count" == "0" ]]; then
        echo_with_color $YELLOW "⚠️  No tokens defined in $(basename "$SETUP_FILE"), skipping token setup"
        return 0
    fi
    
            for ((i=0; i<$token_count; i++)); do
            local token_id=$(parse_yaml "$SETUP_FILE" ".tokens[$i].id" 2>/dev/null)
            local name=$(parse_yaml "$SETUP_FILE" ".tokens[$i].name" 2>/dev/null)
            local description=$(parse_yaml "$SETUP_FILE" ".tokens[$i].description" 2>/dev/null)
            local chain_id=$(parse_yaml "$SETUP_FILE" ".tokens[$i].chain_id" 2>/dev/null)
            local address=$(parse_yaml "$SETUP_FILE" ".tokens[$i].address" 2>/dev/null)
            
            if [[ -n "$token_id" && -n "$name" && -n "$description" && -n "$chain_id" && -n "$address" ]]; then
                total_count=$((total_count + 1))
                if create_token "$token_id" "$name" "$description" "$token_id" "$chain_id" "$address" "$admin_token"; then
                    success_count=$((success_count + 1))
                fi
            else
                echo_with_color $RED "  ❌ Invalid token data at index $i"
            fi
        done
    
    echo_with_color $GREEN "✅ Tokens setup completed: $success_count/$total_count successful"
    return $((success_count == total_count ? 0 : 1))
}

# Function to setup assets
setup_assets() {
    echo_with_color $CYAN "💎 Setting up assets from $(basename "$SETUP_FILE")..."
    
    # Check if payment service is running (where asset GraphQL is available)
    if ! check_token_service_running; then
        echo_with_color $YELLOW "⚠️  Payment service not running on port 3002, skipping asset setup"
        echo_with_color $BLUE "   Start the payment service first: cd ../yieldfabric-payments && cargo run"
        return 0
    fi
    
    # Get admin token for asset operations
    echo_with_color $BLUE "🔑 Getting admin token for asset operations..."
    local admin_token
    admin_token=$(ensure_auth_token)
    if [[ -z "$admin_token" ]]; then
        echo_with_color $RED "❌ Failed to obtain a valid token for asset operations"
        return 1
    fi
    
    echo_with_color $GREEN "✅ Using admin token for asset operations"
    
    local success_count=0
    local total_count=0
    
    # Get asset count
    local asset_count=$(parse_yaml "$SETUP_FILE" '.assets | length' 2>/dev/null)
    
    if [[ -z "$asset_count" || "$asset_count" == "0" ]]; then
        echo_with_color $YELLOW "⚠️  No assets defined in $(basename "$SETUP_FILE"), skipping asset setup"
        return 0
    fi
    
    for ((i=0; i<$asset_count; i++)); do
        local asset_id=$(parse_yaml "$SETUP_FILE" ".assets[$i].id" 2>/dev/null)
        local name=$(parse_yaml "$SETUP_FILE" ".assets[$i].name" 2>/dev/null)
        local asset_type=$(parse_yaml "$SETUP_FILE" ".assets[$i].type" 2>/dev/null)
        local currency=$(parse_yaml "$SETUP_FILE" ".assets[$i].currency" 2>/dev/null)
        local description=$(parse_yaml "$SETUP_FILE" ".assets[$i].description" 2>/dev/null)
        local token_id=$(parse_yaml "$SETUP_FILE" ".assets[$i].token_id" 2>/dev/null)
        
        # Convert asset type to uppercase as expected by the GraphQL API
        asset_type=$(echo "$asset_type" | tr '[:lower:]' '[:upper:]')
        
        if [[ -n "$asset_id" && -n "$name" && -n "$asset_type" && -n "$currency" && -n "$description" && -n "$token_id" ]]; then
            total_count=$((total_count + 1))
            if create_asset "$asset_id" "$name" "$asset_type" "$currency" "$description" "$token_id" "$admin_token"; then
                success_count=$((success_count + 1))
            fi
        else
            echo_with_color $RED "  ❌ Invalid asset data at index $i"
            echo_with_color $YELLOW "     Required: id, name, type, currency, description, token_id"
        fi
    done
    
    echo_with_color $GREEN "✅ Assets setup completed: $success_count/$total_count successful"
    return $((success_count == total_count ? 0 : 1))
}

# Function to setup fiat accounts
setup_fiat_accounts() {
    echo_with_color $CYAN "🏦 Setting up fiat accounts from $(basename "$SETUP_FILE")..."
    
    # Check if payment service is running (where fiat account GraphQL is available)
    if ! check_token_service_running; then
        echo_with_color $YELLOW "⚠️  Payment service not running on port 3002, skipping fiat account setup"
        echo_with_color $BLUE "   Start the payment service first: cd ../yieldfabric-payments && cargo run"
        return 0
    fi
    
    # Get admin token for fiat account operations
    echo_with_color $BLUE "🔑 Getting admin token for fiat account operations..."
    local admin_token
    admin_token=$(ensure_auth_token)
    if [[ -z "$admin_token" ]]; then
        echo_with_color $RED "❌ Failed to obtain a valid token for fiat account operations"
        return 1
    fi
    
    echo_with_color $GREEN "✅ Using admin token for fiat account operations"
    
    local success_count=0
    local total_count=0
    
    # Get fiat account count
    local fiat_account_count=$(parse_yaml "$SETUP_FILE" '.fiat_accounts | length' 2>/dev/null)
    
    if [[ -z "$fiat_account_count" || "$fiat_account_count" == "0" ]]; then
        echo_with_color $YELLOW "⚠️  No fiat accounts defined in $(basename "$SETUP_FILE"), skipping fiat account setup"
        return 0
    fi
    
    for ((i=0; i<$fiat_account_count; i++)); do
        local account_id=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].id" 2>/dev/null)
        local asset_id=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].asset" 2>/dev/null)
        local holder=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].holder" 2>/dev/null)
        local iban=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].iban" 2>/dev/null)
        local currency=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].currency" 2>/dev/null)
        
        # Get user information for delegation
        local user_email=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].user.id" 2>/dev/null)
        local user_password=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].user.password" 2>/dev/null)
        local group_name=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].user.group" 2>/dev/null)
        
        # Get country-specific fields
        local routing_number=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].routing_number" 2>/dev/null)
        local sort_code=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].sort_code" 2>/dev/null)
        local bsb=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].bsb" 2>/dev/null)
        local account_number=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].account_number" 2>/dev/null)
        
        # Set default if not specified
        if [[ -z "$currency" ]]; then
            currency="AUD"  # Default to Australian Dollar
        fi
        
        if [[ -n "$account_id" && -n "$asset_id" && -n "$holder" && -n "$iban" && -n "$account_number" ]]; then
            total_count=$((total_count + 1))
            
            # Determine account type based on currency only
            local account_type=""
            if [[ "$currency" == "USD" ]]; then
                account_type="US"
            elif [[ "$currency" == "GBP" ]]; then
                account_type="UK"
            elif [[ "$currency" == "AUD" ]]; then
                account_type="AU"
            else
                # Default to AU if unclear
                account_type="AU"
            fi
            
            # Log delegation context if group is specified
            if [[ -n "$group_name" ]]; then
                echo_with_color $CYAN "  🏢 Creating fiat account with group delegation: $group_name"
            fi
            
            # Create account based on determined type
            case "$account_type" in
                "US")
                    if [[ -n "$routing_number" ]]; then
                        if create_us_bank_account "$account_id" "$asset_id" "US" "$currency" "$holder" "$iban" "$routing_number" "$account_number" "$admin_token" "$user_email" "$user_password" "$group_name"; then
                            success_count=$((success_count + 1))
                        fi
                    else
                        echo_with_color $RED "  ❌ US account '$account_id' missing routing_number"
                    fi
                    ;;
                "UK")
                    if [[ -n "$sort_code" ]]; then
                        if create_uk_bank_account "$account_id" "$asset_id" "UK" "$currency" "$holder" "$iban" "$sort_code" "$account_number" "$admin_token" "$user_email" "$user_password" "$group_name"; then
                            success_count=$((success_count + 1))
                        fi
                    else
                        echo_with_color $RED "  ❌ UK account '$account_id' missing sort_code"
                    fi
                    ;;
                "AU")
                    if [[ -n "$bsb" ]]; then
                        if create_au_bank_account "$account_id" "$asset_id" "AU" "$currency" "$holder" "$iban" "$bsb" "$account_number" "$admin_token" "$user_email" "$user_password" "$group_name"; then
                            success_count=$((success_count + 1))
                        fi
                    else
                        echo_with_color $RED "  ❌ AU account '$account_id' missing bsb"
                    fi
                    ;;
            esac
        else
            echo_with_color $RED "  ❌ Invalid fiat account data at index $i"
            echo_with_color $YELLOW "     Required: id, asset, holder, iban, account_number"
        fi
    done
    
    echo_with_color $GREEN "✅ Fiat accounts setup completed: $success_count/$total_count successful"
    return $((success_count == total_count ? 0 : 1))
}

# Function to validate setup.yaml
validate_setup_file() {
    echo_with_color $CYAN "Validating $(basename "$SETUP_FILE")..."
    
    if [[ ! -f "$SETUP_FILE" ]]; then
        echo_with_color $RED "Setup file not found: $SETUP_FILE"
        return 1
    fi
    
    if ! check_yq_available; then
        echo_with_color $RED "yq is required for YAML validation"
        return 1
    fi
    
    # Basic structure validation
    local has_users=$(parse_yaml "$SETUP_FILE" '.users | length > 0')
    local has_groups=$(parse_yaml "$SETUP_FILE" '.groups | length > 0')
    
    if [[ "$has_users" != "true" ]]; then
        echo_with_color $RED "No users defined in $(basename "$SETUP_FILE")"
        return 1
    fi
    
    # if [[ "$has_groups" != "true" ]]; then
    #     echo_with_color $RED "No groups defined in setup.yaml"
    #     return 1
    # fi
    
    # Validate group member structure
    local group_count=$(parse_yaml "$SETUP_FILE" '.groups | length')
    for ((i=0; i<$group_count; i++)); do
        local group_name=$(parse_yaml "$SETUP_FILE" ".groups[$i].name")
        local member_count=$(parse_yaml "$SETUP_FILE" ".groups[$i].members | length" 2>/dev/null)
        
        if [[ -z "$member_count" || "$member_count" == "0" ]]; then
            echo_with_color $YELLOW "Warning: Group '$group_name' has no members defined"
        else
            # Validate each member has required fields
            for ((j=0; j<$member_count; j++)); do
                local member_id=$(parse_yaml "$SETUP_FILE" ".groups[$i].members[$j].id" 2>/dev/null)
                local member_role=$(parse_yaml "$SETUP_FILE" ".groups[$i].members[$j].role" 2>/dev/null)
                
                if [[ -z "$member_id" ]]; then
                    echo_with_color $RED "Error: Group '$group_name' member $j missing 'id' field"
                    return 1
                fi
                
                if [[ -z "$member_role" ]]; then
                    echo_with_color $RED "Error: Group '$group_name' member $j missing 'role' field"
                    return 1
                fi
                
                # Validate role values
                case "$member_role" in
                    "owner"|"admin"|"member"|"viewer")
                        ;;
                    *)
                        echo_with_color $RED "Error: Group '$group_name' member '$member_id' has invalid role: '$member_role'"
                        echo_with_color $YELLOW "Valid roles are: owner, admin, member, viewer"
                        return 1
                        ;;
                esac
            done
        fi
    done
    
    # Validate token structure
    local token_count=$(parse_yaml "$SETUP_FILE" '.tokens | length' 2>/dev/null)
    if [[ -n "$token_count" && "$token_count" != "0" ]]; then
        for ((i=0; i<$token_count; i++)); do
            local token_id=$(parse_yaml "$SETUP_FILE" ".tokens[$i].id" 2>/dev/null)
            local name=$(parse_yaml "$SETUP_FILE" ".tokens[$i].name" 2>/dev/null)
            local description=$(parse_yaml "$SETUP_FILE" ".tokens[$i].description" 2>/dev/null)
            local chain_id=$(parse_yaml "$SETUP_FILE" ".tokens[$i].chain_id" 2>/dev/null)
            local address=$(parse_yaml "$SETUP_FILE" ".tokens[$i].address" 2>/dev/null)
            
            if [[ -z "$token_id" ]]; then
                echo_with_color $RED "Error: Token $i missing 'id' field"
                return 1
            fi
            
            if [[ -z "$name" ]]; then
                echo_with_color $RED "Error: Token '$token_id' missing 'name' field"
                return 1
            fi
            
            if [[ -z "$description" ]]; then
                echo_with_color $RED "Error: Token '$token_id' missing 'description' field"
                return 1
            fi
            
            if [[ -z "$chain_id" ]]; then
                echo_with_color $RED "Error: Token '$token_id' missing 'chain_id' field"
                return 1
            fi
            
            if [[ -z "$address" ]]; then
                echo_with_color $RED "Error: Token '$token_id' missing 'address' field"
                return 1
            fi
            
            # Validate address format (basic Ethereum address check)
            if [[ ! "$address" =~ ^0x[a-fA-F0-9]{40}$ ]]; then
                echo_with_color $RED "Error: Token '$token_id' has invalid address format: '$address'"
                echo_with_color $YELLOW "Address must be a valid Ethereum address (0x followed by 40 hex characters)"
                return 1
            fi
        done
    fi
    
    # Validate asset structure
    local asset_count=$(parse_yaml "$SETUP_FILE" '.assets | length' 2>/dev/null)
    if [[ -n "$asset_count" && "$asset_count" != "0" ]]; then
        for ((i=0; i<$asset_count; i++)); do
            local asset_id=$(parse_yaml "$SETUP_FILE" ".assets[$i].id" 2>/dev/null)
            local name=$(parse_yaml "$SETUP_FILE" ".assets[$i].name" 2>/dev/null)
            local asset_type=$(parse_yaml "$SETUP_FILE" ".assets[$i].type" 2>/dev/null)
            local currency=$(parse_yaml "$SETUP_FILE" ".assets[$i].currency" 2>/dev/null)
            local description=$(parse_yaml "$SETUP_FILE" ".assets[$i].description" 2>/dev/null)
            local token_id=$(parse_yaml "$SETUP_FILE" ".assets[$i].token_id" 2>/dev/null)
            
            if [[ -z "$asset_id" ]]; then
                echo_with_color $RED "Error: Asset $i missing 'id' field"
                return 1
            fi
            
            if [[ -z "$name" ]]; then
                echo_with_color $RED "Error: Asset '$asset_id' missing 'name' field"
                return 1
            fi
            
            if [[ -z "$asset_type" ]]; then
                echo_with_color $RED "Error: Asset '$asset_id' missing 'type' field"
                return 1
            fi
            
            if [[ -z "$currency" ]]; then
                echo_with_color $RED "Error: Asset '$asset_id' missing 'currency' field"
                return 1
            fi
            
            if [[ -z "$description" ]]; then
                echo_with_color $RED "Error: Asset '$asset_id' missing 'description' field"
                return 1
            fi
            
            if [[ -z "$token_id" ]]; then
                echo_with_color $RED "Error: Asset '$asset_id' missing 'token_id' field"
                return 1
            fi
            
            # Validate asset type against known types (case-insensitive)
            asset_type_upper=$(echo "$asset_type" | tr '[:lower:]' '[:upper:]')
            case "$asset_type_upper" in
                "CASH"|"TOKEN"|"INVOICE"|"FACTORING_AGREEMENT"|"ESCROW_ACCOUNT"|"PAYABLE"|"RECEIVABLE")
                    ;;
                *)
                    echo_with_color $RED "Error: Asset '$asset_id' has invalid type: '$asset_type'"
                    echo_with_color $YELLOW "Valid types are: Cash, Token, Invoice, Factoring_Agreement, Escrow_Account, Payable, Receivable"
                    return 1
                    ;;
            esac
            
            # Validate currency format (basic check for 3-letter currency codes)
            if [[ ! "$currency" =~ ^[A-Z]{3}$ ]]; then
                echo_with_color $YELLOW "Warning: Asset '$asset_id' currency '$currency' should be a 3-letter code (e.g., USD, EUR, AUD)"
            fi
        done
    fi
    
    # Validate fiat account structure
    local fiat_account_count=$(parse_yaml "$SETUP_FILE" '.fiat_accounts | length' 2>/dev/null)
    if [[ -n "$fiat_account_count" && "$fiat_account_count" != "0" ]]; then
        for ((i=0; i<$fiat_account_count; i++)); do
            local account_id=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].id" 2>/dev/null)
            local holder=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].holder" 2>/dev/null)
            local iban=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].iban" 2>/dev/null)
            local account_number=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].account_number" 2>/dev/null)
            
            # Check for country-specific fields
            local routing_number=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].routing_number" 2>/dev/null)
            local sort_code=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].sort_code" 2>/dev/null)
            local bsb=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].bsb" 2>/dev/null)
            
            if [[ -z "$account_id" ]]; then
                echo_with_color $RED "Error: Fiat account $i missing 'id' field"
                return 1
            fi
            
            if [[ -z "$holder" ]]; then
                echo_with_color $RED "Error: Fiat account '$account_id' missing 'holder' field"
                return 1
            fi
            
            if [[ -z "$iban" ]]; then
                echo_with_color $RED "Error: Fiat account '$account_id' missing 'iban' field"
                return 1
            fi
            
            if [[ -z "$account_number" ]]; then
                echo_with_color $RED "Error: Fiat account '$account_id' missing 'account_number' field"
                return 1
            fi
            
            # Validate that at least one country-specific field is present
            if [[ -z "$routing_number" && -z "$sort_code" && -z "$bsb" ]]; then
                echo_with_color $RED "Error: Fiat account '$account_id' missing country-specific field"
                echo_with_color $YELLOW "Must include one of: routing_number (US), sort_code (UK), bsb (AU)"
                return 1
            fi
            
            # Determine account type based on currency only
            local currency=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].currency" 2>/dev/null)
            
            # Set default if not specified
            if [[ -z "$currency" ]]; then
                currency="AUD"  # Default to Australian Dollar
            fi
            
            # Determine account type based on currency
            local account_type=""
            if [[ "$currency" == "USD" ]]; then
                account_type="US"
            elif [[ "$currency" == "GBP" ]]; then
                account_type="UK"
            elif [[ "$currency" == "AUD" ]]; then
                account_type="AU"
            else
                # Default to AU if unclear
                account_type="AU"
            fi
            
            # Validate country-specific field formats based on account type
            case "$account_type" in
                "US")
                    if [[ -z "$routing_number" ]]; then
                        echo_with_color $RED "Error: Fiat account '$account_id' (US account) missing 'routing_number' field"
                        return 1
                    fi
                    if [[ ! "$routing_number" =~ ^[0-9]{9}$ ]]; then
                        echo_with_color $RED "Error: Fiat account '$account_id' routing_number '$routing_number' must be 9 digits"
                        return 1
                    fi
                    ;;
                "UK")
                    if [[ -z "$sort_code" ]]; then
                        echo_with_color $RED "Error: Fiat account '$account_id' (UK account) missing 'sort_code' field"
                        return 1
                    fi
                    if [[ ! "$sort_code" =~ ^[0-9]{6}$ ]]; then
                        echo_with_color $RED "Error: Fiat account '$account_id' sort_code '$sort_code' must be 6 digits"
                        return 1
                    fi
                    ;;
                "AU")
                    if [[ -z "$bsb" ]]; then
                        echo_with_color $RED "Error: Fiat account '$account_id' (AU account) missing 'bsb' field"
                        return 1
                    fi
                    if [[ ! "$bsb" =~ ^[0-9]{6}$ ]]; then
                        echo_with_color $RED "Error: Fiat account '$account_id' bsb '$bsb' must be 6 digits"
                        return 1
                    fi
                    ;;
            esac
            
            # Validate IBAN format (basic check)
            if [[ ! "$iban" =~ ^[A-Z]{2}[0-9]{2}[A-Z0-9]+$ ]]; then
                echo_with_color $YELLOW "Warning: Fiat account '$account_id' iban '$iban' should be a valid IBAN format"
            fi
        done
    fi
    
    echo_with_color $GREEN "Setup file validation passed"
    return 0
}

# Function to show setup status
show_setup_status() {
    echo_with_color $CYAN "YieldFabric System Setup Status"
    echo "=========================================="
    
    # Check services
    echo_with_color $BLUE "Service Status:"
    if check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
        echo_with_color $GREEN "   Auth Service ($AUTH_SERVICE_URL) - Running"
    else
        echo_with_color $RED "   Auth Service ($AUTH_SERVICE_URL) - Not running"
        echo_with_color $YELLOW "   Start the auth service first or check your connection to $AUTH_SERVICE_URL"
        return 1
    fi
    
    if check_token_service_running; then
        echo_with_color $GREEN "   Payment Service ($PAY_SERVICE_URL) - Running"
    else
        echo_with_color $YELLOW "   Payment Service ($PAY_SERVICE_URL) - Not running"
        echo_with_color $BLUE "   Local: cd ../yieldfabric-payments && cargo run"
        echo_with_color $BLUE "   Remote: Verify $PAY_SERVICE_URL is accessible"
    fi
    
    # Check setup file
    echo_with_color $BLUE "Setup File:"
    if [[ -f "$SETUP_FILE" ]]; then
        echo_with_color $GREEN "   $(basename "$SETUP_FILE") - Found"
        
        if check_yq_available; then
            local user_count=$(parse_yaml "$SETUP_FILE" '.users | length')
            local group_count=$(parse_yaml "$SETUP_FILE" '.groups | length')
            echo_with_color $BLUE "   Users defined: $user_count"
            echo_with_color $BLUE "   Groups defined: $group_count"
            
            # Show group member details
            for ((i=0; i<$group_count; i++)); do
                local group_name=$(parse_yaml "$SETUP_FILE" ".groups[$i].name")
                local member_count=$(parse_yaml "$SETUP_FILE" ".groups[$i].members | length" 2>/dev/null)
                echo_with_color $BLUE "   Group '$group_name': $member_count members"
            done
            
            # Show token details
            local token_count=$(parse_yaml "$SETUP_FILE" '.tokens | length' 2>/dev/null)
            if [[ -n "$token_count" && "$token_count" != "0" ]]; then
                echo_with_color $BLUE "   Tokens defined: $token_count"
                for ((i=0; i<$token_count; i++)); do
                    local token_id=$(parse_yaml "$SETUP_FILE" ".tokens[$i].id" 2>/dev/null)
                    local token_name=$(parse_yaml "$SETUP_FILE" ".tokens[$i].name" 2>/dev/null)
                    local chain_id=$(parse_yaml "$SETUP_FILE" ".tokens[$i].chain_id" 2>/dev/null)
                    echo_with_color $BLUE "   Token '$token_name' ($token_id): Chain $chain_id"
                done
            else
                echo_with_color $BLUE "   Tokens defined: 0"
            fi
            
            # Show asset details
            local asset_count=$(parse_yaml "$SETUP_FILE" '.assets | length' 2>/dev/null)
            if [[ -n "$asset_count" && "$asset_count" != "0" ]]; then
                echo_with_color $BLUE "   Assets defined: $asset_count"
                for ((i=0; i<$asset_count; i++)); do
                    local asset_id=$(parse_yaml "$SETUP_FILE" ".assets[$i].id" 2>/dev/null)
                    local asset_name=$(parse_yaml "$SETUP_FILE" ".assets[$i].name" 2>/dev/null)
                    local asset_type=$(parse_yaml "$SETUP_FILE" ".assets[$i].type" 2>/dev/null)
                    local currency=$(parse_yaml "$SETUP_FILE" ".assets[$i].currency" 2>/dev/null)
                    echo_with_color $BLUE "   Asset '$asset_name' ($asset_id): Type $asset_type, Currency $currency"
                done
            else
                echo_with_color $BLUE "   Assets defined: 0"
            fi
            
            # Show fiat account details
            local fiat_account_count=$(parse_yaml "$SETUP_FILE" '.fiat_accounts | length' 2>/dev/null)
            if [[ -n "$fiat_account_count" && "$fiat_account_count" != "0" ]]; then
                echo_with_color $BLUE "   Fiat accounts defined: $fiat_account_count"
                for ((i=0; i<$fiat_account_count; i++)); do
                    local account_id=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].id" 2>/dev/null)
                    local holder=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].holder" 2>/dev/null)
                    local country=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].country" 2>/dev/null)
                    local currency=$(parse_yaml "$SETUP_FILE" ".fiat_accounts[$i].currency" 2>/dev/null)
                    echo_with_color $BLUE "   Fiat Account '$holder' ($account_id): Country $country, Currency $currency"
                done
            else
                echo_with_color $BLUE "   Fiat accounts defined: 0"
            fi
        else
            echo_with_color $YELLOW "   yq not available - cannot parse YAML"
        fi
    else
        echo_with_color $RED "   $(basename "$SETUP_FILE") - Not found"
        return 1
    fi
    
    # Check yq availability
    echo_with_color $BLUE "YAML Parser:"
    if check_yq_available; then
        echo_with_color $GREEN "   yq - Available"
    else
        echo_with_color $RED "   yq - Not available"
        echo_with_color $YELLOW "   Install yq: brew install yq (macOS) or see https://github.com/mikefarah/yq"
        return 1
    fi
}

# Function to run complete setup
run_setup() {
    echo_with_color $CYAN "🚀 Running YieldFabric System Setup..."
    echo ""
    
    # Validate setup file
    if ! validate_setup_file; then
        echo_with_color $RED "❌ Setup file validation failed"
        return 1
    fi
    
    # Check service status
    if ! check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
        echo_with_color $RED "❌ Auth service is not reachable at $AUTH_SERVICE_URL"
        echo_with_color $YELLOW "Please check your connection or start the auth service:"
        echo "   Local: cd ../yieldfabric-auth && cargo run"
        echo "   Remote: Verify $AUTH_SERVICE_URL is accessible"
        return 1
    fi
    
    # Create initial users first (without admin token)
    if ! create_initial_users; then
        echo_with_color $RED "❌ Failed to create initial users"
        return 1
    fi
    
    echo ""
    
    # Now setup authentication using yieldfabric-auth.sh
    echo_with_color $BLUE "🔐 Setting up authentication..."
    local admin_token=$($AUTH_SCRIPT admin 2>/dev/null)
    if [[ $? -ne 0 || -z "$admin_token" ]]; then
        echo_with_color $RED "❌ Failed to get admin token"
        return 1
    fi
    
    echo_with_color $GREEN "✅ Authentication setup completed"
    echo ""
    
    # Setup groups
    if ! setup_groups "$admin_token"; then
        echo_with_color $YELLOW "⚠️  Group setup had some issues, continuing with relationships..."
    fi
    
    echo ""
    
    # Setup group relationships
    if ! setup_group_relationships "$admin_token"; then
        echo_with_color $YELLOW "⚠️  Group relationship setup had some issues"
    fi
    
    echo ""
    
    # Setup tokens
    if ! setup_tokens; then
        echo_with_color $YELLOW "⚠️  Token setup had some issues"
    fi
    
    echo ""
    
    # Setup assets
    if ! setup_assets; then
        echo_with_color $YELLOW "⚠️  Asset setup had some issues"
    fi
    
    echo ""
    
    # Setup fiat accounts
    if ! setup_fiat_accounts; then
        echo_with_color $YELLOW "⚠️  Fiat account setup had some issues"
    fi
    
    echo ""
    echo_with_color $GREEN "🎉 System setup completed!"
    echo ""
    
    # Show final status
    show_setup_status
}

# Function to show help
show_help() {
    echo_with_color $CYAN "YieldFabric System Setup Script"
    echo "=========================================="
    echo ""
    echo "Usage: $0 [-f|--file <yaml>] [<yaml>] [command ...]"
    echo ""
    echo "  • A leading *.yaml/*.yml argument (or -f <yaml>) selects the config"
    echo "    file. Defaults to setup.yaml beside this script."
    echo "  • One or more commands run in order, e.g. '$0 tokens assets'."
    echo ""
    echo "Commands:"
    echo_with_color $GREEN "  setup" "     - Run complete system setup from setup.yaml"
    echo_with_color $GREEN "  status" "    - Show current setup status and requirements"
    echo_with_color $GREEN "  validate" "  - Validate setup.yaml file structure"
    echo_with_color $GREEN "  users" "     - Setup only users from setup.yaml"
    echo_with_color $GREEN "  groups" "    - Setup only groups from setup.yaml"
    echo_with_color $GREEN "  owners" "    - Setup only group account owners from setup.yaml"
    echo_with_color $GREEN "  tokens" "    - Setup only tokens from setup.yaml"
    echo_with_color $GREEN "  assets" "    - Setup only assets from setup.yaml"
    echo_with_color $GREEN "  fiat" "      - Setup only fiat accounts from setup.yaml"
    echo_with_color $GREEN "  help" "      - Show this help message"
    echo ""
    echo "Requirements:"
    echo "  • yieldfabric-auth service running on port 3000"
    echo "  • yieldfabric-auth.sh script available"
    echo "  • yq YAML parser installed"
    echo "  • setup.yaml file with users and groups configuration"
    echo ""
    echo "Setup.yaml Structure:"
    echo "  • users: array of users with id, password, and role"
    echo "  • groups: array of groups with members array containing id and role"
    echo "  • tokens: array of tokens with id, name, description, chain_id, and address"
    echo "  • assets: array of assets with id, name, type, currency, description, and token_id"
    echo "  • fiat_accounts: array of bank accounts with id, holder, iban, account_number, user info, and country-specific fields"
    echo "  • Member roles: owner, admin, member, viewer"
    echo "  • Asset types: Cash, Token, Invoice, Factoring_Agreement, Escrow_Account, Payable, Receivable"
    echo "  • Fiat account types: US (routing_number), UK (sort_code), AU (bsb)"
    echo "  • Fiat account delegation: Include user.id, user.password, and user.group for group delegation"
    echo ""
    echo "Owner Setup:"
    echo "  • Declared group members are added with the creator's owner credential"
    echo "  • Setup explicitly activates each group on the creator JWT's selected chain"
    echo "  • Use 'owners' command to setup only group account owners"
    echo ""
    echo "Examples:"
    echo "  $0 setup                              # Complete system setup (setup.yaml)"
    echo "  $0 status                             # Check setup requirements"
    echo "  $0 validate                           # Validate setup.yaml structure"
    echo "  $0 setup_testnet.yaml tokens assets   # tokens + assets from a custom file"
    echo "  $0 -f setup_testnet.yaml tokens       # tokens only, custom file via flag"
    echo ""
    echo_with_color $YELLOW "For first-time users, run: $0 setup"
}

# Dispatch a single command name through the original command table.
# Called once per command given on the command line.
dispatch_command() {
case "${1}" in
    "setup")
        run_setup
        ;;
    "status")
        show_setup_status
        ;;
    "validate")
        validate_setup_file
        ;;
    "users")
        if check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
            # Get admin token first, then create users
            echo_with_color $BLUE "Getting admin token first..."
            admin_token=$($AUTH_SCRIPT admin 2>/dev/null)
            if [[ $? -eq 0 && -n "$admin_token" ]]; then
                echo_with_color $GREEN "Admin token obtained, creating users..."
                if setup_users "$admin_token"; then
                    echo_with_color $GREEN "Users created successfully"
                else
                    echo_with_color $RED "Failed to create users"
                    exit 1
                fi
            else
                echo_with_color $RED "Failed to get admin token"
                exit 1
            fi
        else
            echo_with_color $RED "Auth service not running"
            exit 1
        fi
        ;;
    "groups")
        if check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
            # Create users first if they don't exist
            if ! create_initial_users; then
                echo_with_color $RED "Failed to create users"
                exit 1
            fi
            
            # Now get admin token
            admin_token=$($AUTH_SCRIPT admin 2>/dev/null)
            if [[ $? -eq 0 && -n "$admin_token" ]]; then
                setup_groups "$admin_token"
            else
                echo_with_color $RED "Failed to get admin token"
                exit 1
            fi
        else
            echo_with_color $RED "Auth service not running"
            exit 1
        fi
        ;;
    "tokens")
        if check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
            # Create users first if they don't exist
            if ! create_initial_users; then
                echo_with_color $RED "Failed to create users"
                exit 1
            fi
            
            # Setup tokens
            setup_tokens
        else
            echo_with_color $RED "Auth service not running"
            exit 1
        fi
        ;;
    "owners")
        if check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
            # Create users first if they don't exist
            if ! create_initial_users; then
                echo_with_color $RED "Failed to create users"
                exit 1
            fi
            
            # Setup group relationships (which includes owner setup)
            setup_group_relationships
        else
            echo_with_color $RED "Auth service not running"
            exit 1
        fi
        ;;
    "assets")
        if check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
            # Create users first if they don't exist
            if ! create_initial_users; then
                echo_with_color $RED "Failed to create users"
                exit 1
            fi
            
            # Setup assets
            setup_assets
        else
            echo_with_color $RED "Auth service not running"
            exit 1
        fi
        ;;
    "fiat")
        if check_service_running "Auth Service" "$AUTH_SERVICE_URL"; then
            # Create users first if they don't exist
            if ! create_initial_users; then
                echo_with_color $RED "Failed to create users"
                exit 1
            fi
            
            # Setup fiat accounts
            setup_fiat_accounts
        else
            echo_with_color $RED "Auth service not running"
            exit 1
        fi
        ;;
    "help"|"-h"|"--help")
        show_help
        ;;
    *)
        echo_with_color $RED "Unknown command: $1"
        echo ""
        show_help
        exit 1
        ;;
esac
}

# ─────────────────────────────────────────────────────────────────────────────
# Main execution
#
# Usage: setup_system.sh [-f|--file <yaml>] [<yaml>] [command ...]
#
#   • A leading argument ending in .yaml/.yml — or one given via -f/--file —
#     selects the config file. Defaults to setup.yaml next to this script.
#   • One or more commands run in the order given, so you can do e.g.
#         setup_system.sh setup_testnet.yaml tokens assets
#     to run tokens and then assets against setup_testnet.yaml.
#   • With no command, runs the full `setup`.
# ─────────────────────────────────────────────────────────────────────────────
COMMANDS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -f|--file)
            if [[ -z "${2:-}" ]]; then
                echo_with_color $RED "Error: $1 requires a YAML file path"
                exit 1
            fi
            SETUP_FILE="$2"
            shift 2
            ;;
        --file=*)
            SETUP_FILE="${1#*=}"
            shift
            ;;
        *.yaml|*.yml)
            SETUP_FILE="$1"
            shift
            ;;
        *)
            COMMANDS+=("$1")
            shift
            ;;
    esac
done

# Resolve a bare/relative filename against the script directory when it isn't
# found relative to the current working directory (mirrors execute_commands.sh).
if [[ "$SETUP_FILE" != /* && ! -f "$SETUP_FILE" && -f "$SCRIPT_DIR/$SETUP_FILE" ]]; then
    SETUP_FILE="$SCRIPT_DIR/$SETUP_FILE"
fi

# Default to the full setup when no command is given.
if [[ ${#COMMANDS[@]} -eq 0 ]]; then
    COMMANDS=("setup")
fi

# Every command except help needs the config file to exist — fail early with a
# clear message instead of letting yq quietly return empty values downstream.
needs_file=false
for cmd in "${COMMANDS[@]}"; do
    case "$cmd" in
        help|-h|--help) ;;
        *) needs_file=true ;;
    esac
done
if [[ "$needs_file" == true ]]; then
    if [[ ! -f "$SETUP_FILE" ]]; then
        echo_with_color $RED "Setup file not found: $SETUP_FILE"
        exit 1
    fi
    echo_with_color $CYAN "📄 Using config file: $SETUP_FILE"
    echo_with_color $CYAN "▶  Commands: ${COMMANDS[*]}"
    echo ""
fi

# Run each command in order. Infra failures inside a command `exit` the whole
# script (fail-fast); soft per-item setup issues are warned and do not stop it.
for cmd in "${COMMANDS[@]}"; do
    dispatch_command "$cmd"
done
