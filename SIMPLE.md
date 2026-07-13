# YieldFabric API - Simple CURL Examples

> **Note:** This document contains all API examples in one comprehensive file. For easier navigation, see the [organized documentation structure](./README.md#documentation-structure) with separate guides for each topic.

## Base URLs

- **Auth Service**: `https://auth.yieldfabric.com`
- **Payments/GraphQL Service**: `https://pay.test.yieldfabric.com`
- **GraphQL Endpoint**: `https://pay.test.yieldfabric.com/graphql`

---

## How It Works

### Intelligent Accounts with Zero-Knowledge Privacy

YieldFabric provides **intelligent accounts** that enable programmed financial actions with confidential transactions protected by **zero-knowledge proof technology**. Users deposit tokens into these accounts to operate with privacy and programmability.

**Account Types:**

Intelligent accounts can be linked to:
- **Personal Accounts**: Owned by individual users for their own operations
- **Group Accounts**: Shared accounts managed by multiple authorized users

**Group Account Features:**

Group accounts provide all the same capabilities as personal accounts:
- Hold balances and manage funds
- Create and execute programmed payments
- Build and trade payment obligations
- Execute atomic swaps
- Operate with zero-knowledge privacy

The key difference is **governance and access control**:
- **Administrators** can add policies and grant access to specific users
- **Authorized users** act on behalf of the group (not themselves)
- **Permissions and policies** control what operations each user can perform
- **Audit trail** maintained through delegation tokens and session tracking

**How Delegation Works:**

1. User authenticates with their personal credentials
2. User requests a **delegation JWT** for a specific group
3. Delegation JWT includes:
   - User's identity (for audit trail)
   - Group's account address (for operations)
   - Delegation scope (permitted operations)
   - Delegation token ID (for tracking/revocation)
4. User performs operations using the **group's account** instead of their own
5. All actions are logged with both user and group identifiers

This enables **collaborative financial operations** while maintaining security, accountability, and fine-grained access control.

### Basic Payment Flow

1. **Deposit**: Users deposit tokens into their intelligent account to enable programmed actions and confidential operations
2. **Transfer**: Funds can be transferred to another user - payments are **locked** until the counterpart accepts or the sender cancels (depending on how the payment was programmed)
3. **Accept**: The counterpart accepts the incoming payment, claiming the funds
4. **Withdraw**: Users can withdraw funds from their intelligent account back to external addresses

### Payment Obligations

Users can create sophisticated payment obligations representing:
- **Invoices**: Payment due on a specific date
- **Loans**: Structured repayment schedules
- **Annuities**: Recurring payment streams
- **Any future payment commitment**

Payment obligations support two funding models:
- **Fully Funded (Escrow)**: Funds locked upfront, guaranteeing payment
- **Unfunded (Credit)**: Payment obligation without immediate funding

Obligations can be programmed with:
- **Timelocks**: Payments unlock at specific dates
- **Oracle Triggers**: External event-based unlocking (e.g., "goods delivered", "contract signed")
- **Conditional Release**: Payment execution based on oracle verification

### Atomic Swaps for Structured Trades

Participants can execute **bilateral trades** of composed payment obligations:
- **Atomic Settlement**: Both parties exchange simultaneously or transaction fails
- **Programmable Triggers**: Swap execution based on conditions
- **Sophisticated Structures**: Combine multiple obligations into complex financial instruments
- **Risk-Free Construction**: Build obligation structures independently, then swap atomically

Example: An issuer creates annuity obligations (self-referential, no counterparty risk), then atomically swaps them for upfront payment - enabling secure securitization and discounted cash flow transactions.

---

## 1. Authentication with Services

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

## 2. Delegate Authentication

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
curl -X GET https://auth.yieldfabric.com/auth/delegation/tokens \
  -H "Authorization: Bearer $TOKEN"
```

### Revoke Delegation Token

```bash
curl -X DELETE https://auth.yieldfabric.com/auth/delegation/tokens/{token_id} \
  -H "Authorization: Bearer $TOKEN"
```

---

## 3. Get Balance

Get balance for a specific denomination and obligor:

```bash
curl -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=null" \
  -H "Authorization: Bearer $TOKEN"
```

**With specific obligor:**
```bash
curl -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=issuer@yieldfabric.com" \
  -H "Authorization: Bearer $TOKEN"
```

**With group ID (for group/delegation queries):**
```bash
curl -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=null&group_id=550e8400-e29b-41d4-a716-446655440000" \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "private_balance": "125",
  "public_balance": "99775",
  "decimals": "1000000000000000000",
  "locked_out": [
    {
      "id_hash": "38226576697392579486248991160328482056897095088953678834306466678621490414681",
      "sender": "0x207bBcA7ACd050e67e311A45175a8CB0CB0b7396",
      "owner": "0x7d47586B5dc2bC4d6573De060d95dEa7D5835347",
      "amount": "5",
      "created": "1760932198",
      "unlock_sender": "0",
      "unlock_receiver": "0",
      "redeemed": "0",
      "active": true,
      "amount_hash": "19065150524771031435284970883882288895168425523179566388456001105768498065277",
      "obligation_address": "0x7d47586B5dc2bC4d6573De060d95dEa7D5835347",
      "obligation_id": "1760932171949",
      "swap_address": "0xdeE59004e54C976ACf7F877de4169A001fB1174A",
      "swap_id": "0",
      "denomination": "0xe764F77fbCa499E29Ec2B58506fB21CbE4BC2916",
      "obligor": "0x207bBcA7ACd050e67e311A45175a8CB0CB0b7396",
      "oracle_address": "0xC8b17d4A3271922d38f8d5b1Abf6F8c594558a07",
      "oracle_owner": "0x0000000000000000000000000000000000000000",
      "oracle_key_sender": "0",
      "oracle_value_sender": "0",
      "oracle_key_recipient": "0",
      "oracle_value_recipient": "0"
    },
    {
      "id_hash": "47250913374799590777416249090169747339675959205761065009770338687996018257116",
      "sender": "0x207bBcA7ACd050e67e311A45175a8CB0CB0b7396",
      "owner": "0x7d47586B5dc2bC4d6573De060d95dEa7D5835347",
      "amount": "100",
      "created": "1760932237",
      "unlock_sender": "0",
      "unlock_receiver": "0",
      "redeemed": "0",
      "active": true,
      "amount_hash": "8540862089960479027598468084103001504332093299703848384261193335348282518119",
      "obligation_address": "0x7d47586B5dc2bC4d6573De060d95dEa7D5835347",
      "obligation_id": "1760932212811",
      "swap_address": "0xdeE59004e54C976ACf7F877de4169A001fB1174A",
      "swap_id": "0",
      "denomination": "0xe764F77fbCa499E29Ec2B58506fB21CbE4BC2916",
      "obligor": "0x207bBcA7ACd050e67e311A45175a8CB0CB0b7396",
      "oracle_address": "0xC8b17d4A3271922d38f8d5b1Abf6F8c594558a07",
      "oracle_owner": "0x0000000000000000000000000000000000000000",
      "oracle_key_sender": "0",
      "oracle_value_sender": "0",
      "oracle_key_recipient": "0",
      "oracle_value_recipient": "0"
    }
  ],
  "locked_in": [
    {
      "id_hash": "3781619529420270136977292868260507850169038307743773981771100284159493991598",
      "sender": "0xFbC4E5C907BC67C7f47393b8082cE05b0111Fb19",
      "owner": "0x207bBcA7ACd050e67e311A45175a8CB0CB0b7396",
      "amount": "100",
      "created": "1760932274",
      "unlock_sender": "0",
      "unlock_receiver": "0",
      "redeemed": "0",
      "active": true,
      "amount_hash": "8540862089960479027598468084103001504332093299703848384261193335348282518119",
      "obligation_address": "0x207bBcA7ACd050e67e311A45175a8CB0CB0b7396",
      "obligation_id": "0",
      "swap_address": "0xdeE59004e54C976ACf7F877de4169A001fB1174A",
      "swap_id": "123456789",
      "denomination": "0xe764F77fbCa499E29Ec2B58506fB21CbE4BC2916",
      "obligor": "0x0000000000000000000000000000000000000000",
      "oracle_address": "0xC8b17d4A3271922d38f8d5b1Abf6F8c594558a07",
      "oracle_owner": "0xdeE59004e54C976ACf7F877de4169A001fB1174A",
      "oracle_key_sender": "1",
      "oracle_value_sender": "21668155418416697223704814829225222913601556726304084175538103658674395579898",
      "oracle_key_recipient": "1",
      "oracle_value_recipient": "6894414877227513947045417484108893674868878975854235968280453393939941502987"
    }
  ],
  "denomination": "aud-token-asset",
  "obligor": "0x0000000000000000000000000000000000000000",
  "beneficial_balance": "0",
  "beneficial_transaction_ids": [
    "38226576697392579486248991160328482056897095088953678834306466678621490414681",
    "10759558618326676853103774139841747072275039305801890997620452557680674578063",
    "84386874154938447772534248106542510565789722076264626438033699898733304146031",
    "100582819388411396041903522405880506493894909970836357668113966628191164048252",
    "92416405726140074415007586106169462050842524464949735261189538952617984830289",
    "47250913374799590777416249090169747339675959205761065009770338687996018257116"
  ],
  "outstanding": "125"
}
```

**Response Fields:**

### Balance Fields
- **`private_balance`**: Your balance in encrypted/private form (zero-knowledge proof protected)
- **`public_balance`**: Your balance in public/transparent form (visible on-chain)
- **`decimals`**: Token decimal precision as returned by the ERC-20 `decimals()` call (e.g., `"1000000000000000000"` for 18 decimals). Divide amounts by this value to get the human-readable figure
- **`outstanding`**: Total amount currently locked out in pending outgoing transactions

### Transaction Arrays
- **`locked_out`**: Outgoing payments/obligations you've created that are pending acceptance by the recipient
  - These reduce your available balance until accepted or expired
  - Each transaction includes full details: amount, addresses, unlock conditions, oracle requirements
  
- **`locked_in`**: Incoming payments/obligations sent to you that are awaiting your acceptance
  - These don't affect your balance until you explicitly accept them
  - Use the `accept` mutation with the `id_hash` to claim these funds

### Asset Identifiers
- **`denomination`**: The asset identifier (e.g., "aud-token-asset") which maps to a token contract address
- **`obligor`**: The obligor address for this balance query
  - Use `0x0000000000000000000000000000000000000000` for general asset balance (no specific obligor)
  - Use a specific address to query obligations from that obligor

### Beneficial Ownership
- **`beneficial_balance`**: Balance held where you're the beneficial owner (not direct owner)
- **`beneficial_transaction_ids`**: Array of transaction `id_hash` values where `obligation_id != 0`
  - These are transactions associated with obligations/contracts
  - Useful for tracking contract-based payments vs instant transfers

### Transaction Object Fields
Each transaction in `locked_out` and `locked_in` contains:
- **`id_hash`**: Unique identifier for the transaction (use this for accept/redeem operations)
- **`sender`**: Address of the payment sender
- **`owner`**: Address of the payment recipient/owner
- **`amount`**: Payment amount (as string integer)
- **`created`**: Unix timestamp when transaction was created
- **`unlock_sender`**: Timestamp when sender can reclaim (0 = no time lock)
- **`unlock_receiver`**: Timestamp when receiver can accept (0 = no time lock)
- **`redeemed`**: Timestamp when transaction was redeemed (0 = not redeemed)
- **`active`**: Boolean indicating if transaction is still active
- **`amount_hash`**: Zero-knowledge proof hash of the amount
- **`obligation_address`**: Contract address for the obligation (if any)
- **`obligation_id`**: Obligation identifier (0 = instant payment, non-zero = contract/obligation)
- **`swap_address`**: Swap contract address for this transaction
- **`swap_id`**: Swap identifier (0 for non-swap transactions)
- **`denomination`**: Token contract address for this transaction
- **`obligor`**: Obligor address for this transaction
- **`oracle_address`**: Oracle contract address for conditional release
- **`oracle_owner`**: Owner of the oracle contract
- **`oracle_key_sender`**: Oracle key that sender must satisfy
- **`oracle_value_sender`**: Required oracle value for sender condition
- **`oracle_key_recipient`**: Oracle key that recipient must satisfy  
- **`oracle_value_recipient`**: Required oracle value for recipient condition

**Note:** Instant payments have `obligation_id = "0"` and typically have minimal oracle requirements. Contract-based obligations have non-zero `obligation_id` and may include oracle conditions for conditional release.

---

## 4. Get Contracts by Entity

Get contracts for a specific entity:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "query GetEntityContracts($entityId: ID!) { contractFlow { coreContracts { byEntityId(entityId: $entityId) { id name description status contractType manager { id name } currency startDate expiryDate createdAt parties { id entity { id name } role } payments { id amount assetId paymentType status dueDate token { chainId address id } payee { entity { id name } wallet { id name } token { chainId address id } } payer { entity { id name } wallet { id name } token { chainId address id } } description } } } } }",
    "variables": {
      "entityId": "2cee226b-f69a-4385-bb2c-22ecc61eedcc"
    }
  }'
```

