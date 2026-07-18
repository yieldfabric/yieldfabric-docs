"""Focused tests for the explicit Accepted -> Active deal lifecycle."""

from unittest.mock import MagicMock, patch

import pytest

from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.output_store import OutputStore
from yieldfabric.core.runner import YieldFabricRunner
from yieldfabric.executors.deal_executor import DealExecutor
from yieldfabric.models import (
    Command,
    CommandParameters,
    CommandResponse,
    GraphQLResponse,
    User,
)
from yieldfabric.services.agents_service import AgentsService
from yieldfabric.utils.polling import PollResult


@pytest.fixture
def config():
    return YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        agents_service_url="http://localhost:3001",
        command_delay=0,
        debug=False,
    )


def _command(command_type="activate_deal", params=None, *, group=None):
    return Command(
        name=f"test_{command_type}",
        type=command_type,
        user=User(
            id="issuer@yieldfabric.com",
            password="issuer_password",
            group=group,
        ),
        parameters=CommandParameters.from_dict(params or {}),
    )


def _executor(config):
    auth = MagicMock(name="AuthService")
    auth.login.return_value = "proposer.jwt"
    auth.login_with_group.return_value = "group-proposer.jwt"
    payments = MagicMock(name="PaymentsService")
    output_store = OutputStore()
    executor = DealExecutor(auth, payments, output_store, config)
    executor.agents_service = MagicMock(name="AgentsService")
    return executor, auth, output_store


def _active_response():
    return GraphQLResponse(
        success=True,
        data={
            "dealFlow": {
                "activateDeal": {
                    "success": True,
                    "message": "Deal activated via pipelines",
                    "deal": {
                        "id": "DEAL-123",
                        "status": "ACTIVE",
                        "workflowId": "workflow-123",
                    },
                }
            }
        },
    )


def _pending_action():
    return {
        "workflowId": "workflow-1",
        "descriptorInputs": {"_pipeline": {"group_id": "runtime-group"}},
    }


def _step_poll_result(status, *, result=None, workflow_status="running"):
    return PollResult(
        observation={
            "workflow": {
                "id": "workflow-1",
                "status": workflow_status,
            },
            "step": {
                "step_key": "register_policy",
                "status": status,
                "result": result,
                "external_message_id": "message-1",
            },
        },
        attempts=2,
        elapsed=0.25,
    )


def test_activate_deal_calls_agents_as_group_proposer_and_stores_status(config):
    executor, auth, output_store = _executor(config)
    executor.agents_service.graphql.return_value = _active_response()
    command = _command(
        params={"deal_id": "DEAL-123"},
        group="Issuer Group",
    )

    response = executor.execute(command)

    assert response.success
    assert response.data["deal_id"] == "DEAL-123"
    assert response.data["status"] == "ACTIVE"
    assert response.data["workflow_id"] == "workflow-123"
    assert output_store.get("test_activate_deal", "status") == "ACTIVE"
    assert output_store.get("test_activate_deal", "workflow_id") == "workflow-123"
    auth.login_with_group.assert_called_once_with(
        "issuer@yieldfabric.com", "issuer_password", "Issuer Group"
    )
    auth.login.assert_not_called()

    query, variables, token = executor.agents_service.graphql.call_args.args
    assert "activateDeal(input: $input)" in query
    assert variables == {"input": {"dealId": "DEAL-123"}}
    assert token == "group-proposer.jwt"


def test_activate_deal_without_group_preserves_self_session(config):
    executor, auth, _ = _executor(config)
    executor.agents_service.graphql.return_value = _active_response()

    response = executor.execute(
        _command(params={"deal_id": "DEAL-123"})
    )

    assert response.success
    auth.login.assert_called_once_with(
        "issuer@yieldfabric.com", "issuer_password"
    )
    auth.login_with_group.assert_not_called()


def test_activate_deal_requires_deal_id_before_calling_agents(config):
    executor, _, _ = _executor(config)

    response = executor.execute(_command())

    assert not response.success
    assert response.errors == ["activate_deal requires `deal_id`"]
    executor.agents_service.graphql.assert_not_called()


