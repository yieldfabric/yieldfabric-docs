"""
Payments service client
"""

from typing import Any, Callable, Dict, List, Optional, Union

from .base import BaseServiceClient
from ..config import YieldFabricConfig
from ..models.response import GraphQLResponse, RESTResponse
from ..utils.graphql import GraphQLMutation
from ..utils.polling import PollResult, poll_until
from ..utils.validators import is_provided

TokenLike = Union[str, Callable[[], Optional[str]]]


class PaymentsService(BaseServiceClient):
    """Client for Payments Service."""
    
    def __init__(self, config: YieldFabricConfig):
        """
        Initialize Payments Service client.
        
        Args:
            config: YieldFabric configuration
        """
        super().__init__(config.pay_service_url, config)
        self.refresh_token_resolver: Optional[Callable[[str], Optional[str]]] = None

    def _token_value(self, token: TokenLike) -> Optional[str]:
        """Resolve a static token or a refresh-aware token supplier."""
        return token() if callable(token) else token
    
    def graphql_mutation(
        self,
        mutation: str,
        variables: Dict[str, Any],
        token: str,
    ) -> GraphQLResponse:
        """
        Execute GraphQL mutation.
        
        Args:
            mutation: GraphQL mutation string
            variables: Mutation variables
            token: JWT token
            
        Returns:
            GraphQLResponse object
        """
        payload = GraphQLMutation.build_payload(mutation, variables)
        
        self.logger.debug("  📋 GraphQL mutation (variables omitted for brevity)")
        self.logger.debug(f"  📋 GraphQL variables: {variables}")
        
        try:
            refresh_token = (
                self.refresh_token_resolver(token)
                if self.refresh_token_resolver and token
                else None
            )
            response = self._post(
                "/graphql",
                payload,
                token=token,
                refresh_token=refresh_token,
            )
            data = response.json()
            
            self.logger.debug(f"  📡 Raw GraphQL response: {data}")
            
            return GraphQLResponse.from_response(data)
        
        except Exception as e:
            self.logger.error(f"    ❌ GraphQL mutation failed: {e}")
            return GraphQLResponse(
                success=False,
                errors=[{"message": str(e)}]
            )
    
    def get_balance(self, denomination: str, obligor: Optional[str], group_id: Optional[str], 
                    token: str) -> RESTResponse:
        """
        Get account balance.
        
        Args:
            denomination: Asset denomination
            obligor: Optional obligor address
            group_id: Optional group ID
            token: JWT token
            
        Returns:
            RESTResponse object
        """
        params = {"denomination": denomination}

        if is_provided(obligor):
            params["obligor"] = obligor
        if is_provided(group_id):
            params["group_id"] = group_id
        
        self.logger.debug("  📋 Query parameters:")
        for k, v in params.items():
            self.logger.debug(f"    {k}: {v}")
        
        try:
            response = self._get("/balance", params=params, token=token)
            data = response.json()
            
            self.logger.debug(f"  📡 Raw REST API response: {data}")
            
            return RESTResponse.from_response(response.status_code, data)
        
        except Exception as e:
            self.logger.error(f"    ❌ Balance query failed: {e}")
            return RESTResponse(
                success=False,
                status_code=0,
                errors=[str(e)]
            )
    
    def get_obligations(self, token: str) -> RESTResponse:
        """
        Get obligations list.
        
        Args:
            token: JWT token
            
        Returns:
            RESTResponse object
        """
        self.logger.debug("  📋 Fetching obligations")
        
        try:
            response = self._get("/obligations", token=token)
            data = response.json()
            
            self.logger.debug(f"  📡 Raw REST API response: {data}")
            
            return RESTResponse.from_response(response.status_code, data)
        
        except Exception as e:
            self.logger.error(f"    ❌ Obligations query failed: {e}")
            return RESTResponse(
                success=False,
                status_code=0,
                errors=[str(e)]
            )
    
    # ------------------------------------------------------------------
    # Setup-phase mutations (tokens, assets, fiat accounts).
    # All return a uniform dict:
    #   {"status": "created", "id": "...", "message": "..."}
    #   {"status": "exists"}                       (error mentions "already exists")
    #   {"status": "error", "message": "..."}
    # ------------------------------------------------------------------

    def _setup_mutation_call(
        self,
        mutation: str,
        variables: Dict[str, Any],
        token: str,
        flow: str,
        op: str,
        id_field: str = "id",
    ) -> dict:
        """
        Shared helper: submit a nested-flow GraphQL mutation (`flow.op`),
        unify the response into the setup-phase return shape above.
        """
        payload = {"query": mutation, "variables": variables}
        try:
            response = self._post("/graphql", payload, token=token)
            data = response.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}

        flow_data = (data.get("data") or {}).get(flow) or {}
        op_data = flow_data.get(op) or {}
        if op_data.get("success"):
            # Extract id from either {flow.op.<thing>.id} or similar nested shapes.
            thing = None
            for key in ("token", "asset", "bankAccount"):
                if key in op_data and isinstance(op_data[key], dict):
                    thing = op_data[key]
                    break
            created_id = (thing or {}).get(id_field)
            return {
                "status": "created",
                "id": created_id,
                "message": op_data.get("message"),
            }

        # Surface "already exists" as an idempotent "exists" status.
        errors = data.get("errors") or []
        if errors:
            msg = errors[0].get("message") or ""
            if "already exists" in msg.lower():
                return {"status": "exists"}
            return {"status": "error", "message": msg}

        return {
            "status": "error",
            "message": op_data.get("message") or "operation not successful",
        }

    def create_token(
        self,
        token: str,
        *,
        token_id: str,
        name: str,
        description: str,
        chain_id: str,
        address: str,
    ) -> dict:
        """
        GraphQL `tokenFlow { createToken(input: {...}) }` — idempotent
        via the "already exists" error-message check.
        """
        mutation = """
        mutation CreateToken($input: CreateTokenInput!) {
            tokenFlow {
                createToken(input: $input) {
                    success
                    message
                    token { id chainId address }
                    transactionId
                    signature
                    timestamp
                }
            }
        }
        """
        variables = {
            "input": {
                "chainId": chain_id,
                "address": address,
                "tokenId": token_id,
                "name": name,
                "description": description,
            }
        }
        self.logger.info(f"  🪙 create_token id={token_id} chain={chain_id}")
        return self._setup_mutation_call(mutation, variables, token, "tokenFlow", "createToken")

    def create_asset(
        self,
        token: str,
        *,
        name: str,
        description: str,
        asset_type: str,
        currency: str,
        token_id: str,
    ) -> dict:
        """GraphQL `assetFlow { createAsset(input: {...}) }`.

        The backend's asset-type validation is case-sensitive and expects
        UPPERCASE (CASH, TOKEN, INVOICE, …). `setup_system.sh` uppercases
        before sending (line `asset_type=$(echo … | tr '[:lower:]' '[:upper:]')`);
        mirror that here so a YAML `type: Cash` doesn't fail with
        "Invalid asset type provided".
        """
        asset_type = (asset_type or "").upper()
        mutation = """
        mutation CreateAsset($input: CreateAssetInput!) {
            assetFlow {
                createAsset(input: $input) {
                    success
                    message
                    asset {
                        id name description assetType currency tokenId
                        obligorId createdAt deleted transactionId
                    }
                    transactionId
                    signature
                    timestamp
                }
            }
        }
        """
        variables = {
            "input": {
                "name": name,
                "description": description,
                "assetType": asset_type,
                "currency": currency,
                "tokenId": token_id,
            }
        }
        self.logger.info(f"  💎 create_asset name={name} token_id={token_id}")
        return self._setup_mutation_call(mutation, variables, token, "assetFlow", "createAsset")

    def create_us_bank_account(self, token: str, **kwargs) -> dict:
        """GraphQL `fiatAccountFlow { createUsBankAccount(input: {...}) }`."""
        return self._create_bank_account(token, "createUsBankAccount", kwargs)

    def create_uk_bank_account(self, token: str, **kwargs) -> dict:
        """GraphQL `fiatAccountFlow { createUkBankAccount(input: {...}) }`."""
        return self._create_bank_account(token, "createUkBankAccount", kwargs)

    def create_au_bank_account(self, token: str, **kwargs) -> dict:
        """GraphQL `fiatAccountFlow { createAuBankAccount(input: {...}) }`."""
        return self._create_bank_account(token, "createAuBankAccount", kwargs)

    def _create_bank_account(self, token: str, op: str, input_kwargs: dict) -> dict:
        """Shared helper for the three createXBankAccount mutations."""
        # Filter None/empty values and camelCase the keys.
        def _camel(s: str) -> str:
            parts = s.split("_")
            return parts[0] + "".join(p.capitalize() for p in parts[1:])

        input_fields = {
            _camel(k): v for k, v in input_kwargs.items() if v not in (None, "")
        }

        # status is an ENUM in the schema — must be unquoted in the mutation.
        # With variables (typed input), the server handles it. We default to
        # ACTIVE if caller didn't specify.
        input_fields.setdefault("status", "ACTIVE")

        mutation = (
            "mutation Create($input: "
            + op[6:]
            + "Input!) { fiatAccountFlow { "
            + op
            + "(input: $input) { success message bankAccount { id assetId country currency "
            "accountHolderName iban status } transactionId signature timestamp } } }"
        )
        variables = {"input": input_fields}
        self.logger.info(f"  🏦 {op} id={input_fields.get('accountId')}")
        return self._setup_mutation_call(mutation, variables, token, "fiatAccountFlow", op)

    # ------------------------------------------------------------------
    # Raw state-observation endpoints.
    #
    # These power the `poll_*` helpers below (and let callers do their
    # own custom polling if the built-ins don't fit). All return plain
    # dicts / Optionals — no side effects, no retries. The polling
    # wrappers add timing and predicates on top.
    # ------------------------------------------------------------------

    def get_user_message(self, user_id: str, message_id: str, token: str) -> Optional[dict]:
        """
        GET /api/users/{user_id}/messages/{message_id} — the full MQ
        message record. Returns None on 404; the caller decides whether
        "not yet written" is an error or an expected transient state.
        """
        try:
            response = self._get(
                f"/api/users/{user_id}/messages/{message_id}",
                token=token,
            )
            return response.json()
        except Exception as e:
            # 404 is a legitimate "not found yet" outcome; HTTP other
            # errors still surface as None here, but the caller sees
            # them via the polling helper's timeout message if they
            # persist.
            self.logger.debug(f"get_user_message({message_id}) failed: {e}")
            return None

    def get_unsigned_transaction(
        self, user_id: str, message_id: str, token: str
    ) -> Optional[dict]:
        """
        GET /api/users/{user_id}/messages/{message_id}/unsigned-transaction.
        Returns the unsigned-tx payload when the backend has produced it
        (status 200). Returns None when not yet ready (status 404 or
        error). Callers poll this until non-None.
        """
        try:
            response = self._get(
                f"/api/users/{user_id}/messages/{message_id}/unsigned-transaction",
                token=token,
            )
            return response.json()
        except Exception as e:
            self.logger.debug(f"get_unsigned_transaction({message_id}) failed: {e}")
            return None

    def submit_signed_message(
        self,
        user_id: str,
        message_id: str,
        signature_hex: str,
        unsigned_transaction_id: str,
        token: str,
    ) -> dict:
        """
        POST /api/users/{user_id}/messages/{message_id}/submit-signed-message.
        Hands a locally-produced signature back to the backend, bound to the
        exact unsigned-transaction generation returned by the GET endpoint.
        """
        try:
            response = self._post(
                f"/api/users/{user_id}/messages/{message_id}/submit-signed-message",
                data={
                    "signature": signature_hex,
                    "unsigned_transaction_id": unsigned_transaction_id,
                },
                token=token,
            )
            return response.json()
        except Exception as e:
            self.logger.error(f"submit_signed_message failed: {e}")
            return {"status": "error", "message": str(e)}

    def retry_message(
        self,
        user_id: str,
        message_id: str,
        execution_mode: str,
        token: str,
    ) -> dict:
        """Redrive one failed canonical payment Retrieve message in place."""
        try:
            response = self._post(
                f"/api/users/{user_id}/messages/{message_id}/retry",
                data={"execution_mode": execution_mode},
                token=token,
            )
            return response.json()
        except Exception as e:
            self.logger.error(f"retry_message failed: {e}")
            return {"success": False, "message": str(e)}

    def get_messages_awaiting_signature(self, user_id: str, token: str) -> List[dict]:
        """
        GET /api/users/{user_id}/messages/awaiting-signature. Returns the
        list (possibly empty) of messages that need a manual signature
        from the user. Called by the background signature listener.
        """
        try:
            response = self._get(
                f"/api/users/{user_id}/messages/awaiting-signature",
                token=token,
            )
            data = response.json()
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            self.logger.debug(f"get_messages_awaiting_signature failed: {e}")
            return []

    def get_workflow_status(self, workflow_id: str, token: str) -> Optional[dict]:
        """
        GET /api/workflows/{workflow_id}. Unified workflow status
        endpoint covering every workflow type (mint_deposit, onramp,
        loan_process, composed_contract_issue, etc.). Returns the
        status payload (includes `workflow_status`, `current_step`,
        `workflow_type`) or None if not reachable.
        """
        try:
            response = self._get(
                f"/api/workflows/{workflow_id}",
                token=token,
            )
            return response.json()
        except Exception as e:
            self.logger.debug(f"get_workflow_status({workflow_id}) failed: {e}")
            return None

    def query_swap_status(self, swap_id: str, token: str) -> Optional[str]:
        """
        GraphQL `swapFlow { coreSwaps { byId(id) { status } } }`. Returns
        the status string (COMPLETED, PENDING, CANCELLED, EXPIRED,
        FORFEITED, ACCEPTED...) or None if the query fails / swap
        doesn't exist yet.
        """
        mutation = """
        query SwapStatus($id: String!) {
            swapFlow {
                coreSwaps {
                    byId(id: $id) { status }
                }
            }
        }
        """
        payload = {"query": mutation, "variables": {"id": swap_id}}
        try:
            response = self._post("/graphql", payload, token=token)
            data = response.json()
            swap = (
                ((data.get("data") or {}).get("swapFlow") or {}).get("coreSwaps") or {}
            ).get("byId")
            if isinstance(swap, dict):
                return swap.get("status")
        except Exception as e:
            self.logger.debug(f"query_swap_status({swap_id}) failed: {e}")
        return None

    # ------------------------------------------------------------------
    # Polling helpers.
    #
    # All of these are thin wrappers around `poll_until(...)`. They
    # encode the "what constitutes done" predicate for a specific kind
    # of state transition (workflow terminal, swap terminal, message
    # executed, unsigned tx available, accept_all returns any count).
    # They DO NOT retry on network errors — they retry on "not yet".
    # Network errors surface via TimeoutError if persistent.
    # ------------------------------------------------------------------

    # Terminal states for `workflow_status` in the unified endpoint.
    _WORKFLOW_TERMINAL_STATES = {"completed", "failed", "cancelled"}

    # Terminal states for swap status.
    _SWAP_TERMINAL_STATES = {"COMPLETED", "CANCELLED", "EXPIRED", "FORFEITED"}

    def poll_workflow_status(
        self,
        workflow_id: str,
        token: TokenLike,
        *,
        interval: float = 1.0,
        timeout: float = 120.0,
    ) -> PollResult[dict]:
        """
        Poll `GET /api/workflows/{workflow_id}` until the workflow
        reaches a terminal state (`completed`, `failed`, or `cancelled`).
        Returns the final status dict. Raises TimeoutError if the
        workflow is still running after `timeout` seconds.

        Use this after any `*_workflow` POST (issue_workflow,
        mint_deposit, loan_process, etc.) to wait for server-side
        completion before proceeding.
        """

        def _probe() -> dict:
            result = self.get_workflow_status(workflow_id, self._token_value(token))
            return result or {}

        def _done(obs: dict) -> bool:
            status = (obs.get("workflow_status") or "").lower()
            return status in self._WORKFLOW_TERMINAL_STATES

        def _tick(attempt: int, obs: dict):
            if attempt == 1 or attempt % 10 == 0:
                self.logger.debug(
                    f"  ⏳ workflow {workflow_id[:8]}... attempt={attempt} "
                    f"status={obs.get('workflow_status')} step={obs.get('current_step')}"
                )

        return poll_until(
            _probe,
            _done,
            interval=interval,
            timeout=timeout,
            description=f"workflow {workflow_id} to reach a terminal state",
            on_tick=_tick,
        )

    def poll_swap_completion(
        self,
        swap_id: str,
        token: TokenLike,
        *,
        interval: float = 2.0,
        timeout: float = 120.0,
        terminal_only: bool = False,
    ) -> PollResult[str]:
        """
        Poll `swapFlow.coreSwaps.byId(id).status` until the swap reaches
        a terminal state. By default any terminal (COMPLETED, CANCELLED,
        EXPIRED, FORFEITED) satisfies the wait; set `terminal_only=False`
        has no effect — it's the same semantics. The flag is reserved
        for a future "must be COMPLETED specifically" variant if callers
        need it.

        Returns the terminal status string. Raises TimeoutError on
        timeout; callers should NOT treat CANCELLED/FORFEITED as errors
        here — those are legitimate terminal states and the caller
        decides whether the business outcome is acceptable.
        """

        def _probe() -> Optional[str]:
            return self.query_swap_status(swap_id, self._token_value(token))

        def _done(obs: Optional[str]) -> bool:
            return obs in self._SWAP_TERMINAL_STATES

        def _tick(attempt: int, obs: Optional[str]):
            if attempt == 1 or attempt % 5 == 0:
                self.logger.debug(
                    f"  ⏳ swap {swap_id[:8]}... attempt={attempt} status={obs}"
                )

        return poll_until(
            _probe,
            _done,
            interval=interval,
            timeout=timeout,
            description=f"swap {swap_id} to reach a terminal state",
            on_tick=_tick,
        )

    def poll_message_completion(
        self,
        user_id: str,
        message_id: str,
        token: TokenLike,
        *,
        interval: float = 2.0,
        timeout: float = 300.0,
    ) -> PollResult[dict]:
        """
        Poll `/api/users/{user_id}/messages/{message_id}` until the
        message's chain execution and graph post-processing are complete.
        Returns the final message record.

        `executed` alone only means the on-chain transaction returned.
        Dependent flows must wait until the backend reports graph
        post-processing done, otherwise a fast follow-up command can race
        newly-created swap/payment/contract rows.
        """

        def _probe() -> dict:
            return self.get_user_message(user_id, message_id, self._token_value(token)) or {}

        def _done(obs: dict) -> bool:
            if not obs.get("executed"):
                return False

            response = obs.get("response")
            if not isinstance(response, dict):
                return True

            status = str(response.get("status") or "").lower()
            if status == "post_processing":
                return False

            # The current message-status endpoint adds the post-processing
            # lifecycle at the top level of the QueueMessage payload. Accept
            # the older nested shape too so mixed-version local environments
            # remain observable while services are restarted independently.
            post_processed_at = (
                obs.get("post_processed_at")
                or response.get("post_processed_at")
            )
            has_post_lifecycle = any(
                key in source
                for source in (obs, response)
                for key in (
                    "post_processed_at",
                    "post_processing_attempts",
                    "post_processing_error_kind",
                )
            )

            # A failed/error/canceled chain result is not settled until its
            # failure handler has cleared/reconciled context and projected the
            # physical ledger fact. Returning at `executed` lets a same-message
            # redrive race that work and discard the failed attempt's graph
            # event. Fail closed when the lifecycle lookup is temporarily
            # absent: a later probe will observe the canonical marker.
            terminal_failure = (
                status in {"failed", "error", "canceled"}
                or response.get("success") is False
                or bool(response.get("error"))
            )
            if terminal_failure:
                return bool(post_processed_at)

            if not has_post_lifecycle:
                return True

            return bool(post_processed_at)

        return poll_until(
            _probe,
            _done,
            interval=interval,
            timeout=timeout,
            description=f"message {message_id} processing",
        )

    def poll_unsigned_transaction_ready(
        self,
        user_id: str,
        message_id: str,
        token: TokenLike,
        *,
        interval: float = 2.0,
        timeout: float = 120.0,
    ) -> PollResult[dict]:
        """
        Poll `/api/users/.../messages/{id}/unsigned-transaction` until
        the backend produces the unsigned transaction (status 200
        response, not 404). Returns the unsigned-tx payload ready to
        be locally signed.

        Used by manual-signature flows where the user's client must
        sign an on-chain message offline.
        """

        def _probe() -> Optional[dict]:
            return self.get_unsigned_transaction(
                user_id,
                message_id,
                self._token_value(token),
            )

        def _done(obs: Optional[dict]) -> bool:
            return obs is not None and bool(obs)

        return poll_until(
            _probe,
            _done,
            interval=interval,
            timeout=timeout,
            description=f"unsigned transaction for message {message_id}",
        )

    def poll_accept_all_until_ready(
        self,
        token: TokenLike,
        *,
        denomination: str,
        idempotency_key: str,
        obligor: Optional[str] = None,
        wallet_id: Optional[str] = None,
        interval: float = 2.0,
        timeout: float = 90.0,
    ) -> PollResult[dict]:
        """
        Repeatedly call `acceptAll` until at least one payment is
        actually accepted (`acceptedCount > 0`). Early-exit semantics:
        the first iteration that returns `acceptedCount > 0` wins; we
        do NOT keep polling for additional accepts after that.

        Returns the final acceptAll response, including every accepted
        payment's durable MQ message id. Raises TimeoutError if no payments
        ever materialize for acceptance in `timeout` seconds.

        This is how loan_management / payment workflows avoid the race
        where `accept_all` is called before MQ has persisted the
        payables from an upstream `instant` / `createSwap` operation.
        """

        mutation = """
        mutation AcceptAll($input: AcceptAllInput!) {
            acceptAll(input: $input) {
                success
                totalPayments
                acceptedCount
                failedCount
                message
                acceptedPayments {
                    paymentId
                    amount
                    messageId
                    transactionId
                }
                failedPayments {
                    paymentId
                    amount
                    error
                }
            }
        }
        """
        input_obj: dict = {"denomination": denomination, "idempotencyKey": idempotency_key}
        if is_provided(obligor):
            input_obj["obligor"] = obligor
        if wallet_id:
            input_obj["walletId"] = wallet_id
        variables = {"input": input_obj}

        def _probe() -> dict:
            payload = {"query": mutation, "variables": variables}
            try:
                response = self._post(
                    "/graphql",
                    payload,
                    token=self._token_value(token),
                )
                data = response.json()
            except Exception as e:
                self.logger.debug(f"accept_all probe failed: {e}")
                return {}
            return ((data.get("data") or {}).get("acceptAll") or {})

        def _done(obs: dict) -> bool:
            count = obs.get("acceptedCount")
            try:
                return bool(obs.get("success")) and int(count or 0) > 0
            except (TypeError, ValueError):
                return False

        return poll_until(
            _probe,
            _done,
            interval=interval,
            timeout=timeout,
            description=f"acceptAll of {denomination} to accept at least one payable",
        )

    def poll_signatures_cleared(
        self,
        user_id: str,
        token: TokenLike,
        *,
        interval: float = 2.0,
        timeout: float = 30.0,
    ) -> PollResult[int]:
        """
        Poll `/api/users/{user_id}/messages/awaiting-signature` until
        the list is empty — i.e. every message requiring a manual
        signature from this user has been signed. Returns the final
        count (always 0 on success).

        Use AFTER kicking off a background signing listener, to confirm
        no more signatures are pending before teardown.
        """

        def _probe() -> int:
            return len(
                self.get_messages_awaiting_signature(
                    user_id,
                    self._token_value(token),
                )
            )

        def _done(obs: int) -> bool:
            return obs == 0

        return poll_until(
            _probe,
            _done,
            interval=interval,
            timeout=timeout,
            description=f"all awaiting-signature messages for user {user_id} to be signed",
        )

    def get_total_supply(self, denomination: str, obligor: Optional[str], token: str) -> RESTResponse:
        """
        Get total supply for a denomination.
        
        Args:
            denomination: Asset denomination
            obligor: Optional obligor address
            token: JWT token
            
        Returns:
            RESTResponse object
        """
        params = {"denomination": denomination}

        if is_provided(obligor):
            params["obligor"] = obligor

        self.logger.debug("  📋 Query parameters:")
        for k, v in params.items():
            self.logger.debug(f"    {k}: {v}")
        
        try:
            response = self._get("/total-supply", params=params, token=token)
            data = response.json()
            
            self.logger.debug(f"  📡 Raw REST API response: {data}")
            
            return RESTResponse.from_response(response.status_code, data)
        
        except Exception as e:
            self.logger.error(f"    ❌ Total supply query failed: {e}")
            return RESTResponse(
                success=False,
                status_code=0,
                errors=[str(e)]
            )
