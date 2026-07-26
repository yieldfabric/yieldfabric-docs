"""
Ethereum-compatible key generation and signing helpers.

Ports `loan_management/modules/register_external_key.py` (the pure parts):

  - `generate_ethereum_key()` — create a new secp256k1 key pair.
  - `address_from_private_key()` — derive address from hex private key.
  - `ownership_message()` — format the string used for external-key
    registration; must match the frontend exactly so the backend
    accepts the ecrecover result.
  - `sign_ownership_message()` — personal_sign over `ownership_message`.
  - `sign_message_hash()` — personal_sign over a raw 32-byte hash;
    used by the manual-signature flow to sign an unsigned transaction
    produced by the backend.

All functions require `eth_account` at runtime (via eth_account.Account
and eth_account.messages.encode_defunct). The dependency is optional in
requirements.txt; if not installed, calls raise a clear RuntimeError.
"""

import time
from typing import Any, Dict, Sequence, Tuple

# eth-account is an optional dependency. Import lazily and give a
# helpful error message if the caller tries to use these helpers
# without having installed it.
try:
    from eth_account import Account
    from eth_account.messages import encode_defunct
    _HAS_ETH_ACCOUNT = True
except ImportError:
    _HAS_ETH_ACCOUNT = False


_INSTALL_MSG = "eth_account is required for key/signature operations. Install with: pip install eth-account"


def _require_eth_account():
    if not _HAS_ETH_ACCOUNT:
        raise RuntimeError(_INSTALL_MSG)


# ----------------------------------------------------------------------

def generate_ethereum_key() -> Tuple[str, str]:
    """
    Generate a new Ethereum (secp256k1) key pair.

    Returns:
        (private_key_hex, address)
        - private_key_hex: 32-byte hex, no 0x prefix.
        - address: 0x-prefixed, checksummed address.
    """
    _require_eth_account()
    acct = Account.create()
    # acct.key.hex() may or may not include the 0x prefix depending on
    # eth-account version. Normalize to without-prefix for storage.
    priv_hex = acct.key.hex()
    if priv_hex.startswith("0x"):
        priv_hex = priv_hex[2:]
    return priv_hex, acct.address


def address_from_private_key(private_key_hex: str) -> str:
    """
    Derive the Ethereum address from a private key hex string (with or
    without 0x prefix).
    """
    _require_eth_account()
    key = private_key_hex.removeprefix("0x").strip()
    if not key:
        raise ValueError("private_key_hex is empty")
    acct = Account.from_key(key)
    return acct.address


# ----------------------------------------------------------------------
# Ownership message — MUST match the frontend's keysService.registerMetaMaskKey
# format character-for-character, otherwise ecrecover in the backend returns
# a different signer address than the one we claim ownership of.
# ----------------------------------------------------------------------

def ownership_message(address: str) -> str:
    """
    Standard ownership-proof message the backend expects for external
    key registration. The timestamp is in milliseconds to match the
    JavaScript `Date.now()` convention used by the frontend.
    """
    return (
        "Sign this message to prove ownership of your MetaMask wallet "
        "for YieldFabric key registration.\n\n"
        f"Account: {address}\n"
        f"Timestamp: {int(time.time() * 1000)}"
    )


def sign_ownership_message(address: str, private_key_hex: str) -> Tuple[str, str]:
    """
    personal_sign the ownership message for the given address. Returns
    `(message_text, signature_hex)` where signature_hex is 130 hex
    chars (65 bytes of r+s+v), no 0x prefix — the backend expects this
    shape for POST /keys/external/verify-ownership.

    Raises ValueError if the private key doesn't match the address.
    """
    _require_eth_account()
    key = private_key_hex.removeprefix("0x").strip()
    acct = Account.from_key(key)
    if acct.address.lower() != address.lower():
        raise ValueError("private key does not match the given address")

    message_text = ownership_message(address)
    message = encode_defunct(text=message_text)
    signed = acct.sign_message(message)
    sig_hex = signed.signature.hex()
    if sig_hex.startswith("0x"):
        sig_hex = sig_hex[2:]
    return message_text, sig_hex


