"""
Obligation operations executor — create, accept, transfer, cancel.

`accept_obligation` includes a targeted retry on "not found" errors
to handle the MQ-consumer race where the contract record hasn't been
persisted yet when the accept is issued.
"""

import time

from .base import BaseExecutor
from ..models import Command, CommandResponse
from ..utils.graphql import GraphQLMutation
from ..utils.graphql_input import normalize_initial_payments


class ObligationExecutor(BaseExecutor):
    """Executor for obligation operations."""

    # Max retries + delay when `acceptObligation` is called before the
    # backend's MQ consumer has persisted the contract record. We retry
    # specifically on "not found" errors — not all errors. Mirrors the
    # shell's `accept_obligation_graphql` retry-on-MQ-race behaviour
    # from loan_management/modules/payments.py.
    _ACCEPT_NOT_FOUND_MAX_RETRIES = 12
    _ACCEPT_NOT_FOUND_RETRY_SECONDS = 2.0

    def execute(self, command: Command) -> CommandResponse:
        command_type = command.type.lower()
        dispatch = {
            "create_obligation": self._execute_create_obligation,
            "accept_obligation": self._execute_accept_obligation,
            "transfer_obligation": self._execute_transfer_obligation,
            "cancel_obligation": self._execute_cancel_obligation,
        }
        handler = dispatch.get(command_type)
        if handler is None:
            return CommandResponse.error_response(
                command.name, command.type,
                [f"Unknown obligation command type: {command_type}"]
            )
        return handler(command)

    # ------------------------------------------------------------------

    def _execute_create_obligation(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        input_obj = {
            "counterpart": params.counterpart,
            "denomination": params.denomination or params.asset_id,
        }
        # Optional fields — only include if provided.
        if params.obligation_address:
            input_obj["obligationAddress"] = params.obligation_address
        if params.obligation_group_id:
            input_obj["obligationGroupId"] = params.obligation_group_id
        if params.obligor:
            input_obj["obligor"] = params.obligor
        if params.expiry:
            input_obj["expiry"] = params.expiry
        if params.data:
            input_obj["data"] = params.data
        if params.initial_payments:
            input_obj["initialPayments"] = normalize_initial_payments(
                params.initial_payments
            )
        if params.contract_id:
            input_obj["contractId"] = params.contract_id
        if params.idempotency_key:
            input_obj["idempotencyKey"] = params.idempotency_key

        variables = {"input": input_obj}
        response = self.payments_service.graphql_mutation(
            GraphQLMutation.CREATE_OBLIGATION, variables, token
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="Create obligation"
            )

        data = response.get_data("createObligation", {})
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", "Create obligation not successful"),
                operation_name="Create obligation",
            )

        outputs = {
            "account_address": data.get("accountAddress"),
            "contract_id": data.get("contractId"),
            "token_id": data.get("tokenId"),
            "transaction_id": data.get("transactionId"),
            "message": data.get("message"),
            "message_id": data.get("messageId"),
            "obligation_result": data.get("obligationResult"),
            "signature": data.get("signature"),
            "timestamp": data.get("timestamp"),
            "id_hash": data.get("idHash"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message="Create obligation successful!",
        )

    def _execute_accept_obligation(self, command: Command) -> CommandResponse:
        """
        Accept obligation with retry on MQ persistence race.

        Retries only on "not found" / "cannot resolve" / "does not
        exist" errors — those indicate the contract record is not yet
        persisted by the MQ consumer. All other errors surface
        immediately.
        """
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        variables = {"input": {"contractId": params.contract_id}}
        if params.idempotency_key:
            variables["input"]["idempotencyKey"] = params.idempotency_key

        attempt = 0
        response = None
        while True:
            attempt += 1
            response = self.payments_service.graphql_mutation(
                GraphQLMutation.ACCEPT_OBLIGATION, variables, token
            )
            if response.success:
                break

            err_msg = (response.get_error_message() or "").lower()
            is_not_found = (
                "not found" in err_msg
                or "cannot resolve" in err_msg
                or "does not exist" in err_msg
            )
            if not is_not_found or attempt >= self._ACCEPT_NOT_FOUND_MAX_RETRIES:
                return self._finalize_graphql_error(
                    command, response, operation_name="Accept obligation"
                )

            self.logger.info(
                f"    ⏳ contract not yet persisted (attempt {attempt}/"
                f"{self._ACCEPT_NOT_FOUND_MAX_RETRIES}); retrying in "
                f"{self._ACCEPT_NOT_FOUND_RETRY_SECONDS}s"
            )
            time.sleep(self._ACCEPT_NOT_FOUND_RETRY_SECONDS)

        data = response.get_data("acceptObligation", {})
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", "Accept obligation not successful"),
                operation_name="Accept obligation",
            )

        outputs = {
            "account_address": data.get("accountAddress"),
            "obligation_id": data.get("obligationId"),
            "message": data.get("message"),
            "message_id": data.get("messageId"),
            "transaction_id": data.get("transactionId"),
            "signature": data.get("signature"),
            "timestamp": data.get("timestamp"),
            "accept_result": data.get("acceptResult"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message=f"Accept obligation successful! (attempts={attempt})",
        )

    def _execute_transfer_obligation(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        variables = {
            "input": {
                "contractId": params.contract_id,
                "destinationId": params.destination_id,
            }
        }
        if params.idempotency_key:
            variables["input"]["idempotencyKey"] = params.idempotency_key

        response = self.payments_service.graphql_mutation(
            GraphQLMutation.TRANSFER_OBLIGATION, variables, token
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="Transfer obligation"
            )

        data = response.get_data("transferObligation", {})
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", "Transfer obligation not successful"),
                operation_name="Transfer obligation",
            )

        outputs = {
            "message": data.get("message"),
            "account_address": data.get("accountAddress"),
            "obligation_id": data.get("obligationId"),
            "destination_id": data.get("destinationId"),
            "destination_address": data.get("destinationAddress"),
            "transfer_result": data.get("transferResult"),
            "message_id": data.get("messageId"),
            "transaction_id": data.get("transactionId"),
            "signature": data.get("signature"),
            "timestamp": data.get("timestamp"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message="Transfer obligation successful!",
        )

    def _execute_cancel_obligation(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        variables = {"input": {"contractId": params.contract_id}}
        if params.idempotency_key:
            variables["input"]["idempotencyKey"] = params.idempotency_key

        response = self.payments_service.graphql_mutation(
            GraphQLMutation.CANCEL_OBLIGATION, variables, token
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="Cancel obligation"
            )

        data = response.get_data("cancelObligation", {})
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", "Cancel obligation not successful"),
                operation_name="Cancel obligation",
            )

        outputs = {
            "message": data.get("message"),
            "account_address": data.get("accountAddress"),
            "obligation_id": data.get("obligationId"),
            "cancel_result": data.get("cancelResult"),
            "message_id": data.get("messageId"),
            "transaction_id": data.get("transactionId"),
            "signature": data.get("signature"),
            "timestamp": data.get("timestamp"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message="Cancel obligation successful!",
        )