def test_propose_deal_honors_explicit_group_proposer(config):
    executor, auth, _ = _executor(config)
    executor.agents_service.graphql.return_value = GraphQLResponse(
        success=True,
        data={
            "dealFlow": {
                "proposeDeal": {
                    "success": True,
                    "message": "Deal proposed",
                    "deal": {
                        "id": "DEAL-123",
                        "status": "PROPOSED",
                        "name": "Escrow",
                    },
                }
            }
        },
    )
    command = _command(
        "propose_deal",
        {
            "name": "Escrow",
            "plan": {"entry_step_ids": ["start"], "nodes": []},
            "parties": [{"entity_id": "beneficiary-id", "role": "beneficiary"}],
        },
        group="Issuer Group",
    )

    response = executor.execute(command)

    assert response.success
    auth.login_with_group.assert_called_once()
    assert executor.agents_service.graphql.call_args.args[2] == "group-proposer.jwt"


def test_execute_step_honors_explicit_group_assignee(config):
    executor, auth, _ = _executor(config)
    executor.agents_service.execute_step.return_value = {"status": "accepted"}
    executor.agents_service.poll_workflow_step.return_value = _step_poll_result(
        "completed", result={"policy_id": "policy-1"}
    )
    command = _command(
        "execute_step",
        {"deal_id": "DEAL-123", "step_id": "register_policy"},
        group="Issuer Group",
    )

    with patch.object(
        executor, "_await_pending_action", return_value=_pending_action()
    ):
        response = executor.execute(command)

    assert response.success
    assert response.data["step_status"] == "completed"
    assert response.data["step_result"] == {"policy_id": "policy-1"}
    assert response.data["external_message_id"] == "message-1"
    auth.login_with_group.assert_called_once()
    executor.agents_service.execute_step.assert_called_once_with(
        "group-proposer.jwt",
        group_id="runtime-group",
        workflow_id="workflow-1",
        step_key="register_policy",
        refresh_token=None,
    )
    executor.agents_service.poll_workflow_step.assert_called_once_with(
        "group-proposer.jwt",
        group_id="runtime-group",
        workflow_id="workflow-1",
        step_key="register_policy",
        interval=3.0,
        timeout=300.0,
    )


def test_execute_step_surfaces_background_step_failure(config):
    executor, _, output_store = _executor(config)
    executor.agents_service.execute_step.return_value = {"status": "accepted"}
    executor.agents_service.poll_workflow_step.return_value = _step_poll_result(
        "failed",
        result={"error": "payment is already COMPLETED"},
        workflow_status="failed",
    )
    command = _command(
        "execute_step",
        {"deal_id": "DEAL-123", "step_id": "register_policy"},
        group="Issuer Group",
    )

    with patch.object(
        executor, "_await_pending_action", return_value=_pending_action()
    ):
        response = executor.execute(command)

    assert not response.success
    assert response.errors == [
        "workflow step 'register_policy' reached terminal status failed: "
        "payment is already COMPLETED"
    ]
    assert response.data["step_status"] == "failed"
    assert output_store.get("test_execute_step", "step_status") == "failed"


def test_execute_step_accepts_idempotent_execute_then_waits_for_completion(config):
    executor, _, _ = _executor(config)
    executor.agents_service.execute_step.return_value = {
        "status": "error",
        "message": "step is already in progress",
        "status_code": 409,
    }
    executor.agents_service.poll_workflow_step.return_value = _step_poll_result(
        "completed"
    )
    command = _command(
        "execute_step",
        {"deal_id": "DEAL-123", "step_id": "register_policy"},
        group="Issuer Group",
    )

    with patch.object(
        executor, "_await_pending_action", return_value=_pending_action()
    ):
        response = executor.execute(command)

    assert response.success
    assert response.data["step_status"] == "completed"
    executor.agents_service.poll_workflow_step.assert_called_once()