**Response (showing 2 of 5 contracts for brevity):**
```json
{
  "data": {
    "contractFlow": {
      "coreContracts": {
        "byEntityId": [
          {
            "id": "CONTRACT-DEPOSIT-1760931346780",
            "name": "DEPOSIT Contract - 2025-10-20 03:35:46",
            "description": "DEPOSIT contract for 225 tokens to account 0x207bbca7acd050e67e311a45175a8cb0cb0b7396",
            "status": "COMPLETED",
            "contractType": "OTHER",
            "manager": {
              "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
              "name": "issuer@yieldfabric.com",
              "__typename": "Entity"
            },
            "currency": "aud-token-asset",
            "startDate": "2025-10-20T03:35:46.791638611+00:00",
            "expiryDate": "2025-10-21T03:35:46.791638667+00:00",
            "createdAt": "2025-10-20T03:48:05.002844319+00:00",
            "parties": [
              {
                "id": "CONTRACT-DEPOSIT-1760931346780-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                "entity": {
                  "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                  "name": "issuer@yieldfabric.com",
                  "__typename": "Entity"
                },
                "role": "ISSUER",
                "__typename": "Party"
              }
            ],
            "payments": [
              {
                "id": "PAY-DEPOSIT-1760931347129",
                "amount": 225,
                "assetId": "aud-token-asset",
                "paymentType": "PAYABLE",
                "status": "COMPLETED",
                "dueDate": "2025-10-20T03:48:04.756700864+00:00",
                "token": null,
                "payee": {
                  "entity": {
                    "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                    "name": "issuer@yieldfabric.com",
                    "__typename": "Entity"
                  },
                  "wallet": {
                    "id": "WLT-USER-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                    "name": "Personal Account",
                    "__typename": "Wallet"
                  },
                  "token": null,
                  "__typename": "PaymentParty"
                },
                "payer": {
                  "entity": {
                    "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                    "name": "issuer@yieldfabric.com",
                    "__typename": "Entity"
                  },
                  "wallet": {
                    "id": "WLT-USER-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                    "name": "Personal Account",
                    "__typename": "Wallet"
                  },
                  "token": null,
                  "__typename": "PaymentParty"
                },
                "description": "DEPOSIT of 225 to account 0x207bbca7acd050e67e311a45175a8cb0cb0b7396",
                "__typename": "Payment"
              }
            ],
            "__typename": "Contract"
          },
          {
            "id": "CONTRACT-OBLIGATION-1760932171982",
            "name": "Annuity Stream",
            "description": "Annuity Stream Obligation",
            "status": "ACTIVE",
            "contractType": "OTHER",
            "manager": {
              "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
              "name": "issuer@yieldfabric.com",
              "__typename": "Entity"
            },
            "currency": "aud-token-asset",
            "startDate": "2025-10-20T03:49:31.982912978+00:00",
            "expiryDate": "2025-11-01T23:59:59+00:00",
            "createdAt": "2025-10-20T03:51:21.338337113+00:00",
            "parties": [
              {
                "id": "CONTRACT-OBLIGATION-1760932171982-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                "entity": {
                  "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                  "name": "issuer@yieldfabric.com",
                  "__typename": "Entity"
                },
                "role": "COUNTERPARTY",
                "__typename": "Party"
              },
              {
                "id": "CONTRACT-OBLIGATION-1760932171982-2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                "entity": {
                  "id": "2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                  "name": "counterpart@yieldfabric.com",
                  "__typename": "Entity"
                },
                "role": "ISSUER",
                "__typename": "Party"
              }
            ],
            "payments": [
              {
                "id": "PAY-INITIAL-CONTRACT-OBLIGATION-1760932171982-0",
                "amount": 5,
                "assetId": "aud-token-asset",
                "paymentType": "PAYABLE",
                "status": "PROCESSING",
                "dueDate": "2025-11-01T00:00:00+00:00",
                "token": null,
                "payee": {
                  "entity": {
                    "id": "2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                    "name": "counterpart@yieldfabric.com",
                    "__typename": "Entity"
                  },
                  "wallet": {
                    "id": "WLT-USER-2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                    "name": "Personal Account",
                    "__typename": "Wallet"
                  },
                  "token": null,
                  "__typename": "PaymentParty"
                },
                "payer": {
                  "entity": {
                    "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                    "name": "issuer@yieldfabric.com",
                    "__typename": "Entity"
                  },
                  "wallet": {
                    "id": "WLT-USER-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                    "name": "Personal Account",
                    "__typename": "Wallet"
                  },
                  "token": null,
                  "__typename": "PaymentParty"
                },
                "description": "Initial payment 1 for contract CONTRACT-OBLIGATION-1760932171982",
                "__typename": "Payment"
              }
            ],
            "__typename": "Contract"
          }
        ],
        "__typename": "CoreContractsQuery"
      },
      "__typename": "ContractFlowQuery"
    }
  }
}
```

