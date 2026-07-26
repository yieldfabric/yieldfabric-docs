import pytest

from yieldfabric.utils.crypto import (
    meta_transaction_message_hash,
    verify_unsigned_transaction_digest,
)


ACCOUNT = "0x0000000000000000000000000000000000000aaa"
TARGET_A = "0x0000000000000000000000000000000000000bbb"
TARGET_B = "0x0000000000000000000000000000000000000ccc"


def test_matches_solidity_rust_one_operation_vector():
    expected = (
        "8769c2d479082da958a2417ef6a0a1b052d472ec1519cde7bd0d9df01bcd3b10"
    )
    envelope = {
        "account_address": ACCOUNT,
        "chain_id": 31337,
        "account_nonce": "5",
        "transactions": [[TARGET_A, "0x12345678", "1000", None]],
        "message_hash": expected,
    }
    assert meta_transaction_message_hash(
        envelope["account_address"],
        envelope["chain_id"],
        envelope["account_nonce"],
        envelope["transactions"],
    ) == expected
    assert verify_unsigned_transaction_digest(envelope) == expected


def test_high_uint256_and_operation_order_are_bound():
    high_nonce = str(2**255 + 123)
    expected = (
        "fd0359561e070de62f25af369201c6d5841aa5c0625273002271988f220c12da"
    )
    operations = [
        [TARGET_A, "0x00", "0", None],
        [TARGET_B, "0xdeadbeef", str(2**200), None],
    ]
    assert meta_transaction_message_hash(
        ACCOUNT, "153", high_nonce, operations
    ) == expected
    assert meta_transaction_message_hash(
        ACCOUNT, "153", high_nonce, list(reversed(operations))
    ) != expected


@pytest.mark.parametrize(
    "mutation",
    [
        {"account_address": TARGET_B},
        {"chain_id": "153"},
        {"account_nonce": "6"},
        {"transactions": [[TARGET_B, "0x12345678", "1000", None]]},
        {"transactions": [[TARGET_A, "0x12345679", "1000", None]]},
        {"transactions": [[TARGET_A, "0x12345678", "1001", None]]},
    ],
)
def test_verifier_rejects_every_signed_field_mutation(mutation):
    envelope = {
        "account_address": ACCOUNT,
        "chain_id": "31337",
        "account_nonce": "5",
        "transactions": [[TARGET_A, "0x12345678", "1000", None]],
        "message_hash": (
            "8769c2d479082da958a2417ef6a0a1b052d472ec1519cde7bd0d9df01bcd3b10"
        ),
    }
    envelope.update(mutation)
    with pytest.raises(ValueError, match="refusing to sign"):
        verify_unsigned_transaction_digest(envelope)


def test_verifier_rejects_legacy_live_nonce_envelope():
    with pytest.raises(ValueError, match="account_nonce"):
        verify_unsigned_transaction_digest({
            "account_address": ACCOUNT,
            "chain_id": "31337",
            "transactions": [[TARGET_A, "0x", "0", None]],
            "message_hash": "00" * 32,
        })