def eip191_message_hash(message_hash_hex: str) -> str:
    """
    Compute the EIP-191 personal_sign digest of a raw 32-byte hash —
    keccak256("\\x19Ethereum Signed Message:\\n32" || hash) — and return
    it as BARE hex (no 0x prefix).

    This is NOT a signature. It only PREPARES the value a server-held key
    must sign, so the resulting signature recovers under the backend's
    `recover_personal_sign_address_bytes` (EIP-191 personal_sign). The
    signing itself is delegated to the auth REST API
    (`POST /key-operations/vault/sign`, which signs the 32-byte digest it
    is handed verbatim) — we never touch a private key here.

    Mirrors the wallet-SDK's `wrapEip191Hash32` (core/eip191.ts), whose
    output is also bare hex because the sign endpoint `hex::decode`s the
    value and rejects a leading `0x`. Uses eth_account's message encoder
    (already a dependency) — no hand-rolled crypto.
    """
    _require_eth_account()
    msg_hex = (message_hash_hex or "").strip().removeprefix("0x").strip()
    if not msg_hex:
        raise ValueError("message_hash_hex is required")
    hash_bytes = bytes.fromhex(msg_hex)
    if len(hash_bytes) != 32:
        raise ValueError(f"message_hash must be 32 bytes, got {len(hash_bytes)}")

    # Prefer eth_account's own EIP-191 hasher (same encode_defunct used by
    # sign_message_hash below, so the two paths stay byte-identical); fall
    # back to eth_utils.keccak — both ship with eth-account.
    try:
        from eth_account.messages import _hash_eip191_message
        digest = _hash_eip191_message(encode_defunct(primitive=hash_bytes))
    except Exception:
        from eth_utils import keccak
        digest = keccak(b"\x19Ethereum Signed Message:\n32" + hash_bytes)
    return digest.hex()


def recover_eip191_address(message_hash_hex: str, signature: str) -> str:
    """
    Recover the EOA that EIP-191 personal_sign'd a raw 32-byte hash — the SAME address the
    on-chain `ConfidentialOracle.recoverDocumentSigner` / `getSigner` yields. The exact inverse of
    the `eip191_message_hash` + `sign_vault` pair: recovers over
    `keccak256("\\x19Ethereum Signed Message:\\n32" || hash)`.

    `signature` is r+s+v hex (0x optional). A `v` of 0/1 is normalised to 27/28 (the form
    `Account.recover_message` accepts), mirroring the backend's / contract's `v < 27 ⇒ v += 27`.
    """
    _require_eth_account()
    msg_hex = (message_hash_hex or "").strip().removeprefix("0x").strip()
    hash_bytes = bytes.fromhex(msg_hex)
    if len(hash_bytes) != 32:
        raise ValueError(f"message_hash must be 32 bytes, got {len(hash_bytes)}")
    sig_hex = (signature or "").strip().removeprefix("0x").strip()
    sig_bytes = bytearray.fromhex(sig_hex)
    if len(sig_bytes) != 65:
        raise ValueError(f"signature must be 65 bytes, got {len(sig_bytes)}")
    if sig_bytes[64] < 27:
        sig_bytes[64] += 27
    return Account.recover_message(encode_defunct(primitive=hash_bytes), signature=bytes(sig_bytes))


def sign_message_hash(private_key_hex: str, message_hash_hex: str) -> str:
    """
    personal_sign a raw 32-byte hash.

    Used by the manual-signature flow: the backend emits an unsigned
    transaction whose `message_hash` is a 32-byte digest; the smart
    contract recovers the signer with
    `ecrecover(keccak256("\\x19Ethereum Signed Message:\\n32" || hash))`,
    so we sign the digest of that prefixed hash. `encode_defunct` with
    `primitive=<32 bytes>` applies that exact prefix.

    Returns 130 hex chars (65-byte r+s+v), no 0x prefix.
    """
    _require_eth_account()
    key = private_key_hex.removeprefix("0x").strip()
    acct = Account.from_key(key)

    msg_hex = (message_hash_hex or "").strip().removeprefix("0x").strip()
    if not msg_hex:
        raise ValueError("message_hash_hex is required")
    hash_bytes = bytes.fromhex(msg_hex)
    if len(hash_bytes) != 32:
        raise ValueError(f"message_hash must be 32 bytes, got {len(hash_bytes)}")

    message = encode_defunct(primitive=hash_bytes)
    signed = acct.sign_message(message)
    sig_hex = signed.signature.hex()
    if sig_hex.startswith("0x"):
        sig_hex = sig_hex[2:]
    return sig_hex


# ----------------------------------------------------------------------
# Nonce-bound ConfidentialAccount Manual envelope verification.
# ----------------------------------------------------------------------

_UINT256_MAX = (1 << 256) - 1


def _hex_bytes(value: Any, label: str, expected_length: int = None) -> bytes:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a hex string")
    clean = value.strip()
    if clean.startswith(("0x", "0X")):
        clean = clean[2:]
    if len(clean) % 2:
        raise ValueError(f"{label} must have an even number of hex characters")
    try:
        result = bytes.fromhex(clean)
    except ValueError as exc:
        raise ValueError(f"{label} must be valid hex") from exc
    if expected_length is not None and len(result) != expected_length:
        raise ValueError(f"{label} must be {expected_length} bytes")
    return result