**Contract Types Shown:**
- **DEPOSIT**: Completed deposit contract with single payment
- **OBLIGATION (Annuity Stream)**: Active contract with multiple scheduled payments (showing 1 of 5)
- Other types in full response: INSTANT, OBLIGATION (Redemption), SWAP_PAYMENT

**Key Fields:**
- **`status`**: `COMPLETED`, `ACTIVE`, `PENDING`, etc.
- **`contractType`**: Type classification (e.g., `OTHER`, `ServiceAgreement`)
- **`manager`**: Entity managing the contract
- **`parties`**: Array of entities involved with their roles (`ISSUER`, `COUNTERPARTY`, `PAYER`, `PAYEE`)
- **`payments`**: Associated payments with full details including:
  - `paymentType`: `PAYABLE` (outgoing) or `RECEIVABLE` (incoming)
  - `status`: `COMPLETED`, `PROCESSING`, `PENDING`, etc.
  - `token`: On-chain token information (if completed), `null` if pending
  - `payee`/`payer`: Full entity and wallet details for both parties

---

## 5. Get Payments

Fetch all payments for an entity:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "query GetTransactions($currentEntityId: ID) { paymentsByEntity(currentEntityId: $currentEntityId) { id amount assetId asset { id name assetType currency } paymentType status dueDate unlockSender unlockReceiver description contractId createdAt token { chainId address id } payee { entity { id name } wallet { id name } token { chainId address id } } payer { entity { id name } wallet { id name } token { chainId address id } } } }",
    "variables": {
      "currentEntityId": "2cee226b-f69a-4385-bb2c-22ecc61eedcc"
    }
  }'
