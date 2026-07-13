# Authentication Guide

Complete guide to YieldFabric authentication, including login, delegation, and JWT tokens.

---

## Login with Services

Login to YieldFabric and request specific service access:

```bash
curl -X POST https://auth.yieldfabric.com/auth/login/with-services \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "your-password",
    "services": ["vault", "payments"]
  }'
```

**Response:**
```json
{
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "refresh_token_here",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "role": "User",
    "account_address": "0x1234..."
  }
}
```

**Save the token** for subsequent requests:
```bash
export TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

## Delegate Authentication

Create a delegation JWT for group operations:

```bash
curl -X POST https://auth.yieldfabric.com/auth/delegation/jwt \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": "550e8400-e29b-41d4-a716-446655440000",
    "delegation_scope": ["read", "write", "manage"],
    "expiry_seconds": 3600
  }'
```

**Response:**
```json
{
  "delegation_jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "delegation_scope": ["read", "write", "manage"],
  "expiry_seconds": 3600,
  "group_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### List Delegation Tokens

```bash
curl -X GET https://auth.yieldfabric.com/auth/groups/{group_id}/delegation-tokens \
  -H "Authorization: Bearer $TOKEN"
```

### Revoke Delegation Token

```bash
curl -X POST https://auth.yieldfabric.com/auth/groups/{group_id}/delegation-tokens/{token_id}/revoke \
  -H "Authorization: Bearer $TOKEN"
```

### Using Delegation Tokens

**For Group Operations:**
```bash
# Use delegation token for group crypto operations
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $DELEGATION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { instant(input: { assetId: \"aud-token-asset\", amount: \"100\", destinationId: \"recipient@yieldfabric.com\" }) { success paymentId } }"
  }'
```

**For Group Balance Queries:**
```bash
# Query group balance using delegation token
curl -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=null" \
  -H "Authorization: Bearer $DELEGATION_TOKEN"
```

**For Group Contract Operations:**
```bash
# Create obligations on behalf of group
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $DELEGATION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { createObligation(input: { counterpart: \"buyer@yieldfabric.com\", denomination: \"aud-token-asset\", notional: \"1000\" }) { success contractId } }"
  }'
```

**Delegation Token Lifecycle:**
1. **Create**: Admin creates delegation token with specific scope
2. **Use**: User performs operations using group's account address
3. **Audit**: All operations logged with both user and group identifiers
4. **Revoke**: Admin can revoke token to stop access immediately
5. **Expire**: Token automatically expires based on `expiry_seconds`

---

## JWT Token Structure

### Standard User JWT Token

Your JWT token includes the following claims:

```json
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",
  "aud": ["vault", "payments"],
  "exp": 1697712000,
  "iat": 1697625600,
  "role": "Operator",
  "permissions": [
    "CryptoOperations",
    "ViewSignatureKeys",
    "ManageSignatureKeys"
  ],
  "entity_scope": [],
  "session_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "auth_method": "jwt",
  "entity_type": "user",
  "email": "user@example.com",
  "account_address": "0x1234567890abcdef1234567890abcdef12345678",
  "group_account_address": null,
  "acting_as": null,
  "delegation_scope": null,
  "delegation_token_id": null,
  "mcp_agent_id": null,
  "mcp_session_id": null,
  "mcp_impersonation": false,
  "mcp_selected_key": null
}
```

**Core Fields:**
- `sub`: User ID (UUID)
- `aud`: Allowed services (e.g., `["vault", "payments"]`)
- `exp`: Expiration timestamp (Unix)
- `iat`: Issued at timestamp (Unix)
- `role`: User role (`SuperAdmin`, `Admin`, `Manager`, `Operator`, `Viewer`, `ApiClient`)
- `permissions`: Specific permission strings
- `entity_scope`: Entity IDs the user can access
- `session_id`: Session identifier
- `auth_method`: Authentication method (`"jwt"` for standard, `"delegation"` for delegation)
- `entity_type`: Type of entity (`"user"` or `"group"`)

**User-Specific Fields:**
- `email`: User's email address
- `account_address`: User's deployed intelligent account address
- `group_account_address`: Group's account address (null for user tokens)

**Delegation Fields (null for standard tokens):**
- `acting_as`: Group ID when acting on behalf of a group
- `delegation_scope`: Allowed operations for delegation
- `delegation_token_id`: Delegation token ID for audit trail

**MCP Fields (for agent integration):**
- `mcp_agent_id`: Agent identifier
- `mcp_session_id`: MCP session tracking
- `mcp_impersonation`: Flag for agent impersonation
- `mcp_selected_key`: Selected key ID

### Delegation JWT Token

When using group delegation, the JWT structure includes additional fields:

```json
{
  "sub": "550e8400-e29b-41d4-a716-446655440000",
  "aud": ["yieldfabric"],
  "exp": 1697712000,
  "iat": 1697625600,
  "role": "Operator",
  "permissions": [],
  "entity_scope": ["entity-1", "entity-2"],
  "session_id": "b2c3d4e5-f6a7-8901-bcde-f12345678901",
  "auth_method": "delegation",
  "entity_type": "user",
  "email": "user@example.com",
  "account_address": "0x1234567890abcdef1234567890abcdef12345678",
  "group_account_address": "0xabcdef1234567890abcdef1234567890abcdef12",
  "acting_as": "group-id-550e8400-e29b-41d4-a716-446655440001",
  "delegation_scope": [
    "CryptoOperations",
    "ReadGroup",
    "UpdateGroup",
    "ManageGroupMembers"
  ],
  "delegation_token_id": "c3d4e5f6-a7b8-9012-cdef-123456789012",
  "mcp_agent_id": null,
  "mcp_session_id": null,
  "mcp_impersonation": false,
  "mcp_selected_key": null
}
```

**Delegation-Specific Differences:**
- `auth_method`: Set to `"delegation"` (instead of `"jwt"`)
- `aud`: Set to `["yieldfabric"]` (broader audience)
- `group_account_address`: Contains the group's deployed account address
- `acting_as`: Contains the group ID the user is acting on behalf of
- `delegation_scope`: Array of allowed operations (replaces permissions for delegation)
- `delegation_token_id`: UUID for tracking and revoking delegation
- `entity_scope`: Contains entity IDs the group has access to

**Usage:**
- **Standard JWT**: User operates with their own account address
- **Delegation JWT**: User operates with the group's account address while maintaining audit trail
- The `acting_as` field tells the system to use `group_account_address` instead of user's `account_address`

---

## User Roles

### **SuperAdmin Role**
- **Access Level**: Full system access
- **Permissions**: All permissions automatically granted
- **Use Case**: System administration and management
- **Operations**: Can perform any operation in the system

### **Admin Role**
- **Access Level**: Administrative operations
- **Permissions**: User management, group management, system configuration
- **Use Case**: Administrative tasks and user/group management
- **Operations**: Create users, manage groups, configure permissions

### **Manager Role**
- **Access Level**: Manage entities and groups
- **Permissions**: Group operations, member management, delegation
- **Use Case**: Group administration and team management
- **Operations**: Manage group members, create delegation tokens, group operations

### **Operator Role**
- **Access Level**: Service access + limited administration
- **Permissions**: Service operations + group management
- **Use Case**: Service operation and group administration
- **Operations**: Use services, manage groups, create delegation tokens

### **Viewer Role**
- **Access Level**: Read-only access
- **Permissions**: Read operations only
- **Use Case**: Information viewing and monitoring
- **Operations**: View information but cannot modify anything

### **ApiClient Role**
- **Access Level**: API integration access
- **Permissions**: Service-specific operations
- **Use Case**: API integration and service-to-service communication
- **Operations**: Execute API operations within service scope

---

## Required Permissions for Operations

### **User Management Operations**
| **Operation** | **Required Permission** | **API Endpoint** | **Description** |
|---------------|------------------------|------------------|-----------------|
| **Create User** | `CreateUser` | `POST /auth/users` | Register new users in the system |
| **Read User** | `ReadUser` | `GET /auth/users/{id}` | View user information and profiles |
| **Update User** | `UpdateUser` | `PUT /auth/users/{id}` | Modify user details and settings |
| **Delete User** | `DeleteUser` | `DELETE /auth/users/{id}` | Remove users from the system |
| **Manage Users** | `UsersManage` | Various endpoints | Full user lifecycle management |

### **Group Management Operations**
| **Operation** | **Required Permission** | **API Endpoint** | **Description** |
|---------------|------------------------|------------------|-----------------|
| **Create Group** | `CreateGroup` | `POST /auth/groups` | Set up new groups for organizing users |
| **Read Group** | `ReadGroup` | `GET /auth/groups/{id}` | View group information and settings |
| **Update Group** | `UpdateGroup` | `PUT /auth/groups/{id}` | Modify group name, description, etc. |
| **Delete Group** | `DeleteGroup` | `DELETE /auth/groups/{id}` | Remove groups and all associated data |
| **Manage Groups** | `ManageGroups` | Various endpoints | Full group lifecycle management |

### **Group Member Operations**
| **Operation** | **Required Permission** | **API Endpoint** | **Description** |
|---------------|------------------------|------------------|-----------------|
| **Add Member** | `AddGroupMember` | `POST /auth/groups/{id}/members` | Include users in groups with roles |
| **Remove Member** | `RemoveGroupMember` | `DELETE /auth/groups/{id}/members/{user_id}` | Remove users from groups |
| **Manage Members** | `ManageGroupMembers` | Various endpoints | Full member lifecycle management |

### **Permission Management Operations**
| **Operation** | **Required Permission** | **API Endpoint** | **Description** |
|---------------|------------------------|------------------|-----------------|
| **Grant Permission** | `ManageUsers` | `POST /auth/users/{user_id}/permissions/{permission}` | Give users specific permissions |
| **Revoke Permission** | `ManageUsers` | `DELETE /auth/users/{user_id}/permissions/{permission}` | Remove specific permissions |
| **Check Permission** | `ManageUsers` | `GET /auth/users/{user_id}/permissions/{permission}` | Verify user permissions |
| **Grant Multiple Permissions** | `ManageUsers` | `POST /auth/users/{user_id}/permissions` | Grant multiple permissions at once |
| **Revoke Multiple Permissions** | `ManageUsers` | `DELETE /auth/users/{user_id}/permissions` | Revoke multiple permissions at once |
| **Replace Permissions** | `ManageUsers` | `PUT /auth/users/{user_id}/permissions` | Set complete permission set |
| **Get User Permissions** | `ManageUsers` | `GET /auth/users/{user_id}/permissions` | Retrieve all user permissions |

### **Cryptographic Operations**
| **Operation** | **Required Permission** | **API Endpoint** | **Description** |
|---------------|------------------------|------------------|-----------------|
| **Encrypt Data** | `CryptoOperations` | `POST /api/v1/encrypt` | Encrypt data using public keys |
| **Decrypt Data** | `CryptoOperations` | `POST /api/v1/decrypt` | Decrypt data using private keys |
| **Sign Data** | `CryptoOperations` | `POST /api/v1/sign` | Create digital signatures |
| **Verify Signatures** | `CryptoOperations` | `POST /api/v1/verify` | Verify digital signatures |
| **Generate Keypair** | `CryptoOperations` | `POST /api/v1/generate-keypair` | Generate cryptographic key pair |
| **Get Key Info** | `CryptoOperations` | `GET /api/v1/keys/{key_id}/info` | Retrieve key pair details |
| **Get Public Key** | `CryptoOperations` | `GET /api/v1/public-key/{contact_id}` | Get public key by contact |

### **Delegation Operations**
| **Operation** | **Required Permission** | **API Endpoint** | **Description** |
|---------------|------------------------|------------------|-----------------|
| **Create Delegation JWT** | `CreateDelegationToken` | `POST /auth/delegation/jwt` | Generate limited-scope JWT |
| **Create Delegation Token** | `CreateDelegationToken` | `POST /auth/groups/{group_id}/delegation-tokens` | Create delegation token for group |
| **View Delegation Tokens** | `ViewDelegationTokens` | `GET /auth/groups/{group_id}/delegation-tokens` | List active delegation tokens for group |
| **Revoke Delegation Token** | `RevokeDelegationToken` | `POST /auth/groups/{group_id}/delegation-tokens/{token_id}/revoke` | Invalidate delegation token |

### **System Administration Operations**
| **Operation** | **Required Permission** | **API Endpoint** | **Description** |
|---------------|------------------------|------------------|-----------------|
| **System Configuration** | `SystemConfig` | Various endpoints | Modify system-wide settings |
| **View Logs** | `ViewLogs` | Various endpoints | Access system logs and audit trails |
| **Manage Roles** | `ManageRoles` | Various endpoints | Create and modify user roles |
| **API Access** | `ApiRead`, `ApiWrite`, `ApiAdmin` | Various endpoints | Control API access levels |

---

## Group Member Roles

### **Owner Role**
- **Permissions**: Full control over the group
- **Capabilities**: Everything in the group, including deletion
- **Use Case**: Group leadership and ultimate control

### **Admin Role**
- **Permissions**: Member management and group operations
- **Capabilities**: Add/remove members, manage permissions
- **Use Case**: Group administration and day-to-day management

### **Member Role**
- **Permissions**: Group operations and participation
- **Capabilities**: Perform group-specific tasks and operations
- **Use Case**: Active group participation

### **Viewer Role**
- **Permissions**: Read-only access to group information
- **Capabilities**: View group information and members
- **Use Case**: Group monitoring and information access

---

## Common Permissions

- `CryptoOperations` - Cryptographic operations
- `ViewSignatureKeys` - View signing keys
- `ManageSignatureKeys` - Manage signing keys
- `CreateGroup` - Create groups
- `ManageGroupPermissions` - Manage group access
- `CreateDelegationToken` - Create delegation tokens

---

## Delegation Scope

When acting on behalf of groups:
- `CryptoOperations` - Perform crypto operations for group
- `ReadGroup` - Read group information
- `UpdateGroup` - Update group settings
- `ManageGroupMembers` - Manage group membership

---

## Auth Service Endpoints

- `POST /auth/login/with-services` — Login with service selection
- `POST /auth/refresh` — Refresh access token
- `GET /auth/users/me` — Get user profile
- `POST /auth/logout` — Logout current device
- `POST /auth/logout-all` — Logout all devices
- `POST /auth/delegation/jwt` — Create delegation JWT
- `GET /auth/groups/{group_id}/delegation-tokens` — List delegation tokens for a group
- `POST /auth/groups/{group_id}/delegation-tokens` — Create delegation token for a group
- `POST /auth/groups/{group_id}/delegation-tokens/{token_id}/revoke` — Revoke delegation token
- `POST /auth/users` — Create a new user
- `POST /auth/users/{user_id}/deploy-account` — Deploy an intelligent account for a user

