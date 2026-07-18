# Swaps & Atomic Trading

Complete guide to YieldFabric's swap system, covering atomic swaps and repo swaps with collateral.

---

## Overview

YieldFabric's swap system enables atomic trading of obligations and payments between parties. The system supports two main types of swaps:

1. **Atomic Swaps**: Immediate execution with no collateral (expiry = 0)
2. **Repo Swaps**: Collateralized swaps with repurchase options (expiry > deadline)

**Repo rolling** allows the collateral provider (initiator) of a completed repo to move collateral into a new repo with a new counterparty and terms via a two-step flow: **initiate roll** (creates a new pending swap) and **complete roll** (new counterparty pays the original repurchase amount; old repo is repurchased and collateral migrates to the new repo). See section 5.

**Important**: Users primarily interact with swaps through the GraphQL API. The swap system provides atomic settlement guarantees, ensuring either both sides execute or neither does.

### Transaction IDs are opaque

The `transactionId` returned by a swap mutation is a chain-scoped submission
anchor. Submission anchors are UUID-backed (`TXN-{OPERATION}-{UUID}`), but the
authoritative chain is the anchor's EIP-155 scope, not a value to infer from the
ID text. Use the returned ID verbatim; do not construct or parse it.

Asynchronous post-processing can create stable transaction records for a
logical swap operation. Those deterministic IDs are explicitly chain-qualified
and have the schematic shape
`TXN-{KIND}-eip155-{CHAIN_ID}-v1-{HEX_COMPONENT}[-{HEX_COMPONENT}...]`.
Each source component is UTF-8 hex encoded separately, so these IDs are also
opaque. The same logical operation on testnet and mainnet produces distinct
IDs.

---

## Swap Types

### Atomic Swaps

Atomic swaps execute immediately upon completion with no collateral requirements:

- **Execution**: All assets transfer atomically when counterparty completes the swap
- **Deadline**: Time by which swap must be completed (acceptance window)
- **Expiry**: Always `0` (indicates no repo mechanism)
- **Collateral**: Not used for atomic swaps
- **Use Cases**: Direct obligation-for-payment exchanges, immediate settlement

**Characteristics:**
- All-or-nothing execution
- No collateral held
- Immediate settlement upon completion
- Cannot be repurchased (not applicable)

### Repo Swaps

Repo swaps include collateral that can be repurchased before expiry:

- **Execution**: Immediate swap assets transfer atomically, collateral held until expiry
- **Deadline**: Time by which swap must be completed (acceptance window)
- **Expiry**: Time after which collateral can be forfeited (must be > deadline)
- **Collateral**: Locked assets that secure the swap agreement
- **Use Cases**: Secured lending, repurchase agreements, collateralized trading

**Characteristics:**
- Immediate swap assets transfer on completion
- Collateral assets held in escrow until expiry
- Repurchase option before expiry
- Automatic forfeiture after expiry if not repurchased

---

## Swap Operations

### 1. Create Swap

Creates a swap agreement between two parties.

**GraphQL Mutation:**
```graphql
mutation CreateSwap($input: CreateSwapInput!) {
  createSwap(input: $input) {
    success
    message
    swapId
    counterparty
    swapResult
    messageId
    transactionId
    timestamp
  }
}
```

**Input Parameters:**
- `swapId`: Unique identifier for the swap (required)
- `counterparty`: Entity name/email or wallet address of counterparty (required)
- `deadline`: Swap expiration date/time - ISO 8601 format or YYYY-MM-DD (required)
- `expiry`: Repurchase deadline for repo swaps - ISO 8601 format or YYYY-MM-DD (optional)
- `initiatorObligationIds`: Contract IDs the initiator is offering (optional)
- `initiatorContractReferences`: Contract references for initiator obligations (optional)
- `initiatorExpectedPayments`: Payment details expected from initiator (optional)
- `counterpartyObligationIds`: Contract IDs the counterparty is offering (optional)
- `counterpartyContractReferences`: Contract references for counterparty obligations (optional)
- `counterpartyExpectedPayments`: Payment details expected from counterparty (optional)
- `initiatorCollateralObligationIds`: Initiator collateral obligations (optional, repo swaps)
- `initiatorCollateralContractReferences`: Initiator collateral contract references (optional)
- `initiatorCollateralPayments`: Initiator collateral payments (optional, repo swaps)
- `counterpartyCollateralObligationIds`: Counterparty collateral obligations (optional, repo swaps)
- `counterpartyCollateralContractReferences`: Counterparty collateral contract references (optional)
- `counterpartyCollateralPayments`: Counterparty collateral payments (optional, repo swaps)
- `initiatorRepurchaseObligationIds`: Obligations to provide for repurchase (optional)
- `initiatorRepurchaseContractReferences`: Initiator repurchase contract references (optional)
- `initiatorRepurchasePayments`: Payments to provide for repurchase (optional)
- `counterpartyRepurchaseObligationIds`: Obligations to provide for repurchase (optional)
- `counterpartyRepurchaseContractReferences`: Counterparty repurchase contract references (optional)
- `counterpartyRepurchasePayments`: Payments to provide for repurchase (optional)
- `idempotencyKey`: Unique key for duplicate prevention (optional)