```

**Response (showing 3 of 9 payments for brevity):**
```json
{
  "paymentsByEntity": [
    {
      "id": "PAY-DEPOSIT-1760931347129",
      "amount": 225,
      "assetId": "aud-token-asset",
      "asset": {
        "id": "aud-token-asset",
        "name": "AUD Token",
        "assetType": "CASH",
        "currency": "AUD",
        "__typename": "Asset"
      },
      "paymentType": "PAYABLE",
      "status": "COMPLETED",
      "dueDate": "2025-10-20T03:48:04.756700864+00:00",
      "unlockSender": null,
      "unlockReceiver": null,
      "description": "DEPOSIT of 225 to account 0x207bbca7acd050e67e311a45175a8cb0cb0b7396",
      "contractId": "CONTRACT-DEPOSIT-1760931346780",
      "createdAt": "2025-10-20T03:48:04.771157268+00:00",
      "token": null,
      "payee": {
        "entity": {
          "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
          "name": "issuer@yieldfabric.com",
          "__typename": "Entity"
        },
        "wallet": {
          "id": "WLT-USER-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
          "name": "Personal Account",
          "__typename": "Wallet"
        },
        "token": null,
        "__typename": "PaymentParty"
      },
      "payer": {
        "entity": {
          "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
          "name": "issuer@yieldfabric.com",
          "__typename": "Entity"
        },
        "wallet": {
          "id": "WLT-USER-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
          "name": "Personal Account",
          "__typename": "Wallet"
        },
        "token": null,
        "__typename": "PaymentParty"
      },
      "__typename": "Payment"
    },
    {
      "id": "PAY-INITIAL-CONTRACT-OBLIGATION-1760932171982-0",
      "amount": 5,
      "assetId": "aud-token-asset",
      "asset": {
        "id": "aud-token-asset",
        "name": "AUD Token",
        "assetType": "CASH",
        "currency": "AUD",
        "__typename": "Asset"
      },
      "paymentType": "PAYABLE",
      "status": "PROCESSING",
      "dueDate": "2025-11-01T00:00:00+00:00",
      "unlockSender": "2025-11-01T00:00:00+00:00",
      "unlockReceiver": "2025-11-01T00:00:00+00:00",
      "description": "Initial payment 1 for contract CONTRACT-OBLIGATION-1760932171982",
      "contractId": "CONTRACT-OBLIGATION-1760932171982",
      "createdAt": "2025-10-20T03:51:21.985640137+00:00",
      "token": null,
      "payee": {
        "entity": {
          "id": "2b5c7a69-5c2c-44f3-b621-6c0438d679be",
          "name": "counterpart@yieldfabric.com",
          "__typename": "Entity"
        },
        "wallet": {
          "id": "WLT-USER-2b5c7a69-5c2c-44f3-b621-6c0438d679be",
          "name": "Personal Account",
          "__typename": "Wallet"
        },
        "token": null,
        "__typename": "PaymentParty"
      },
      "payer": {
        "entity": {
          "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
          "name": "issuer@yieldfabric.com",
          "__typename": "Entity"
        },
        "wallet": {
          "id": "WLT-USER-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
          "name": "Personal Account",
          "__typename": "Wallet"
        },
        "token": null,
        "__typename": "PaymentParty"
      },
      "__typename": "Payment"
    },
    {
      "id": "PAY-INSTANT-1760932133588",
      "amount": 100,
      "assetId": "aud-token-asset",
      "asset": {
        "id": "aud-token-asset",
        "name": "AUD Token",
        "assetType": "CASH",
        "currency": "AUD",
        "__typename": "Asset"
      },
      "paymentType": "PAYABLE",
      "status": "COMPLETED",
      "dueDate": "2025-10-20T03:49:03.807744427+00:00",
      "unlockSender": null,
      "unlockReceiver": null,
      "description": "Send payment from 0x207bbca7acd050e67e311a45175a8cb0cb0b7396 to 0xfbc4e5c907bc67c7f47393b8082ce05b0111fb19",
      "contractId": "CONTRACT-INSTANT-1760932133267",
      "createdAt": "2025-10-20T03:49:21.791216299+00:00",
      "token": {
        "chainId": "153",
        "address": "0x373a54221cc0f483757f527a4f586ff2b804833f8afbecbfc22476a5806dd0dc",
        "id": "PAY-INSTANT-1760932133588-payment-token",
        "__typename": "Token"
      },
      "payee": {
        "entity": {
          "id": "2b5c7a69-5c2c-44f3-b621-6c0438d679be",
          "name": "counterpart@yieldfabric.com",
          "__typename": "Entity"
        },
        "wallet": {
          "id": "WLT-USER-2b5c7a69-5c2c-44f3-b621-6c0438d679be",
          "name": "Personal Account",
          "__typename": "Wallet"
        },
        "token": {
          "chainId": "153",
          "address": "0x373a54221cc0f483757f527a4f586ff2b804833f8afbecbfc22476a5806dd0dc",
          "id": "PAY-INSTANT-1760932133588-payment-token",
          "__typename": "Token"
        },
        "__typename": "PaymentParty"
      },
      "payer": {
        "entity": {
          "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
          "name": "issuer@yieldfabric.com",
          "__typename": "Entity"
        },
        "wallet": {
          "id": "WLT-USER-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
          "name": "Personal Account",
          "__typename": "Wallet"
        },
        "token": {
          "chainId": "153",
          "address": "0x373a54221cc0f483757f527a4f586ff2b804833f8afbecbfc22476a5806dd0dc",
          "id": "PAY-INSTANT-1760932133588-payment-token",
          "__typename": "Token"
        },
        "__typename": "PaymentParty"
      },
      "__typename": "Payment"
    }
  ]
}
```

**Payment Types Shown:**
- **DEPOSIT**: Completed deposit payment (225 tokens) with `unlockSender`/`unlockReceiver` as `null` (no time locks)
- **OBLIGATION**: Processing obligation payment (5 tokens) from annuity stream with time locks (due Nov 1)
- **INSTANT**: Completed instant payment (100 tokens) with on-chain `token` data
- Other types in full response: Additional obligation payments (4 more), SWAP_PAYMENT (receivable)

**Key Fields:**
- **`paymentType`**: 
  - `PAYABLE` = Outgoing payment (you are the payer)
  - `RECEIVABLE` = Incoming payment (you are the payee)
- **`status`**: 
  - `COMPLETED` = Payment finalized on-chain
  - `PROCESSING` = Payment scheduled/pending execution
- **`unlockSender`/`unlockReceiver`**: Time lock dates (ISO 8601 format), `null` = no time lock
- **`token`**: On-chain token data with `chainId`, `address`, and `id` (populated when `COMPLETED`, `null` when `PROCESSING`)
- **`asset`**: Asset metadata including `name`, `assetType` (e.g., `CASH`), and `currency`
- **`contractId`**: Associated contract ID for tracking related payments
- **`payee`/`payer`**: Complete party information including entity, wallet, and token details

---

## 6. Create Contract

Create a new contract/obligation:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { createObligation(input: { counterpart: \"counterpart@yieldfabric.com\", denomination: \"aud-token-asset\", obligor: \"issuer@yieldfabric.com\", notional: \"100\", expiry: \"2025-11-01T23:59:59+00:00\", idempotencyKey: \"unique-key-123\" }) { success message accountAddress obligationResult messageId contractId transactionId signature timestamp idHash } }"
  }'
```

