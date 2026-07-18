"""
Deal-lifecycle executor — the DMS deal-flow GraphQL on the AGENTS service
(:3001/graphql, `dealFlow { … }` namespace), NOT payments (:3002).

Exercises the periodic-deal engine + the user-managed auto-pay credential
system end to end:

    propose_deal           → dealFlow.proposeDeal      (raw DealPlan in)
    sign_deal              → dealFlow.signDeal         (all signatures ⇒ Accepted)
    activate_deal          → dealFlow.activateDeal     (proposer only; Accepted ⇒ Active)
    set_automation_key     → POST /auth/api-key/generate (caller mints a yf_api_… key)
                             then dealFlow.setDealAutomationKey (seal it to the deal)
    deal_automation_status → dealFlow.dealAutomationStatus  (non-secret status; read)
    revoke_automation_key  → dealFlow.revokeDealAutomationKey (kill-switch)
    deal_periods           → dealFlow.dealPeriods      (per-period status; read)

Unlike the payment executors, deal mutations do NOT return an MQ
`message_id` to poll — `proposeDeal`/`signDeal`/`activateDeal` return a
`Deal`, and the scheduler fires periods out-of-band on the wall clock. So
these methods store outputs and return directly; the suite sequences with
`sleep`.

Auth: every call carries the caller's JWT (acquired via the base executor).
Commands act as the user by default; proposer/activation/step commands honor
an explicitly supplied `user.group` delegation. The agents request-auth
middleware signature-validates the token before any resolver runs, and the
deal resolvers gate on deal-party membership (`require_caller_is_principal`).
"""

import json
import time
from typing import Any, Dict, List, Optional

from .base import BaseExecutor
from ..models import Command, CommandResponse
from ..services.agents_service import AgentsService
from ..utils.validators import is_provided


def _camel(snake: str) -> str:
    """`entity_id` → `entityId`. Idempotent for already-camelCase keys."""
    parts = str(snake).split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


# ── GraphQL operations (dealFlow namespace) ──────────────────────────────

_PROPOSE_DEAL = """
mutation ProposeDeal($input: ProposeDealInput!) {
  dealFlow {
    proposeDeal(input: $input) {
      success
      message
      deal { id status name }
    }
  }
}
"""

_SIGN_DEAL = """
mutation SignDeal($input: SignDealInput!) {
  dealFlow {
    signDeal(input: $input) {
      success
      message
      deal { id status }
    }
  }
}
"""

_ACTIVATE_DEAL = """
mutation ActivateDeal($input: ActivateDealInput!) {
  dealFlow {
    activateDeal(input: $input) {
      success
      message
      deal { id status workflowId }
    }
  }
}
"""

_SET_AUTOMATION_KEY = """
mutation SetDealAutomationKey($input: SetDealAutomationKeyInput!) {
  dealFlow {
    setDealAutomationKey(input: $input) {
      active
      entityId
      role
      keyLabel
      createdAt
    }
  }
}
"""

_SET_LOAN_COLLECT = """
mutation SetLoanCollect($input: SetLoanCollectAutomationInput!) {
  dealFlow {
    setLoanCollectAutomation(input: $input)
  }
}
"""

_REVOKE_LOAN_COLLECT = """
mutation RevokeLoanCollect($input: RevokeLoanCollectAutomationInput!) {
  dealFlow {
    revokeLoanCollectAutomation(input: $input)
  }
}
"""

_REVOKE_AUTOMATION_KEY = """
mutation RevokeDealAutomationKey($input: RevokeDealAutomationKeyInput!) {
  dealFlow {
    revokeDealAutomationKey(input: $input) {
      active
      entityId
      role
      keyLabel
      createdAt
    }
  }
}
"""

_DEAL_AUTOMATION_STATUS = """
query DealAutomationStatus($dealId: String!) {
  dealFlow {
    dealAutomationStatus(dealId: $dealId) {
      active
      entityId
      role
      keyLabel
      createdAt
    }
  }
}
"""

_DEAL_PERIODS = """
query DealPeriods($dealId: String!) {
  dealFlow {
    dealPeriods(dealId: $dealId) {
      periodIndex
      status
      dueAt
      workflowId
      startedAt
      completedAt
      hasRealised
      retryCount
      retrying
    }
  }
}
"""

