# Linking Python to manual signing

This doc explains two ways to complete the manual signature flow:

1. **User signs in the app** – Python triggers an operation; the message appears in the app (SignaturePreviewDrawer); the user signs in the UI; Python can poll for completion.
2. **Python signs with its key** – Python triggers an operation, then (optionally polls until the backend has the unsigned tx, then) signs with the issuer private key and submits. No app interaction needed.

## Does this flow enable: create → backend processes → Python polls & signs → backend continues?

**Yes.** The flow is supported as follows:

| Step | What happens |
|------|----------------|
| 1. Python creates message and submits to backend | Python calls a workflow API (e.g. `accept_obligation_graphql`) with the right wallet/account. The backend enqueues the message and returns `messageId`. |
| 2. Backend processes message for signature | MQ validates the message, creates the unsigned transaction, stores it, and sets status to `manual_signature`. |
| 3. Python concurrently polls for message_id awaiting signature, signs with local private key | Python polls until the unsigned transaction is available (`wait_for_unsigned_transaction_ready` or `poll_until_sign_and_submit_manual_message`), then signs the `message_hash` with the local private key and calls `submit_signed_message`. |
| 4. Backend continues processing of signed message as per normal flow | MQ receives the signature via `submit-signed-message`, continues execution, and completes the message (same as when the app submits a signature). |

**One-call helper:** Use `poll_until_sign_and_submit_manual_message(pay_service_url, jwt_token, user_id, message_id, private_key_hex)` after you have `message_id` from step 1. It polls until the unsigned tx is ready, then signs and submits. Optionally poll `wait_for_message_completion` afterward to wait for execution to finish.

---

## Does the backend support flagging a specific message to manual signature?

**New messages (at creation):** No. When a message is created (e.g. via acceptObligation, completeSwap), the backend does **not** accept an `execution_mode` on the message. The payments service always enqueues with `Automatic`; the MQ then applies **wallet execution mode preference** for `(wallet_id, message_type)`. So to get manual signature for a new message you must set the **wallet** to Manual for that message type (e.g. `PUT /api/wallets/{wallet_id}/execution-mode-preferences/AcceptObligation` with `"Manual"`). Every message created for that wallet + type will then require manual signature.

**Existing failed message:** No mode conversion is supported. A failed Manual
command is inspect-only; correct the condition and submit a fresh typed command,
which creates a fresh unsigned-transaction generation. The public
`POST /api/users/{user_id}/messages/{message_id}/retry` resource is deliberately
narrow: it redrives only a failed, fully post-processed `Retrieve` whose stored
mode is already `Automatic`, and its body may only request
`{ "execution_mode": "Automatic" }`. It preserves the canonical payment-claim
message id and never changes execution mode.

So: **per-message Manual is not a retry feature**. Use the wallet-level Manual
preference before submitting a new operation.

## End-to-end flow

1. **Execution mode** – The **wallet** used for the operation must have **Manual** execution mode for that **message type** (e.g. `AcceptObligation`). Then when the message is enqueued, the MQ uses that preference and the message waits for manual signature instead of auto-executing.
2. **Python** – Calls the same workflow APIs it already uses (e.g. GraphQL `acceptObligation`) with the right **wallet** (e.g. loan wallet) and **account** (e.g. `X-Account-Address`, `X-Wallet-Id`). The backend creates a message with that `wallet_id`; MQ looks up execution mode for `(wallet_id, message_type)` and, if Manual, validates the message, creates and stores an **unsigned transaction**, and sets status to `manual_signature`.
3. **App** – User sees the message in “awaiting signature” (or message list). Opens the drawer → gets unsigned transaction (with `message_hash`) → selects key (e.g. issuer external key) → signs (MetaMask or API) → submits signature.
4. **Backend** – MQ receives the signature via `submit-signed-message`, continues execution, and completes the message.
5. **Python** – Can **poll** `GET /api/users/{user_id}/messages/{message_id}` (or use the returned `messageId` from the mutation) until the message is completed.

So the “link” is: **same operations** (accept obligation, complete swap, etc.) + **Manual** for that wallet + message type; no new “submit message” API from Python.