**Response:**
```json
{
  "data": {
    "createObligation": {
      "success": true,
      "message": "Obligation created successfully",
      "accountAddress": "0x1234...",
      "obligationResult": "...",
      "messageId": "msg-123",
      "contractId": "contract-456",
      "transactionId": "tx-789",
      "signature": "0xabcd...",
      "timestamp": "2025-10-19T12:00:00Z",
      "idHash": "hash-abc"
    }
  }
}
```

**Required Input:**
- `denomination`: Asset ID (e.g., `"aud-token-asset"`)
- `counterpart`: Entity name/email of the counterparty (or use `counterpartWalletId` for direct wallet ID)

**Optional Input:**
- `obligor`: Entity name/email of the obligor (or use `obligorWalletId` for direct wallet ID)
- `obligationAddress`: Specific obligation address (if not provided, uses your account address)
- `notional`: Total notional value of the obligation
- `expiry`: Expiry date in ISO 8601 format
- `data`: Custom JSON data for the contract
- `initialPayments`: Initial payment structure with amount and payment details
- `idempotencyKey`: Unique key for duplicate prevention

---

## 7. Get Contract by ID

**Using GraphQL query with variables** (recommended):

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "query GetContract($id: ID!) { contractFlow { coreContracts { all { id name description status contractType currency startDate expiryDate parties { id entity { id name } role } payments { id amount status } } } } }"
  }'
```

Then filter by ID in your application, or use the full contracts list above.

---

## 8. Create Instant Payment

Send an instant payment to another entity:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { instant(input: { assetId: \"aud-token-asset\", amount: \"10\", destinationId: \"counterpart@yieldfabric.com\", idempotencyKey: \"instant-payment-001\" }) { success message accountAddress destinationId idHash messageId paymentId sendResult timestamp } }"
  }'
```

**Alternative with destination wallet ID:**
```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { instant(input: { assetId: \"aud-token-asset\", amount: \"10\", destinationWalletId: \"wallet-id-here\", idempotencyKey: \"instant-payment-002\" }) { success message accountAddress destinationId idHash messageId paymentId sendResult timestamp } }"
  }'
```

**Response:**
```json
{
  "data": {
    "instant": {
      "success": true,
      "message": "Send message submitted successfully",
      "accountAddress": "0x0620cFad3f9798FA036a0795e70661a98feDE9D4",
      "destinationId": "counterpart@yieldfabric.com",
      "idHash": "0xabc...",
      "messageId": "95e7ef5e-baca-49d7-9917-76f45b644915",
      "paymentId": "PAY-INSTANT-1759048183145",
      "sendResult": "...",
      "timestamp": "2025-10-19T12:00:00Z"
    }
  }
}
```

**Important Notes:**
- `amount` must be an **integer string** (e.g., `"10"`, NOT `"10.00"`)
- Either `destinationId` (entity name/email) OR `destinationWalletId` (wallet ID) is required
- `assetId` options: `"aud-token-asset"`, `"usd-token-asset"`, etc.
- `idempotencyKey` ensures duplicate prevention

---

## 9. Accept Payment

