# Complete Workflows

End-to-end examples demonstrating real-world use cases.

---

## Annuity Settlement Workflow

This example demonstrates how to create and settle an annuity using self-referential obligations and atomic swaps.

### Overview

An issuer creates future payment obligations and atomically swaps them for immediate liquidity:
- **Issuer**: Creates 105 AUD in future obligations, receives 100 AUD immediately
- **Counterparty**: Pays 100 AUD upfront, receives 105 AUD over time (5% yield)

---

### Step 1: Create Annuity Stream Obligation

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

Save the contract ID:
```bash
export ANNUITY_CONTRACT_ID="CONTRACT-OBLIGATION-1760932171982"
```

---

### Step 2: Accept the Annuity Stream Obligation

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { acceptObligation(input: { contractId: \"CONTRACT-OBLIGATION-1760932171982\" }) { success message obligationId messageId } }"
  }'
```

---

### Step 3: Create Redemption Obligation

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

Save the contract ID:
```bash
export REDEMPTION_CONTRACT_ID="CONTRACT-OBLIGATION-1760932212849"
```

---

### Step 4: Accept the Redemption Obligation

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { acceptObligation(input: { contractId: \"CONTRACT-OBLIGATION-1760932212849\" }) { success message obligationId messageId } }"
  }'
```

---

### Step 5: Create Atomic Swap

Exchange obligations for upfront payment:

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

---

### Step 6: Counterpart Completes the Swap

Counterpart pays 100 AUD upfront and receives obligation rights:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $COUNTERPART_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { completeSwap(input: { swapId: \"123456789\" }) { success message swapId messageId } }"
  }'
```

---

## Workflow Explanation

This demonstrates an **annuity securitization**:

### 1. Create Self-Referential Obligations

Issuer creates obligations with **themselves as both obligor AND counterpart**:
- **Annuity Stream**: 5 AUD paid over 5 days (Nov 1-5)
- **Redemption**: 100 AUD paid on Nov 6
- **Total obligation value**: 105 AUD
- **No counterparty risk during creation**

### 2. Accept Obligations

Issuer accepts their own obligations:
- Commits to the payment schedule
- Structure is now locked and ready for transfer

### 3. Create Atomic Swap

Issuer offers both obligations to the actual counterparty:
- In exchange for 100 AUD upfront (instant payment, no obligor)
- Swap transfers obligation ownership atomically

### 4. Complete Swap

Counterpart executes the swap:
- Pays 100 AUD immediately
- Receives ownership rights to both obligations (105 AUD total)
- Settlement is **secure and atomic** - both transfers happen simultaneously or not at all

---

## Economic Result

**Issuer:**
- Receives: 100 AUD immediately (liquidity)
- Owes: 105 AUD over time (as obligor)

**Counterparty:**
- Pays: 100 AUD upfront
- Receives: 105 AUD over time (5% yield)

---

## Key Security Features

- **Self-referential structure**: Build obligations with yourself as counterpart (no external dependency)
- **Atomic swap**: Obligations transfer only when payment is received
- **No counterparty risk during creation**: Structure built independently before involving external party
- **Instant settlement**: Counterparty's payment has no obligor (unconditional, immediate)
- **Bilateral commitment**: Both parties exchange simultaneously or transaction fails

This pattern enables **secure securitization**: Pre-package future payment obligations and atomically exchange them for immediate liquidity, while the counterparty gets a yield-bearing asset with guaranteed delivery.

---

## Distribution Workflow

This example demonstrates a **one-to-many distribution**: a single sender pays multiple recipients in a single operation.

### Overview

A sender distributes funds to multiple parties (e.g., dividend payout, commission splits). Each recipient accepts their share independently.

---

### Step 1: Create Distribution

Sender creates a distribution specifying each recipient and amount:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { createDistribution(input: { assetId: \"aud-token-asset\", recipients: [{ address: \"0x037b69a7ca6b327ddf843c9ac4ff784e08b5eb6d\", amount: \"5000000000000000000\" }, { address: \"0x5821aa342bd011e0e77ac5eb8663b052592363a5\", amount: \"10000000000000000000\" }], idempotencyKey: \"dist-dividend-001\" }) { success messageId transactionId } }"
  }'
```

**What happens:**
- One `CONTRACT-DISTRIBUTION-*` is created
- One RECEIVABLE payment per recipient is created
- Total amount (15 × 10^18) is locked from the sender's balance

---

### Step 2: Recipients Accept Their Share

Each recipient accepts their individual payment using the standard `accept` mutation:

```bash
# Recipient 1 accepts
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $RECIPIENT1_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { accept(input: { paymentId: \"PAYMENT-DIST-177374060471601661010-0\" }) { success messageId } }"
  }'

# Recipient 2 accepts
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $RECIPIENT2_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { accept(input: { paymentId: \"PAYMENT-DIST-177374060471601661010-1\" }) { success messageId } }"
  }'
```

---

### Step 3 (Optional): Cancel Distribution

If **no** recipient has accepted yet, the sender can cancel the entire distribution:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { accept(input: { paymentId: \"PAYMENT-DIST-177374060471601661010-0\" }) { success messageId } }"
  }'
```

> Once any recipient has accepted their share, `canCancel` becomes `false` and the distribution can no longer be cancelled.

---

### Distribution Key Points

- **Atomic creation**: All recipient payments are created in a single transaction
- **Independent acceptance**: Each recipient accepts independently; no dependency between recipients
- **Cancel-all-or-nothing**: Sender can only cancel if zero claims have been made
- **NFT recipients**: Set `obligationId` on a recipient to enable NFT-based claiming (claimant = `ownerOf` at claim time)

---

## Repo Rolling Workflow

This example demonstrates **repo rolling**: moving collateral from an existing repo into a new repo with a new counterparty and terms.

### Overview

A borrower has an existing repo swap (Swap A) with Lender A. The borrower wants to roll the collateral into a new repo (Swap B) with Lender B, possibly with different terms or to obtain better rates.

---

### Step 1: Initiate Roll

The borrower (initiator / collateral provider) proposes a new repo:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $BORROWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { initiateRoll(input: { oldSwapId: \"987654321\", newSwapId: \"987654322\", newCounterparty: \"newlender@yieldfabric.com\", newDeadline: \"2025-12-15\", newExpiry: \"2026-01-15\" }) { success oldSwapId newSwapId messageId } }"
  }'
```

**What happens:**
- New swap `987654322` is created in `PENDING` state
- Upfront payment(s) from borrower to the new lender are created
- Original swap `987654321` remains `COMPLETED` (unchanged for now)

---

### Step 2: Complete Roll

The new lender completes the roll:

```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $NEW_LENDER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { completeRoll(input: { newSwapId: \"987654322\" }) { success newSwapId messageId } }"
  }'
```

**What happens (atomically):**
1. New lender's payment repurchases the old repo (R1 sent to Lender A)
2. Collateral moves from old repo → new repo
3. New swap `987654322` becomes `COMPLETED`
4. Old swap is effectively settled

---

### Repo Rolling Key Points

- **Initiator only**: Only the party who provided collateral in the original repo can initiate a roll
- **New counterparty only**: Only the party specified in `newCounterparty` can complete the roll
- **Atomic**: Old repo repurchase and new repo completion happen in a single atomic step
- **No manual repurchase**: The borrower does not need to repurchase the old repo first — the roll handles it

---

## Other Common Workflows

### Simple Invoice Payment

1. Seller creates obligation with buyer as counterparty
2. Buyer accepts obligation
3. Payment unlocks on due date
4. Buyer executes payment
5. Seller receives funds

### Loan Repayment Schedule

1. Borrower creates repayment obligation (self-referential)
2. Borrower accepts obligation
3. Lender provides loan via instant payment
4. Borrower's repayments unlock on schedule
5. Lender receives repayments over time

### Escrow Transaction

1. Buyer creates fully-funded obligation
2. Funds locked with oracle conditions (e.g., "goods_delivered")
3. Seller ships goods
4. Oracle confirms delivery
5. Payment releases to seller

### Discounted Cash Flow

1. Entity creates future payment obligations
2. Accepts obligations (locks structure)
3. Creates swap offering obligations at discount
4. Investor provides upfront capital via swap
5. Both parties receive their exchange atomically

