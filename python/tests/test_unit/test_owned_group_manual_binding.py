"""Fail-closed client checks for nested external signing."""

from unittest.mock import MagicMock

import pytest

from yieldfabric.core.message_listener import MessageSignatureListener
from yieldfabric.utils.polling import PollResult


ATTEMPT_ID = "5ce1ce91-f8aa-4db7-ae56-ac2f0a82358a"
EXPECTED_BINDING = {
    "actor_sub": "11111111-1111-4111-8111-111111111111",
    "acting_as": "22222222-2222-4222-8222-222222222222",
    "delegation_token_id": "33333333-3333-4333-8333-333333333333",
    "delegation_path": [
        "44444444-4444-4444-8444-444444444444",
        "22222222-2222-4222-8222-222222222222",
    ],
    "authority_source": "nft_membership",
    "membership_edge": {
        "parent_group_id": "44444444-4444-4444-8444-444444444444",
        "child_group_id": "22222222-2222-4222-8222-222222222222",
        "chain_id": "153",
        "credential_contract": "0x1111111111111111111111111111111111111111",
        "token_id": "42",
    },
    "signer_key_id": "55555555-5555-4555-8555-555555555555",
    "signer_address": "0x2222222222222222222222222222222222222222",
    "signer_scheme": "account_ecdsa65_v1",
    "signer_custody": "external",
}


def _listener(unsigned):
    payments = MagicMock(name="PaymentsService")
    payments.poll_unsigned_transaction_ready.return_value = PollResult(
        observation=unsigned,
        attempts=1,
        elapsed=0.0,
    )
    payments.submit_signed_message.return_value = {"success": True}
    signer = MagicMock(return_value="0xsigned")
    listener = MessageSignatureListener(
        payments,
        EXPECTED_BINDING["acting_as"],
        "owned-child-jwt",
        sign_callback=signer,
        expected_authorization_binding=EXPECTED_BINDING,
    )
    return listener, payments, signer


def test_nested_manual_listener_signs_only_exact_authorization_binding():
    unsigned = {
        "unsigned_transaction_id": ATTEMPT_ID,
        "authorization_binding": EXPECTED_BINDING,
    }
    listener, payments, signer = _listener(unsigned)

    listener._process_one("message-1")

    signer.assert_called_once_with(unsigned)
    payments.submit_signed_message.assert_called_once()
    assert listener.signed_count == 1
    assert listener.errored_count == 0


def test_nested_manual_listener_refuses_missing_authorization_binding():
    listener, payments, signer = _listener({
        "unsigned_transaction_id": ATTEMPT_ID,
    })

    listener._process_one("message-1")

    signer.assert_not_called()
    payments.submit_signed_message.assert_not_called()
    assert listener.signed_count == 0
    assert listener.errored_count == 1


def test_nested_manual_listener_refuses_any_binding_mismatch():
    for field in EXPECTED_BINDING:
        changed = dict(EXPECTED_BINDING)
        changed[field] = "tampered"
        listener, payments, signer = _listener({
            "unsigned_transaction_id": ATTEMPT_ID,
            "authorization_binding": changed,
        })

        listener._process_one("message-1")

        signer.assert_not_called()
        payments.submit_signed_message.assert_not_called()
        assert listener.signed_count == 0
        assert listener.errored_count == 1


def test_nested_manual_listener_refuses_legacy_or_extra_binding_fields():
    changed = dict(EXPECTED_BINDING)
    changed["authority_key_id"] = "66666666-6666-4666-8666-666666666666"
    listener, payments, signer = _listener({
        "unsigned_transaction_id": ATTEMPT_ID,
        "authorization_binding": changed,
    })

    listener._process_one("message-1")

    signer.assert_not_called()
    payments.submit_signed_message.assert_not_called()
    assert listener.signed_count == 0
    assert listener.errored_count == 1


def test_direct_listener_refuses_owned_binding_outside_owned_session():
    unsigned = {
        "unsigned_transaction_id": ATTEMPT_ID,
        "authorization_binding": EXPECTED_BINDING,
    }
    payments = MagicMock(name="PaymentsService")
    payments.poll_unsigned_transaction_ready.return_value = PollResult(
        observation=unsigned,
        attempts=1,
        elapsed=0.0,
    )
    signer = MagicMock(return_value="0xsigned")
    listener = MessageSignatureListener(
        payments,
        EXPECTED_BINDING["acting_as"],
        "direct-group-jwt",
        sign_callback=signer,
    )

    listener._process_one("message-1")

    signer.assert_not_called()
    payments.submit_signed_message.assert_not_called()
    assert listener.signed_count == 0
    assert listener.errored_count == 1


def test_stopped_listener_never_signs_or_submits_an_inflight_observation():
    unsigned = {
        "unsigned_transaction_id": ATTEMPT_ID,
        "authorization_binding": EXPECTED_BINDING,
    }
    listener, payments, signer = _listener(unsigned)
    listener._stop_event.set()

    listener._process_one("message-1")

    signer.assert_not_called()
    payments.submit_signed_message.assert_not_called()
    assert listener.signed_count == 0
    assert listener.errored_count == 0


def test_stop_fails_visibly_while_worker_remains_alive():
    listener, _, _ = _listener({})
    worker = MagicMock()
    worker.is_alive.return_value = True
    listener._thread = worker

    with pytest.raises(RuntimeError, match="cancellation-pending"):
        listener.stop(timeout=0)

    worker.join.assert_called_once_with(timeout=0)
