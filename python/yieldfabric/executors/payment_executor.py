"""
Payment operations executor — deposit, withdraw, instant, accept,
accept_all. Single operations return `message_id`; batch operations return
`message_ids`. Unless explicitly disabled with `wait: false`, callers block
until every MQ message has executed and completed graph post-processing.
"""

from .base import BaseExecutor
from ..models import Command, CommandResponse
from ..utils.jwt import get_entity_id
from ..utils.graphql import GraphQLMutation
from ..utils.validators import is_provided


class PaymentExecutor(BaseExecutor):
    """Executor for payment operations."""

    def execute(self, command: Command) -> CommandResponse:
        command_type = command.type.lower()
        dispatch = {
            "deposit": self._execute_deposit,
            "withdraw": self._execute_withdraw,
            "instant": self._execute_instant,
            "accept": self._execute_accept,
            "accept_all": self._execute_accept_all,
            "retry_message": self._execute_retry_message,
        }
        handler = dispatch.get(command_type)
        if handler is None:
            return CommandResponse.error_response(
                command.name, command.type,
                [f"Unknown payment command type: {command_type}"]
            )
        return handler(command)

    # ------------------------------------------------------------------
    # Deposit / Withdraw share identical shape — assetId + amount + idem.
    # ------------------------------------------------------------------

    def _execute_deposit(self, command: Command) -> CommandResponse:
        return self._execute_amount_only(
            command,
            mutation=GraphQLMutation.DEPOSIT,
            response_root="deposit",
            operation_name="Deposit",
            result_field="depositResult",
            output_key="deposit_result",
        )

    def _execute_withdraw(self, command: Command) -> CommandResponse:
        return self._execute_amount_only(
            command,
            mutation=GraphQLMutation.WITHDRAW,
            response_root="withdraw",
            operation_name="Withdraw",
            result_field="withdrawResult",
            output_key="withdraw_result",
        )

    def _execute_amount_only(
        self,
        command: Command,
        *,
        mutation: str,
        response_root: str,
        operation_name: str,
        result_field: str,
        output_key: str,
    ) -> CommandResponse:
        """
        Shared implementation for mutations whose input is
        `{assetId, amount, idempotencyKey?}` and whose response is the
        standard `{success, accountAddress, message, messageId,
        timestamp, <op>Result}` shape.

        Signature mirrors `_execute_treasury_mutation` and
        `_execute_terminal_swap` for cross-executor consistency.
        """
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        denomination = params.denomination or params.asset_id

        self.log_parameters({
            "denomination": denomination,
            "amount": params.amount,
            "idempotency_key": params.idempotency_key,
        })

        variables = {
            "input": {
                "assetId": denomination,
                "amount": str(params.amount),
            }
        }
        if params.idempotency_key:
            variables["input"]["idempotencyKey"] = params.idempotency_key

        response = self.payments_service.graphql_mutation(mutation, variables, token)
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name=operation_name
            )

        data = response.get_data(response_root, {})
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", f"{operation_name} not successful"),
                operation_name=operation_name,
            )

        outputs = {
            "account_address": data.get("accountAddress"),
            "message": data.get("message"),
            "message_id": data.get("messageId"),
            output_key: data.get(result_field),
            "timestamp": data.get("timestamp"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message=f"{operation_name} successful!",
        )

    # ------------------------------------------------------------------

    def _execute_instant(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        denomination = params.denomination or params.asset_id

        contract_id = getattr(params, "contract_id", None)

        self.log_parameters({
            "denomination": denomination,
            "amount": params.amount,
            "destination_id": params.destination_id,
            "contract_id": contract_id,
            "idempotency_key": params.idempotency_key,
        })

        variables = {
            "input": {
                "assetId": denomination,
                "amount": str(params.amount),
                "destinationId": params.destination_id,
            }
        }
        # Route by an existing contract instead of an explicit destination. The
        # resolver resolves the payee from the contract's parties — for an
        # OBLIGATION (`CONTRACT-OBLIGATION-…`) that's the current NFT HOLDER, so
        # the payment follows a transfer. Lets a suite prove holder-routing.
        if contract_id:
            variables["input"]["contractId"] = contract_id
        if params.idempotency_key:
            variables["input"]["idempotencyKey"] = params.idempotency_key

        response = self.payments_service.graphql_mutation(
            GraphQLMutation.INSTANT, variables, token
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="Instant payment"
            )

        data = response.get_data("instant", {})
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", "Instant payment not successful"),
                operation_name="Instant payment",
            )

        outputs = {
            "account_address": data.get("accountAddress"),
            "destination_id": data.get("destinationId"),
            "message": data.get("message"),
            "id_hash": data.get("idHash"),
            "message_id": data.get("messageId"),
            "payment_id": data.get("paymentId"),
            "send_result": data.get("sendResult"),
            "timestamp": data.get("timestamp"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message="Instant payment successful!",
        )

    def _execute_accept(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        self.log_parameters({
            "payment_id": params.payment_id,
            "idempotency_key": params.idempotency_key,
        })

        variables = {"input": {"paymentId": params.payment_id}}
        if params.idempotency_key:
            variables["input"]["idempotencyKey"] = params.idempotency_key
        # ZKP oracle-document unlock: when the payment's unlock side carries a document constraint,
        # supply the committed document + the SAME query/salt used at create so the server rebuilds
        # the witness for acceptWithDocument.
        for key, gql in (
            ("oracle_document_json", "oracleDocumentJson"),
            ("oracle_query", "oracleQuery"),
            ("oracle_query_salt", "oracleQuerySalt"),
        ):
            val = params.raw_params.get(key)
            if val is not None:
                variables["input"][gql] = val

        response = self.payments_service.graphql_mutation(
            GraphQLMutation.ACCEPT, variables, token
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="Accept"
            )

        data = response.get_data("accept", {})
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", "Accept not successful"),
                operation_name="Accept",
            )

        outputs = {
            "account_address": data.get("accountAddress"),
            "disposition": data.get("disposition"),
            "message": data.get("message"),
            "id_hash": data.get("idHash"),
            "message_id": data.get("messageId"),
            "transaction_id": data.get("transactionId"),
            "accept_result": data.get("acceptResult"),
            "timestamp": data.get("timestamp"),
        }
        return self._finalize_success(
            command, token, outputs, success_message="Accept successful!",
        )

    def _execute_retry_message(self, command: Command) -> CommandResponse:
        """Redrive the same failed canonical payment Retrieve and wait for it."""
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        message_id = params.get("message_id")
        raw_mode = params.get("execution_mode") or "Automatic"
        execution_mode = {
            "automatic": "Automatic",
        }.get(str(raw_mode).strip().lower())
        entity_id = params.get("user_id") or get_entity_id(token)

        self.log_parameters({
            "message_id": message_id,
            "execution_mode": raw_mode,
        })

        if not message_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name,
                command.type,
                ["retry_message requires `message_id`"],
            )
        if execution_mode is None:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name,
                command.type,
                ["retry_message only supports `Automatic` execution_mode"],
            )
        if not entity_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name,
                command.type,
                ["Could not derive the message owner from the JWT"],
            )

        result = self.payments_service.retry_message(
            entity_id,
            str(message_id),
            execution_mode,
            token,
        )
        if not result.get("success"):
            return self._finalize_business_error(
                command,
                result.get("message", "Message retry was not accepted"),
                operation_name="Retry message",
            )

        returned_message_id = result.get("message_id")
        if str(returned_message_id or "") != str(message_id):
            return self._finalize_business_error(
                command,
                "Retry did not return the same message_id; canonical redrive was not preserved",
                operation_name="Retry message",
            )

        outputs = {
            "message": result.get("message"),
            "message_id": str(message_id),
            "execution_mode": result.get("execution_mode") or execution_mode,
        }
        return self._finalize_success(
            command,
            token,
            outputs,
            success_message="Canonical message redrive completed!",
        )

    def _execute_accept_all(self, command: Command) -> CommandResponse:
        """
        Accept every pending PAYABLE the user is the RECEIVER for,
        optionally filtered by `denomination` + `obligor`. Mirrors the
        shell's `execute_accept_all` (executors.sh:544).

        `acceptAll` returns one durable message id per accepted payment.
        Preserve all of them so the shared batch waiter can block until
        execution and graph post-processing finish. `wait_for_accept_all`
        remains useful when the payable itself may not have materialised yet.
        """
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        params = command.parameters
        denomination = params.denomination or params.asset_id
        if not denomination:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, ["accept_all requires `denomination`"]
            )

        self.log_parameters({
            "denomination": denomination,
            "obligor": params.obligor,
            "idempotency_key": params.idempotency_key,
        })

        variables = {"input": {"denomination": denomination}}
        if is_provided(params.obligor):
            variables["input"]["obligor"] = params.obligor
        if params.idempotency_key:
            variables["input"]["idempotencyKey"] = params.idempotency_key

        response = self.payments_service.graphql_mutation(
            GraphQLMutation.ACCEPT_ALL, variables, token
        )
        if not response.success:
            return self._finalize_graphql_error(
                command, response, operation_name="AcceptAll"
            )

        data = response.get_data("acceptAll", {})
        if not data.get("success"):
            return self._finalize_business_error(
                command,
                data.get("message", "acceptAll not successful"),
                operation_name="AcceptAll",
            )

        accepted_payments = data.get("acceptedPayments") or []
        failed_payments = data.get("failedPayments") or []
        message_ids = self._normalize_message_ids(
            payment.get("messageId")
            for payment in accepted_payments
            if isinstance(payment, dict)
        )
        accepted_count = int(data.get("acceptedCount") or 0)
        if accepted_count != len(message_ids):
            return self._finalize_business_error(
                command,
                (
                    "acceptAll returned "
                    f"{accepted_count} accepted payment(s) but "
                    f"{len(message_ids)} distinct durable message id(s)"
                ),
                operation_name="AcceptAll",
            )

        outputs = {
            "message": data.get("message"),
            "total_payments": data.get("totalPayments"),
            "accepted_count": accepted_count,
            "failed_count": data.get("failedCount"),
            "accepted_payments": accepted_payments,
            "failed_payments": failed_payments,
            "message_ids": message_ids,
            "denomination": denomination,
            "obligor": params.obligor,
            "timestamp": data.get("timestamp"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message=(
                f"AcceptAll: total={outputs['total_payments']} "
                f"accepted={outputs['accepted_count']} "
                f"failed={outputs['failed_count']}"
            ),
        )
