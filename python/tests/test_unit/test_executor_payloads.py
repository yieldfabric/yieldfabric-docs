from unittest.mock import MagicMock, patch

import pytest

from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.output_store import OutputStore
from yieldfabric.executors.group_admin_executor import GroupAdminExecutor
from yieldfabric.executors.obligation_executor import ObligationExecutor
from yieldfabric.executors.swap_executor import SwapExecutor
from yieldfabric.models import Command, CommandParameters, GraphQLResponse, User


@pytest.fixture
def config():
    return YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        command_delay=0,
        debug=False,
    )


@pytest.fixture
def services():
    auth = MagicMock(name="AuthService")
    auth.login.return_value = "user.jwt"
    auth.login_with_group.return_value = "delegation.jwt"

    payments = MagicMock(name="PaymentsService")
    return auth, payments


def _command(name, cmd_type, params, *, group=None):
    params = dict(params)
    params.setdefault("wait", False)
    return Command(
        name=name,
        type=cmd_type,
        user=User(id="issuer@yieldfabric.com", password="pw", group=group),
        parameters=CommandParameters.from_dict(params),
    )


def test_create_obligation_sends_yaml_contract_id(config, services):
    auth, payments = services
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={
            "createObligation": {
                "success": True,
                "contractId": "credit_token_1",
                "messageId": "msg-1",
            }
        },
    )

    executor = ObligationExecutor(auth, payments, OutputStore(), config)
    response = executor.execute(
        _command(
            "credit_token",
            "create_obligation",
            {
                "counterpart": "Issuer Group",
                "expiry": "2027-01-30T00:00:00Z",
                "contract_id": "credit_token_1",
                "initial_payments": {
                    "amount": 10,
                    "payments": [{"id": "script-local-payment-id"}],
                },
            },
            group="Issuer Group",
        )
    )

    assert response.success
    payload = payments.graphql_mutation.call_args.args[1]
    assert payload["input"]["contractId"] == "credit_token_1"
    assert payload["input"]["initialPayments"]["amount"] == "10"
    payment = payload["input"]["initialPayments"]["payments"][0]
    assert "id" not in payment
    assert "oracleOwner" not in payment
    assert "oracleAddress" not in payment


def test_create_swap_flattens_ergonomic_yaml_shape(config, services):
    auth, payments = services
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={
            "createSwap": {
                "success": True,
                "swapId": "123456789",
                "messageId": "msg-1",
            }
        },
    )

    executor = SwapExecutor(auth, payments, OutputStore(), config)
    response = executor.execute(
        _command(
            "create_investment_swap_1",
            "create_swap",
            {
                "swap_id": "123456789",
                "initiator": {"obligation_ids": ["investment_token_1"]},
                "counterparty": {
                    "id": "investor@yieldfabric.com",
                    "expected_payments": {
                        "denomination": "aud-token-asset",
                        "amount": 1000,
                        "payments": [{"id": "swap-payment-1"}],
                    },
                },
                "deadline": "2027-01-30T00:00:00Z",
            },
            group="Issuer Group",
        )
    )

    assert response.success
    payload = payments.graphql_mutation.call_args.args[1]
    assert payload["input"]["swapId"] == "123456789"
    assert payload["input"]["counterparty"] == "investor@yieldfabric.com"
    assert payload["input"]["deadline"] == "2027-01-30T00:00:00Z"
    assert payload["input"]["initiatorObligationIds"] == ["investment_token_1"]
    assert payload["input"]["counterpartyExpectedPayments"]["denomination"] == "aud-token-asset"
    assert payload["input"]["counterpartyExpectedPayments"]["amount"] == "1000"
    payment = payload["input"]["counterpartyExpectedPayments"]["payments"][0]
    assert "id" not in payment
    assert "oracleOwner" not in payment
    assert "oracleAddress" not in payment
    assert payment["oracleKeySender"] == "0"
    mutation = payments.graphql_mutation.call_args.args[0]
    assert "counterpartyAddress" not in mutation
    assert "counterparty" in mutation


def test_add_account_member_retries_contract_resolution_race(config, services):
    auth, payments = services
    auth.login.return_value = "user.jwt"
    auth.get_user_group_id_by_name.return_value = "group-1"
    auth.add_account_member.side_effect = [
        {
            "status": "error",
            "message": "Cannot resolve custom contract_id 'credit_token_1' to obligation_id",
        },
        {"status": "success"},
    ]

    executor = GroupAdminExecutor(auth, payments, OutputStore(), config)
    with patch("yieldfabric.executors.group_admin_executor.time.sleep"):
        response = executor.execute(
            _command(
                "add_issuer_group_member_1",
                "add_account_member",
                {"obligation_id": "credit_token_1"},
                group="Issuer Group",
            )
        )

    assert response.success
    assert auth.add_account_member.call_count == 2


def test_add_account_member_waits_for_durable_operation_confirmation(config, services):
    auth, payments = services
    auth.login.return_value = "user.jwt"
    auth.get_user_group_id_by_name.return_value = "group-1"
    auth.add_account_member.return_value = {
        "success": True,
        "status": "pending_signature",
        "operation_id": "operation-1",
        "message_id": "message-1",
    }
    auth.get_group_account_operation.side_effect = [
        {
            "success": True,
            "status": "pending",
            "operation_id": "operation-1",
            "message_id": "message-1",
        },
        {
            "success": True,
            "status": "confirmed",
            "operation_id": "operation-1",
            "message_id": "message-1",
        },
    ]

    executor = GroupAdminExecutor(auth, payments, OutputStore(), config)
    with patch("yieldfabric.executors.group_admin_executor.time.sleep"):
        response = executor.execute(
            _command(
                "add_issuer_group_member_1",
                "add_account_member",
                {
                    "obligation_id": "credit_token_1",
                    "wait": True,
                    "wait_interval": 0,
                },
                group="Issuer Group",
            )
        )

    assert response.success
    assert response.data["operation_id"] == "operation-1"
    assert response.data["message_id"] == "message-1"
    assert response.data["operation_status"] == "confirmed"
    assert auth.get_group_account_operation.call_count == 2
