# YieldFabric API - Overview

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

### Distributions (One-to-Many Payments)

Distributions allow sending to **multiple recipients** in a single operation:
- Sender creates a distribution with a list of (recipient, amount) pairs
- Each recipient accepts their share using the standard Accept flow
- Sender can cancel the distribution only if **no recipient has claimed yet**
- Supports NFT-based recipients (claim by `ownerOf` at claim time)

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

### Repo Swaps & Rolling

**Repo swaps** add collateral to an atomic swap, with a repurchase option before expiry:
- Collateral held in escrow; repurchase before expiry or forfeit after
- **Repo rolling**: Two-step flow (initiate roll → complete roll) to move collateral into a new repo with a new counterparty and terms — without the original counterparty repurchasing first

---

## Common Headers

All authenticated requests require:

```bash
-H "Authorization: Bearer $TOKEN"
-H "Content-Type: application/json"
```

---

## Next Steps

1. [**Authentication**](./02-AUTHENTICATION.md) - Login and delegation
2. [**Balances**](./03-BALANCES.md) - Check balances and locked transactions
3. [**Contracts**](./04-CONTRACTS.md) - Create and view obligations
4. [**Payments**](./05-PAYMENTS.md) - Deposits, instant payments, distributions, accept and cancel
5. [**Swaps**](./06-SWAPS.md) - Atomic swaps, repo swaps, repurchase, and repo rolling
6. [**Workflows**](./07-WORKFLOWS.md) - Complete end-to-end examples
7. [**Reference**](./08-REFERENCE.md) - Error codes, assets, chains
8. [**Cryptographic Operations**](./09-CRYPTOGRAPHIC-OPERATIONS.md) - Key management, encryption, signatures