**Rules:**
1. **Deadline**: Must be in the future (swap acceptance window)
2. **Expiry**: For repo swaps, must be `> deadline` (if provided)
3. **Collateral**: If collateral is provided, `expiry` must be set
4. **Contract Locking**: Initiator's obligations are locked after blockchain confirmation
5. **Payment Creation**: Initiator's expected payments are created during swap creation
6. **Collateral Locking**: Initiator's collateral is locked during `createSwap()`
7. **Ownership**: The initiator can only offer obligations/collateral its swap wallet HOLDs. An explicitly-named reference (a `*ContractReferences` entry with `contractId`, or a legacy `*ObligationIds` / `*CollateralObligationIds` entry) it does not hold is rejected synchronously with `"Initiator does not hold … contract <id>"` — no silent under-collateralization. A `composedContractId` reference instead silently drops un-held *nested* legs (rehypothecation), pledging only the held leg.

**Example - Atomic Swap:**
```graphql
mutation {
  createSwap(input: {
    swapId: "123456789"
    counterparty: "counterpart@yieldfabric.com"
    deadline: "2025-11-10"
    initiatorObligationIds: ["CONTRACT-OBLIGATION-1760932171982"]
    counterpartyExpectedPayments: {
      denomination: "aud-token-asset"
      amount: "100"
      payments: [{
        oracleAddress: null
        oracleOwner: null
        oracleKeySender: "0"
        oracleValueSenderSecret: "0"
        oracleKeyRecipient: "0"
        oracleValueRecipientSecret: "0"
        unlockSender: null
        unlockReceiver: null
      }]
    }
  }) {
    success
    swapId
    messageId
  }
}
```

**Example - Repo Swap:**
```graphql
mutation {
  createSwap(input: {
    swapId: "987654321"
    counterparty: "lender@yieldfabric.com"
    deadline: "2025-11-10"
    expiry: "2025-12-10"
    initiatorObligationIds: ["CONTRACT-OBLIGATION-1760932171982"]
    initiatorCollateralObligationIds: ["CONTRACT-OBLIGATION-1760932171983"]
    initiatorCollateralPayments: {
      denomination: "usd-token-asset"
      amount: "50"
      payments: [{
        oracleAddress: null
        oracleOwner: null
        oracleKeySender: "0"
        oracleValueSenderSecret: "0"
        oracleKeyRecipient: "0"
        oracleValueRecipientSecret: "0"
        unlockSender: null
        unlockReceiver: null
      }]
    }
    counterpartyExpectedPayments: {
      denomination: "aud-token-asset"
      amount: "100"
      payments: [{
        oracleAddress: null
        oracleOwner: null
        oracleKeySender: "0"
        oracleValueSenderSecret: "0"
        oracleKeyRecipient: "0"
        oracleValueRecipientSecret: "0"
        unlockSender: null
        unlockReceiver: null
      }]
    }
    initiatorRepurchasePayments: {
      denomination: "usd-token-asset"
      amount: "105"
      payments: [{
        oracleAddress: null
        oracleOwner: null
        oracleKeySender: "0"
        oracleValueSenderSecret: "0"
        oracleKeyRecipient: "0"
        oracleValueRecipientSecret: "0"
        unlockSender: null
        unlockReceiver: null
      }]
    }
  }) {
    success
    swapId
    messageId
  }
}
```

**Response:**
```json
{
  "data": {
    "createSwap": {
      "success": true,
      "message": "Create unified swap message submitted successfully",
      "swapId": "123456789",
      "counterparty": "counterpart@yieldfabric.com",
      "swapResult": "PENDING",
      "messageId": "msg-swap-123",
      "transactionId": "TXN-CREATE-SWAP-<uuid>",
      "timestamp": "2025-10-20T03:51:25.797693681+00:00"
    }
  }
}
```

---

### 2. Complete Swap

Counterparty completes the swap by providing their side of the agreement.

**GraphQL Mutation:**
```graphql
mutation CompleteSwap($input: CompleteSwapInput!) {
  completeSwap(input: $input) {
    success
    message
    swapId
    completeResult
    messageId
    transactionId
    signature
    timestamp
  }
}
```

**Input Parameters:**
- `swapId`: The swap ID to complete (required)
- `counterpartyCollateralObligationIds`: Counterparty collateral obligations (optional, repo swaps)
- `counterpartyCollateralContractReferences`: Counterparty collateral contract references (optional)
- `counterpartyCollateralPayments`: Counterparty collateral payments (optional, repo swaps)
- `idempotencyKey`: Unique key for duplicate prevention (optional)

