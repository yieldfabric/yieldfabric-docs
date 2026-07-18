"""
Messages API: get message, list awaiting signature, wait for completion, get unsigned tx, submit signature.

Used to link Python-triggered operations with manual signing:
- In the app: user signs in SignaturePreviewDrawer; Python can poll for completion.
- From Python: get unsigned transaction (message_hash), sign with issuer key, submit signature.

All endpoints are on the payments service: PAY_SERVICE_URL.
"""

import time
from typing import List, Optional

import requests

from .http_client import auth_headers


def get_unsigned_transaction(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    message_id: str,
    timeout: int = 15,
) -> dict:
    """
    GET /api/users/{user_id}/messages/{message_id}/unsigned-transaction.
    Returns dict with message_hash (hex), unsigned_transaction_id,
    account_address, chain_id, context, etc. Both message_hash and
    unsigned_transaction_id must be carried into signature submission.
    Raises RuntimeError if not found (404) or other error.
    """
    url = f"{pay_service_url.rstrip('/')}/api/users/{user_id}/messages/{message_id}/unsigned-transaction"
    headers = auth_headers(jwt_token)
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error", resp.text)
        except Exception:
            msg = resp.text
        raise RuntimeError(f"Get unsigned transaction failed ({resp.status_code}): {msg}")
    return resp.json()


def wait_for_unsigned_transaction_ready(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    message_id: str,
    poll_interval_seconds: float = 2.0,
    max_wait_seconds: float = 120.0,
    timeout_per_request: int = 15,
) -> dict:
    """
    Poll until the backend has produced the unsigned transaction for this message (status manual_signature).
    Use after creating a message (e.g. acceptObligation returns messageId): poll until the MQ has
    validated the message and stored the unsigned tx, then sign and submit.

    Returns the unsigned transaction dict (with message_hash). Raises RuntimeError on timeout.
    """
    start = time.monotonic()
    while (time.monotonic() - start) < max_wait_seconds:
        try:
            return get_unsigned_transaction(
                pay_service_url, jwt_token, user_id, message_id, timeout=timeout_per_request
            )
        except RuntimeError as e:
            if "404" in str(e) or "not found" in str(e).lower():
                time.sleep(poll_interval_seconds)
                continue
            raise
        time.sleep(poll_interval_seconds)
    raise RuntimeError(
        f"Timeout ({max_wait_seconds}s) waiting for unsigned transaction for message {message_id}"
    )


def submit_signed_message(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    message_id: str,
    signature_hex: str,
    unsigned_transaction_id: str,
    timeout: int = 15,
) -> dict:
    """
    POST /api/users/{user_id}/messages/{message_id}/submit-signed-message.
    Body: { "signature": "<hex with 0x>",
            "unsigned_transaction_id": "<UUID from GET>" }.
    Returns success/status.
    """
    sig = (signature_hex or "").strip()
    if not sig.startswith("0x"):
        sig = "0x" + sig
    url = f"{pay_service_url.rstrip('/')}/api/users/{user_id}/messages/{message_id}/submit-signed-message"
    headers = auth_headers(jwt_token)
    resp = requests.post(
        url,
        json={
            "signature": sig,
            "unsigned_transaction_id": unsigned_transaction_id,
        },
        headers=headers,
        timeout=timeout,
    )
    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error", err.get("message", resp.text))
        except Exception:
            msg = resp.text
        raise RuntimeError(f"Submit signed message failed ({resp.status_code}): {msg}")
    return resp.json()


def get_message(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    message_id: str,
    timeout: int = 15,
) -> dict:
    """
    GET /api/users/{user_id}/messages/{message_id}.
    Returns the message payload (id, executed, response.status, response.success, data, etc.).
    """
    url = f"{pay_service_url.rstrip('/')}/api/users/{user_id}/messages/{message_id}"
    headers = auth_headers(jwt_token)
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error", resp.text)
        except Exception:
            msg = resp.text
        raise RuntimeError(f"Get message failed ({resp.status_code}): {msg}")
    return resp.json()


def get_messages_awaiting_signature(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    timeout: int = 15,
) -> List[dict]:
    """
    GET /api/users/{user_id}/messages/awaiting-signature.
    Returns the list of messages that require manual signature (same as the app's drawer list).
    """
    url = f"{pay_service_url.rstrip('/')}/api/users/{user_id}/messages/awaiting-signature"
    headers = auth_headers(jwt_token)
    resp = requests.get(url, headers=headers, timeout=timeout)
    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error", resp.text)
        except Exception:
            msg = resp.text
        raise RuntimeError(f"Get messages awaiting signature failed ({resp.status_code}): {msg}")
    data = resp.json()
    # API returns {"messages": [...], "count": N, ...}; support both list and object response
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "messages" in data:
        return data["messages"]
    return []


