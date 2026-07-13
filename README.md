# YieldFabric API Documentation

Complete API documentation and examples for YieldFabric - a platform for programmable financial operations with zero-knowledge privacy.

## Table of Contents

- [Quick Links](#documentation-structure)
- [Getting Started](#getting-started)
- [Core Capabilities](#core-capabilities)
- [Example Workflows](#example-workflows)
- [GraphQL Schema](#graphql-schema)
- [Authentication & Authorization](#authentication--authorization)
- [Architecture](#architecture)

---

## Overview

YieldFabric provides **intelligent accounts** that enable sophisticated financial operations with confidential transactions protected by zero-knowledge proof technology. Create, program, and trade payment obligations with atomic settlement guarantees.

## Key Features

- 🔐 **Zero-Knowledge Privacy**: Confidential transactions using ZK-proof technology
- 💰 **Intelligent Accounts**: Programmable accounts for users and groups
- 📅 **Payment Obligations**: Create invoices, loans, annuities, and structured payments
- ⚡ **Instant Payments**: Send and receive payments with atomic settlement
- 📤 **Distributions**: One-to-many payments (one sender, multiple recipients; each accepts their share)
- 🔄 **Atomic Swaps**: Exchange payment obligations with guaranteed execution
- 📦 **Repo Swaps & Rolling**: Collateralized repos with repurchase and two-step roll to a new counterparty
- ⏰ **Programmable Triggers**: Timelocks and oracle-based conditional execution
- 👥 **Group Accounts**: Collaborative operations with fine-grained access control
- 🔍 **Full Audit Trail**: Complete transaction history and delegation tracking

## Documentation Structure

> **Not sure where to start?** See [NAVIGATION.md](./NAVIGATION.md) for guided reading paths based on your experience level and use case.

### Quick Start
- **[QUICKSTART.md](./QUICKSTART.md)** - Get started in 5 minutes ⚡
- **[01-OVERVIEW.md](./01-OVERVIEW.md)** - How the platform works 📖
- **[00-ARCHITECTURE.md](./00-ARCHITECTURE.md)** - Platform architecture and components 🏗️

### Core Guides (Step-by-Step)
- **[02-AUTHENTICATION.md](./02-AUTHENTICATION.md)** - Login, delegation, JWT tokens 🔐
- **[03-BALANCES.md](./03-BALANCES.md)** - Balance queries and locked transactions 💰
- **[04-CONTRACTS.md](./04-CONTRACTS.md)** - Creating and querying obligations 📄
- **[05-PAYMENTS.md](./05-PAYMENTS.md)** - Deposits, instant payments, distributions, accept and cancel 💸
- **[06-SWAPS.md](./06-SWAPS.md)** - Atomic swaps, repo swaps, repurchase, and repo rolling 🔄
- **[07-WORKFLOWS.md](./07-WORKFLOWS.md)** - End-to-end examples: annuity securitization, distributions, repo rolling 🎯
- **[08-REFERENCE.md](./08-REFERENCE.md)** - Error codes, assets, quick reference 📚
- **[09-CRYPTOGRAPHIC-OPERATIONS.md](./09-CRYPTOGRAPHIC-OPERATIONS.md)** - Key management, encryption, signatures 🔑
- **[13-LLM-ACCESS.md](./13-LLM-ACCESS.md)** - LLM access through YieldFabric: OpenAI-compatible /v1, tool calling, RAG grounding, multi-agent reasoning 🧠

### Complete Reference
- **[SIMPLE.md](./SIMPLE.md)** - All API examples in one comprehensive file
- **[NAVIGATION.md](./NAVIGATION.md)** - Reading guide based on your needs

### Additional Documentation
- **[10_STRUCTURING.md](./10_STRUCTURING.md)** - Structuring and intelligent accounts
- **[11_ABS.md](./11_ABS.md)** - Asset-backed securities and waterfall distributions
- **Subdirectories**: [composed_contracts/](./composed_contracts/), [loan_management/](./loan_management/), [annuities/](./annuities/), [python/](./python/) for domain-specific guides

### Service URLs
- **Production Auth**: `https://auth.yieldfabric.com`
- **Production API**: `https://pay.test.yieldfabric.com`
- **GraphQL Endpoint**: `https://pay.test.yieldfabric.com/graphql`

## Getting Started

### New to YieldFabric?

Start here: **[QUICKSTART.md](./QUICKSTART.md)** - Complete beginner's guide with step-by-step examples.

### For Developers

1. **[01-OVERVIEW.md](./01-OVERVIEW.md)** - Understand the platform architecture
2. **[02-AUTHENTICATION.md](./02-AUTHENTICATION.md)** - Get authenticated
3. **[03-BALANCES.md](./03-BALANCES.md)** - Query your balances
4. **[05-PAYMENTS.md](./05-PAYMENTS.md)** - Send your first payment

### Quick Example

```bash
# Login
export TOKEN=$(curl -s -X POST https://auth.yieldfabric.com/auth/login/with-services \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password","services":["vault","payments"]}' \
  | jq -r '.token')

# Check balance
curl -X GET "https://pay.test.yieldfabric.com/balance?denomination=aud-token-asset&obligor=null" \
  -H "Authorization: Bearer $TOKEN" | jq

# Send payment
curl -X POST https://pay.test.yieldfabric.com/graphql \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "mutation { instant(input: { assetId: \"aud-token-asset\", amount: \"10\", destinationId: \"recipient@yieldfabric.com\" }) { success paymentId } }"
  }' | jq
```

## Core Capabilities

### Intelligent Accounts

**Personal Accounts**
- Owned by individual users
- Full control over funds and operations
- Deployed on-chain with zero-knowledge privacy

**Group Accounts**
- Shared accounts managed by multiple users
- Policy-based access control
- Delegation with audit trail
- Same features as personal accounts (balances, payments, obligations, swaps)

### Payment Operations

**Instant Payments**
- Send funds to other users immediately
- Locked until counterpart accepts or sender cancels
- Atomic settlement guarantees

**Distributions**
- One-to-many payments: one sender, multiple recipients with fixed amounts
- Each recipient accepts their share via the same Accept flow; sender can cancel only if no one has claimed yet
- See [05-PAYMENTS.md](./05-PAYMENTS.md) section 6

**Payment Obligations**
- Create structured payment commitments (invoices, loans, annuities)
- **Fully Funded (Escrow)**: Funds locked upfront
- **Unfunded (Credit)**: Payment commitment without immediate funding
- Programmable with timelocks and oracle triggers

**Atomic Swaps**
- Exchange payment obligations bilaterally
- Both parties exchange simultaneously or transaction fails
- Enables securitization and structured finance

**Repo Swaps & Rolling**
- **Repo swaps**: Collateralized swaps with repurchase before expiry; collateral can be forfeited after expiry
- **Repo rolling**: Two-step flow (initiate roll → complete roll) to move collateral into a new repo with a new counterparty without the original counterparty repurchasing first
- See [06-SWAPS.md](./06-SWAPS.md) sections 4–6

## API Sections

The complete API documentation in [SIMPLE.md](./SIMPLE.md) includes:

1. **Authentication** - Login and delegation
2. **Balance Queries** - Check balances and locked transactions
3. **Contracts** - View and create payment obligations
4. **Payments** - Query payment history
5. **Instant Payments** - Send and accept payments
6. **Distributions** - Create one-to-many payments; recipients accept their share
7. **Swaps** - Create and complete atomic swaps; repo repurchase, expire collateral, and repo rolling
8. **Annuity Workflows** - Complete securitization examples

## Key Concepts

### Self-Referential Obligations

Create obligation structures with yourself as both obligor and counterpart:
- Build complex payment schedules without counterparty risk
- Lock the structure by accepting your own obligations
- Atomically transfer to actual counterparty via swap
- Ensures secure construction and settlement

### Atomic Settlement

All bilateral operations use atomic execution:
- Payment and obligation transfer happen simultaneously
- Transaction succeeds completely or fails entirely
- No partial execution or settlement risk

### Zero-Knowledge Privacy

All account balances and transactions use ZK-proofs:
- Confidential balances (encrypted amounts)
- Public balances (transparent amounts)
- Privacy-preserving transfers
- On-chain verification without revealing details

## Example Workflows

### Simple Payment Flow
1. Deposit funds into intelligent account
2. Send instant payment to recipient
3. Recipient accepts payment
4. Recipient withdraws funds

### Annuity Securitization
1. Create annuity stream obligation (self-referential)
2. Create redemption obligation (self-referential)
3. Accept both obligations (lock structure)
4. Create atomic swap offering obligations for upfront payment
5. Counterparty completes swap (pays upfront, receives obligation rights)
6. Issuer receives liquidity, counterparty receives yield-bearing asset

See [Section 13 in SIMPLE.md](./SIMPLE.md#13-annuity-settlement-workflow) for complete example.

### Distribution Flow
1. Sender creates distribution with asset and list of (recipient, amount)
2. Each recipient accepts their share via `accept` with their distribution payment ID
3. Sender can cancel the whole distribution only before any recipient has claimed

### Repo Roll Flow
1. Initiator (collateral provider) of a completed repo calls `initiateRoll` with new swap ID, new counterparty, and new terms
2. New counterparty calls `completeRoll` (or completes via the swap flow); old repo is repurchased and collateral moves into the new repo

## GraphQL Schema

The API uses GraphQL for most operations:

**Queries:**
- `contractFlow.coreContracts.byEntityId` - Get contracts for entity
- `paymentsByEntity` - Get payments for entity
- `swapFlow.coreSwaps.byEntityId` - Get swaps for entity
- `entities.all` - List entities
- `wallets` - Query wallets

**Mutations:**
- `deposit` — Deposit funds into your wallet
- `withdraw` — Withdraw funds from your wallet
- `instant` — Send instant payment (cash or credit)
- `accept` — Accept incoming payment (or cancel/retrieve where allowed)
- `acceptAll` — Batch-accept all pending payments matching a denomination/obligor
- `hidePayment` — Hide a payment from view (soft delete)
- `createDistribution` — Create one-to-many distribution
- `createObligation` — Create payment obligation
- `acceptObligation` — Accept obligation
- `transferObligation` — Transfer obligation to new holder
- `cancelObligation` — Cancel obligation
- `createSwap` — Create atomic or repo swap
- `completeSwap` — Complete swap (or complete roll when swap was created via roll)
- `cancelSwap` — Cancel pending swap
- `repurchaseSwap` — Repurchase collateral (repo swaps)
- `initiateRoll` — Initiate repo roll (new repo, new counterparty)
- `completeRoll` — Complete repo roll (new counterparty)
- `expireCollateral` — Forfeit collateral after expiry (repo swaps)

## Authentication & Authorization

### User Roles
- **SuperAdmin** - Full system access
- **Admin** - Administrative operations
- **Manager** - Manage entities and groups
- **Operator** - Execute operations
- **Viewer** - Read-only access
- **ApiClient** - API integration access

### Permissions
- `CryptoOperations` - Cryptographic operations
- `ViewSignatureKeys` - View signing keys
- `ManageSignatureKeys` - Manage signing keys
- `CreateGroup` - Create groups
- `ManageGroupPermissions` - Manage group access
- `CreateDelegationToken` - Create delegation tokens

### Delegation Scope
When acting on behalf of groups:
- `CryptoOperations` - Perform crypto operations for group
- `ReadGroup` - Read group information
- `UpdateGroup` - Update group settings
- `ManageGroupMembers` - Manage group membership

## Supported Assets

- `aud-token-asset` - Australian Dollars
- `usd-token-asset` - US Dollars

## Blockchain Networks

- **Chain 151** - Redbelly Mainnet (Governors)
- **Chain 153** - Redbelly Testnet (Governors)

## Security Notes

- Always use HTTPS in production
- Store JWT tokens securely
- Implement token refresh before expiration
- Use delegation for group operations (maintains audit trail)
- Revoke delegation tokens when access should be removed
- Monitor audit logs for unauthorized access attempts

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                       YieldFabric Platform                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────┐     ┌───────────────────┐   ┌──────────────┐ │
│  │  Auth Service     │────▶│  Payments Service │──▶│ Vault Service│ │
│  │                   │ JWT │                   │   │              │ │
│  │  • Authentication │     │  • GraphQL API    │   │  • ZK Proofs │ │
│  │  • Authorization  │     │  • Balance Queries│   │  • Balances  │ │
│  │  • Delegation     │     │  • Payments       │   │  • Token Ops │ │
│  │  • Groups         │     │  • Obligations    │   │  • Smart     │ │
│  │  • Key Management │     │  • Swaps          │   │    Contract  │ │
│  │  • Crypto Ops     │     │  • Distributions  │   │    Calls     │ │
│  └───────────────────┘     └───────────────────┘   └──────────────┘ │
│                                     │                    │          │
│                                     ▼                    ▼          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │          Intelligent Accounts (On-Chain)                     │   │
│  │                                                              │   │
│  │  • Zero-Knowledge Privacy   • Programmable Payments          │   │
│  │  • Timelocks & Oracles      • Atomic Swaps & Repos           │   │
│  │  • Distribution Merkle Trees                                 │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## License

See main YieldFabric repository for license information.