**Rules:**
1. **Permission**: Only counterparty can call `completeSwap` (not initiator)
2. **Status**: Swap must be in `PENDING` status
3. **Deadline**: Swap must not be expired (deadline not passed)
4. **Expected Payments**: Retrieved from stored swap data (automatically)
5. **Contract Locking**: Counterparty's obligations are locked during completion
6. **Collateral Locking**: Counterparty's collateral is locked during `completeSwap()`
7. **Payment Creation**: Counterparty's expected payments are created during completion
8. **Atomic Settlement**: All immediate swap assets transfer atomically
9. **Collateral Escrow**: Collateral assets held in contract until expiry (repo swaps)

**Example:**
```graphql
mutation {
  completeSwap(input: {
    swapId: "123456789"
  }) {
    success
    swapId
    messageId
  }
}
```

**Response:**
```json
{
  "data": {
    "completeSwap": {
      "success": true,
      "message": "Complete swap message submitted successfully",
      "swapId": "123456789",
      "completeResult": "Message queued for processing with ID: msg-complete-123",
      "messageId": "msg-complete-123",
      "transactionId": "TXN-COMPLETE-SWAP-<uuid>",
      "signature": "0xdef...",
      "timestamp": "2025-10-20T03:51:28.040236966+00:00"
    }
  }
}
```

**Note:** The `completeSwap` mutation automatically retrieves expected payment details from the stored swap record, so you only need to provide the `swapId`. Counterparty collateral can be provided if required for repo swaps.

**Completing as a group account.** The counterparty can be a **group / shared account** rather than a personal wallet — it funds its `counterpartyExpectedPayments` from the group's own balance. The caller presents a **group-delegation JWT** so the bearer acts AS the group (which must be the swap's `counterparty`). In a DMS deal this is driven by the `acting_as_group` input on the `complete_swap` step (the bridge strips it and mints the delegation JWT before calling `completeSwap` — it is not a GraphQL input field). Since an expected payment is funded by whoever *completes* the swap, the payer must sit on the **counterparty/complete** side to debit value FROM a group account. This is the **loan-origination** pattern: the borrower initiates a swap offering a bare loan-agreement obligation, and the lender's funded **loan account** completes-and-pays the principal.

---

### 3. Cancel Swap

Cancels a swap, returning all locked assets to their original owners.

**GraphQL Mutation:**
```graphql
mutation CancelSwap($input: CancelSwapInput!) {
  cancelSwap(input: $input) {
    success
    message
    swapId
    cancelResult
    messageId
    transactionId
    signature
    timestamp
  }
}
```

**Input Parameters:**
- `swapId`: The swap ID to cancel (required)
- `key`: Cancellation key (optional, used for verification)
- `value`: Cancellation value (optional, used for verification)
- `idempotencyKey`: Unique key for duplicate prevention (optional)

**Rules:**
1. **Permission**: Either party can cancel a swap
2. **Status**: Swap must be in `PENDING` status
3. **Deadline Expiry**: If deadline has passed, automatically routes to `expireSwap` flow
4. **Contract Unlocking**: Contracts are unlocked after blockchain confirmation
5. **Payment Retrieval**: Payments are returned to sender's balance
6. **Collateral Unlocking**: Collateral assets are returned to original owners

**Example:**
```graphql
mutation {
  cancelSwap(input: {
    swapId: "123456789"
    key: "reason"
    value: "terms_changed"
  }) {
    success
    swapId
    messageId
  }
}
```

**Response:**
```json
{
  "data": {
    "cancelSwap": {
      "success": true,
      "message": "Cancel swap message submitted successfully",
      "swapId": "123456789",
      "cancelResult": "Message queued for processing with ID: msg-cancel-123",
      "messageId": "msg-cancel-123",
      "transactionId": "TXN-CANCEL-SWAP-<uuid>",
      "signature": "0xabc...",
      "timestamp": "2025-10-20T03:51:30.123456789+00:00"
    }
  }
}
```

**Note:** If the swap deadline has passed and status is still `PENDING`, canceling the swap automatically routes to the `expireSwap` flow, which sets the status to `EXPIRED` instead of `CANCELLED`.

---

### 4. Repurchase Swap (Repo Swaps Only)

Repurchase collateral before expiry to reclaim your locked assets.

**GraphQL Mutation:**
```graphql
mutation RepurchaseSwap($input: RepurchaseSwapInput!) {
  repurchaseSwap(input: $input) {
    success
    message
    swapId
    repurchaseResult
    messageId
    transactionId
    signature
    timestamp
  }
}
```

**Input Parameters:**
- `swapId`: The swap ID to repurchase (required)
- `repurchaseObligationIds`: Obligation IDs to provide for repurchase (optional)
- `repurchaseContractReferences`: Contract references for repurchase obligations (optional)
- `repurchasePaymentIds`: Payment ID hashes to provide for repurchase (optional)
- `idempotencyKey`: Unique key for duplicate prevention (optional)