def test_execute_step_poll_timeout_is_command_failure(config):
    executor, _, _ = _executor(config)
    executor.agents_service.execute_step.return_value = {"status": "accepted"}
    executor.agents_service.poll_workflow_step.side_effect = TimeoutError(
        "timed out waiting for register_policy"
    )
    command = _command(
        "execute_step",
        {
            "deal_id": "DEAL-123",
            "step_id": "register_policy",
            "wait_timeout": 12,
        },
        group="Issuer Group",
    )

    with patch.object(
        executor, "_await_pending_action", return_value=_pending_action()
    ):
        response = executor.execute(command)

    assert not response.success
    assert response.errors == ["timed out waiting for register_policy"]
    assert response.data["wait_timed_out"] is True
    assert response.data["wait_error"] == "timed out waiting for register_policy"
    assert executor.agents_service.poll_workflow_step.call_args.kwargs["timeout"] == 12.0


def test_execute_step_wait_false_preserves_fire_and_forget(config):
    executor, _, _ = _executor(config)
    executor.agents_service.execute_step.return_value = {"status": "accepted"}
    command = _command(
        "execute_step",
        {
            "deal_id": "DEAL-123",
            "step_id": "register_policy",
            "wait": False,
        },
        group="Issuer Group",
    )

    with patch.object(
        executor, "_await_pending_action", return_value=_pending_action()
    ):
        response = executor.execute(command)

    assert response.success
    assert "step_status" not in response.data
    executor.agents_service.poll_workflow_step.assert_not_called()


def test_execute_step_forwards_the_refresh_token_paired_with_its_delegation(config):
    executor, auth, _ = _executor(config)
    manager = MagicMock(name="TokenManager")
    manager.get_token.return_value = "group-proposer.jwt"
    manager.refresh_token_for_access_token.return_value = "delegation-refresh-1"
    executor.token_manager = manager
    executor.agents_service.execute_step.return_value = {"status": "accepted"}
    command = _command(
        "execute_step",
        {
            "deal_id": "DEAL-123",
            "step_id": "register_policy",
            "wait": False,
        },
        group="Issuer Group",
    )

    with patch.object(
        executor, "_await_pending_action", return_value=_pending_action()
    ):
        response = executor.execute(command)

    assert response.success
    auth.login_with_group.assert_not_called()
    manager.refresh_token_for_access_token.assert_called_once_with(
        "group-proposer.jwt"
    )
    executor.agents_service.execute_step.assert_called_once_with(
        "group-proposer.jwt",
        group_id="runtime-group",
        workflow_id="workflow-1",
        step_key="register_policy",
        refresh_token="delegation-refresh-1",
    )


def test_execute_step_wait_false_rejects_a_409_instead_of_false_passing(config):
    executor, _, _ = _executor(config)
    executor.agents_service.execute_step.return_value = {
        "status": "error",
        "message": "step is already in progress",
        "status_code": 409,
    }
    command = _command(
        "execute_step",
        {
            "deal_id": "DEAL-123",
            "step_id": "register_policy",
            "wait": False,
        },
        group="Issuer Group",
    )

    with patch.object(
        executor, "_await_pending_action", return_value=_pending_action()
    ):
        response = executor.execute(command)

    assert not response.success
    assert response.errors == ["/execute failed: step is already in progress"]
    executor.agents_service.poll_workflow_step.assert_not_called()


def test_execute_step_does_not_infer_success_from_error_text(config):
    executor, _, _ = _executor(config)
    executor.agents_service.execute_step.return_value = {
        "status": "error",
        "message": "step is not ready",
        "status_code": 400,
    }
    command = _command(
        "execute_step",
        {"deal_id": "DEAL-123", "step_id": "register_policy"},
        group="Issuer Group",
    )

    with patch.object(
        executor, "_await_pending_action", return_value=_pending_action()
    ):
        response = executor.execute(command)

    assert not response.success
    assert response.errors == ["/execute failed: step is not ready"]
    executor.agents_service.poll_workflow_step.assert_not_called()


