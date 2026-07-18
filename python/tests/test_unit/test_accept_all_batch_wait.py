"""Regression coverage for acceptAll's asynchronous child messages."""

from unittest.mock import MagicMock

from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.output_store import OutputStore
from yieldfabric.executors.payment_executor import PaymentExecutor
from yieldfabric.executors.wait_executor import WaitExecutor
from yieldfabric.models import Command, CommandParameters, GraphQLResponse, User
from yieldfabric.utils.graphql import GraphQLMutation
from yieldfabric.utils.polling import PollResult


def _config():
    return YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        command_delay=0,
        debug=False,
    )


def _command(command_type="accept_all", **params):
    return Command(
        name="accept_batch",
        type=command_type,
        user=User(id="investor@yieldfabric.com", password="pw"),
        parameters=CommandParameters.from_dict(params),
    )


def _services():
    auth = MagicMock(name="AuthService")
    auth.login.return_value = "user.jwt"
    payments = MagicMock(name="PaymentsService")
    return auth, payments


def _completed(message_id):
    return PollResult(
        observation={
            "executed": "2026-07-17T00:28:11Z",
            "response": {
                "status": "completed",
                "success": True,
                "post_processed_at": "2026-07-17T00:28:13Z",
            },
            "message_id": message_id,
        },
        attempts=2,
        elapsed=2.0,
    )


def _accept_all_data(message_ids):
    return {
        "success": True,
        "message": f"Successfully accepted all {len(message_ids)} payments",
        "totalPayments": len(message_ids),
        "acceptedCount": len(message_ids),
        "failedCount": 0,
        "acceptedPayments": [
            {
                "paymentId": f"payment-{index}",
                "amount": "100",
                "messageId": message_id,
                "transactionId": f"transaction-{index}",
            }
            for index, message_id in enumerate(message_ids)
        ],
        "failedPayments": [],
        "timestamp": "2026-07-17T00:28:09Z",
    }


def test_accept_exposes_canonical_idempotency_result():
    auth, payments = _services()
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={
            "accept": {
                "success": True,
                "disposition": "ALREADY_SATISFIED",
                "message": "Payment already accepted (idempotent no-op)",
                "accountAddress": "0x1234",
                "idHash": None,
                "acceptResult": (
                    "Payment is already COMPLETED; no on-chain action was submitted"
                ),
                "messageId": "canonical-message",
                "transactionId": "canonical-transaction",
                "timestamp": "2026-07-17T03:28:43Z",
            }
        },
    )
    executor = PaymentExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(
            "accept",
            payment_id="payment-1",
            idempotency_key="compatibility-only",
            wait=False,
        )
    )

    assert response.success
    assert response.data["disposition"] == "ALREADY_SATISFIED"
    assert response.data["message_id"] == "canonical-message"
    assert response.data["transaction_id"] == "canonical-transaction"
    assert "disposition" in GraphQLMutation.ACCEPT
    assert "transactionId" in GraphQLMutation.ACCEPT


def test_accept_all_waits_for_every_returned_message_before_success():
    auth, payments = _services()
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"acceptAll": _accept_all_data(["message-1", "message-2"])},
    )
    payments.poll_message_completion.side_effect = [
        _completed("message-1"),
        _completed("message-2"),
    ]
    executor = PaymentExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(
            denomination="aud-token-asset",
            wait=True,
            user_id="entity-1",
        )
    )

    assert response.success
    assert response.data["message_ids"] == ["message-1", "message-2"]
    assert [call.args[1] for call in payments.poll_message_completion.call_args_list] == [
        "message-1",
        "message-2",
    ]
    assert len(response.data["message_waits"]) == 2
    assert response.data["wait_attempts"] == 4


def test_accept_all_wait_false_preserves_fire_and_forget_behavior():
    auth, payments = _services()
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"acceptAll": _accept_all_data(["message-1"])},
    )
    executor = PaymentExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(denomination="aud-token-asset", wait=False)
    )

    assert response.success
    assert response.data["message_ids"] == ["message-1"]
    payments.poll_message_completion.assert_not_called()