**Rules:**
1. **Permission**: Only the party who provided collateral can repurchase their own collateral
2. **Status**: Swap must be in `COMPLETED` status
3. **Expiry**: Must be called before expiry timestamp
4. **Expiry vs Deadline**: `expiry > deadline` (expiry is repurchase deadline, deadline is completion deadline)
5. **Repurchase Requirements**: Must provide obligations/payments specified at swap creation
6. **Repurchase Payments**: Always cash payments (obligor = null), not credit payments
7. **Collateral Return**: Your collateral is returned to you
8. **Repurchase Transfer**: Repurchase obligations/payments transfer to the other party

**Example:**
```graphql
mutation {
  repurchaseSwap(input: {
    swapId: "987654321"
    repurchaseContractReferences: [{
      contractId: "CONTRACT-OBLIGATION-1760932171984"
    }]
  }) {
    success
    swapId
    messageId
  }
}
```

**Response:**
```json
{
  "data": {
    "repurchaseSwap": {
      "success": true,
      "message": "Repurchase swap message submitted successfully",
      "swapId": "987654321",
      "repurchaseResult": "Message queued for processing with ID: msg-repurchase-123",
      "messageId": "msg-repurchase-123",
      "transactionId": "TXN-REPURCHASE-SWAP-<uuid>",
      "signature": "0xdef...",
      "timestamp": "2025-12-05T10:30:00.123456789+00:00"
    }
  }
}
```

**Note:** Repurchase payments are always cash payments (without obligor). The system automatically sets `obligor = null` for repurchase payments, even if provided.

---

### 5. Repo Rolling (Two-Step Roll)

**Repo rolling** extends a repo swap by moving collateral into a new repo with a new counterparty and new terms, without the original counterparty first repurchasing. The **initiator** (the party who provided collateral in the original repo) proposes a new repo; the **new counterparty** completes the roll by paying the original repurchase amount (R1) to the original counterparty. Atomically: the old repo is repurchased and the collateral moves into the new repo.

**Two-step flow:**
1. **Initiate Roll** (initiator only): Creates a new swap in `PENDING` state on-chain. The old repo is unchanged. Initiator specifies new swap ID, new counterparty, new deadline/expiry, and new expected/repurchase payments. The system creates upfront payment(s) from initiator to the new counterparty (used when the new counterparty completes the roll).
2. **Complete Roll** (new counterparty only): New counterparty accepts the initiator’s upfront payment(s), which atomically repurchases the old repo and completes the new repo (collateral migrates to the new repo).

---

#### 5a. Initiate Roll (Repo Swaps Only)

Initiator (collateral provider) of an existing **completed** repo proposes a roll into a new repo.

**GraphQL Mutation:**
```graphql
mutation InitiateRoll($input: RollRepoInput!) {
  initiateRoll(input: $input) {
    success
    message
    accountAddress
    oldSwapId
    newSwapId
    messageId
    transactionId
    signature
    timestamp
  }
}
```

**Input Parameters:**
- `oldSwapId`: The existing (completed) repo swap ID to roll (required)
- `newSwapId`: Unique ID for the new swap (required)
- `newCounterparty`: Entity name/email or wallet address of the new counterparty (required)
- `newCounterpartyWalletId`: Optional wallet ID for the new counterparty
- `newDeadline`: New swap completion deadline – ISO 8601 or YYYY-MM-DD (required)
- `newExpiry`: New repurchase deadline – ISO 8601 or YYYY-MM-DD (optional; must be > newDeadline for repo)
- `newCounterpartyExpectedPayments`: What the new counterparty will pay at complete_roll (R1). If omitted, derived from old swap’s initiator repurchase terms
- `newInitiatorExpectedPayments`: Upfront payment from initiator to new counterparty. If omitted, derived from old swap’s counterparty repurchase (R1) so amounts match
- `newInitiatorRepurchasePayments`: Initiator’s repurchase terms in the new repo (optional)
- `newCounterpartyRepurchasePayments`: New counterparty’s repurchase terms in the new repo (optional)
- `idempotencyKey`: Unique key for duplicate prevention (optional)
- `requireManualSignature`: If true, message is queued for manual signing (optional)
- `name`: Optional label for the roll (optional)

**Rules:**
1. **Permission**: Only the **initiator** (collateral provider) of the old repo can initiate a roll
2. **Old swap**: Must be in `COMPLETED` status (repo swap)
3. **New swap**: Created in `PENDING`; old swap is not repurchased until the new counterparty completes the roll
4. **Upfront**: Initiator’s upfront payment to the new counterparty typically matches the old repo’s R1 (amount the new counterparty will pay to the original counterparty at complete_roll)
5. **Time-weighted repos**: If the old repo uses linear vesting for repurchase, the amount may be prorated when initiating the roll

**Example:**
```graphql
mutation {
  initiateRoll(input: {
    oldSwapId: "987654321"
    newSwapId: "987654322"
    newCounterparty: "newlender@yieldfabric.com"
    newDeadline: "2025-12-15"
    newExpiry: "2026-01-15"
  }) {
    success
    oldSwapId
    newSwapId
    messageId
  }
}
```

