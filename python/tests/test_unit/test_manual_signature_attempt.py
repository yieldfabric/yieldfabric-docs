"""Attempt-bound manual-signature wire coverage."""

from unittest.mock import MagicMock

from loan_management.modules import messages as loan_messages
from loan_management.modules import register_external_key
from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.message_listener import MessageSignatureListener
from yieldfabric.services.payments_service import PaymentsService
from yieldfabric.utils.polling import PollResult


ATTEMPT_ID = "5ce1ce91-f8aa-4db7-ae56-ac2f0a82358a"


def _config() -> YieldFabricConfig:
    return YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        debug=False,
    )


def test_payments_service_submits_signature_with_unsigned_generation():
    service = PaymentsService(_config())
    response = MagicMock(name="Response")
    response.json.return_value = {"success": True}
    service.session.post = MagicMock(return_value=response)

    result = service.submit_signed_message(
        "user-1",
        "message-1",
        "0xsigned",
        ATTEMPT_ID,
        "jwt-1",
    )

    assert result == {"success": True}
    service.session.post.assert_called_once_with(
        "http://localhost:3002/api/users/user-1/messages/message-1/submit-signed-message",
        json={
            "signature": "0xsigned",
            "unsigned_transaction_id": ATTEMPT_ID,
        },
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer jwt-1",
        },
        timeout=service.config.request_timeout,
    )
    response.raise_for_status.assert_called_once_with()


def test_message_listener_carries_polled_generation_into_submit():
    payments = MagicMock(name="PaymentsService")
    unsigned = {
        "message_hash": "ab" * 32,
        "unsigned_transaction_id": ATTEMPT_ID,
    }
    payments.poll_unsigned_transaction_ready.return_value = PollResult(
        observation=unsigned,
        attempts=1,
        elapsed=0.0,
    )
    payments.submit_signed_message.return_value = {"success": True}
    signer = MagicMock(return_value="0xsigned")
    listener = MessageSignatureListener(
        payments,
        "user-1",
        "jwt-1",
        sign_callback=signer,
    )

    listener._process_one("message-1")

    signer.assert_called_once_with(unsigned)
    payments.submit_signed_message.assert_called_once_with(
        "user-1",
        "message-1",
        "0xsigned",
        ATTEMPT_ID,
        "jwt-1",
    )
    assert listener.signed_count == 1
    assert listener.errored_count == 0


def test_message_listener_refuses_unsigned_payload_without_generation():
    payments = MagicMock(name="PaymentsService")
    payments.poll_unsigned_transaction_ready.return_value = PollResult(
        observation={"message_hash": "ab" * 32},
        attempts=1,
        elapsed=0.0,
    )
    signer = MagicMock(return_value="0xsigned")
    listener = MessageSignatureListener(
        payments,
        "user-1",
        "jwt-1",
        sign_callback=signer,
    )

    listener._process_one("message-1")

    signer.assert_not_called()
    payments.submit_signed_message.assert_not_called()
    assert listener.signed_count == 0
    assert listener.errored_count == 1


def test_loan_helper_carries_get_generation_into_submit(monkeypatch):
    unsigned = {
        "message_hash": "ab" * 32,
        "unsigned_transaction_id": ATTEMPT_ID,
    }
    get_unsigned = MagicMock(return_value=unsigned)
    submit = MagicMock(return_value={"success": True})
    signer = MagicMock(return_value="0xsigned")
    monkeypatch.setattr(loan_messages, "get_unsigned_transaction", get_unsigned)
    monkeypatch.setattr(loan_messages, "submit_signed_message", submit)
    monkeypatch.setattr(register_external_key, "sign_message_hash_manual_flow", signer)

    result = loan_messages.sign_and_submit_manual_message(
        "http://localhost:3002",
        "jwt-1",
        "user-1",
        "message-1",
        "private-key",
        timeout=11,
    )

    assert result == {"success": True}
    signer.assert_called_once_with("private-key", unsigned["message_hash"])
    submit.assert_called_once_with(
        "http://localhost:3002",
        "jwt-1",
        "user-1",
        "message-1",
        "0xsigned",
        ATTEMPT_ID,
        timeout=11,
    )


def test_loan_submit_uses_attempt_bound_rest_body(monkeypatch):
    response = MagicMock(name="Response")
    response.status_code = 200
    response.json.return_value = {"success": True}
    post = MagicMock(return_value=response)
    monkeypatch.setattr(loan_messages.requests, "post", post)

    result = loan_messages.submit_signed_message(
        "http://localhost:3002/",
        "jwt-1",
        "user-1",
        "message-1",
        "signed",
        ATTEMPT_ID,
        timeout=9,
    )

    assert result == {"success": True}
    post.assert_called_once_with(
        "http://localhost:3002/api/users/user-1/messages/message-1/submit-signed-message",
        json={
            "signature": "0xsigned",
            "unsigned_transaction_id": ATTEMPT_ID,
        },
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer jwt-1",
        },
        timeout=9,
    )


def test_loan_helper_rejects_unsigned_payload_without_generation(monkeypatch):
    monkeypatch.setattr(
        loan_messages,
        "get_unsigned_transaction",
        MagicMock(return_value={"message_hash": "ab" * 32}),
    )
    submit = MagicMock()
    signer = MagicMock(return_value="0xsigned")
    monkeypatch.setattr(loan_messages, "submit_signed_message", submit)
    monkeypatch.setattr(register_external_key, "sign_message_hash_manual_flow", signer)

    try:
        loan_messages.sign_and_submit_manual_message(
            "http://localhost:3002",
            "jwt-1",
            "user-1",
            "message-1",
            "private-key",
        )
    except RuntimeError as error:
        assert "unsigned_transaction_id" in str(error)
    else:
        raise AssertionError("missing attempt ID must fail before signing")

    signer.assert_not_called()
    submit.assert_not_called()