def wait_for_message_completion(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    message_id: str,
    poll_interval_seconds: float = 2.0,
    max_wait_seconds: float = 300.0,
    timeout_per_request: int = 15,
) -> dict:
    """
    Poll GET message until executed or max_wait_seconds.
    Returns the last message payload. If completed, message has executed=True.
    On timeout, returns dict with "error" and "last" (last message payload).
    """
    start = time.monotonic()
    last: Optional[dict] = None
    while (time.monotonic() - start) < max_wait_seconds:
        try:
            last = get_message(
                pay_service_url, jwt_token, user_id, message_id, timeout=timeout_per_request
            )
        except Exception as e:
            if last is not None:
                return {"error": str(e), "last": last}
            raise
        if last.get("executed"):
            return last
        time.sleep(poll_interval_seconds)
    return {
        "error": f"Timeout waiting for message completion ({max_wait_seconds}s)",
        "last": last,
    }


def sign_and_submit_manual_message(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    message_id: str,
    private_key_hex: str,
    timeout: int = 15,
) -> dict:
    """
    Get unsigned transaction (message_hash), sign with private key (Ethereum personal_sign),
    submit signature. Uses the same flow as the app's SignaturePreviewDrawer for external keys.

    Use the issuer key from e.g. issuer_external_key.txt (created by ensure_issuer_key flow).
    If the backend may not have produced the unsigned tx yet, use poll_until_sign_and_submit_manual_message.

    Returns the response from submit-signed-message (success, message_id, status).
    """
    unsigned = get_unsigned_transaction(
        pay_service_url, jwt_token, user_id, message_id, timeout=timeout
    )
    return _sign_and_submit_unsigned_transaction(
        pay_service_url,
        jwt_token,
        user_id,
        message_id,
        private_key_hex,
        unsigned,
        timeout=timeout,
    )


def _sign_and_submit_unsigned_transaction(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    message_id: str,
    private_key_hex: str,
    unsigned: dict,
    timeout: int,
) -> dict:
    """Sign and submit one exact backend-issued unsigned generation."""
    from .register_external_key import sign_message_hash_manual_flow

    message_hash = unsigned.get("message_hash")
    if not message_hash:
        raise RuntimeError("Unsigned transaction has no message_hash")
    unsigned_transaction_id = unsigned.get("unsigned_transaction_id")
    if not isinstance(unsigned_transaction_id, str) or not unsigned_transaction_id.strip():
        raise RuntimeError("Unsigned transaction has no unsigned_transaction_id")

    signature_hex = sign_message_hash_manual_flow(private_key_hex, message_hash)
    return submit_signed_message(
        pay_service_url,
        jwt_token,
        user_id,
        message_id,
        signature_hex,
        unsigned_transaction_id,
        timeout=timeout,
    )


def poll_until_sign_and_submit_manual_message(
    pay_service_url: str,
    jwt_token: str,
    user_id: str,
    message_id: str,
    private_key_hex: str,
    poll_interval_seconds: float = 2.0,
    max_wait_seconds: float = 120.0,
    timeout_per_request: int = 15,
) -> dict:
    """
    Full flow: poll until backend has produced the unsigned transaction for this message,
    then sign with the local private key and submit. Use after creating a message (e.g.
    acceptObligation returns messageId) so Python can concurrently wait for the backend
    to be ready, then sign and submit without app interaction.

    - Python creates message (gets message_id) and submits to backend
    - Backend processes message for signature (MQ creates unsigned tx, status manual_signature)
    - This function polls until unsigned tx is ready, signs with private_key_hex, submits
    - Backend continues processing the signed message as per normal flow

    Returns the response from submit-signed-message.
    """
    unsigned = wait_for_unsigned_transaction_ready(
        pay_service_url,
        jwt_token,
        user_id,
        message_id,
        poll_interval_seconds=poll_interval_seconds,
        max_wait_seconds=max_wait_seconds,
        timeout_per_request=timeout_per_request,
    )
    return _sign_and_submit_unsigned_transaction(
        pay_service_url,
        jwt_token,
        user_id,
        message_id,
        private_key_hex,
        unsigned,
        timeout=timeout_per_request,
    )