**Response:**
```json
{
  "data": {
    "initiateRoll": {
      "success": true,
      "message": "Initiate roll message submitted successfully",
      "accountAddress": "0x...",
      "oldSwapId": "987654321",
      "newSwapId": "987654322",
      "messageId": "msg-initiate-roll-123",
      "transactionId": "TXN-INITIATE-ROLL-<uuid>",
      "signature": "0x...",
      "timestamp": "2025-12-01T10:00:00.000Z"
    }
  }
}
```

---

#### 5b. Complete Roll (Repo Swaps Only)

New counterparty completes the roll by accepting the initiator’s upfront payment(s). This atomically repurchases the old repo (R1 paid to the original counterparty) and completes the new repo (collateral moves to the new repo).

**GraphQL Mutation:**
```graphql
mutation CompleteRoll($input: CompleteRollInput!) {
  completeRoll(input: $input) {
    success
    message
    accountAddress
    newSwapId
    messageId
    transactionId
    signature
    timestamp
  }
}
```

**Input Parameters:**
- `newSwapId`: The new swap ID (created by initiate roll) (required)
- `walletId`: Optional wallet ID for the completing party
- `idempotencyKey`: Unique key for duplicate prevention (optional)
- `requireManualSignature`: If true, message is queued for manual signing (optional)

**Rules:**
1. **Permission**: Only the **new counterparty** (the entity specified as `newCounterparty` at initiate roll) can complete the roll
2. **Status**: New swap must be in `PENDING` (created by initiate roll)
3. **Payment**: Completing party accepts the initiator’s upfront payment(s) (e.g. via the standard Accept flow or as part of this atomic step); that acceptance triggers the on-chain complete_roll
4. **Effect**: Old repo is repurchased (R1); new repo is completed; collateral is now in the new repo

**Example:**
```graphql
mutation {
  completeRoll(input: {
    newSwapId: "987654322"
  }) {
    success
    newSwapId
    messageId
  }
}
```

**Response:**
```json
{
  "data": {
    "completeRoll": {
      "success": true,
      "message": "Complete roll message submitted successfully",
      "accountAddress": "0x...",
      "newSwapId": "987654322",
      "messageId": "msg-complete-roll-123",
      "transactionId": "TXN-COMPLETE-ROLL-<uuid>",
      "signature": "0x...",
      "timestamp": "2025-12-02T14:00:00.000Z"
    }
  }
}
```

**Note:** If you call `completeSwap` with a swap that was created via a roll (`source_swap_id` set), the API redirects to the complete roll flow automatically.

---

### 6. Expire Collateral (Repo Swaps Only)

Forfeit collateral after expiry, transferring it to the other party.

**GraphQL Mutation:**
```graphql
mutation ExpireCollateral($input: ExpireCollateralInput!) {
  expireCollateral(input: $input) {
    success
    message
    swapId
    expireResult
    messageId
    transactionId
    signature
    timestamp
  }
}
```

**Input Parameters:**
- `swapId`: The swap ID to expire (required)
- `idempotencyKey`: Unique key for duplicate prevention (optional)

**Rules:**
1. **Permission**: Anyone can call `expireCollateral` after expiry
2. **Status**: Swap must be in `COMPLETED` status
3. **Expiry**: Must be called after expiry timestamp
4. **Expiry vs Deadline**: `expiry > deadline` (expiry is repurchase deadline, deadline is completion deadline)
5. **Forfeiture**: Initiator's collateral → Counterparty, Counterparty's collateral → Initiator
6. **Irreversible**: Cannot be undone after expiry

**Example:**
```graphql
mutation {
  expireCollateral(input: {
    swapId: "987654321"
  }) {
    success
    swapId
    messageId
  }
}
```

**Response:**
```json
{
  "data": {
    "expireCollateral": {
      "success": true,
      "message": "Expire collateral message submitted successfully",
      "swapId": "987654321",
      "expireResult": "Message queued for processing with ID: msg-expire-123",
      "messageId": "msg-expire-123",
      "transactionId": "TXN-EXPIRE-COLLATERAL-<uuid>",
      "signature": "0xghi...",
      "timestamp": "2025-12-11T00:00:00.123456789+00:00"
    }
  }
}
```

---

## Swap Lifecycle

### Atomic Swap Lifecycle

1. **Create Swap** (`PENDING`):
   - Initiator creates swap with obligations/payments
   - Initiator's obligations locked (after blockchain confirmation)
   - Initiator's payments created and sent to counterparty
   - Swap window active (counting down to deadline)

2. **Complete Swap** (`COMPLETED`):
   - Counterparty completes swap by providing their side
   - Counterparty's obligations locked
   - Counterparty's payments created and sent to initiator
   - Atomic transfer: All assets exchange simultaneously
   - Final state - cannot be reversed

3. **Cancel Swap** (`CANCELLED` or `EXPIRED`):
   - Either party can cancel before deadline
   - If deadline passed, automatically expires
   - All locked assets returned to original owners
   - Swap becomes inactive