def _uint256(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a non-negative integer")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, str):
        if value.startswith(("0x", "0X")):
            if len(value) <= 2:
                raise ValueError(f"{label} must be a non-negative integer")
            try:
                parsed = int(value, 16)
            except ValueError as exc:
                raise ValueError(f"{label} must be a non-negative integer") from exc
        else:
            if not value or (value != "0" and (value.startswith("0") or not value.isdigit())):
                raise ValueError(f"{label} must be a canonical decimal integer")
            parsed = int(value, 10)
    else:
        raise ValueError(f"{label} must be a non-negative integer")
    if parsed < 0 or parsed > _UINT256_MAX:
        raise ValueError(f"{label} is outside uint256")
    return parsed


def _manual_transaction_fields(transaction: Any, index: int) -> Tuple[Any, Any, Any]:
    if isinstance(transaction, (list, tuple)):
        if len(transaction) < 3:
            raise ValueError(
                f"transactions[{index}] must contain address, calldata, and value"
            )
        return transaction[0], transaction[1], transaction[2]
    if isinstance(transaction, dict):
        return (
            transaction.get("contract_address", transaction.get("contractAddress")),
            transaction.get(
                "calldata",
                transaction.get(
                    "function_signature", transaction.get("functionSignature")
                ),
            ),
            transaction.get("value"),
        )
    raise ValueError(f"transactions[{index}] is invalid")


def meta_transaction_message_hash(
    account_address: str,
    chain_id: Any,
    account_nonce: Any,
    transactions: Sequence[Any],
) -> str:
    """
    Byte-exact mirror of Solidity `MetaTransactionLib.buildMessageHash` and
    Rust `yieldfabric_vault::sign_meta`.

    Returns bare lower-case 32-byte hex. It performs no RPC, token, key, or
    database access and is safe to run immediately before wallet consent.
    """
    _require_eth_account()
    from eth_utils import keccak

    account = _hex_bytes(account_address, "account_address", 20)
    if not isinstance(transactions, (list, tuple)) or not transactions:
        raise ValueError("transactions must contain at least one operation")

    aggregate = bytes(32)
    for index, transaction in enumerate(transactions):
        target, calldata, value = _manual_transaction_fields(transaction, index)
        target_bytes = _hex_bytes(
            target, f"transactions[{index}].contract_address", 20
        )
        calldata_bytes = _hex_bytes(
            calldata, f"transactions[{index}].calldata"
        )
        value_bytes = _uint256(
            value, f"transactions[{index}].value"
        ).to_bytes(32, "big")
        aggregate = keccak(
            aggregate + target_bytes + value_bytes + keccak(calldata_bytes)
        )

    return keccak(
        account
        + _uint256(chain_id, "chain_id").to_bytes(32, "big")
        + _uint256(account_nonce, "account_nonce").to_bytes(32, "big")
        + aggregate
    ).hex()


def verify_unsigned_transaction_digest(unsigned_tx: Dict[str, Any]) -> str:
    """
    Recompute a server Manual envelope and reject any body/hash mismatch.

    The returned digest is bare lower-case hex and can be passed directly to
    `sign_message_hash`. Missing nonce/operations are a hard failure: accepting
    an older envelope would silently reintroduce the live-nonce trust gap this
    migration removes.
    """
    if not isinstance(unsigned_tx, dict):
        raise ValueError("unsigned_tx must be an object")
    advertised = unsigned_tx.get("message_hash") or unsigned_tx.get("messageHash")
    if not isinstance(advertised, str):
        raise ValueError("unsigned_tx is missing message_hash")
    advertised = advertised.removeprefix("0x").lower()
    if len(advertised) != 64:
        raise ValueError("message_hash must be 32 bytes")
    try:
        bytes.fromhex(advertised)
    except ValueError as exc:
        raise ValueError("message_hash must be valid hex") from exc

    if "account_nonce" not in unsigned_tx:
        raise ValueError("unsigned_tx is missing account_nonce")
    computed = meta_transaction_message_hash(
        unsigned_tx.get("account_address"),
        unsigned_tx.get("chain_id"),
        unsigned_tx.get("account_nonce"),
        unsigned_tx.get("transactions"),
    )
    if computed != advertised:
        raise ValueError(
            "refusing to sign: message_hash does not match the nonce-bound envelope"
        )
    return computed
