"""
Wait-executor — declarative `wait_for_*` command types for YAML flows.

Loan-management-style workflows sequence mutations with state-based
waits in between:

    - deposit               → wait_for_message
    - issue_workflow        → wait_for_workflow
    - completeSwap          → wait_for_swap
    - background listener   → wait_for_signatures_cleared
    - accept                → wait_for_accept_all  (accept + poll)

Rather than forcing callers to write Python, these are declarative
YAML commands backed by the polling helpers on PaymentsService.

Example YAML:

    - name: wait_issue
      type: wait_for_workflow
      user: { id: issuer@yieldfabric.com, password: issuer_password }
      parameters:
        workflow_id: $issue_workflow_1.workflow_id
        interval: 1.0       # optional, default 1.0
        timeout: 120        # optional, default 120

    - name: wait_swap
      type: wait_for_swap
      user: { id: ..., password: ... }
      parameters:
        swap_id: $create_swap_1.swap_id
        timeout: 120

    - name: wait_msg
      type: wait_for_message
      user: { id: ..., password: ... }
      parameters:
        message_id: $deposit_1.message_id
        user_id: $deposit_1.account_address       # (or JWT sub)

Every wait populates downstream-usable outputs on success:
    <name>.attempts, <name>.elapsed, <name>.observation (raw probe result)
"""

import time

from .base import BaseExecutor
from ..models import Command, CommandResponse
from ..utils.jwt import get_sub


