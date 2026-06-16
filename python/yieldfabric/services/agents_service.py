"""
Agents service client.

The agents service (:3001) hosts the federated deal-flow GraphQL — the
`dealFlow { … }` namespace (proposeDeal / signDeal / setDealAutomationKey /
revokeDealAutomationKey / dealAutomationStatus / dealPeriods). This is a
SEPARATE GraphQL endpoint from payments (:3002/graphql); deal-lifecycle
commands must target the agents URL, so the deal executor talks to this
client rather than `PaymentsService.graphql_mutation`.

A router-wide request-auth middleware on agents signature-validates every
presented bearer before any resolver runs, so every call here carries the
caller's user JWT in the Authorization header (handled by `_post`).
"""

from typing import Any, Dict

from .base import BaseServiceClient
from ..config import YieldFabricConfig
from ..models.response import GraphQLResponse


class AgentsService(BaseServiceClient):
    """Client for the Agents Service deal-flow GraphQL."""

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
        """
        endpoint = (
            f"/working-groups/{group_id}/workflows/{workflow_id}"
            f"/steps/{step_key}/execute"
        )
        try:
            response = self._post(endpoint, {}, token=token)
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