def test_accept_all_rejects_duplicate_child_message_ids():
    auth, payments = _services()
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"acceptAll": _accept_all_data(["message-1", "message-1"])},
    )
    executor = PaymentExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(
            denomination="aud-token-asset",
            wait=True,
            user_id="entity-1",
        )
    )

    assert not response.success
    assert "2 accepted payment(s)" in response.errors[0]
    assert "1 distinct durable message id(s)" in response.errors[0]
    payments.poll_message_completion.assert_not_called()


def test_accept_all_fails_when_any_child_execution_fails():
    auth, payments = _services()
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"acceptAll": _accept_all_data(["message-1"])},
    )
    payments.poll_message_completion.return_value = PollResult(
        observation={
            "executed": "2026-07-17T00:28:11Z",
            "response": {"status": "failed", "success": False, "error": "reverted"},
        },
        attempts=2,
        elapsed=2.0,
    )
    executor = PaymentExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(
            denomination="aud-token-asset",
            wait=True,
            user_id="entity-1",
        )
    )

    assert not response.success
    assert "message-1: reverted" in response.errors


def test_accept_all_fails_when_child_is_canceled():
    auth, payments = _services()
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"acceptAll": _accept_all_data(["message-1"])},
    )
    payments.poll_message_completion.return_value = PollResult(
        observation={
            "executed": "2026-07-17T00:28:11Z",
            "response": {"status": "canceled"},
        },
        attempts=2,
        elapsed=2.0,
    )
    executor = PaymentExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(
            denomination="aud-token-asset",
            wait=True,
            user_id="entity-1",
        )
    )

    assert not response.success
    assert "message-1: message execution canceled" in response.errors


def test_accept_all_fails_when_child_has_error_without_failure_status():
    auth, payments = _services()
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"acceptAll": _accept_all_data(["message-1"])},
    )
    payments.poll_message_completion.return_value = PollResult(
        observation={
            "executed": "2026-07-17T00:28:11Z",
            "response": {"status": "completed", "error": "projection failed"},
        },
        attempts=2,
        elapsed=2.0,
    )
    executor = PaymentExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(
            denomination="aud-token-asset",
            wait=True,
            user_id="entity-1",
        )
    )

    assert not response.success
    assert "message-1: projection failed" in response.errors


def test_accept_all_fails_when_child_wait_times_out():
    auth, payments = _services()
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"acceptAll": _accept_all_data(["message-1"])},
    )
    payments.poll_message_completion.side_effect = TimeoutError(
        "message processing timed out"
    )
    executor = PaymentExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(
            denomination="aud-token-asset",
            wait=True,
            user_id="entity-1",
        )
    )

    assert not response.success
    assert "message-1: message processing timed out" in response.errors
    assert response.data["wait_timed_out"] is True
    assert response.data["message_waits"][0]["wait_timed_out"] is True


def test_wait_for_accept_all_also_waits_for_trailing_settlement():
    auth, payments = _services()
    payments.poll_accept_all_until_ready.return_value = PollResult(
        observation=_accept_all_data(["message-1"]),
        attempts=3,
        elapsed=4.0,
    )
    payments.poll_message_completion.return_value = _completed("message-1")
    executor = WaitExecutor(auth, payments, OutputStore(), _config())

    response = executor.execute(
        _command(
            "wait_for_accept_all",
            denomination="aud-token-asset",
            idempotency_key="accept-batch-1",
            user_id="entity-1",
        )
    )

    assert response.success
    payments.poll_accept_all_until_ready.assert_called_once()
    payments.poll_message_completion.assert_called_once()
    assert response.data["message_ids"] == ["message-1"]
    assert response.data["message_waits"][0]["post_processed_at"] == (
        "2026-07-17T00:28:13Z"
    )