class WaitExecutor(BaseExecutor):
    """Executor for the wait_for_* declarative poll commands."""

    def execute(self, command: Command) -> CommandResponse:
        command_type = command.type.lower()

        if command_type == "wait_for_workflow":
            return self._wait_for_workflow(command)
        if command_type == "wait_for_swap":
            return self._wait_for_swap(command)
        if command_type == "wait_for_message":
            return self._wait_for_message(command)
        if command_type == "wait_for_signatures_cleared":
            return self._wait_for_signatures_cleared(command)
        if command_type == "wait_for_accept_all":
            return self._wait_for_accept_all(command)
        if command_type == "sleep":
            return self._sleep(command)
        if command_type == "advance_chain_time":
            return self._advance_chain_time(command)
        if command_type == "mine_block":
            return self._mine_block(command)

        return CommandResponse.error_response(
            command.name, command.type,
            [f"Unknown wait command type: {command_type}"]
        )

    # ------------------------------------------------------------------

    def _get_interval(self, command: Command, default: float) -> float:
        raw = command.parameters.get("interval")
        try:
            return float(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    def _get_timeout(self, command: Command, default: float) -> float:
        raw = command.parameters.get("timeout")
        try:
            return float(raw) if raw is not None else default
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------
    # sleep — blocking wall-clock delay
    # ------------------------------------------------------------------

    def _sleep(self, command: Command) -> CommandResponse:
        """Blocking wall-clock sleep. Used to advance past a short collateral
        `expiry` so a subsequent `expire_collateral` mines a block beyond it
        (local nodes timestamp blocks with the current wall clock). Param
        `seconds` (default 1)."""
        self.log_command_start(command)
        raw = command.parameters.get("seconds")
        try:
            seconds = float(raw) if raw is not None else 1.0
        except (TypeError, ValueError):
            seconds = 1.0
        self.logger.info(f"  ⏳ sleeping {seconds:.0f}s ({command.name})")
        time.sleep(seconds)
        outputs = {"slept_seconds": seconds}
        self.store_outputs(command.name, outputs)
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    def _advance_chain_time(self, command: Command) -> CommandResponse:
        """Advance the TEST node's block timestamp by `seconds` (evm_increaseTime +
        evm_mine) so a subsequent expire_collateral sees the collateral expiry passed —
        deterministic, unlike a wall-clock sleep when the node clock is offset. TEST-NODE
        ONLY (anvil / hardhat); a real chain requires a real wait. Node RPC from
        `ETH_RPC_URL` (default the manifest's localhost:8545)."""
        import os
        import requests

        self.log_command_start(command)
        raw = command.parameters.get("seconds")
        try:
            seconds = int(float(raw)) if raw is not None else 1
        except (TypeError, ValueError):
            seconds = 1

        rpc = os.environ.get("ETH_RPC_URL", "http://localhost:8545")
        try:
            for method, params in (("evm_increaseTime", [seconds]), ("evm_mine", [])):
                resp = requests.post(
                    rpc, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15
                ).json()
                if "error" in resp:
                    self.log_command_failure(command)
                    return CommandResponse.error_response(
                        command.name, command.type, [f"{method} failed: {resp['error']}"]
                    )
        except Exception as e:  # noqa: BLE001
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, [f"advance_chain_time RPC to {rpc} failed: {e}"]
            )

        self.logger.success(f"  ⏩ advanced chain time by {seconds}s via {rpc} ({command.name})")
        outputs = {"advanced_seconds": seconds}
        self.store_outputs(command.name, outputs)
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    def _mine_block(self, command: Command) -> CommandResponse:
        """Mine block(s) on a LOCAL test node (Hardhat / anvil). Such nodes do not
        produce blocks on their own — `block.timestamp` only advances when a block is
        mined — so sprinkle this into a flow to force the chain clock forward
        (optionally by a time interval) before a timestamp-sensitive step.

        NO-OP when ETH_RPC_URL is not localhost, so the SAME YAML runs unchanged
        against a real deployment (where the network produces blocks itself).

        Params (all optional):
            blocks   — number of blocks to mine (default 1)
            interval — seconds between consecutive blocks (default 0); with blocks>1
                       this advances chain time by blocks*interval.
        Node RPC from ETH_RPC_URL (default the manifest's localhost:8545)."""
        import os
        import requests
        from urllib.parse import urlparse

        self.log_command_start(command)

        rpc = os.environ.get("ETH_RPC_URL", "http://localhost:8545")
        host = (urlparse(rpc).hostname or "").lower()
        is_local = host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")

        def _int_param(key: str, default: int) -> int:
            raw = command.parameters.get(key)
            try:
                return int(float(raw)) if raw is not None else default
            except (TypeError, ValueError):
                return default

        blocks = max(1, _int_param("blocks", 1))
        interval = max(0, _int_param("interval", 0))

        if not is_local:
            # Real chain: the network mines blocks; nothing for us to do.
            self.logger.info(
                f"  ⛏️  mine_block is a no-op vs non-localhost RPC {rpc} ({command.name})"
            )
            outputs = {"mined": False, "blocks": 0, "rpc": rpc}
            self.store_outputs(command.name, outputs)
            self.log_command_success(command)
            return CommandResponse.success_response(command.name, command.type, outputs)

        def _rpc(method, params):
            return requests.post(
                rpc, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=15
            ).json()

        try:
            # Hardhat: mine `blocks` blocks, each `interval` seconds apart, in one call.
            resp = _rpc("hardhat_mine", [hex(blocks), hex(interval)])
            if "error" in resp:
                # Fallback for anvil / nodes without hardhat_mine: bump time once (if an
                # interval was requested) then mine one block per requested block.
                if interval > 0:
                    bump = _rpc("evm_increaseTime", [blocks * interval])
                    if "error" in bump:
                        self.log_command_failure(command)
                        return CommandResponse.error_response(
                            command.name, command.type, [f"evm_increaseTime failed: {bump['error']}"]
                        )
                for _ in range(blocks):
                    mined = _rpc("evm_mine", [])
                    if "error" in mined:
                        self.log_command_failure(command)
                        return CommandResponse.error_response(
                            command.name, command.type, [f"evm_mine failed: {mined['error']}"]
                        )
        except Exception as e:  # noqa: BLE001
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, [f"mine_block RPC to {rpc} failed: {e}"]
            )

        self.logger.success(
            f"  ⛏️  mined {blocks} block(s) (interval {interval}s) via {rpc} ({command.name})"
        )
        outputs = {"mined": True, "blocks": blocks, "interval": interval, "rpc": rpc}
        self.store_outputs(command.name, outputs)
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # wait_for_workflow
    # ------------------------------------------------------------------

    def _wait_for_workflow(self, command: Command) -> CommandResponse:
        self.log_command_start(command)

        workflow_id = command.parameters.get("workflow_id")
        if not workflow_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type,
                ["wait_for_workflow requires `workflow_id`"]
            )

        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        interval = self._get_interval(command, 1.0)
        timeout = self._get_timeout(command, 120.0)

        try:
            result = self.payments_service.poll_workflow_status(
                workflow_id,
                self._token_for_polling(command, token),
                interval=interval,
                timeout=timeout,
            )
        except TimeoutError as e:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, [str(e)]
            )

        outputs = {
            "workflow_id": workflow_id,
            "workflow_status": (result.observation.get("workflow_status") or ""),
            "current_step": result.observation.get("current_step"),
            "workflow_type": result.observation.get("workflow_type"),
            "attempts": result.attempts,
            "elapsed": result.elapsed,
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"  ✅ workflow {workflow_id[:8]}... reached {outputs['workflow_status']} "
            f"in {result.attempts} attempt(s) / {result.elapsed:.1f}s"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # wait_for_swap
    # ------------------------------------------------------------------

    def _wait_for_swap(self, command: Command) -> CommandResponse:
        self.log_command_start(command)

        swap_id = command.parameters.swap_id or command.parameters.get("swap_id")
        if not swap_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, ["wait_for_swap requires `swap_id`"]
            )

        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        interval = self._get_interval(command, 2.0)
        timeout = self._get_timeout(command, 120.0)

        try:
            result = self.payments_service.poll_swap_completion(
                swap_id,
                self._token_for_polling(command, token),
                interval=interval,
                timeout=timeout,
            )
        except TimeoutError as e:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, [str(e)]
            )

        outputs = {
            "swap_id": swap_id,
            "status": result.observation,
            "attempts": result.attempts,
            "elapsed": result.elapsed,
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"  ✅ swap {swap_id[:8]}... reached {result.observation} "
            f"in {result.attempts} attempt(s) / {result.elapsed:.1f}s"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # wait_for_message
    # ------------------------------------------------------------------

    def _wait_for_message(self, command: Command) -> CommandResponse:
        """
        Wait for `message_id` to finish chain execution and graph
        post-processing. Requires `message_id` and either explicit
        `user_id` (the subject of the message; defaults to the logged-in
        user's JWT sub if absent).
        """
        self.log_command_start(command)

        message_id = command.parameters.get("message_id")
        if not message_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, ["wait_for_message requires `message_id`"]
            )

        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        # The message lookup endpoint is keyed by user_id (the subject
        # of the MQ message, usually the acting user's id). If the YAML
        # doesn't provide it, derive it from the JWT `sub` claim.
        user_id = command.parameters.get("user_id") or get_sub(token)
        if not user_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type,
                ["wait_for_message could not determine user_id (JWT sub missing)"],
            )

        interval = self._get_interval(command, 2.0)
        timeout = self._get_timeout(command, 300.0)

        try:
            result = self.payments_service.poll_message_completion(
                user_id,
                message_id,
                self._token_for_polling(command, token),
                interval=interval,
                timeout=timeout,
            )
        except TimeoutError as e:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, [str(e)]
            )

        outputs = {
            "message_id": message_id,
            "user_id": user_id,
            "executed": result.observation.get("executed"),
            "response": result.observation.get("response"),
            "attempts": result.attempts,
            "elapsed": result.elapsed,
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"  ✅ message {message_id[:8]}... processed "
            f"in {result.attempts} attempt(s) / {result.elapsed:.1f}s"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # wait_for_signatures_cleared
    # ------------------------------------------------------------------

    def _wait_for_signatures_cleared(self, command: Command) -> CommandResponse:
        self.log_command_start(command)

        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        user_id = command.parameters.get("user_id") or get_sub(token)
        if not user_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type,
                ["wait_for_signatures_cleared could not determine user_id"],
            )

        interval = self._get_interval(command, 2.0)
        timeout = self._get_timeout(command, 30.0)

        try:
            result = self.payments_service.poll_signatures_cleared(
                user_id,
                self._token_for_polling(command, token),
                interval=interval,
                timeout=timeout,
            )
        except TimeoutError as e:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, [str(e)]
            )

        outputs = {
            "user_id": user_id,
            "remaining": result.observation,
            "attempts": result.attempts,
            "elapsed": result.elapsed,
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"  ✅ signature queue drained in "
            f"{result.attempts} attempt(s) / {result.elapsed:.1f}s"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # wait_for_accept_all — also SUBMITS the accept_all mutation.
    # ------------------------------------------------------------------

    def _wait_for_accept_all(self, command: Command) -> CommandResponse:
        """
        `accept_all` + poll until something is actually accepted. This
        is what payment workflows use after a completeSwap to absorb
        the payables the swap generated — see loan_management's
        payment_workflow.py for the canonical usage.

        Required: denomination, idempotency_key.
        Optional: obligor, walletId — filter targets when multiple
        pending payables exist.
        """
        self.log_command_start(command)

        params = command.parameters
        denomination = params.denomination or params.asset_id or params.get("denomination")
        idempotency_key = params.idempotency_key or params.get("idempotency_key")
        if not denomination or not idempotency_key:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type,
                ["wait_for_accept_all requires `denomination` and `idempotency_key`"]
            )

        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        interval = self._get_interval(command, 2.0)
        timeout = self._get_timeout(command, 90.0)

        try:
            result = self.payments_service.poll_accept_all_until_ready(
                self._token_for_polling(command, token),
                denomination=denomination,
                idempotency_key=idempotency_key,
                obligor=params.obligor or params.get("obligor"),
                wallet_id=params.get("wallet_id"),
                interval=interval,
                timeout=timeout,
            )
        except TimeoutError as e:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, [str(e)]
            )

        observation = result.observation
        accepted_payments = observation.get("acceptedPayments") or []
        failed_payments = observation.get("failedPayments") or []
        message_ids = self._normalize_message_ids(
            payment.get("messageId")
            for payment in accepted_payments
            if isinstance(payment, dict)
        )
        accepted_count = int(observation.get("acceptedCount") or 0)
        if accepted_count != len(message_ids):
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name,
                command.type,
                [
                    "acceptAll returned "
                    f"{accepted_count} accepted payment(s) but "
                    f"{len(message_ids)} distinct durable message id(s)"
                ],
            )

        outputs = {
            "denomination": denomination,
            "total_payments": observation.get("totalPayments"),
            "accepted_count": accepted_count,
            "failed_count": observation.get("failedCount"),
            "accepted_payments": accepted_payments,
            "failed_payments": failed_payments,
            "message_ids": message_ids,
            "message": observation.get("message"),
            "attempts": result.attempts,
            "elapsed": result.elapsed,
        }
        return self._finalize_success(
            command,
            token,
            outputs,
            success_message=(
                f"accept_all {denomination}: accepted={outputs['accepted_count']} "
                f"failed={outputs['failed_count']} "
                f"in {result.attempts} attempt(s) / {result.elapsed:.1f}s"
            ),
        )