### Repo Swap Lifecycle

1. **Create Swap** (`PENDING`):
   - Initiator creates swap with obligations/payments + collateral
   - Initiator's obligations locked (after blockchain confirmation)
   - Initiator's collateral locked (after blockchain confirmation)
   - Initiator's payments created and sent to counterparty
   - Swap window active (counting down to deadline)

2. **Complete Swap** (`COMPLETED`):
   - Counterparty completes swap by providing their side + collateral
   - Counterparty's obligations locked
   - Counterparty's collateral locked
   - Counterparty's payments created and sent to initiator
   - Atomic transfer: Immediate swap assets exchange
   - Collateral assets held in escrow until expiry
   - Repurchase window active (from completion to expiry)

3. **Repurchase Swap** (Before Expiry):
   - Collateral provider repurchases their collateral
   - Provides repurchase obligations/payments
   - Collateral returned to original owner
   - Repurchase assets transfer to other party

4. **Expire Collateral** (After Expiry):
   - Anyone can call `expireCollateral` after expiry
   - Initiator's collateral → Counterparty
   - Counterparty's collateral → Initiator
   - Irreversible forfeiture

5. **Cancel Swap** (`CANCELLED` or `EXPIRED`):
   - Either party can cancel before deadline
   - If deadline passed, automatically expires
   - All locked assets (including collateral) returned to original owners
   - Swap becomes inactive

6. **Repo Rolling** (optional): Initiator can **initiate roll** to propose a new repo (new counterparty, new terms). New counterparty **completes roll** by accepting the upfront payment; old repo is repurchased and collateral moves into the new repo. See section 5.

### Repo Roll Lifecycle

1. **Initiate Roll** (initiator):
   - Initiator of a **completed** repo calls `initiateRoll` with old swap ID, new swap ID, new counterparty, new deadline/expiry, and payment terms
   - New swap is created in `PENDING`; upfront payment(s) from initiator to new counterparty are created (new counterparty sees them as incoming)

2. **Complete Roll** (new counterparty):
   - New counterparty calls `completeRoll` with the new swap ID (or accepts the upfront payment, which may route through `completeSwap` to complete roll)
   - On-chain: old repo is repurchased (R1), new repo is completed, collateral migrates to the new repo
   - New repo is in `COMPLETED`; original repo is effectively replaced by the new one

---

## Deadline & Expiry Rules

### Deadline (Swap Acceptance Window)

The `deadline` defines when the swap must be completed:

- **Purpose**: Time limit for counterparty to accept and complete the swap
- **Effect**: After deadline, swap cannot be completed
- **Expiry**: If deadline passed and swap not completed, automatically expires
- **Cancellation**: Swaps can be cancelled before deadline
- **Atomic Swaps**: Deadline is the only time constraint
- **Repo Swaps**: Deadline is completion deadline, separate from expiry

**Rules:**
1. Deadline must be in the future when creating swap
2. Swap must be completed before deadline
3. After deadline, swap cannot be completed
4. Canceling after deadline routes to `expireSwap` flow (status = `EXPIRED`)

### Expiry (Repurchase Deadline - Repo Swaps Only)

The `expiry` defines when collateral can be forfeited (repo swaps only):

- **Purpose**: Time limit for repurchasing collateral
- **Effect**: After expiry, collateral can be forfeited via `expireCollateral`
- **Requirement**: Must be `> deadline` if provided
- **Default**: `0` means atomic swap (no repo mechanism)
- **Relation**: `expiry > deadline` for repo swaps

**Rules:**
1. If collateral is provided, `expiry` must be set and `> deadline`
2. If `expiry = 0`, it's an atomic swap (no collateral/repo)
3. Repurchase must happen before expiry
4. After expiry, collateral can be forfeited (irreversible)

**Timeline Example:**
```
Swap Created:     2025-10-20
Deadline:         2025-11-10  (completion deadline)
Expiry:           2025-12-10  (repurchase deadline)
                   │          │              │
                   │          │              └─ After expiry: forfeit collateral
                   │          └─ After deadline: cannot complete swap
                   └─ Before deadline: can complete swap
                       
Periods:
- Creation → Deadline: Swap acceptance window (can complete)
- Completion → Expiry: Repurchase window (can repurchase)
- After Expiry: Forfeit window (can expire collateral)
```

---

## Contract Locking

Contracts are locked when included in a swap to prevent double-spending:

**Locking Mechanism:**
- `locked_in_swap_id`: ID of swap that locks the contract (optional)
- `locked_in_swap_status`: Status of the swap locking the contract (optional)

**Locking Rules:**
1. **When Locked**: After blockchain confirmation of swap creation/completion
2. **What Gets Locked**: All obligations included in the swap
3. **Lock Status**: Matches swap status (`PENDING`, `COMPLETED`, etc.)
4. **Unlocking**: After swap completion/cancellation/expiry (confirmed on-chain)

