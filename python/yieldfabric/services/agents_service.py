"""
Agents service client.

The agents service (:3001) hosts the federated deal-flow GraphQL — the
`dealFlow { … }` namespace (proposeDeal / signDeal / activateDeal /
setDealAutomationKey / revokeDealAutomationKey / dealAutomationStatus /
dealPeriods). This is a
SEPARATE GraphQL endpoint from payments (:3002/graphql); deal-lifecycle
commands must target the agents URL, so the deal executor talks to this
client rather than `PaymentsService.graphql_mutation`.

A router-wide request-auth middleware on agents signature-validates every
presented bearer before any resolver runs, so every call here carries the
caller's user JWT in the Authorization header (handled by `_post`).
"""

from typing import Any, Callable, Dict, Optional, Union

from .base import BaseServiceClient
from ..config import YieldFabricConfig
from ..models.response import GraphQLResponse
from ..utils.polling import PollResult, poll_until


TokenLike = Union[str, Callable[[], Optional[str]]]


class AgentsService(BaseServiceClient):
    """Client for the Agents Service deal-flow GraphQL."""

    _STEP_TERMINAL_STATES = {
        "completed",
        "failed",
        "rejected",
        "cancelled",
        "skipped",
    }
    _WORKFLOW_TERMINAL_STATES = {"completed", "failed", "cancelled"}

    def __init__(self, config: YieldFabricConfig):
        super().__init__(config.agents_service_url, config)

    def graphql(
        self,
        query: str,
        variables: Dict[str, Any],
        token: str,
    ) -> GraphQLResponse:
        """
        Execute a GraphQL operation (mutation OR query) against
        `<agents_url>/graphql`. Mirrors
        `PaymentsService.graphql_mutation` — same payload shape, same
        `GraphQLResponse` wrapper — but points at the agents subgraph.
        """
        payload = {"query": query, "variables": variables}

        self.logger.debug("  📋 Agents GraphQL operation")
        self.logger.debug(f"  📋 Agents GraphQL variables: {variables}")

        try:
            response = self._post("/graphql", payload, token=token)
            data = response.json()
            self.logger.debug(f"  📡 Raw agents GraphQL response: {data}")
            return GraphQLResponse.from_response(data)
        except Exception as e:
            self.logger.error(f"    ❌ Agents GraphQL operation failed: {e}")
            return GraphQLResponse(success=False, errors=[{"message": str(e)}])

    def execute_step(
        self,
        token: str,
        *,
        group_id: str,
        workflow_id: str,
        step_key: str,
        refresh_token: Optional[str] = None,
    ) -> dict:
        """
        Drive a deferred on-chain payment step via
        `POST /working-groups/{group_id}/workflows/{workflow_id}/steps/{step_key}/execute`.

        This is the per-step-consent path: the working-group runtime defers any
        payment step with a named human assignee to that party's inbox, and
        ONLY this endpoint signs it — under the caller's JWT, gated by
        `ensure_step_assignment_or_admin` (the caller must BE the step's
        assignee or a group admin). No request body. Returns the JSON body on
        success (202/200), or a uniform error dict on HTTP failure.
        The refresh token must be the secret paired with ``token``; agents
        captures it for any asynchronous work spawned by this request.
        """
        endpoint = (
            f"/working-groups/{group_id}/workflows/{workflow_id}"
            f"/steps/{step_key}/execute"
        )
        try:
            response = self._post(
                endpoint,
                {},
                token=token,
                refresh_token=refresh_token,
            )
            return response.json()
        except Exception as e:
            resp = getattr(e, "response", None)
            body = None
            if resp is not None:
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text
            return {
                "status": "error",
                "message": str(body if body else e),
                "status_code": getattr(resp, "status_code", None),
            }

    def get_workflow(
        self,
        token: str,
        *,
        group_id: str,
        workflow_id: str,
    ) -> Optional[dict]:
        """Return a working-group workflow and its authoritative step rows."""
        endpoint = f"/working-groups/{group_id}/workflows/{workflow_id}"
        try:
            response = self._get(endpoint, token=token)
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception as e:
            # A transient read failure is an incomplete polling observation,
            # not evidence that the asynchronous step failed. Persistent
            # failures remain visible in poll_until's timeout diagnostic.
            self.logger.debug(f"get_workflow({workflow_id}) failed: {e}")
            return None

    def poll_workflow_step(
        self,
        token: TokenLike,
        *,
        group_id: str,
        workflow_id: str,
        step_key: str,
        interval: float = 2.0,
        timeout: float = 300.0,
    ) -> PollResult[dict]:
        """
        Poll the authoritative workflow row until ``step_key`` is terminal.

        The returned observation has ``workflow`` and ``step`` objects. A
        terminal workflow also stops the wait so a failed workflow cannot
        masquerade as a missing-step timeout.
        """

        def _token_value() -> str:
            value = token() if callable(token) else token
            return value or ""

        def _probe() -> dict:
            payload = self.get_workflow(
                _token_value(),
                group_id=group_id,
                workflow_id=workflow_id,
            ) or {}
            workflow = payload.get("workflow")
            if not isinstance(workflow, dict):
                workflow = {}
            steps = payload.get("steps")
            if not isinstance(steps, list):
                steps = []
            step = next(
                (
                    item
                    for item in steps
                    if isinstance(item, dict)
                    and str(item.get("step_key")) == str(step_key)
                ),
                {},
            )
            return {"workflow": workflow, "step": step}

        def _done(observation: dict) -> bool:
            step = observation.get("step") or {}
            workflow = observation.get("workflow") or {}
            step_status = str(step.get("status") or "").lower()
            workflow_status = str(workflow.get("status") or "").lower()
            return (
                step_status in self._STEP_TERMINAL_STATES
                or workflow_status in self._WORKFLOW_TERMINAL_STATES
            )

        def _tick(attempt: int, observation: dict):
            if attempt == 1 or attempt % 10 == 0:
                step = observation.get("step") or {}
                workflow = observation.get("workflow") or {}
                self.logger.debug(
                    f"  ⏳ workflow step {step_key} attempt={attempt} "
                    f"step_status={step.get('status')} "
                    f"workflow_status={workflow.get('status')}"
                )

        return poll_until(
            _probe,
            _done,
            interval=interval,
            timeout=timeout,
            description=(
                f"workflow {workflow_id} step '{step_key}' "
                "to reach a terminal state"
            ),
            on_tick=_tick,
        )