_PENDING_ACTIONS_FOR_DEAL = """
query PendingActionsForDeal($dealId: String!) {
  dealFlow {
    pendingActionsForDeal(dealId: $dealId) {
      id
      stepId
      workflowId
      status
      descriptorInputs
    }
  }
}
"""


class DealExecutor(BaseExecutor):
    """Executor for the DMS deal-lifecycle + auto-pay GraphQL."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Deal flow lives on the agents subgraph, not payments — give this
        # executor its own client pointed at config.agents_service_url.
        self.agents_service = AgentsService(self.config)

    def execute(self, command: Command) -> CommandResponse:
        command_type = command.type.lower()
        dispatch = {
            "propose_deal": self._execute_propose_deal,
            "sign_deal": self._execute_sign_deal,
            "activate_deal": self._execute_activate_deal,
            "set_automation_key": self._execute_set_automation_key,
            "set_loan_collect_key": self._execute_set_loan_collect_key,
            "revoke_loan_collect_key": self._execute_revoke_loan_collect_key,
            "revoke_automation_key": self._execute_revoke_automation_key,
            "deal_automation_status": self._execute_deal_automation_status,
            "deal_periods": self._execute_deal_periods,
            "execute_step": self._execute_execute_step,
        }
        handler = dispatch.get(command_type)
        if handler is None:
            return CommandResponse.error_response(
                command.name, command.type,
                [f"Unknown deal command type: {command_type}"],
            )
        return handler(command)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _graphql(self, query: str, variables: dict, token: str):
        return self.agents_service.graphql(query, variables, token)

    def _fail(self, command: Command, message: str) -> CommandResponse:
        self.log_command_failure(command)
        return CommandResponse.error_response(command.name, command.type, [message])

    # ------------------------------------------------------------------
    # propose_deal — landlord/lender proposes a periodic deal (raw plan).
    # ------------------------------------------------------------------

    def _execute_propose_deal(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        # A deal may be authored by a group. Honor an explicitly supplied
        # `user.group`; with no group this remains the caller's self session.
        token, err = self._acquire_token_or_error(command, use_delegation=True)
        if err:
            return err

        p = command.parameters
        plan = p.get("plan")
        # Allow loading the plan from a FILE (e.g. a frozen template's plan.json)
        # so a deal-flow test drives the ACTUAL template, not a drifting inline copy.
        # Path is resolved relative to the harness CWD (yieldfabric-docs/python).
        if plan is None and is_provided(p.get("plan_file")):
            pf = str(p.get("plan_file"))
            try:
                with open(pf, encoding="utf-8") as fh:
                    plan = json.load(fh)
            except Exception as e:  # noqa: BLE001
                return self._fail(command, f"propose_deal: failed to read plan_file '{pf}': {e}")
        if not isinstance(plan, (dict, list)):
            return self._fail(
                command,
                "propose_deal requires `plan` (a DealPlan mapping) or `plan_file` (a "
                "path to a plan.json). It is submitted verbatim as the GraphQL `plan` JSON scalar.",
            )
        raw_parties = p.get("parties") or []
        if not isinstance(raw_parties, list) or not raw_parties:
            return self._fail(
                command,
                "propose_deal requires at least one `parties` entry "
                "({entity_id, role}); the proposer auto-signs and is not listed.",
            )
        parties: List[Dict[str, Any]] = []
        for party in raw_parties:
            if not isinstance(party, dict) or not party.get("entity_id"):
                return self._fail(command, f"propose_deal: malformed party entry {party!r}")
            parties.append({"entityId": party["entity_id"], "role": party.get("role")})

        gql_input: Dict[str, Any] = {"parties": parties, "plan": plan}
        if is_provided(p.get("name")):
            gql_input["name"] = str(p.get("name"))
        if is_provided(p.get("cashflow_ref")):
            gql_input["cashflowRef"] = str(p.get("cashflow_ref"))
        if is_provided(p.get("idempotency_key")):
            gql_input["idempotencyKey"] = str(p.get("idempotency_key"))

        self.log_parameters({
            "name": p.get("name"),
            "parties": parties,
            "idempotency_key": p.get("idempotency_key"),
        })

        response = self._graphql(_PROPOSE_DEAL, {"input": gql_input}, token)
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="ProposeDeal")
        data = response.get_data("dealFlow.proposeDeal", {}) or {}
        if not data.get("success"):
            return self._finalize_business_error(
                command, data.get("message", "proposeDeal not successful"),
                operation_name="ProposeDeal",
            )

        deal = data.get("deal") or {}
        outputs = {
            "deal_id": deal.get("id"),
            "status": deal.get("status"),
            "name": deal.get("name"),
            "message": data.get("message"),
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ propose_deal: {outputs['deal_id']} ({outputs['status']})"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # sign_deal — a counter-signing party signs. Once every party has
    # signed, the deal becomes Accepted. A counterparty's JWT is never
    # reused to activate the proposer's workflow; the proposer follows
    # with activate_deal.
    # ------------------------------------------------------------------

    def _execute_sign_deal(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return err

        deal_id = command.parameters.get("deal_id")
        if not deal_id:
            return self._fail(command, "sign_deal requires `deal_id`")

        self.log_parameters({"deal_id": deal_id})

        response = self._graphql(_SIGN_DEAL, {"input": {"dealId": str(deal_id)}}, token)
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="SignDeal")
        data = response.get_data("dealFlow.signDeal", {}) or {}
        if not data.get("success"):
            return self._finalize_business_error(
                command, data.get("message", "signDeal not successful"),
                operation_name="SignDeal",
            )

        deal = data.get("deal") or {}
        # GraphQL serialises DealStatus in SCREAMING form (DRAFT / PROPOSED /
        # ACCEPTED / ACTIVE …).
        outputs = {
            "deal_id": deal.get("id") or str(deal_id),
            "status": deal.get("status"),
            "message": data.get("message"),
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ sign_deal {outputs['deal_id']}: status={outputs['status']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # activate_deal — the proposer explicitly starts an Accepted deal's
    # pipeline. If a group proposed the deal, the matching group delegation
    # must be supplied here so DMS sees the same effective proposer entity.
    # ------------------------------------------------------------------

    def _execute_activate_deal(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=True)
        if err:
            return err

        deal_id = command.parameters.get("deal_id")
        if not deal_id:
            return self._fail(command, "activate_deal requires `deal_id`")

        self.log_parameters({"deal_id": deal_id})

        response = self._graphql(
            _ACTIVATE_DEAL,
            {"input": {"dealId": str(deal_id)}},
            token,
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="ActivateDeal"
            )
        data = response.get_data("dealFlow.activateDeal", {}) or {}
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", "activateDeal not successful"),
                operation_name="ActivateDeal",
            )

        deal = data.get("deal") or {}
        outputs = {
            "deal_id": deal.get("id") or str(deal_id),
            "status": deal.get("status"),
            "workflow_id": deal.get("workflowId"),
            "message": data.get("message"),
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ activate_deal {outputs['deal_id']}: status={outputs['status']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # set_automation_key — the PAYER mints a yf_api_… key in their own
    # session and seals it to the deal's auto-pay credential.
    # ------------------------------------------------------------------

    def _execute_set_automation_key(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        # Arm AS the payer themselves (no group delegation): the credential
        # is sealed to the caller's own entity and the resolver requires the
        # caller to be a deal principal.
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return err

        p = command.parameters
        deal_id = p.get("deal_id")
        if not deal_id:
            return self._fail(command, "set_automation_key requires `deal_id`")

        key_label = p.get("key_label")
        # 1. Mint a fresh API key for the caller (owned by their entity).
        api_key = p.get("api_key")  # allow an externally-supplied key for advanced use
        if not api_key:
            service_name = p.get("service_name") or f"deal-autopay-{deal_id}"
            api_key = self.auth_service.generate_api_key(
                token,
                service_name=str(service_name),
                description=f"Auto-pay credential for deal {deal_id}",
            )
            if not api_key:
                return self._fail(
                    command,
                    "set_automation_key: POST /auth/api-key/generate returned no key",
                )

        # 2. Seal it to the deal's auto-pay credential.
        gql_input: Dict[str, Any] = {"dealId": str(deal_id), "apiKey": str(api_key)}
        if is_provided(key_label):
            gql_input["keyLabel"] = str(key_label)
        if is_provided(p.get("key_id")):
            gql_input["keyId"] = str(p.get("key_id"))

        self.log_parameters({"deal_id": deal_id, "key_label": key_label})

        response = self._graphql(_SET_AUTOMATION_KEY, {"input": gql_input}, token)
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="SetDealAutomationKey"
            )
        status = response.get_data("dealFlow.setDealAutomationKey")
        if not isinstance(status, dict):
            return self._finalize_business_error(
                command, "setDealAutomationKey returned no status",
                operation_name="SetDealAutomationKey",
            )

        outputs = self._automation_outputs(status)
        # Never store/echo the secret key — only the non-secret status.
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ set_automation_key {deal_id}: active={outputs['active']} "
            f"entity={outputs['entity_id']} role={outputs['role']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # set_loan_collect_key — the CURRENT note-holder mints a yf_api_… key and arms
    # auto-collect for a transferable loan: the scheduler drives
    # executeUnderPolicy(Send→self) from the servicing account each tick. Sealed to
    # the caller's entity; the on-chain ownerOf gate ensures only the current holder
    # collects (a sold loan re-routes to the buyer who arms their own).
    def _execute_set_loan_collect_key(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return err

        p = command.parameters
        required = [
            "wallet_id", "servicing_group_id", "servicing_account",
            "policy_id", "token_address", "amount",
        ]
        missing = [k for k in required if not p.get(k)]
        if missing:
            return self._fail(command, f"set_loan_collect_key requires {missing}")

        # 1. Mint a fresh API key for the holder (owned by their entity).
        api_key = p.get("api_key")
        if not api_key:
            api_key = self.auth_service.generate_api_key(
                token,
                service_name=str(p.get("service_name") or f"loan-collect-{p.get('policy_id')}"),
                description=f"Auto-collect credential for policy {p.get('policy_id')}",
            )
            if not api_key:
                return self._fail(
                    command,
                    "set_loan_collect_key: POST /auth/api-key/generate returned no key",
                )

        # 2. Seal it + the loan's collect params.
        gql_input: Dict[str, Any] = {
            "walletId": str(p.get("wallet_id")),
            "servicingGroupId": str(p.get("servicing_group_id")),
            "servicingAccount": str(p.get("servicing_account")),
            "policyId": str(p.get("policy_id")),
            "tokenAddress": str(p.get("token_address")),
            "amount": str(p.get("amount")),
            "apiKey": str(api_key),
        }
        # Cadence: when set, the holder collects `amount` once per `period_secs`
        # (paced to the borrower's repayments) instead of every tick. Omit ⇒ un-paced.
        if is_provided(p.get("period_secs")):
            gql_input["periodSecs"] = int(p.get("period_secs"))
        if is_provided(p.get("key_label")):
            gql_input["keyLabel"] = str(p.get("key_label"))

        self.log_parameters({"policy_id": p.get("policy_id"), "amount": p.get("amount")})

        response = self._graphql(_SET_LOAN_COLLECT, {"input": gql_input}, token)
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="SetLoanCollectAutomation"
            )
        armed = response.get_data("dealFlow.setLoanCollectAutomation")
        outputs = {"armed": bool(armed)}
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ set_loan_collect_key {p.get('policy_id')}: armed={outputs['armed']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # revoke_loan_collect_key — the seller stops auto-collect after selling
    # the note (drops the stale credential so the scheduler stops retrying it).
    # ------------------------------------------------------------------
    def _execute_revoke_loan_collect_key(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return err

        p = command.parameters
        missing = [k for k in ("wallet_id", "policy_id") if not p.get(k)]
        if missing:
            return self._fail(command, f"revoke_loan_collect_key requires {missing}")

        gql_input = {"walletId": str(p.get("wallet_id")), "policyId": str(p.get("policy_id"))}
        self.log_parameters({"policy_id": p.get("policy_id")})

        response = self._graphql(_REVOKE_LOAN_COLLECT, {"input": gql_input}, token)
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="RevokeLoanCollectAutomation"
            )
        revoked = response.get_data("dealFlow.revokeLoanCollectAutomation")
        outputs = {"revoked": bool(revoked)}
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ revoke_loan_collect_key {p.get('policy_id')}: revoked={outputs['revoked']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # revoke_automation_key — the kill-switch.
    # ------------------------------------------------------------------

    def _execute_revoke_automation_key(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return err

        deal_id = command.parameters.get("deal_id")
        if not deal_id:
            return self._fail(command, "revoke_automation_key requires `deal_id`")

        self.log_parameters({"deal_id": deal_id})

        response = self._graphql(
            _REVOKE_AUTOMATION_KEY, {"input": {"dealId": str(deal_id)}}, token
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="RevokeDealAutomationKey"
            )
        status = response.get_data("dealFlow.revokeDealAutomationKey")
        # Post-revoke the resolver returns the now-inactive status row.
        outputs = self._automation_outputs(status if isinstance(status, dict) else None)
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ revoke_automation_key {deal_id}: active={outputs['active']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # deal_automation_status — non-secret status read (for asserts/UX).
    # ------------------------------------------------------------------

    def _execute_deal_automation_status(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return err

        deal_id = command.parameters.get("deal_id")
        if not deal_id:
            return self._fail(command, "deal_automation_status requires `deal_id`")

        response = self._graphql(
            _DEAL_AUTOMATION_STATUS, {"dealId": str(deal_id)}, token
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="DealAutomationStatus"
            )
        # `dealAutomationStatus` is a LIST — one row per arming party (a
        # two-sided rental holds the landlord's auto-collect row AND the
        # tenant's auto-settle row). Pick the row this step cares about:
        # filter by `role`/`entity_id` when given, else prefer the first
        # ACTIVE row. Empty / no match ⇒ inactive. (Back-compat: a single-
        # sided deal has one row, so an unfiltered read still picks it.)
        rows = response.get_data("dealFlow.dealAutomationStatus")
        status = self._select_automation_row(
            rows,
            role=command.parameters.get("role"),
            entity_id=command.parameters.get("entity_id"),
        )
        outputs = self._automation_outputs(status)
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ deal_automation_status {deal_id}: active={outputs['active']} "
            f"entity={outputs['entity_id']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # execute_step — drive a deferred on-chain step's /execute as its
    # assignee. Used for one-time setup steps a party must consent to
    # (e.g. the landlord deploying the property account in create_property).
    # The recurring per-period payments are driven by the scheduler, not
    # here — this is the human-in-the-loop counterpart for setup steps.
    # ------------------------------------------------------------------

    def _execute_execute_step(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        # Execute as the declared assignee. A self-assigned party omits group;
        # a group-as-proposer step supplies user.group and uses its delegation.
        token, err = self._acquire_token_or_error(command, use_delegation=True)
        if err:
            return err

        p = command.parameters
        deal_id = p.get("deal_id")
        step_id = p.get("step_id")
        if not deal_id or not step_id:
            return self._fail(command, "execute_step requires `deal_id` and `step_id`")

        interval = self._float_param(command, "wait_interval", 3.0)
        find_timeout = self._float_param(command, "find_timeout", 90.0)
        wait_timeout = self._float_param(command, "wait_timeout", 300.0)

        # 1. The deferred step materialises a pending action carrying its
        #    pipeline coordinates (group_id + workflow_id) under `_pipeline`.
        #    It appears asynchronously after activation, so poll for it.
        action = self._await_pending_action(
            token, str(deal_id), str(step_id), find_timeout, interval
        )
        if action is None:
            return self._fail(
                command,
                f"execute_step: no pending action for step '{step_id}' on deal "
                f"{deal_id} within {find_timeout:.0f}s — did the deal activate and "
                f"the step defer? (a step with no human assignee auto-fires and "
                f"won't appear here)",
            )

        pipeline = (action.get("descriptorInputs") or {}).get("_pipeline") or {}
        group_id = pipeline.get("group_id")
        workflow_id = action.get("workflowId") or pipeline.get("workflow_id")
        if not group_id or not workflow_id:
            return self._fail(
                command,
                f"execute_step: pending action for '{step_id}' is missing "
                f"_pipeline.group_id / workflow_id (got {pipeline})",
            )

        self.log_parameters({
            "deal_id": deal_id,
            "step_id": step_id,
            "group_id": group_id,
            "workflow_id": workflow_id,
        })

        # 2. Drive /execute. Only a successful response is authoritative. A
        #    precise 409 may mean another caller already claimed this step, but
        #    it is safe to continue only when the workflow row will be polled.
        should_wait = self._should_wait(command)
        refresh_token = (
            self.token_manager.refresh_token_for_access_token(token)
            if self.token_manager
            else None
        )
        res = self.agents_service.execute_step(
            token,
            group_id=str(group_id),
            workflow_id=str(workflow_id),
            step_key=str(step_id),
            refresh_token=refresh_token,
        )
        if isinstance(res, dict) and res.get("status") == "error":
            msg = str(res.get("message") or "")
            if res.get("status_code") != 409 or not should_wait:
                return self._finalize_business_error(
                    command, f"/execute failed: {msg}", operation_name="ExecuteStep"
                )
            self.logger.info(
                "      /execute returned 409; reconciling from the "
                "authoritative workflow step"
            )

        outputs = {
            "deal_id": deal_id,
            "step_id": step_id,
            "group_id": group_id,
            "workflow_id": workflow_id,
            "execute_response": res,
        }

        # 3. `/execute` only acknowledges that the asynchronous chain was
        #    accepted. The workflow row is the authoritative outcome: wait for
        #    THIS step to complete or fail so a background error cannot be
        #    misreported as success and surface later as a missing-next-step
        #    timeout. Explicit `wait: false` preserves fire-and-forget callers.
        if should_wait:
            self.logger.info(
                f"  ⏳ awaiting workflow step '{step_id}' "
                f"(interval={interval}s, timeout={wait_timeout}s)"
            )
            try:
                poll = self.agents_service.poll_workflow_step(
                    self._token_for_polling(
                        command, token, use_delegation=True
                    ),
                    group_id=str(group_id),
                    workflow_id=str(workflow_id),
                    step_key=str(step_id),
                    interval=interval,
                    timeout=wait_timeout,
                )
            except TimeoutError as e:
                outputs["wait_timed_out"] = True
                outputs["wait_error"] = str(e)
                return self._execute_step_failure(command, outputs, str(e))

            observation = (
                poll.observation if isinstance(poll.observation, dict) else {}
            )
            workflow = observation.get("workflow") or {}
            step = observation.get("step") or {}
            step_status = str(step.get("status") or "").lower()
            workflow_status = str(workflow.get("status") or "").lower()
            outputs.update(
                {
                    "step_status": step_status or None,
                    "step_result": step.get("result"),
                    "external_message_id": step.get("external_message_id"),
                    "workflow_status": workflow_status or None,
                    "wait_attempts": poll.attempts,
                    "wait_elapsed": poll.elapsed,
                    "wait_timed_out": False,
                }
            )

            if step_status != "completed":
                message = self._workflow_step_failure_message(
                    str(step_id), step_status, step, workflow
                )
                return self._execute_step_failure(command, outputs, message)

            self.logger.success(
                f"    ✅ workflow step {step_id} completed in "
                f"{poll.attempts} poll(s) / {poll.elapsed:.1f}s"
            )

        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ execute_step {step_id}: "
            f"{'completed' if should_wait else '/execute accepted'} "
            f"(group={group_id} workflow={workflow_id})"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    def _execute_step_failure(
        self,
        command: Command,
        outputs: dict,
        message: str,
    ) -> CommandResponse:
        """Return a failed execute_step while retaining its diagnostics."""
        self.store_outputs(command.name, outputs)
        self.logger.error(f"    ❌ ExecuteStep failed: {message}")
        self.log_command_failure(command)
        return CommandResponse(
            success=False,
            command_name=command.name,
            command_type=command.type,
            message="Command execution failed",
            data=outputs,
            errors=[message],
        )

    @staticmethod
    def _workflow_step_failure_message(
        step_id: str,
        step_status: str,
        step: dict,
        workflow: dict,
    ) -> str:
        """Build a concise error from the terminal workflow observation."""
        result = step.get("result")
        detail = None
        if isinstance(result, dict):
            detail = (
                result.get("error")
                or result.get("reason")
                or result.get("message")
            )
        elif result is not None:
            detail = str(result)
        detail = detail or workflow.get("result_summary")

        status = step_status or "unknown"
        workflow_status = str(workflow.get("status") or "").lower()
        if status not in {"failed", "rejected", "cancelled", "skipped"}:
            message = (
                f"workflow reached terminal status {workflow_status or 'unknown'} "
                f"while step '{step_id}' remained {status}"
            )
            if detail:
                message += f": {detail}"
            return message

        message = f"workflow step '{step_id}' reached terminal status {status}"
        if detail:
            message += f": {detail}"
        return message

    def _await_pending_action(
        self,
        token: str,
        deal_id: str,
        step_id: str,
        timeout: float,
        interval: float,
    ) -> Optional[dict]:
        """
        Poll `pendingActionsForDeal(dealId)` until a pending action for
        `step_id` (carrying `_pipeline` coordinates) appears, or `timeout`
        elapses. Returns the action dict (newest match), or None on timeout.
        """
        deadline = time.monotonic() + timeout
        attempt = 0
        while True:
            attempt += 1
            response = self._graphql(
                _PENDING_ACTIONS_FOR_DEAL, {"dealId": deal_id}, token
            )
            if response.success:
                actions = response.get_data("dealFlow.pendingActionsForDeal", []) or []
                if not isinstance(actions, list):
                    actions = []
                match = next(
                    (
                        a
                        for a in reversed(actions)
                        if isinstance(a, dict)
                        if str(a.get("stepId")) == step_id
                        and str(a.get("status") or "").upper()
                        in {"PENDING", "IN_PROGRESS"}
                        and isinstance(a.get("descriptorInputs"), dict)
                        and isinstance(
                            a["descriptorInputs"].get("_pipeline"), dict
                        )
                    ),
                    None,
                )
                if match is not None:
                    return match
            if time.monotonic() >= deadline:
                return None
            if attempt == 1 or attempt % 5 == 0:
                self.logger.info(
                    f"  ⏳ awaiting pending action for step '{step_id}' "
                    f"(attempt {attempt})"
                )
            time.sleep(interval)

    @staticmethod
    def _select_automation_row(
        rows: Any,
        role: Optional[str] = None,
        entity_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Pick one `DealAutomationStatus` row from the list the resolver
        returns. Filters by `role` (case-insensitive) / `entity_id` when
        given; otherwise prefers the first ACTIVE row, falling back to the
        first row. Returns ``None`` when there are no rows / no match (⇒
        inactive). Tolerates a server that still returns a single object or
        ``null`` (back-compat)."""
        if not isinstance(rows, list):
            return rows if isinstance(rows, dict) else None
        candidates = [r for r in rows if isinstance(r, dict)]
        if role is not None:
            want = str(role).lower()
            candidates = [r for r in candidates if str(r.get("role") or "").lower() == want]
        if entity_id is not None:
            candidates = [r for r in candidates if r.get("entityId") == entity_id]
        if not candidates:
            return None
        return next((r for r in candidates if r.get("active")), candidates[0])

    def _automation_outputs(self, status: Optional[dict]) -> Dict[str, Any]:
        """
        Normalise a (possibly-null) DealAutomationStatus into assert-friendly
        outputs. A null status means "no active auto-pay" ⇒ active=False.
        `active` is stored as a Python bool so `str(active)` matches the
        suite's `equals: "True"` / `equals: "False"` asserts.
        """
        if not isinstance(status, dict):
            return {
                "active": False,
                "entity_id": None,
                "role": None,
                "key_label": None,
                "created_at": None,
            }
        return {
            "active": bool(status.get("active")),
            "entity_id": status.get("entityId"),
            "role": status.get("role"),
            "key_label": status.get("keyLabel"),
            "created_at": status.get("createdAt"),
        }

    # ------------------------------------------------------------------
    # deal_periods — per-period status read (for lifecycle asserts).
    # Surfaces both a flat per-index projection (`period_<i>_status`,
    # `period_<i>_has_realised`, …) and list aggregates so a suite can
    # assert on any single period or on counts.
    # ------------------------------------------------------------------

    def _execute_deal_periods(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return err
        # The wait_for_status poll below can run PAST the access-token TTL (900s)
        # — e.g. waiting out the late-funding backoff window. Build a refresh-aware
        # supplier (cached until near-expiry, then refreshed via the refresh token,
        # same pattern as wait_executor) and re-resolve the token each iteration so
        # a long poll doesn't 401 with "missing or invalid Bearer token" mid-wait.
        token_supplier = self._token_supplier(command, use_delegation=False)

        deal_id = command.parameters.get("deal_id")
        if not deal_id:
            return self._fail(command, "deal_periods requires `deal_id`")
        p = command.parameters

        # Optional polling: when `wait_for_status` is set, re-query until the
        # target period (`wait_period_index`, default 0) reaches that status,
        # or `wait_timeout` elapses. This makes a lifecycle assert robust to
        # scheduler-timing jitter (e.g. the leader-election throttle) instead
        # of betting on a single fixed sleep landing after the period fires.
        wait_for = p.get("wait_for_status")
        wait_idx = int(p.get("wait_period_index") or 0)
        timeout = self._float_param(command, "wait_timeout", 300.0)
        interval = self._float_param(command, "wait_interval", 5.0)

        deadline = time.monotonic() + timeout
        attempt = 0
        periods: List[Any] = []
        while True:
            attempt += 1
            # Refresh the token as needed before each poll (long waits outlive the
            # 900s access-token TTL). Falls back to the prior token if the supplier
            # transiently returns None.
            token = token_supplier() or token
            response = self._graphql(_DEAL_PERIODS, {"dealId": str(deal_id)}, token)
            if not response.success:
                return self._finalize_graphql_error(
                    command, response, operation_name="DealPeriods"
                )
            periods = response.get_data("dealFlow.dealPeriods", []) or []
            if not is_provided(wait_for):
                break
            target = next(
                (r for r in periods if isinstance(r, dict) and r.get("periodIndex") == wait_idx),
                None,
            )
            cur = target.get("status") if isinstance(target, dict) else None
            cur_retrying = bool(target.get("retrying")) if isinstance(target, dict) else False
            if cur == str(wait_for):
                self.logger.success(
                    f"    ✅ period {wait_idx} reached {wait_for} after {attempt} poll(s)"
                )
                break
            # FAILED handling. FAILED is a TRANSIENT state on the auto-settle
            # path: the late-funding reaper flips a stuck PROCESSING period to
            # FAILED (retrying=true) on a funding revert, then the backoff sweep
            # re-SCHEDULEs and re-fires it → PROCESSING → COMPLETED. So when the
            # caller is explicitly waiting for COMPLETED, a FAILED snapshot that
            # is still RETRYING (retry budget not exhausted) is NOT terminal —
            # keep polling, it is on its way to COMPLETED. Only stop early when
            # FAILED can no longer advance to the target: either the caller is
            # waiting for something other than COMPLETED, or the FAILED is itself
            # terminal (retrying=false — a hard revert / exhausted backoff
            # budget). Without this guard the COMPLETED-poll bails out on the
            # very FAILED window the reaper deliberately produces, turning the
            # late-funding regression suite into a false negative.
            if cur == "FAILED":
                if str(wait_for) == "COMPLETED" and cur_retrying:
                    if attempt == 1 or attempt % 6 == 0:
                        self.logger.info(
                            f"  ⏳ period {wait_idx} transiently FAILED (retrying) — "
                            f"awaiting backoff re-fire → {wait_for} (attempt {attempt})"
                        )
                    if time.monotonic() >= deadline:
                        self.logger.warning(
                            f"    ⚠️  period {wait_idx} still FAILED (retrying) after "
                            f"{timeout:.0f}s (wanted {wait_for}) — surfacing current state"
                        )
                        break
                    time.sleep(interval)
                    continue
                # Terminal-but-not-the-target: stop polling and let the assert
                # surface the FAILED state rather than spinning to the timeout.
                self.logger.error(
                    f"    ❌ period {wait_idx} is FAILED (was waiting for {wait_for})"
                )
                break
            if time.monotonic() >= deadline:
                self.logger.warning(
                    f"    ⚠️  period {wait_idx} still {cur} after {timeout:.0f}s "
                    f"(wanted {wait_for}) — surfacing current state"
                )
                break
            if attempt == 1 or attempt % 6 == 0:
                self.logger.info(
                    f"  ⏳ waiting for period {wait_idx} → {wait_for} "
                    f"(now {cur}, attempt {attempt})"
                )
            time.sleep(interval)

        outputs: Dict[str, Any] = {
            "period_count": len(periods),
            "periods": periods,
        }
        completed = 0
        for row in periods:
            if not isinstance(row, dict):
                continue
            idx = row.get("periodIndex")
            status = row.get("status")
            if status == "COMPLETED":
                completed += 1
            if idx is None:
                continue
            outputs[f"period_{idx}_status"] = status
            outputs[f"period_{idx}_due_at"] = row.get("dueAt")
            outputs[f"period_{idx}_workflow_id"] = row.get("workflowId")
            outputs[f"period_{idx}_has_realised"] = bool(row.get("hasRealised"))
            outputs[f"period_{idx}_retry_count"] = row.get("retryCount")
            outputs[f"period_{idx}_retrying"] = bool(row.get("retrying"))
        outputs["completed_count"] = completed

        self.store_outputs(command.name, outputs)
        statuses = ", ".join(
            f"{r.get('periodIndex')}:{r.get('status')}"
            for r in periods
            if isinstance(r, dict)
        )
        self.logger.success(
            f"    ✅ deal_periods {deal_id}: {len(periods)} period(s) "
            f"({completed} completed) [{statuses}]"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)