**Locking States:**
- **PENDING**: Contracts locked, swap awaiting completion
- **COMPLETED**: Contracts remain locked if swap is a repo swap (until repurchase/expiry)
- **CANCELLED/EXPIRED**: Contracts unlocked, returned to owners

**Query Locked Contracts:**
```graphql
query {
  contracts(lockedInSwapId: "123456789") {
    id
    status
    lockedInSwapId
    lockedInSwapStatus
  }
}
```

---

## Atomic Settlement Guarantees

**All-or-Nothing Execution:**
- If counterparty's payment succeeds → obligations transfer
- If payment fails → obligations remain with initiator
- No partial execution possible
- Smart contract enforced atomicity

**Security Features:**
- Smart contract enforced atomicity
- On-chain verification
- Immutable transaction records
- Full audit trail
- Contract locking prevents double-spending

**Use Cases:**
- Securitization (sell future payment rights)
- Debt trading (transfer loan obligations)
- Structured finance (composite obligation packages)
- Liquidity provision (exchange obligations for cash)
- Repurchase agreements (secured lending with collateral)

---

## Querying Swaps

### Get Swaps by Entity

Query all swaps for a specific entity:

```graphql
query GetSwaps($entityId: ID!) {
  swapFlow {
    coreSwaps {
      byEntityId(entityId: $entityId) {
        id
        swapId
        swapType
        status
        deadline
        expiry
        createdAt
        parties {
          id
          entity {
            id
            name
          }
          role
        }
        initiatorObligationIds
        counterpartyObligationIds
        paymentIds
        payments {
          id
          amount
          assetId
          paymentType
          status
        }
      }
    }
  }
}
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
            "expiry": null,
            "createdAt": "2025-10-20T03:51:25.797693681+00:00",
            "parties": [
              {
                "entity": {
                  "id": "2cee226b-f69a-4385-bb2c-22ecc61eedcc",
                  "name": "issuer@yieldfabric.com"
                },
                "role": "INITIATOR"
              },
              {
                "entity": {
                  "id": "2b5c7a69-5c2c-44f3-b621-6c0438d679be",
                  "name": "counterpart@yieldfabric.com"
                },
                "role": "COUNTERPARTY"
              }
            ],
            "initiatorObligationIds": [
              "CONTRACT-OBLIGATION-1760932171982"
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
                "status": "COMPLETED"
              }
            ]
          }
        ]
      }
    }
  }
}
```

---

## Swap Status

Swaps progress through the following statuses:

1. **PENDING**: Initial state after `createSwap`
   - Swap created, awaiting counterparty completion
   - Contracts locked
   - Swap window active (before deadline)

2. **COMPLETED**: After counterparty calls `completeSwap`
   - Both sides executed atomically
   - Immediate swap assets transferred
   - Collateral held in escrow (repo swaps)
   - Final state for atomic swaps

3. **CANCELLED**: Terminated via `cancelSwap`
   - Can occur before deadline
   - All locked assets returned
   - Swap becomes inactive

4. **EXPIRED**: Automatically cancelled after deadline passes
   - Only if swap not completed before deadline
   - All locked assets returned
   - Cannot be completed after expiration

---

## Best Practices

### Atomic Swaps

1. **Set Realistic Deadlines**: Allow sufficient time for counterparty review
2. **Verify Obligations**: Ensure obligations are in correct status before creating swap
3. **Monitor Status**: Track swap status to ensure completion before deadline
4. **Handle Expiration**: Be prepared for swap expiration if counterparty doesn't complete

### Repo Swaps

1. **Understand Expiry**: `expiry > deadline` (expiry is repurchase deadline)
2. **Repurchase Timing**: Repurchase before expiry to avoid forfeiture
3. **Repurchase Requirements**: Understand what obligations/payments are required for repurchase
4. **Cash Payments**: Repurchase payments are always cash (obligor = null)
5. **Forfeiture Risk**: Be aware that collateral can be forfeited after expiry

### Repo Rolling

1. **Initiator only**: Only the initiator (collateral provider) of the existing completed repo can call `initiateRoll`
2. **Complete roll**: Only the new counterparty (specified in `initiateRoll`) can call `completeRoll` (or complete via the redirected `completeSwap` flow)
3. **Upfront amounts**: Initiator’s upfront payment to the new counterparty typically matches the old repo’s R1 so the new counterparty can pay R1 when completing the roll
4. **New swap ID**: Use a unique `newSwapId`; the new swap is created in `PENDING` until the roll is completed

### General

1. **Idempotency Keys**: Use idempotency keys to prevent duplicate operations
2. **Contract References**: Use contract references for better flexibility
3. **Error Handling**: Handle errors gracefully and retry if needed
4. **Monitoring**: Monitor swap status and deadlines
5. **Security**: Verify counterparty identity before creating swaps

---

## Error Handling

**Common Errors:**

1. **Swap Not Found**: Swap ID doesn't exist
   - **Solution**: Verify swap ID and entity access