Accept a pending payment:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { accept(input: { paymentId: \"PAY-INSTANT-1759048183145\", idempotencyKey: \"accept-payment-001\" }) { success message accountAddress idHash acceptResult messageId timestamp } }"
  }'
```

**Response:**
```json
{
  "data": {
    "accept": {
      "success": true,
      "message": "Accept message submitted successfully",
      "accountAddress": "0x0620cFad3f9798FA036a0795e70661a98feDE9D4",
      "idHash": "0xabc123...",
      "acceptResult": "...",
      "messageId": "msg-456",
      "timestamp": "2025-10-19T12:00:00Z"
    }
  }
}
```

**Required Input:**
- `paymentId`: The payment ID to accept (use `id_hash` from balance locked_in transactions)
- `idempotencyKey`: Unique key to prevent duplicate accepts (optional)

---

## 10. Get Swaps by Entity

Get all swaps for a specific entity:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "query GetSwaps($entityId: ID!) { swapFlow { coreSwaps { byEntityId(entityId: $entityId) { id swapId swapType status deadline createdAt parties { id entity { id name } role } initiatorObligationIds counterpartyObligationIds paymentIds payments { id amount assetId paymentType status dueDate unlockSender unlockReceiver description contractId createdAt asset { id name assetType currency } token { chainId address id } payee { entity { id name } wallet { id name } token { chainId address id } } payer { entity { id name } wallet { id name } token { chainId address id } } } } } } }",
    "variables": {
      "entityId": "2cee226b-f69a-4385-bb2c-22ecc61eedcc"
    }
  }'
```

**Response:**
```json
{
  "data": {
    "swapFlow": {
      "coreSwaps": {
        "byEntityId": [
          {
            "id": "123456789",
            "swapId": "123456789",
            "swapType": "CONFIGURABLE",
            "status": "COMPLETED",
            "deadline": "2025-11-10T23:59:59+00:00",
            "createdAt": "2025-10-20T03:51:25.797693681+00:00",
            "parties": [
              {
                "id": "123456789-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                "entity": {
                  "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                  "name": "issuer@yieldfabric.com",
                  "__typename": "Entity"
                },
                "role": "INITIATOR",
                "__typename": "SwapParty"
              },
              {
                "id": "123456789-2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                "entity": {
                  "id": "2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                  "name": "counterpart@yieldfabric.com",
                  "__typename": "Entity"
                },
                "role": "COUNTERPARTY",
                "__typename": "SwapParty"
              }
            ],
            "initiatorObligationIds": [
              "CONTRACT-OBLIGATION-1760932171982",
              "CONTRACT-OBLIGATION-1760932212849"
            ],
            "counterpartyObligationIds": [],
            "paymentIds": [
              "PAY-SWAP-123456789-0-1760932285444"
            ],
            "payments": [
              {
                "id": "PAY-SWAP-123456789-0-1760932285444",
                "amount": 100,
                "assetId": "aud-token-asset",
                "paymentType": "RECEIVABLE",
                "status": "COMPLETED",
                "dueDate": "2025-10-20T03:51:25.467436455+00:00",
                "unlockSender": null,
                "unlockReceiver": null,
                "description": "SWAP_PAYMENT of 100 to account 0xfbc4e5c907bc67c7f47393b8082ce05b0111fb19",
                "contractId": "CONTRACT-SWAP_PAYMENT-1760932285124",
                "createdAt": "2025-10-20T03:51:25.486221774+00:00",
                "asset": {
                  "id": "aud-token-asset",
                  "name": "AUD Token",
                  "assetType": "CASH",
                  "currency": "AUD",
                  "__typename": "Asset"
                },
                "token": {
                  "chainId": "153",
                  "address": "0xe764F77fbCa499E29Ec2B58506fB21CbE4BC2916",
                  "id": "AUD-token",
                  "__typename": "Token"
                },
                "payee": {
                  "entity": {
                    "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                    "name": "issuer@yieldfabric.com",
                    "__typename": "Entity"
                  },
                  "wallet": {
                    "id": "WLT-USER-2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                    "name": "Personal Account",
                    "__typename": "Wallet"
                  },
                  "token": {
                    "chainId": "153",
                    "address": "0xe764F77fbCa499E29Ec2B58506fB21CbE4BC2916",
                    "id": "AUD-token",
                    "__typename": "Token"
                  },
                  "__typename": "PaymentParty"
                },
                "payer": {
                  "entity": {
                    "id": "2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                    "name": "counterpart@yieldfabric.com",
                    "__typename": "Entity"
                  },
                  "wallet": {
                    "id": "WLT-USER-2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                    "name": "Personal Account",
                    "__typename": "Wallet"
                  },
                  "token": {
                    "chainId": "153",
                    "address": "0xe764F77fbCa499E29Ec2B58506fB21CbE4BC2916",
                    "id": "AUD-token",
                    "__typename": "Token"
                  },
                  "__typename": "PaymentParty"
                },
                "__typename": "Payment"
              }
            ],
            "__typename": "Swap"
          }
        ],
        "__typename": "CoreSwapsQuery"
      },
      "__typename": "SwapFlowQuery"
    }
  }
}
```

**Swap Structure:**
- **`swapType`**: Type of swap (e.g., `CONFIGURABLE`)
- **`status`**: Current swap status (`COMPLETED`, `PENDING`, `ACTIVE`)
- **`deadline`**: Swap deadline in ISO 8601 format
- **`parties`**: Array of swap participants with roles:
  - `INITIATOR`: The entity that created the swap
  - `COUNTERPARTY`: The entity participating in the swap
- **`initiatorObligationIds`**: Contract IDs that the initiator is swapping (obligations to settle)
- **`counterpartyObligationIds`**: Contract IDs that the counterparty is swapping
- **`paymentIds`**: IDs of payments created as part of the swap settlement
- **`payments`**: Full payment details for swap-related payments

**Swap Example Explained:**
This example shows a completed swap where:
- The initiator (`issuer@yieldfabric.com`) exchanged 2 obligations for 100 AUD tokens
- The counterparty (`counterpart@yieldfabric.com`) paid 100 AUD tokens
- The swap resulted in 1 payment (`RECEIVABLE` from initiator's perspective)
- Status is `COMPLETED` with on-chain token data populated

---

## 11. Create Atomic Swap

Create a swap to exchange obligations for payment:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation($counterpartyExpectedPayments: InitialPaymentsInput) { createSwap(input: { swapId: \"123456789\", counterparty: \"counterpart@yieldfabric.com\", deadline: \"2025-11-10\", initiatorObligationIds: [\"CONTRACT-OBLIGATION-1760932171982\", \"CONTRACT-OBLIGATION-1760932212849\"], counterpartyExpectedPayments: $counterpartyExpectedPayments }) { success message swapId messageId transactionId signature timestamp } }",
    "variables": {
      "counterpartyExpectedPayments": {
        "denomination": "aud-token-asset",
        "amount": "100",
        "payments": [
          { "oracleAddress": null, "oracleOwner": null, "oracleKeySender": "0", "oracleValueSenderSecret": "0", "oracleKeyRecipient": "0", "oracleValueRecipientSecret": "0", "unlockSender": null, "unlockReceiver": null }
        ]
      }
    }
  }'
```

**Response:**
```json
{
  "data": {
    "createSwap": {
      "success": true,
      "message": "Swap created successfully",
      "swapId": "123456789",
      "messageId": "msg-swap-123",
      "transactionId": "TXN-SWAP-123",
      "signature": "0xabc...",
      "timestamp": "2025-10-20T03:51:25.797693681+00:00"
    }
  }
}
```

**Required Input:**
- `swapId`: Unique identifier for the swap
- `counterparty`: Entity name/email of the counterparty (or use `counterpartyWalletId`)
- `deadline`: Swap expiration date in ISO 8601 format

**Optional Input:**
- `initiatorObligationIds`: Array of contract IDs the initiator is offering
- `counterpartyExpectedPayments`: Payment details expected from counterparty (amount, denomination, payments array)
- `idempotencyKey`: Unique key for duplicate prevention

---

## 12. Complete Swap

Complete a swap by providing the required payment:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { completeSwap(input: { swapId: \"123456789\" }) { success message swapId messageId transactionId signature timestamp } }"
  }'
```

**Response:**
```json
{
  "data": {
    "completeSwap": {
      "success": true,
      "message": "Swap completed successfully",
      "swapId": "123456789",
      "messageId": "msg-complete-123",
      "transactionId": "TXN-COMPLETE-123",
      "signature": "0xdef...",
      "timestamp": "2025-10-20T03:51:28.040236966+00:00"
    }
  }
}
```

**Required Input:**
- `swapId`: The swap ID to complete

**Optional Input:**
- `idempotencyKey`: Unique key for duplicate prevention

**Note:** The `completeSwap` mutation retrieves the expected payment details from the stored swap data, so you only need to provide the `swapId`.

---

## 13. Create Distribution (One-to-Many Payment)

Send tokens to multiple recipients in a single operation using Merkle trees:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { createDistribution(input: { assetId: \"aud-token-asset\", recipients: [{ address: \"0xRecipient1Address\", amount: \"50\" }, { address: \"0xRecipient2Address\", amount: \"30\" }, { address: \"0xRecipient3Address\", amount: \"20\" }] }) { success message messageId accountAddress transactionId signature } }"
  }' | jq
```

**Required Input:**
- `assetId`: Asset/denomination ID
- `recipients`: Array of `{ address, amount }` pairs

**Optional Input:**
- `obligor`: Obligor entity (defaults to sender)
- `walletId`: Sender wallet to use
- `idempotencyKey`: Unique key for duplicate prevention
- `requireManualSignature`: Route to manual signing UX

**Each recipient** accepts their share using the standard `accept` mutation. The sender can cancel the distribution only if **no recipient** has claimed yet.

**NFT Recipients:** Set `obligationId` to a non-zero token ID to make the claim available to the NFT owner (`ownerOf(address, obligationId)`) at claim time.

---

## 14. Deposit Funds

Deposit tokens into your intelligent account:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { deposit(input: { assetId: \"aud-token-asset\", amount: \"100\" }) { success message messageId accountAddress } }"
  }' | jq
```

---

## 15. Withdraw Funds

Withdraw tokens from your intelligent account:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { withdraw(input: { assetId: \"aud-token-asset\", amount: \"50\" }) { success message messageId accountAddress } }"
  }' | jq
```

---

## 16. Batch Accept All Payments

Accept all pending payables for a given denomination in a single call:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { acceptAll(input: { denomination: \"aud-token-asset\" }) { success message totalAccepted paymentIds } }"
  }' | jq
```

**Optional Input:**
- `obligor`: Filter by obligor entity
- `walletId`: Scope to a specific wallet

---

## 17. Repurchase Collateral (Repo Swap)

Repurchase collateral from a repo swap before expiry:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { repurchaseSwap(input: { swapId: \"REPO-SWAP-001\" }) { success message swapId messageId transactionId signature } }"
  }' | jq
```

---

## 18. Roll a Repo (Two-Step Process)

**Step 1: Initiate Roll** — Creates a new swap in Pending state:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation($input: RollRepoInput!) { initiateRoll(input: $input) { success message newSwapId messageId } }",
    "variables": {
      "input": {
        "oldSwapId": "REPO-SWAP-001",
        "newSwapId": "REPO-SWAP-002",
        "newCounterparty": "new-counterparty@yieldfabric.com",
        "newDeadline": "2025-12-31"
      }
    }
  }' | jq
```

**Step 2: Complete Roll** — Counterparty pays upfront, old repo repurchased, collateral migrated:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $COUNTERPARTY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { completeRoll(input: { newSwapId: \"REPO-SWAP-002\" }) { success message newSwapId accountAddress messageId transactionId signature } }"
  }' | jq
```

---

## 19. Annuity Settlement Workflow

This example demonstrates how to create and settle an annuity using self-referential obligations and atomic swaps:

**Step 1: Create annuity stream obligation (5 AUD over 5 days)**

Issuer creates obligation with **themselves as both obligor AND counterpart** to build structure without counterparty risk:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation($initialPayments: InitialPaymentsInput, $data: JSON) { createObligation(input: { counterpart: \"issuer@yieldfabric.com\", denomination: \"aud-token-asset\", obligor: \"issuer@yieldfabric.com\", notional: \"5\", expiry: \"2025-11-01\", data: $data, initialPayments: $initialPayments }) { success contractId messageId } }",
    "variables": {
      "data": { "name": "Annuity Stream", "description": "Annuity Stream Obligation" },
      "initialPayments": {
        "amount": "5",
        "payments": [
          { "oracleAddress": null, "oracleOwner": null, "oracleKeySender": "0", "oracleValueSenderSecret": "0", "oracleKeyRecipient": "0", "oracleValueRecipientSecret": "0", "unlockSender": "2025-11-01T00:00:00+00:00", "unlockReceiver": "2025-11-01T00:00:00+00:00" },
          { "oracleAddress": null, "oracleOwner": null, "oracleKeySender": "0", "oracleValueSenderSecret": "0", "oracleKeyRecipient": "0", "oracleValueRecipientSecret": "0", "unlockSender": "2025-11-02T00:00:00+00:00", "unlockReceiver": "2025-11-02T00:00:00+00:00" },
          { "oracleAddress": null, "oracleOwner": null, "oracleKeySender": "0", "oracleValueSenderSecret": "0", "oracleKeyRecipient": "0", "oracleValueRecipientSecret": "0", "unlockSender": "2025-11-03T00:00:00+00:00", "unlockReceiver": "2025-11-03T00:00:00+00:00" },
          { "oracleAddress": null, "oracleOwner": null, "oracleKeySender": "0", "oracleValueSenderSecret": "0", "oracleKeyRecipient": "0", "oracleValueRecipientSecret": "0", "unlockSender": "2025-11-04T00:00:00+00:00", "unlockReceiver": "2025-11-04T00:00:00+00:00" },
          { "oracleAddress": null, "oracleOwner": null, "oracleKeySender": "0", "oracleValueSenderSecret": "0", "oracleKeyRecipient": "0", "oracleValueRecipientSecret": "0", "unlockSender": "2025-11-05T00:00:00+00:00", "unlockReceiver": "2025-11-05T00:00:00+00:00" }
        ]
      }
    }
  }'
```

**Step 2: Accept the annuity stream obligation**

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { acceptObligation(input: { contractId: \"CONTRACT-OBLIGATION-1760932171982\" }) { success message obligationId messageId } }"
  }'
```

**Step 3: Create redemption obligation (100 AUD)**

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation($initialPayments: InitialPaymentsInput, $data: JSON) { createObligation(input: { counterpart: \"issuer@yieldfabric.com\", denomination: \"aud-token-asset\", obligor: \"issuer@yieldfabric.com\", notional: \"100\", expiry: \"2025-11-01\", data: $data, initialPayments: $initialPayments }) { success contractId messageId } }",
    "variables": {
      "data": { "name": "Redemption", "description": "Redemption Obligation" },
      "initialPayments": {
        "amount": "100",
        "payments": [
          { "oracleAddress": null, "oracleOwner": null, "oracleKeySender": "0", "oracleValueSenderSecret": "0", "oracleKeyRecipient": "0", "oracleValueRecipientSecret": "0", "unlockSender": "2025-11-06T00:00:00+00:00", "unlockReceiver": "2025-11-06T00:00:00+00:00" }
        ]
      }
    }
  }'
```

**Step 4: Accept the redemption obligation**

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { acceptObligation(input: { contractId: \"CONTRACT-OBLIGATION-1760932212849\" }) { success message obligationId messageId } }"
  }'
```

**Step 5: Create atomic swap (exchange obligations for upfront payment)**

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation($counterpartyExpectedPayments: InitialPaymentsInput) { createSwap(input: { swapId: \"123456789\", counterparty: \"counterpart@yieldfabric.com\", deadline: \"2025-11-10\", initiatorObligationIds: [\"CONTRACT-OBLIGATION-1760932171982\", \"CONTRACT-OBLIGATION-1760932212849\"], counterpartyExpectedPayments: $counterpartyExpectedPayments }) { success message swapId messageId } }",
    "variables": {
      "counterpartyExpectedPayments": {
        "denomination": "aud-token-asset",
        "amount": "100",
        "payments": [
          { "oracleAddress": null, "oracleOwner": null, "oracleKeySender": "0", "oracleValueSenderSecret": "0", "oracleKeyRecipient": "0", "oracleValueRecipientSecret": "0", "unlockSender": null, "unlockReceiver": null }
        ]
      }
    }
  }'
```

**Step 6: Counterpart completes the swap (pays 100 AUD upfront)**

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $COUNTERPART_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { completeSwap(input: { swapId: \"123456789\" }) { success message swapId messageId } }"
  }'
```

**Workflow Explanation:**

This demonstrates an **annuity securitization** where:

1. **Create Self-Referential Obligations**:
   - Issuer creates obligations with **themselves as both obligor AND counterpart**
   - **Annuity Stream**: 5 tokens paid over 5 days (Nov 1-5)
   - **Redemption**: 100 tokens paid on Nov 6
   - Total obligation value: 105 tokens
   - This creates the payment structure **without counterparty risk**

2. **Accept Obligations**: 
   - Issuer accepts their own obligations (commits to the payment schedule)
   - Structure is now locked and ready for transfer

3. **Create Atomic Swap**: 
   - Issuer offers both obligations to the actual counterparty
   - In exchange for 100 tokens upfront (instant payment, no obligor)
   - Swap transfers obligation ownership atomically

4. **Complete Swap**: 
   - Counterpart pays 100 tokens immediately
   - Receives ownership rights to both obligations (105 tokens total)
   - Settlement is **secure and atomic** - both transfers happen simultaneously or not at all

**Economic Result:**
- **Issuer**: Receives 100 tokens immediately (liquidity), owes 105 tokens over time (obligor)
- **Counterpart**: Pays 100 tokens upfront, receives 105 tokens over time (5% yield, no credit risk to issuer)

**Key Security Features:**
- **Self-referential structure**: Issuer creates obligations with themselves as counterpart (no external dependency)
- **Atomic swap**: Obligations transfer to counterparty only when payment is received
- **No counterparty risk during creation**: Structure is built independently before involving external party
- **Instant settlement**: Counterpart's payment has no obligor (unconditional, immediate)
- **Bilateral commitment**: Both parties exchange simultaneously or transaction fails

This pattern enables **secure securitization**: The issuer pre-packages future payment obligations and atomically exchanges them for immediate liquidity, while the counterparty gets a yield-bearing asset with guaranteed delivery.

---

## Common Headers

All authenticated requests require:

```bash
-H "Authorization: Bearer $TOKEN"
-H "Content-Type: application/json"
```

---

## Quick Reference

### Auth Service
- `POST /auth/login/with-services` — Login with service selection
- `POST /auth/refresh` — Refresh access token
- `GET /auth/users/me` — Get user profile
- `POST /auth/logout` — Logout current device
- `POST /auth/logout-all` — Logout all devices
- `POST /auth/delegation/jwt` — Create delegation JWT
- `POST /auth/delegation/tokens` — Create delegation token
- `GET /auth/delegation/tokens` — List delegation tokens
- `DELETE /auth/delegation/tokens/{id}` — Revoke delegation token
- `POST /auth/users` — Create user
- `POST /auth/users/:user_id/deploy-account` — Deploy user account
- `POST /auth/api-key` — Authenticate with API key
- `POST /auth/api-key/generate` — Generate API key

### Payments/GraphQL Service
- `GET /balance?denomination={asset}&obligor={obligor}&group_id={group_id}` — Get balance
- `POST /graphql` — GraphQL endpoint for:
  - **Queries:** `contractFlow.coreContracts`, `paymentsByEntity`, `swapFlow.coreSwaps`, `entities`, `wallets`, `contracts`, `loans`, `payments`, `tokens`, `assets`, `transactions`, `entityWallets`, `health`
  - **Mutations:** `deposit`, `withdraw`, `instant`, `accept`, `acceptAll`, `createDistribution`, `createObligation`, `acceptObligation`, `transferObligation`, `cancelObligation`, `createSwap`, `completeSwap`, `cancelSwap`, `repurchaseSwap`, `initiateRoll`, `completeRoll`, `expireCollateral`, `swapObligorPayment`, `createLoan`, `updateLoan`, `acceptLoan`, `processLoan`, `executeComposedOperations`, `hidePayment`, `hideContract`

---

## Error Handling

### Common Error Responses

**401 Unauthorized:**
```json
{
  "error": "Invalid or expired token"
}
```

**403 Forbidden:**
```json
{
  "error": "Insufficient permissions"
}
```

**422 Validation Error:**
```json
{
  "error": "Invalid input: amount must be integer string"
}
```

**500 Server Error:**
```json
{
  "error": "Internal server error",
  "details": "..."
}
```

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

## Asset IDs Reference

Common asset identifiers:

- `aud-token-asset` - Australian Dollars
- `usd-token-asset` - US Dollars

---

## Chain IDs Reference

- `151` - Redbelly Mainnet (Governors)
- `153` - Redbelly Testnet (Governors)