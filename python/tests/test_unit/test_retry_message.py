"""Canonical failed-message redrive coverage."""

import base64
import json
from unittest.mock import MagicMock

from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.output_store import OutputStore
from yieldfabric.core.runner import YieldFabricRunner
from yieldfabric.executors.payment_executor import PaymentExecutor
from yieldfabric.models import Command, CommandParameters, CommandResponse, User
from yieldfabric.services.payments_service import PaymentsService
from yieldfabric.utils.polling import PollResult


def _jwt(**claims):
    def part(value):
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{part({'alg': 'none'})}.{part(claims)}.signature"


def _config():
    return YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        command_delay=0,
        debug=False,
    )


def _command(**parameters):
    return Command(
        name="collect_rent_2",
        type="retry_message",
        user=User(
            id="originator@yieldfabric.com",
            password="pw",
            group="Rental Property",
        ),
        parameters=CommandParameters.from_dict(parameters),
    )


def _executor():
    token = _jwt(sub="user-1", acting_as="group-1")
    auth = MagicMock(name="AuthService")
    auth.login_with_group.return_value = token
    payments = MagicMock(name="PaymentsService")
    return PaymentExecutor(auth, payments, OutputStore(), _config()), payments, token


def test_retry_message_redrives_and_polls_the_same_canonical_id():
    executor, payments, token = _executor()
    payments.retry_message.return_value = {
        "success": True,
        "message": "Message submitted for re-execution",
        "message_id": "message-1",
        "execution_mode": "Automatic",
    }
    payments.poll_message_completion.return_value = PollResult(
        observation={
            "executed": "2026-07-17T04:20:00Z",
            "response": {
                "success": True,
                "status": "completed",
                "post_processed_at": "2026-07-17T04:20:01Z",
            },
        },
        attempts=3,
        elapsed=4.0,
    )

    response = executor.execute(
        _command(message_id="message-1", execution_mode="automatic")
    )

    assert response.success
    assert response.data["message_id"] == "message-1"
    payments.retry_message.assert_called_once_with(
        "group-1", "message-1", "Automatic", token
    )
    assert payments.poll_message_completion.call_args.args[:3] == (
        "group-1",
        "message-1",
        token,
    )


def test_retry_message_rest_failure_does_not_poll():
    executor, payments, _ = _executor()
    payments.retry_message.return_value = {
        "success": False,
        "message": "Message cannot be re-executed",
    }

    response = executor.execute(_command(message_id="message-1"))

    assert not response.success
    assert "cannot be re-executed" in response.errors[0]
    payments.poll_message_completion.assert_not_called()


def test_retry_message_requires_same_id_in_success_response():
    executor, payments, _ = _executor()
    payments.retry_message.return_value = {
        "success": True,
        "message": "Message submitted for re-execution",
    }

    response = executor.execute(_command(message_id="message-1"))

    assert not response.success
    assert "same message_id" in response.errors[0]
    payments.poll_message_completion.assert_not_called()


def test_expected_execution_failure_keeps_message_id_for_later_redrive():
    executor, payments, token = _executor()
    payments.poll_message_completion.return_value = PollResult(
        observation={
            "executed": "2026-07-17T04:12:29Z",
            "response": {
                "success": False,
                "status": "failed",
                "error_message": "Vault address mismatch",
            },
        },
        attempts=2,
        elapsed=2.0,
    )
    early = Command(
        name="collect_rent_2_early_fails",
        type="accept",
        user=User(id="originator@yieldfabric.com", password="pw"),
        parameters=CommandParameters.from_dict({"expect_failure": True}),
    )

    response = executor._finalize_success(
        early,
        token,
        {"message_id": "failed-message"},
        success_message="Accept successful!",
    )

    assert not response.success
    assert executor.output_store.substitute(
        "$collect_rent_2_early_fails.message_id"
    ) == "failed-message"


def test_retry_message_requires_message_id_before_calling_service():
    executor, payments, _ = _executor()

    response = executor.execute(_command())

    assert not response.success
    assert "requires `message_id`" in response.errors[0]
    payments.retry_message.assert_not_called()


def test_retry_message_rejects_manual_mode_before_calling_service():
    executor, payments, _ = _executor()

    response = executor.execute(
        _command(message_id="message-1", execution_mode="Manual")
    )

    assert not response.success
    assert "only supports `Automatic`" in response.errors[0]
    payments.retry_message.assert_not_called()
    payments.poll_message_completion.assert_not_called()


def test_runner_routes_retry_message_to_payment_executor():
    runner = object.__new__(YieldFabricRunner)
    runner.payment_executor = MagicMock(name="PaymentExecutor")
    expected = CommandResponse.success_response(
        "collect_rent_2", "retry_message", {"message_id": "message-1"}
    )
    runner.payment_executor.execute.return_value = expected
    command = _command(message_id="message-1", wait=False)

    assert runner.execute_command(command) is expected
    runner.payment_executor.execute.assert_called_once_with(command)


def test_payments_service_retry_uses_exact_rest_contract():
    config = _config()
    service = PaymentsService(config)
    http_response = MagicMock(name="Response")
    http_response.status_code = 200
    http_response.json.return_value = {
        "success": True,
        "message_id": "message-1",
        "execution_mode": "Automatic",
    }
    service.session.post = MagicMock(return_value=http_response)

    result = service.retry_message(
        "group-1", "message-1", "Automatic", "delegated-token"
    )

    assert result["message_id"] == "message-1"
    service.session.post.assert_called_once_with(
        "http://localhost:3002/api/users/group-1/messages/message-1/retry",
        json={"execution_mode": "Automatic"},
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer delegated-token",
        },
        timeout=config.request_timeout,
    )
    http_response.raise_for_status.assert_called_once_with()