2. **Deadline Expired**: Swap deadline has passed
   - **Solution**: Create a new swap with a future deadline

3. **Insufficient Permissions**: Not authorized to perform operation
   - **Solution**: Verify JWT permissions and entity access

4. **Contract Locked**: Contract is locked in another swap
   - **Solution**: Wait for other swap to complete/cancel

5. **Expiry Invalid**: Expiry not > deadline for repo swaps
   - **Solution**: Set expiry > deadline when providing collateral

6. **Not the Holder**: Offering an explicitly-named obligation/collateral the initiator's wallet doesn't hold (`"Initiator does not hold … contract <id>"`)
   - **Solution**: Only offer assets your swap wallet HOLDs; if the asset is on another wallet, pass that `walletId`. (A `composedContractId` reference instead silently drops un-held nested legs.)

---

## Rehypothecation and True Collateral Mobility

YieldFabric’s repo swap design supports **rehypothecation** in a way that keeps risk anchored to the obligor and makes the **chain of risk** explicit. That is what enables **true collateral mobility**.

### How risk is anchored by the obligor

When an obligor pledges an asset as collateral in a repo swap, they remain the **anchor of credit risk**. The underlying obligation (e.g. bond or loan) stays tied to that obligor: payment streams and default risk are not reassigned. The obligor has committed to either **repurchasing** (paying cash by expiry) or **forfeiting** the collateral. That binary outcome is what the lender is exposed to.

### The contingent token the lender receives

On swap completion, the **lender** (counterparty) receives a **new tokenised asset** that is **contingent** in nature. In the system this is represented as a composed contract (e.g. Cont_A) that bundles:

- **Collateral (Col_A)**: the pledged assets (obligations / digital assets) held in escrow
- **Repurchase (Rep_A)**: the right to receive a repurchase payment by expiry

The lender therefore holds a single instrument whose economic outcome is **either** the repurchase payment **or** the collateral. There is no ambiguity: the contract and the swap rules define exactly what the lender gets in each branch (repurchase vs. default/expiry).

### How rehypothecation works in this context

**Rehypothecation** is the reuse of collateral by the party that received it. Here, the lender holds a **token** (the contingent composed contract) that represents those clear rights. They can:

- **Pledge that contingent token** as collateral in a **further** repo swap with another lender.
- In that new repo, the “collateral” is the contingent asset (repurchase or underlying collateral), not a vague claim. The new lender (or the system) can treat the contingent token as the encumbered asset and, if needed, resolve to repurchase payment or collateral according to the first repo’s outcome.

So the **flow** is: Obligor pledges asset → Lender receives contingent token (repurchase or collateral) → Lender can pledge that contingent token → Next lender receives a new contingent layer (Cont_B), and so on. Each link is a repo with defined collateral and repurchase terms; the **chain of risk** is the sequence of these links, and the **obligor remains the anchor** at the root.

### Value of defining the flow / chain of risk

Defining and encoding the flow in this way delivers:

1. **True collateral mobility**  
   Collateral can move through multiple layers of financing without physically moving the same underlying assets each time. What moves is the **tokenised rights** (the contingent asset): repurchase payment or collateral, with rules and expiry defined at each repo.

2. **Transparent chain of risk**  
   Each repo is a clear link: who pledged what, who received which contingent token, and what happens on repurchase vs. expiry. Regulators and participants can trace risk from any contingent token back to the original obligor and the underlying collateral.

3. **No double-counting of collateral**  
   The structure (Col_A, Rep_A, Cont_A, and nested Cont_B where applicable) makes it explicit what is locked as collateral at each level and what is repurchase obligation. The same physical or on-chain collateral is not “used” in two places without the chain being visible.

4. **Efficient re-use of collateral**  
   Lenders can fund themselves by re-pledging the contingent token they received, while the original obligor’s commitment (repurchase or forfeit) remains the anchor. Liquidity and leverage are improved without breaking the link to the initial source of risk.

In summary: **risk is anchored by the obligor** when they pledge the asset; the **lender receives a tokenised contingent asset** (repurchase or collateral); that contingent asset can be **rehypothecated** in further repos; and defining the **flow and chain of risk** in this way is what makes **true collateral mobility** possible—collateral that can be reused and re-pledged along a clear, auditable chain back to the obligor.

---

## Summary

YieldFabric's swap system provides:

- **Atomic Swaps**: Immediate settlement with no collateral
- **Repo Swaps**: Collateralized swaps with repurchase options
- **Repo Rolling**: Two-step roll (initiate roll → complete roll) to move collateral into a new repo with a new counterparty and terms without the original counterparty repurchasing first
- **Deadline Management**: Acceptance window for swap completion
- **Expiry Management**: Repurchase window for collateral (repo swaps)
- **Contract Locking**: Prevents double-spending
- **Atomic Settlement**: All-or-nothing execution guarantees
- **Security**: Smart contract enforced atomicity and immutability

Users primarily interact with swaps through the GraphQL API, with the system handling all blockchain interactions and state management automatically.
