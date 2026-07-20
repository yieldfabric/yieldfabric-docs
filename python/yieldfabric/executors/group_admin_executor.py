"""
Group-admin executor — account ownership and account-member management.

Handles the six command types the shell implements via
`executors_additional.sh`:

    add_owner              → POST /auth/groups/{id}/add-owner
    remove_owner           → POST /auth/groups/{id}/remove-owner
    add_account_member     → POST /auth/groups/{id}/add-account-member
    remove_account_member  → POST /auth/groups/{id}/remove-account-member
    get_account_owners     → GET  /auth/groups/{id}/account-owners
    get_account_members    → GET  /auth/groups/{id}/account-members

All six are REST calls to the auth service (not GraphQL to payments),
and all use `_acquire_token_or_error(use_delegation=False)` because
the user must sign as themselves — `user.group` is only a lookup hint
to resolve `group_id` by name. Acquiring a delegation JWT here would
make the on-chain owner/member endpoints reject the call.
"""

import time
from typing import Optional

from .base import BaseExecutor
from ..models import Command, CommandResponse


class GroupAdminExecutor(BaseExecutor):
    """Executor for group ownership + account-member operations."""

    _ACCOUNT_MEMBER_RESOLVE_MAX_RETRIES = 12
    _ACCOUNT_MEMBER_RESOLVE_RETRY_SECONDS = 2.0

    def execute(self, command: Command) -> CommandResponse:
        command_type = command.type.lower()
        dispatch = {
            "add_owner": self._execute_add_owner,
            "remove_owner": self._execute_remove_owner,
            "add_member": self._execute_add_member,
            "add_account_member": lambda c: self._execute_account_member_mutation(c, add=True),
            "remove_account_member": lambda c: self._execute_account_member_mutation(c, add=False),
            "get_account_owners": self._execute_get_account_owners,
            "get_account_members": self._execute_get_account_members,
        }
        handler = dispatch.get(command_type)
        if handler is None:
            return CommandResponse.error_response(
                command.name, command.type,
                [f"Unknown group-admin command type: {command_type}"]
            )
        return handler(command)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_group_id(self, token: str, command: Command) -> Optional[str]:
        """
        Resolve `command.user.group` → group_id via the caller's
        group-membership list. Returns None (with a logged error) if
        the group isn't found or `user.group` wasn't set.
        """
        group_name = command.user.group
        if not group_name:
            self.logger.error(
                f"    ❌ {command.type} requires `user.group` to identify the target group"
            )
            return None
        return self.auth_service.get_user_group_id_by_name(token, group_name)

    def _preflight(self, command: Command):
        """
        Combined pre-flight: log start, acquire direct (non-delegation)
        token, resolve group_id. Returns `(token, group_id, None)` on
        success, or `(None, None, error_response)` on any failure.
        """
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return None, None, err

        group_id = self._resolve_group_id(token, command)
        if not group_id:
            self.log_command_failure(command)
            return None, None, CommandResponse.error_response(
                command.name, command.type,
                [f"Group not found: {command.user.group}"]
            )
        return token, group_id, None

    def _finalize_rest_success(
        self, command: Command, outputs: dict, *, success_message: str
    ) -> CommandResponse:
        """
        Like `_finalize_success` but without the MQ wait/poll step —
        these are synchronous REST calls with no message_id.
        """
        self.store_outputs(command.name, outputs)
        self.logger.success(f"    ✅ {success_message}")
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    def _finalize_rest_error(
        self, command: Command, result: dict, *, fallback: str
    ) -> CommandResponse:
        """
        Standard failure return for the {status, message, error} REST
        response shape. Falls back to `fallback` if neither message nor
        error was populated.
        """
        message = result.get("message") or result.get("error") or fallback
        self.log_command_failure(command)
        return CommandResponse.error_response(
            command.name, command.type, [message]
        )

    @staticmethod
    def _mutation_was_accepted(result: dict) -> bool:
        """Accept both the legacy synchronous and durable operation shapes."""
        if result.get("status") == "success":
            return True
        return result.get("success") is True and result.get("status") not in {
            "failed",
            "retry_required",
            "error",
        }

    def _settle_group_account_operation(
        self,
        command: Command,
        token: str,
        group_id: str,
        result: dict,
    ) -> dict:
        """Wait for auth's durable group mutation unless YAML opts out."""
        if not self._mutation_was_accepted(result):
            return result

        # Compatibility with the former synchronous response and explicit
        # fire-and-forget commands.
        operation_id = result.get("operation_id")
        if not operation_id or not self._should_wait(command):
            return result
        if result.get("status") == "confirmed":
            return result

        timeout = self._float_param(
            command, "wait_timeout", self._DEFAULT_WAIT_TIMEOUT_SEC
        )
        interval = self._float_param(
            command, "wait_interval", self._DEFAULT_WAIT_INTERVAL_SEC
        )
        deadline = time.monotonic() + timeout
        attempts = 0
        latest = result
        self.logger.info(
            f"  ⏳ polling group account operation {str(operation_id)[:8]}... "
            f"(interval={interval}s, timeout={timeout}s)"
        )

        while True:
            status = str(latest.get("status") or "").lower()
            if status == "confirmed":
                latest["wait_attempts"] = attempts
                self.logger.success(
                    f"    ✅ group account operation {str(operation_id)[:8]}... confirmed"
                )
                return latest
            if status in {"failed", "retry_required"} or latest.get("success") is False:
                return latest
            if time.monotonic() >= deadline:
                return {
                    **latest,
                    "status": "error",
                    "success": False,
                    "message": (
                        f"Timed out waiting for group account operation "
                        f"{operation_id} after {timeout}s"
                    ),
                    "wait_timed_out": True,
                    "wait_attempts": attempts,
                }

            time.sleep(interval)
            attempts += 1
            observed = self.auth_service.get_group_account_operation(
                token, group_id, str(operation_id)
            )
            if isinstance(observed, dict):
                latest = observed

    # ------------------------------------------------------------------
    # add_owner / remove_owner
    # ------------------------------------------------------------------

    def _execute_add_owner(self, command: Command) -> CommandResponse:
        token, group_id, err = self._preflight(command)
        if err:
            return err

        new_owner = command.parameters.get("new_owner")
        if not new_owner:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, ["add_owner requires `new_owner`"]
            )

        self.log_parameters({"group": command.user.group, "new_owner": new_owner})

        result = self.auth_service.add_group_owner(token, group_id, new_owner)
        result = self._settle_group_account_operation(
            command, token, group_id, result
        )
        if not self._mutation_was_accepted(result):
            return self._finalize_rest_error(command, result, fallback="add_owner failed")
        return self._finalize_rest_success(
            command,
            {
                "group_id": group_id,
                "new_owner": new_owner,
                "operation_id": result.get("operation_id"),
                "message_id": result.get("message_id"),
                "operation_status": result.get("status"),
            },
            success_message=f"add_owner: {new_owner} added to {command.user.group}",
        )

    def _execute_remove_owner(self, command: Command) -> CommandResponse:
        token, group_id, err = self._preflight(command)
        if err:
            return err

        old_owner = command.parameters.get("old_owner")
        if not old_owner:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type, ["remove_owner requires `old_owner`"]
            )

        self.log_parameters({"group": command.user.group, "old_owner": old_owner})

        result = self.auth_service.remove_group_owner(token, group_id, old_owner)
        result = self._settle_group_account_operation(
            command, token, group_id, result
        )
        if not self._mutation_was_accepted(result):
            return self._finalize_rest_error(command, result, fallback="remove_owner failed")
        return self._finalize_rest_success(
            command,
            {
                "group_id": group_id,
                "old_owner": old_owner,
                "operation_id": result.get("operation_id"),
                "message_id": result.get("message_id"),
                "operation_status": result.get("status"),
            },
            success_message=f"remove_owner: {old_owner} removed from {command.user.group}",
        )

    # ------------------------------------------------------------------
    # add_member — ROLE-based group membership (distinct from the NFT-based
    # account-member mutations below). Used to provision a `policymember`:
    # the restricted role that may EXECUTE a group's data policy but is not
    # an on-chain owner and cannot approve. `member_user_id` is the target
    # user's UUID (e.g. `$member_whoami.sub`); `role` defaults to member.
    # ------------------------------------------------------------------

    def _execute_add_member(self, command: Command) -> CommandResponse:
        token, group_id, err = self._preflight(command)
        if err:
            return err

        member_user_id = command.parameters.get("member_user_id") or command.parameters.get("user_id")
        role = command.parameters.get("role", "member")
        if not member_user_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type,
                ["add_member requires `member_user_id` (the target user's UUID)"],
            )

        self.log_parameters({
            "group": command.user.group,
            "member_user_id": member_user_id,
            "role": role,
        })

        result = self.auth_service.add_group_member(token, group_id, member_user_id, role)
        if result.get("status") not in ("added", "exists"):
            return self._finalize_rest_error(command, result, fallback="add_member failed")
        return self._finalize_rest_success(
            command,
            {"group_id": group_id, "member_user_id": member_user_id, "role": role},
            success_message=f"add_member: {member_user_id} ({role}) → {command.user.group} [{result.get('status')}]",
        )

    # ------------------------------------------------------------------
    # add_account_member / remove_account_member
    # ------------------------------------------------------------------

    def _execute_account_member_mutation(
        self, command: Command, add: bool
    ) -> CommandResponse:
        token, group_id, err = self._preflight(command)
        if err:
            return err

        # obligation_id and obligation_address come from raw_params.
        # obligation_address is optional (backend uses
        # CONFIDENTIAL_OBLIGATION_ADDRESS as default).
        obligation_id = command.parameters.get("obligation_id")
        obligation_address = command.parameters.get("obligation_address")
        if not obligation_id:
            self.log_command_failure(command)
            return CommandResponse.error_response(
                command.name, command.type,
                [f"{command.type} requires `obligation_id`"]
            )

        self.log_parameters({
            "group": command.user.group,
            "obligation_id": obligation_id,
            "obligation_address": obligation_address or "(default)",
        })

        result = None
        for attempt in range(1, self._ACCOUNT_MEMBER_RESOLVE_MAX_RETRIES + 1):
            if add:
                result = self.auth_service.add_account_member(
                    token, group_id, obligation_id, obligation_address
                )
            else:
                result = self.auth_service.remove_account_member(
                    token, group_id, obligation_id, obligation_address
                )

            if self._mutation_was_accepted(result):
                break

            message = str(result.get("message") or result.get("error") or "")
            if (
                attempt >= self._ACCOUNT_MEMBER_RESOLVE_MAX_RETRIES
                or not self._is_transient_contract_resolution_error(result, message)
            ):
                break

            self.logger.info(
                f"    ⏳ obligation {obligation_id} not resolvable yet "
                f"(attempt {attempt}/{self._ACCOUNT_MEMBER_RESOLVE_MAX_RETRIES}); "
                f"retrying in {self._ACCOUNT_MEMBER_RESOLVE_RETRY_SECONDS}s"
            )
            time.sleep(self._ACCOUNT_MEMBER_RESOLVE_RETRY_SECONDS)

        result = self._settle_group_account_operation(
            command, token, group_id, result
        )
        if not self._mutation_was_accepted(result):
            return self._finalize_rest_error(
                command, result, fallback=f"{command.type} failed"
            )
        return self._finalize_rest_success(
            command,
            {
                "group_id": group_id,
                "obligation_id": obligation_id,
                "obligation_address": obligation_address,
                "operation_id": result.get("operation_id"),
                "message_id": result.get("message_id"),
                "operation_status": result.get("status"),
            },
            success_message=f"{command.type} ok",
        )

    def _is_transient_contract_resolution_error(self, result: dict, message: str) -> bool:
        """Auth can briefly outrun payments' contract-token persistence."""
        msg = message.lower()
        return (
            result.get("status_code") in (400, 404)
            or "400 client error" in msg
            or "404 client error" in msg
            or "cannot resolve custom contract_id" in msg
            or "not found in payments" in msg
            or "not have a token_id yet" in msg
            or "contract may not have a token_id yet" in msg
        )

    # ------------------------------------------------------------------
    # get_account_owners / get_account_members — read endpoints.
    # ------------------------------------------------------------------

    def _execute_get_account_owners(self, command: Command) -> CommandResponse:
        return self._execute_account_query(
            command,
            fetch=self.auth_service.get_account_owners,
            list_key="owners",
            count_key="owners_count",
            operation_name="get_account_owners",
        )

    def _execute_get_account_members(self, command: Command) -> CommandResponse:
        return self._execute_account_query(
            command,
            fetch=self.auth_service.get_account_members,
            list_key="members",
            count_key="members_count",
            operation_name="get_account_members",
        )

    def _execute_account_query(
        self,
        command: Command,
        *,
        fetch,  # callable(token, group_id) -> dict
        list_key: str,
        count_key: str,
        operation_name: str,
    ) -> CommandResponse:
        """
        Shared implementation for get_account_{owners,members}. Both
        endpoints return `{account_address, <list_key>: [...]}` on
        success; we surface the list count for downstream chaining.
        """
        token, group_id, err = self._preflight(command)
        if err:
            return err

        result = fetch(token, group_id)
        items = result.get(list_key)
        if not isinstance(items, list):
            return self._finalize_rest_error(
                command, result, fallback=f"{operation_name} failed"
            )

        return self._finalize_rest_success(
            command,
            {
                "group_id": group_id,
                "account_address": result.get("account_address"),
                list_key: items,
                count_key: len(items),
            },
            success_message=f"{operation_name}: {len(items)} {list_key}",
        )
