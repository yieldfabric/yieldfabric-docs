# Balance Queries

Complete guide to querying account balances and understanding locked transactions.

---

## Get Balance

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

---

## Response Example

```json
{
  "private_balance": "125",
  "public_balance": "99775",
  "decimals": "100",
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

---

## Response Fields

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

**Notes:**
- Instant payments have `obligation_id = "0"` and typically have minimal oracle requirements. Contract-based obligations have non-zero `obligation_id` and may include oracle conditions for conditional release.
- **Distribution** payments also appear in `locked_in` / `locked_out`. Each recipient sees their share as a `locked_in` entry with the distribution contract's address. The sender sees the total locked amount in `locked_out`.

---

## Understanding Your Balance

Your available balance is calculated as:
```
Available = private_balance - outstanding
```

Where:
- `private_balance`: Total encrypted balance
- `outstanding`: Sum of all `locked_out` transaction amounts

Incoming `locked_in` transactions don't affect your balance until you accept them.