---

## 1. Set wallet execution mode to Manual

For the **wallet** that will be used in the operation (e.g. loan wallet `WLT-LOAN-{entity}-{loan_id}`), set execution mode to **Manual** for the relevant **message type** (e.g. `AcceptObligation`, `Retrieve`). Then any message created for that wallet + type will wait for manual signature.

**API (payments service):**

- **Single preference:**  
  `PUT /api/wallets/{wallet_id}/execution-mode-preferences/{message_type}`  
  Body: `{ "execution_mode": "Manual" }`  
  Headers: `Authorization: Bearer <jwt>`
- **All preferences:**  
  `PUT /api/wallets/{wallet_id}/execution-mode-preferences`  
  Body: `{ "preferences": [ { "message_type": "AcceptObligation", "execution_mode": "Manual" }, ... ] }`

**Message type** must match the enum (e.g. `AcceptObligation`, `Retrieve`, `CompleteSwap`, `Deposit`, `Send`, etc.).

**From Python** (using `modules.wallet_preferences`):

```python
from modules.wallet_preferences import set_wallet_execution_mode_preference

# After loading env and obtaining jwt_token (e.g. login_user)
set_wallet_execution_mode_preference(
    pay_service_url, jwt_token,
    wallet_id="WLT-LOAN-<entity_id>-<loan_id>",
    message_type="AcceptObligation",
    execution_mode="Manual",
)
# Then any AcceptObligation for this wallet will require manual sign in the app
```

You can do this once per wallet (or per wallet + message type) before running the workflow. The app’s Wallet Policies screen uses the same APIs.

---

## 2. Python triggers the operation (creates the message)

Use your **existing** workflow calls that create messages, with the **same wallet and account** you want to sign as (e.g. loan wallet / loan account). The backend will enqueue a message with that `wallet_id`; MQ will apply the execution mode preference and, if Manual, produce an unsigned transaction and set status to `manual_signature`.

**Example – accept obligation as loan wallet (already in wisr):**

- `accept_obligation_graphql(pay_service_url, jwt_token, contract_id, account_address=obligor_address_for_loan, wallet_id=obligor_wallet_id_for_loan)`  
- Response includes `messageId`. That message will be in `manual_signature` if the wallet has Manual for `AcceptObligation`.

Other operations (complete swap, retrieve, deposit, send, etc.) work the same way: call the same GraphQL/REST you already use, with the right wallet/account; the created message will follow that wallet’s execution mode.

---

## 3. User signs in the app

- User opens the app, goes to the wallet/actions view where “awaiting signature” messages are shown (or the main message list).
- Clicks the message → **SignaturePreviewDrawer** opens.
- App calls `GET /api/users/{user_id}/messages/{message_id}/unsigned-transaction` (payments adds `message_hash` and the attempt-bound `unsigned_transaction_id`).
- User selects a key (e.g. issuer external key registered for that loan wallet).
- User signs (MetaMask for external key, or API for internal key).
- App calls `POST /api/users/{user_id}/messages/{message_id}/submit-signed-message` with `{ "signature": "<hex>", "unsigned_transaction_id": "<UUID returned by GET>" }`.

The ID must come from the same GET response whose `message_hash` was signed.
If the transaction is rebuilt before submission, payments returns `409`; the
app reloads and asks the user to review and sign the current transaction.

No change needed in Python for this step; it’s the existing app flow (see [MANUAL_SIGNATURE_FLOW.md](./MANUAL_SIGNATURE_FLOW.md)).

---

## 4. Python polls for message completion (optional)

After triggering the operation, Python has the **message ID** (e.g. from `acceptObligation.messageId` or the mutation response). You can poll until the message is no longer “awaiting signature” and has completed (or failed).

**API (payments service):**

- **Single message:**  
  `GET /api/users/{user_id}/messages/{message_id}`  
  Headers: `Authorization: Bearer <jwt>`
- **Messages awaiting signature:**  
  `GET /api/users/{user_id}/messages/awaiting-signature`