def test_pending_action_selects_the_newest_active_matching_step(config):
    executor, _, _ = _executor(config)
    old_completed = {
        "id": "old-completed",
        "stepId": "register_policy",
        "status": "COMPLETED",
        "descriptorInputs": {"_pipeline": {"group_id": "old"}},
    }
    older_pending = {
        "id": "older-pending",
        "stepId": "register_policy",
        "status": "PENDING",
        "descriptorInputs": {"_pipeline": {"group_id": "older"}},
    }
    newest_active = {
        "id": "newest-active",
        "stepId": "register_policy",
        "status": "IN_PROGRESS",
        "descriptorInputs": {"_pipeline": {"group_id": "newest"}},
    }
    executor.agents_service.graphql.return_value = GraphQLResponse(
        success=True,
        data={
            "dealFlow": {
                "pendingActionsForDeal": [
                    old_completed,
                    older_pending,
                    newest_active,
                ]
            }
        },
    )

    selected = executor._await_pending_action(
        "jwt", "DEAL-123", "register_policy", timeout=0, interval=0
    )

    assert selected == newest_active


def test_agents_execute_step_forwards_refresh_token_header(config):
    service = AgentsService(config)
    response = MagicMock()
    response.json.return_value = {"status": "accepted"}
    service._post = MagicMock(return_value=response)

    result = service.execute_step(
        "delegation.jwt",
        group_id="group-1",
        workflow_id="workflow-1",
        step_key="register_policy",
        refresh_token="delegation-refresh-1",
    )

    assert result == {"status": "accepted"}
    service._post.assert_called_once_with(
        "/working-groups/group-1/workflows/workflow-1/steps/register_policy/execute",
        {},
        token="delegation.jwt",
        refresh_token="delegation-refresh-1",
    )


def test_agents_service_polls_the_exact_step_until_terminal(config):
    service = AgentsService(config)
    service.get_workflow = MagicMock(
        side_effect=[
            {
                "workflow": {"status": "running"},
                "steps": [
                    {"step_key": "other", "status": "completed"},
                    {"step_key": "target", "status": "in_progress"},
                ],
            },
            {
                "workflow": {"status": "running"},
                "steps": [
                    {"step_key": "other", "status": "completed"},
                    {
                        "step_key": "target",
                        "status": "completed",
                        "result": {"value": 1},
                    },
                ],
            },
        ]
    )

    result = service.poll_workflow_step(
        "jwt",
        group_id="group-1",
        workflow_id="workflow-1",
        step_key="target",
        interval=0.001,
        timeout=1,
    )

    assert result.attempts == 2
    assert result.observation["step"]["step_key"] == "target"
    assert result.observation["step"]["status"] == "completed"


def test_agents_service_stops_when_workflow_fails_before_step_is_terminal(config):
    service = AgentsService(config)
    service.get_workflow = MagicMock(
        return_value={
            "workflow": {
                "status": "failed",
                "result_summary": "background operation failed",
            },
            "steps": [{"step_key": "target", "status": "in_progress"}],
        }
    )

    result = service.poll_workflow_step(
        "jwt",
        group_id="group-1",
        workflow_id="workflow-1",
        step_key="target",
        interval=0.001,
        timeout=1,
    )

    assert result.attempts == 1
    assert result.observation["workflow"]["status"] == "failed"
    assert result.observation["step"]["status"] == "in_progress"


def test_runner_routes_activate_deal_to_deal_executor(config):
    runner = YieldFabricRunner(config)
    expected = CommandResponse.success_response(
        "test_activate_deal",
        "activate_deal",
        {"deal_id": "DEAL-123", "status": "ACTIVE"},
    )
    runner.deal_executor = MagicMock(name="DealExecutor")
    runner.deal_executor.execute.return_value = expected
    command = _command(params={"deal_id": "DEAL-123"})

    response = runner.execute_command(command)

    assert response is expected
    runner.deal_executor.execute.assert_called_once_with(command)


def test_runner_logs_unexpected_command_errors_before_halting(config):
    runner = YieldFabricRunner(config)
    command = _command("balance", {"asset_id": "aud-token-asset"})
    runner.logger = MagicMock()
    runner.yaml_validator.validate = MagicMock(return_value=(True, []))
    runner.service_validator.validate_services = MagicMock(return_value=True)
    runner.yaml_parser.parse_file = MagicMock(return_value=[command])
    runner.execute_command = MagicMock(
        return_value=CommandResponse.error_response(
            command.name,
            command.type,
            ["timed out waiting for an incoming payment"],
        )
    )

    assert runner.execute_file("suite.yaml") is False
    runner.logger.error.assert_any_call(
        "    ❌ timed out waiting for an incoming payment"
    )
