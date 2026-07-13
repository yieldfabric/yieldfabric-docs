# YieldFabric Quick Start

Get up and running with YieldFabric in 5 minutes.

---

## What You'll Learn

- Authenticate and get a JWT token
- Deposit funds into your intelligent account
- Check your account balance
- Send an instant payment
- Accept an incoming payment

---

## Prerequisites

- `curl` and `jq` installed
- YieldFabric account credentials
- Access to YieldFabric production services

---

## Step 1: Login and Save Token

```bash
export TOKEN=$(curl -s -X POST https://auth.yieldfabric.com/auth/login/with-services \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "your-password",
    "services": ["vault", "payments"]
  }' | jq -r '.token')

echo "Token: ${TOKEN:0:50}..."
```

---

## Step 2: Deposit Funds

Before you can send payments, deposit tokens into your intelligent account:

```bash
curl -s -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { deposit(input: { assetId: \"aud-token-asset\", amount: \"100\" }) { success message messageId accountAddress } }"
  }' | jq
```

---

## Step 3: Check Your Balance

```bash
curl -s -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=null" \
  -H "Authorization: Bearer $TOKEN" | jq
```

**What to look for:**
- `private_balance`: Your encrypted balance (zero-knowledge proof protected)
- `public_balance`: Your public balance (visible on-chain)
- `locked_out`: Payments you've sent (pending acceptance)
- `locked_in`: Payments you've received (awaiting your acceptance)
- `outstanding`: Total locked in outgoing payments

---

## Step 4: Send an Instant Payment

```bash
curl -s -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { instant(input: { assetId: \"aud-token-asset\", amount: \"10\", destinationId: \"recipient@yieldfabric.com\" }) { success paymentId messageId accountAddress } }"
  }' | jq

# Save the payment ID for the recipient to accept
```

**Response will include:**
- `paymentId`: ID for tracking
- `messageId`: Message queue ID
- `accountAddress`: Your account address

---

## Step 5: Accept an Incoming Payment (As Recipient)

First, check your balance to see incoming payments:

```bash
curl -s -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=null" \
  -H "Authorization: Bearer $RECIPIENT_TOKEN" | jq '.locked_in'
```

Then accept using the `id_hash` from locked_in:

```bash
curl -s -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $RECIPIENT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { accept(input: { paymentId: \"PAY-INSTANT-1759048183145\" }) { success message messageId } }"
  }' | jq
```

---

## Step 6: Check Balance Again

```bash
curl -s -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=null" \
  -H "Authorization: Bearer $TOKEN" | jq
```

**You should now see:**
- Payment moved from `locked_out` (sender) or `locked_in` (recipient)
- Balance updated to reflect the transfer

---

## Next Steps

### Learn More

1. **[01-OVERVIEW.md](./01-OVERVIEW.md)** — Understand intelligent accounts and zero-knowledge privacy
2. **[04-CONTRACTS.md](./04-CONTRACTS.md)** — Create payment obligations (invoices, loans, annuities)
3. **[05-PAYMENTS.md](./05-PAYMENTS.md)** — Distributions, obligation payments, and advanced payment features
4. **[06-SWAPS.md](./06-SWAPS.md)** — Trade obligations using atomic swaps and repos
5. **[07-WORKFLOWS.md](./07-WORKFLOWS.md)** — Complete end-to-end examples (annuities, distributions, repo rolling)

### Try Advanced Features

**Create a Payment Obligation:**
```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { createObligation(input: { counterpart: \"buyer@yieldfabric.com\", denomination: \"aud-token-asset\", notional: \"1000\", expiry: \"2025-12-31\" }) { success contractId } }"
  }' | jq
```

**Create a Distribution (One-to-Many Payment):**
```bash
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { createDistribution(input: { assetId: \"aud-token-asset\", recipients: [{ address: \"0xRecipient1...\", amount: \"50\" }, { address: \"0xRecipient2...\", amount: \"30\" }] }) { success message messageId } }"
  }' | jq
```

**Use Group Delegation:**
```bash
# Get delegation token for a group
export DELEGATION_TOKEN=$(curl -s -X POST https://auth.yieldfabric.com/auth/delegation/jwt \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_id": "your-group-id",
    "delegation_scope": ["CryptoOperations", "ReadGroup"],
    "expiry_seconds": 3600
  }' | jq -r '.delegation_jwt')

# Use delegation token for group operations
curl -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=null" \
  -H "Authorization: Bearer $DELEGATION_TOKEN" | jq
```

---

## Troubleshooting

### Token Invalid or Expired

```bash
# Get a fresh token
export TOKEN=$(curl -s -X POST https://auth.yieldfabric.com/auth/login/with-services \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password","services":["vault","payments"]}' \
  | jq -r '.token')
```

### Payment Not Showing in Balance

- Check you're using the correct `denomination` and `obligor`
- Verify the payment was actually sent (check sender's `locked_out`)
- Ensure you're querying as the correct entity

### Payment Amount Error

- Make sure amount is an integer string: `"10"` not `"10.00"` or `10`
- No decimal points allowed

---

## Testing Scripts

The `scripts/` directory contains automated test sequences:

```bash
# Run the annuity settlement workflow
cd scripts
./execute_commands.sh settle_annuity.yaml

# Run basic setup
./execute_commands.sh setup.yaml
```

---

## Support

For detailed documentation:
- Navigation Guide: [NAVIGATION.md](./NAVIGATION.md)
- API Reference: [08-REFERENCE.md](./08-REFERENCE.md)
- Curl Examples: [SIMPLE.md](./SIMPLE.md)
- Workflow Examples: [07-WORKFLOWS.md](./07-WORKFLOWS.md)
- Error Codes: [08-REFERENCE.md](./08-REFERENCE.md#error-handling)