Response for a message includes fields like `executed`, `response.status`, `response.success`. When the user has signed and the backend has finished execution, the message will be completed (or failed).

**From Python** (using `modules.messages`):

```python
from modules.messages import wait_for_message_completion, get_message

# After triggering the operation (e.g. accept_obligation_graphql) you have message_id
result = wait_for_message_completion(
    pay_service_url, jwt_token, user_id, message_id,
    poll_interval_seconds=2.0,
    max_wait_seconds=300.0,
)
if result.get("executed"):
    # User signed and message completed
    pass
elif "error" in result:
    # Timeout or error; result.get("last") has last message payload
    print(result["error"])
```

Single message fetch: `get_message(pay_service_url, jwt_token, user_id, message_id)`.  
List awaiting signature: `get_messages_awaiting_signature(pay_service_url, jwt_token, user_id)`.

---

## 5. Python signs the message (no app)

To have **Python** sign the message using the private key it created (e.g. from `ensure_issuer_key` / `issuer_external_key.txt`):

1. Trigger the operation as in section 2; capture `messageId`. The message enters `manual_signature`.
2. Get the unsigned transaction (includes `message_hash`), sign the hash with the issuer private key (Ethereum `personal_sign` format, same as the app/MetaMask), submit the signature.

**From Python (one call):**

```python
from pathlib import Path
from modules.messages import sign_and_submit_manual_message

private_key_hex = Path("issuer_external_key.txt").read_text().strip()
result = sign_and_submit_manual_message(
    pay_service_url, jwt_token, user_id, message_id, private_key_hex
)
```

**CLI:** `./run.sh manual_signature_flow.py sign-and-submit --message-id <uuid> [--key-file issuer_external_key.txt]`

**Full flow (create → poll → sign → submit):**

```python
from pathlib import Path
from modules.auth import login_user, get_user_id_from_profile
from modules.payments import accept_obligation_graphql
from modules.messages import poll_until_sign_and_submit_manual_message

# 1. Login, set Manual for wallet (once), then trigger operation
jwt_token = login_user(auth_service_url, email, password)
user_id = get_user_id_from_profile(auth_service_url, jwt_token)
result = accept_obligation_graphql(
    pay_service_url, jwt_token, contract_id,
    account_address=obligor_address, wallet_id=obligor_wallet_id,
)
message_id = result.get("messageId")

# 2. Poll until backend has unsigned tx, then sign with local key and submit
private_key_hex = Path("issuer_external_key.txt").read_text().strip()
poll_until_sign_and_submit_manual_message(
    pay_service_url, jwt_token, user_id, message_id, private_key_hex,
    poll_interval_seconds=2.0, max_wait_seconds=120.0,
)
# 3. Backend continues and completes the message
```

**Step-by-step (manual):** `wait_for_unsigned_transaction_ready` → `sign_and_submit_manual_message`. Or `get_unsigned_transaction` → `sign_message_hash_manual_flow` (from `modules.register_external_key`) → `submit_signed_message`. The key must be the same external key registered as owner of the wallet the message is for.

---

## Summary

| Step | Who | What |
|------|-----|------|
| 1 | Python or App | Set wallet execution mode to **Manual** for the relevant message type (`PUT /api/wallets/{wallet_id}/execution-mode-preferences/{message_type}`). |
| 2 | Python | Trigger the operation (e.g. `acceptObligation`) with the **loan wallet** and **account**; capture `messageId`. |
| 3 | Backend | Message is enqueued; MQ creates unsigned transaction and sets status `manual_signature`. |
| 4 | User in App **or** Python | App: opens drawer, signs, submits. **Python:** `sign_and_submit_manual_message(..., private_key_hex)` (uses key from e.g. `issuer_external_key.txt`). |
| 5 | Backend | MQ receives signature, continues execution, completes message. |
| 6 | Python | Optionally poll until `executed` or use `wait_for_message_completion`. |

No new “submit raw message” endpoint is required: Python uses the **same workflow APIs** (GraphQL/REST) that already create messages; the only extra is setting **Manual** for that wallet + message type so the message waits for the app’s manual signature flow.
