"""
Owned-group authority executor.

This module gives YAML suites first-class commands for the Head Co → Subsidiary
flow without ever putting the short-lived child JWT in OutputStore:

    user_signing_key       select/provision the operator's bound USER key
    group_signing_key      look up a GROUP key (negative assertions only)
    establish_group_owner  reserve/advance the A→B NFT relationship saga
    list_group_owners      inspect the child-side relationship state
    revoke_group_owner     remove every approved A-held credential from B
    list_group_members     inspect direct membership without inferring owners
    discover_owned_groups  call the direct-parent discovery endpoint
    assume_owned_group     exchange the direct parent and retain the child under
                           an opaque, process-local credential handle
    validate_credential    validate a named credential at /protected/jwt
    service_request        exercise an authorization-denial matrix safely
"""

import json
import re
import time
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from .base import BaseExecutor
from ..core.key_manager import FileBackedSigner, KeyManager
from ..core.message_listener import MessageSignatureListener
from ..models import Command, CommandResponse
from ..utils.jwt import decode_payload, extract_claim, get_sub


class OwnedGroupExecutor(BaseExecutor):
    """Executor for nested group-account ownership and delegated operation."""

    # Auth's owned-group TTL clamp, mirrored:
    # `requested.clamp(60, OWNED_GROUP_MAX_ACCESS_TTL_SECS)` in
    # `group_delegation.rs::owned_group_ttl_seconds`. The FLOOR is why a
    # request below it legitimately comes back longer than asked.
    _OWNED_GROUP_TTL_FLOOR_SECS = 60
    _OWNED_GROUP_TTL_CEILING_SECS = 900

    _RELATIONSHIP_ALLOWED_KEYS = {
        "relationship_id",
        "parent_group_id",
        "child_group_id",
        "chain_id",
        "status",
        "stage",
        "credential_contract",
        "token_id",
        "message_id",
        "operation_id",
        "retry_required",
        "error",
    }
    _RELATIONSHIP_STATUSES = {
        "provisioning",
        "active",
        "revoking",
        "revoked",
        "failed_retryable",
    }
    _RELATIONSHIP_STAGES = {
        "parent_credential_authorization_required",
        "parent_credential_pending",
        "parent_credential_retry_required",
        "child_membership_authorization_required",
        "child_membership_pending",
        "child_membership_retry_required",
        "active",
        "revocation_pending",
        "revocation_retry_required",
        "revoked",
    }
    _RELATIONSHIP_STAGE_CONTRACT = {
        "parent_credential_authorization_required": ("provisioning", False),
        "parent_credential_pending": ("provisioning", False),
        "parent_credential_retry_required": ("failed_retryable", True),
        "child_membership_authorization_required": ("provisioning", False),
        "child_membership_pending": ("provisioning", False),
        "child_membership_retry_required": ("failed_retryable", True),
        "active": ("active", False),
        "revocation_pending": ("revoking", False),
        "revocation_retry_required": ("failed_retryable", True),
        "revoked": ("revoked", False),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._signature_listeners: Dict[str, MessageSignatureListener] = {}

    def execute(self, command: Command) -> CommandResponse:
        dispatch = {
            "user_signing_key": self._execute_user_signing_key,
            "group_signing_key": self._execute_group_signing_key,
            "establish_group_owner": self._execute_establish_group_owner,
            "list_group_owners": self._execute_list_group_owners,
            "revoke_group_owner": self._execute_revoke_group_owner,
            "start_signature_listener": self._execute_start_signature_listener,
            "stop_signature_listener": self._execute_stop_signature_listener,
            "list_group_members": self._execute_list_group_members,
            "discover_owned_groups": self._execute_discover_owned_groups,
            "assume_owned_group": self._execute_assume_owned_group,
            "validate_credential": self._execute_validate_credential,
            "service_request": self._execute_service_request,
        }
        handler = dispatch.get(command.type.lower())
        if handler is None:
            return CommandResponse.error_response(
                command.name,
                command.type,
                [f"Unknown owned-group command type: {command.type}"],
            )
        return handler(command)

    def close(self) -> None:
        """Stop every daemon signer so no test leaks signing authority."""
        failures = []
        for name, listener in list(self._signature_listeners.items()):
            try:
                listener.stop()
                self._signature_listeners.pop(name, None)
            except RuntimeError as exc:
                failures.append(f"{name}: {exc}")
        if failures:
            raise RuntimeError(
                "one or more signature listeners remain cancellation-pending: "
                + "; ".join(failures)
            )

    def _success(
        self,
        command: Command,
        outputs: Dict[str, Any],
        message: str,
    ) -> CommandResponse:
        self.store_outputs(command.name, outputs)
        self.logger.success(f"    ✅ {message}")
        self.log_command_success(command)
        return CommandResponse.success_response(
            command.name, command.type, outputs
        )

    def _failure(
        self,
        command: Command,
        message: str,
    ) -> CommandResponse:
        self.log_command_failure(command)
        return CommandResponse.error_response(
            command.name, command.type, [message]
        )

    @staticmethod
    def _canonical_uuid(value: Any, label: str) -> str:
        if not isinstance(value, str):
            raise ValueError(f"{label} must be a UUID string")
        try:
            canonical = str(UUID(value))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"{label} must be a canonical UUID") from exc
        if canonical != value:
            raise ValueError(f"{label} must be a canonical UUID")
        return canonical

    @staticmethod
    def _canonical_chain_id(value: Any, label: str = "chain_id") -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[1-9][0-9]*", value):
            raise ValueError(f"{label} must be a canonical positive decimal string")
        if int(value) >= 1 << 64:
            raise ValueError(f"{label} is outside uint64")
        return value

    @staticmethod
    def _canonical_address(value: Any, label: str) -> str:
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"0x[0-9a-f]{40}", value)
            or value == "0x" + "0" * 40
        ):
            raise ValueError(f"{label} must be a canonical non-zero EVM address")
        return value

    @staticmethod
    def _canonical_token_id(value: Any, label: str) -> str:
        if (
            not isinstance(value, str)
            or not re.fullmatch(r"[1-9][0-9]*", value)
            or int(value) >= 1 << 256
        ):
            raise ValueError(f"{label} must be a positive decimal uint256")
        return value

    @classmethod
    def _direct_parent_provenance(
        cls, claims: Dict[str, Any]
    ) -> Dict[str, Any]:
        actor_sub = cls._canonical_uuid(claims.get("sub"), "parent sub")
        acting_as = cls._canonical_uuid(
            claims.get("acting_as"), "parent acting_as"
        )
        delegation_token_id = cls._canonical_uuid(
            claims.get("delegation_token_id"),
            "parent delegation_token_id",
        )
        chain_id = cls._canonical_chain_id(
            claims.get("default_chain_id"), "parent default_chain_id"
        )
        scope = claims.get("delegation_scope")
        expires_at = claims.get("exp")
        if (
            claims.get("entity_type") != "user"
            or claims.get("auth_method") != "delegation"
            or claims.get("kind") == "service"
            or actor_sub.startswith("service:")
            or claims.get("password_change_only") is True
            or claims.get("mcp_impersonation") is True
            or claims.get("mcp_agent_id") is not None
            or claims.get("mcp_session_id") is not None
            or claims.get("mcp_selected_key") is not None
            or claims.get("delegation_path") is not None
            or claims.get("authority_source") is not None
            or claims.get("authority_key_id") is not None
            or claims.get("membership_edge") is not None
            or claims.get("signer_key_id") is not None
            or claims.get("signer_address") is not None
            or claims.get("signer_scheme") is not None
            or claims.get("signer_custody") is not None
            or not isinstance(scope, list)
            or not scope
            or any(
                not isinstance(permission, str)
                or not permission
                or permission.strip() != permission
                for permission in scope
            )
            or len(set(scope)) != len(scope)
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or expires_at <= int(time.time())
        ):
            raise ValueError(
                "owned-group exchange requires a direct human parent delegation"
            )
        return {
            "actor_sub": actor_sub,
            "acting_as": acting_as,
            "delegation_token_id": delegation_token_id,
            "chain_id": chain_id,
            "delegation_scope": list(scope),
            "exp": expires_at,
        }

    @classmethod
    def _personal_user_provenance(
        cls, claims: Dict[str, Any]
    ) -> Dict[str, str]:
        actor_sub = cls._canonical_uuid(claims.get("sub"), "personal sub")
        chain_id = cls._canonical_chain_id(
            claims.get("default_chain_id"), "personal default_chain_id"
        )
        auth_method = claims.get("auth_method")
        expires_at = claims.get("exp")
        if (
            claims.get("entity_type") != "user"
            or claims.get("kind") == "service"
            or not isinstance(auth_method, str)
            or not auth_method
            or auth_method == "delegation"
            or claims.get("password_change_only") is True
            or claims.get("mcp_impersonation") is True
            or claims.get("mcp_agent_id") is not None
            or claims.get("mcp_session_id") is not None
            or claims.get("mcp_selected_key") is not None
            or claims.get("acting_as") is not None
            or claims.get("delegation_scope") is not None
            or claims.get("delegation_token_id") is not None
            or claims.get("delegation_path") is not None
            or claims.get("authority_source") is not None
            or claims.get("authority_key_id") is not None
            or claims.get("membership_edge") is not None
            or claims.get("signer_key_id") is not None
            or claims.get("signer_address") is not None
            or claims.get("signer_scheme") is not None
            or claims.get("signer_custody") is not None
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or expires_at <= int(time.time())
        ):
            raise ValueError(
                "group-owner relationship mutations require a personal human JWT"
            )
        return {"actor_sub": actor_sub, "chain_id": chain_id}

    @classmethod
    def _owned_group_provenance(
        cls, claims: Dict[str, Any]
    ) -> Dict[str, Any]:
        actor_sub = cls._canonical_uuid(claims.get("sub"), "owned actor sub")
        acting_as = cls._canonical_uuid(
            claims.get("acting_as"), "owned acting_as"
        )
        delegation_token_id = cls._canonical_uuid(
            claims.get("delegation_token_id"),
            "owned delegation_token_id",
        )
        signer_key_id = cls._canonical_uuid(
            claims.get("signer_key_id"), "owned signer_key_id"
        )
        signer_address = cls._canonical_address(
            claims.get("signer_address"), "owned signer_address"
        )
        chain_id = cls._canonical_chain_id(
            claims.get("default_chain_id"), "owned default_chain_id"
        )
        path = claims.get("delegation_path")
        if not isinstance(path, list) or len(path) != 2:
            raise ValueError("owned delegation_path must contain [parent, child]")
        parent_group_id = cls._canonical_uuid(
            path[0], "owned parent_group_id"
        )
        child_group_id = cls._canonical_uuid(
            path[1], "owned child_group_id"
        )
        edge = claims.get("membership_edge")
        if (
            not isinstance(edge, dict)
            or set(edge)
            != {
                "parent_group_id",
                "child_group_id",
                "chain_id",
                "credential_contract",
                "token_id",
            }
        ):
            raise ValueError("owned membership_edge has an invalid field set")
        credential_contract = cls._canonical_address(
            edge.get("credential_contract"),
            "membership_edge.credential_contract",
        )
        token_id = cls._canonical_token_id(
            edge.get("token_id"), "membership_edge.token_id"
        )
        scope = claims.get("delegation_scope")
        expires_at = claims.get("exp")
        if (
            claims.get("authority_source") != "nft_membership"
            or claims.get("authority_key_id") is not None
            or parent_group_id == child_group_id
            or acting_as != child_group_id
            or edge.get("parent_group_id") != parent_group_id
            or edge.get("child_group_id") != child_group_id
            or edge.get("chain_id") != chain_id
            or claims.get("signer_scheme") != "account_ecdsa65_v1"
            or claims.get("signer_custody")
            not in {"custodial", "external"}
            or claims.get("entity_type") != "user"
            or claims.get("auth_method") != "delegation"
            or claims.get("kind") == "service"
            or claims.get("password_change_only") is True
            or claims.get("mcp_impersonation") is True
            or claims.get("mcp_agent_id") is not None
            or claims.get("mcp_session_id") is not None
            or claims.get("mcp_selected_key") is not None
            or not isinstance(scope, list)
            or not scope
            or any(
                not isinstance(permission, str)
                or not permission
                or permission.strip() != permission
                for permission in scope
            )
            or len(set(scope)) != len(scope)
            or not isinstance(expires_at, int)
            or isinstance(expires_at, bool)
            or expires_at <= int(time.time())
        ):
            raise ValueError(
                "owned-group JWT has inconsistent NFT/signer provenance"
            )
        return {
            "actor_sub": actor_sub,
            "acting_as": acting_as,
            "delegation_token_id": delegation_token_id,
            "delegation_path": [parent_group_id, child_group_id],
            "authority_source": "nft_membership",
            "membership_edge": {
                "parent_group_id": parent_group_id,
                "child_group_id": child_group_id,
                "chain_id": chain_id,
                "credential_contract": credential_contract,
                "token_id": token_id,
            },
            "signer_key_id": signer_key_id,
            "signer_address": signer_address,
            "signer_scheme": "account_ecdsa65_v1",
            "signer_custody": claims["signer_custody"],
            "chain_id": chain_id,
        }

    @staticmethod
    def _error_text(result: Dict[str, Any], fallback: str) -> str:
        status_code = result.get("status_code")
        body = result.get("body")
        if isinstance(body, dict):
            detail = json.dumps(body, sort_keys=True)
        elif body is None:
            detail = fallback
        else:
            detail = str(body)
        return f"HTTP {status_code}: {detail}" if status_code else detail

    def _resolve_group_id(
        self,
        command: Command,
        token: str,
        *,
        allow_acting_as: bool,
    ) -> Optional[str]:
        explicit = command.parameters.get("group_id")
        if explicit:
            return str(explicit)
        if allow_acting_as:
            acting_as = extract_claim(token, "acting_as")
            if isinstance(acting_as, str) and acting_as:
                return acting_as
        if command.user.group:
            return self.auth_service.get_user_group_id_by_name(
                token, command.user.group
            )
        return None

    def _execute_user_signing_key(self, command: Command) -> CommandResponse:
        """Select/provision one ECDSA USER key; group keys are never eligible."""
        self.log_command_start(command)
        if command.parameters.get("credential") is not None:
            return self._failure(
                command,
                "user_signing_key cannot use a named credential",
            )
        token, err = self._acquire_token_or_error(
            command, use_delegation=False
        )
        if err:
            return err
        try:
            personal = self._personal_user_provenance(
                decode_payload(token) or {}
            )
        except ValueError as exc:
            return self._failure(command, str(exc))
        user_id = personal["actor_sub"]
        custody = str(command.parameters.get("custody") or "custodial").lower()
        if custody not in {"custodial", "external"}:
            return self._failure(
                command,
                "user_signing_key custody must be custodial or external",
            )
        key_file = command.parameters.get("key_file")
        if custody == "external":
            if not isinstance(key_file, str) or not key_file.strip():
                return self._failure(
                    command,
                    "external user_signing_key requires parameters.key_file",
                )
            try:
                ensured = KeyManager(
                    self.auth_service,
                    token=token,
                    user_id=user_id,
                    debug=self.config.debug,
                ).ensure_external_key(
                    key_file.strip(),
                    key_name=str(
                        command.parameters.get("key_name")
                        or "Nested group external key (Python CLI)"
                    ),
                    # Registering with A is an explicit add_owner operation;
                    # this flag only targets the user's personal account.
                    register_with_wallet=bool(
                        command.parameters.get("register_with_personal_wallet", False)
                    ),
                )
            except Exception as exc:
                return self._failure(command, str(exc))
            if not ensured.key_id:
                return self._failure(
                    command,
                    "external key file exists but Auth has no matching USER key record",
                )
            outputs = {
                "user_id": user_id,
                "signer_key_id": ensured.key_id,
                "signer_address": ensured.address.lower(),
                "signer_custody": "external",
                "key_file": key_file.strip(),
                "newly_created": ensured.newly_created,
            }
            return self._success(
                command,
                outputs,
                f"external USER signer selected ({ensured.address})",
            )

        requested_key_id = command.parameters.get("key_id")
        eligible = []
        for key in self.auth_service.get_user_keys(token, user_id):
            if not isinstance(key, dict):
                continue
            if key.get("is_active") is not True:
                continue
            if str(key.get("provider_type", "")).lower() == "external":
                continue
            if str(key.get("key_type", "")).lower() != "signing":
                continue
            if key.get("entity_type") not in {None, "user"}:
                continue
            if key.get("entity_id") not in {None, user_id}:
                continue
            if requested_key_id and str(key.get("id")) != str(requested_key_id):
                continue
            eligible.append(key)
        eligible.sort(
            key=lambda key: (
                str(key.get("created_at") or ""),
                str(key.get("id") or ""),
            )
        )
        if not eligible:
            return self._failure(command, "no eligible custodial USER signing key found")
        key = eligible[0]
        public_key = str(key.get("public_key") or "")
        signer_address = (
            public_key.lower()
            if len(public_key) == 42 and public_key.lower().startswith("0x")
            else None
        )
        outputs = {
            "user_id": user_id,
            "signer_key_id": key.get("id"),
            "signer_address": signer_address,
            "signer_custody": "custodial",
            "key_name": key.get("key_name"),
            "key_type": key.get("key_type"),
            "provider_type": key.get("provider_type"),
        }
        return self._success(
            command, outputs, f"custodial USER signer selected for {user_id}"
        )

    def _execute_group_signing_key(self, command: Command) -> CommandResponse:
        """Look up a GROUP's signing key — for negative assertions only.

        The nested model binds the exact HUMAN key of the actor; a parent-group
        key is never an eligible signer. This exists so a suite can obtain a
        real group key id and prove `assume-owned-group` rejects it with
        `owned_group_signer_required`, rather than asserting against an
        invented UUID that would be rejected for merely not existing.
        """
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err
        group_id = self._resolve_group_id(command, token, allow_acting_as=True)
        if not group_id:
            return self._failure(
                command,
                "group_signing_key requires parameters.group_id or a group context",
            )
        result = self.auth_service._request_json_safe(
            "GET",
            f"/auth/groups/{group_id}/keypairs",
            token=token,
        )
        if not result.get("ok"):
            return self._failure(
                command,
                self._error_text(result, "unable to list group keypairs"),
            )
        keypairs = result.get("body")
        if not isinstance(keypairs, list):
            return self._failure(
                command, "group keypair response was not a list"
            )

        eligible = [
            key
            for key in keypairs
            if isinstance(key, dict)
            and key.get("is_active") is True
            and str(key.get("key_type", "")).lower() == "signing"
        ]
        eligible.sort(
            key=lambda key: (
                str(key.get("created_at") or ""),
                str(key.get("id") or ""),
            )
        )
        if not eligible:
            return self._failure(
                command, f"group {group_id} has no active signing keypair"
            )
        key = eligible[0]
        public_key = str(key.get("public_key") or "")
        outputs = {
            "group_id": group_id,
            # Deliberately NOT `signer_key_id`: this key must never be bound as
            # a nested signer, and the distinct name keeps a copy-paste from
            # silently turning a negative test into a positive one.
            "signing_key_id": key.get("id"),
            "key_type": key.get("key_type"),
            "provider_type": key.get("provider_type"),
            "public_key": public_key,
        }
        return self._success(
            command,
            outputs,
            f"group signing key selected for {group_id} (negative assertions only)",
        )

    def _execute_list_group_members(
        self, command: Command
    ) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err
        group_id = self._resolve_group_id(
            command, token, allow_acting_as=True
        )
        if not group_id:
            return self._failure(
                command,
                "list_group_members requires parameters.group_id or a group context",
            )
        result = self.auth_service._request_json_safe(
            "GET",
            f"/auth/groups/{group_id}/members",
            token=token,
        )
        if not result.get("ok"):
            return self._failure(
                command,
                self._error_text(result, "unable to list group members"),
            )
        members = result.get("body")
        if not isinstance(members, list):
            return self._failure(
                command, "group member response was not a list"
            )
        user_ids = [
            str(member["user_id"])
            for member in members
            if isinstance(member, dict) and member.get("user_id")
        ]
        outputs = {
            "group_id": group_id,
            "members_count": len(members),
            "member_user_ids": user_ids,
            "member_user_ids_csv": ",".join(user_ids),
        }
        return self._success(
            command, outputs, f"listed {len(members)} group member(s)"
        )

    @classmethod
    def _relationship_outputs(
        cls,
        body: Dict[str, Any],
        *,
        expected_parent_group_id: Optional[str] = None,
        expected_child_group_id: Optional[str] = None,
        expected_chain_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate and flatten only non-secret lifecycle fields."""
        keys = set(body)
        if keys != cls._RELATIONSHIP_ALLOWED_KEYS:
            raise ValueError("group-owner response has an invalid field set")

        relationship_id = cls._canonical_uuid(
            body.get("relationship_id"), "relationship_id"
        )
        parent_group_id = cls._canonical_uuid(
            body.get("parent_group_id"), "parent_group_id"
        )
        child_group_id = cls._canonical_uuid(
            body.get("child_group_id"), "child_group_id"
        )
        chain_id = cls._canonical_chain_id(body.get("chain_id"))
        if (
            expected_parent_group_id
            and parent_group_id != str(expected_parent_group_id)
        ):
            raise ValueError("group-owner response changed parent_group_id")
        if (
            expected_child_group_id
            and child_group_id != str(expected_child_group_id)
        ):
            raise ValueError("group-owner response changed child_group_id")
        if expected_chain_id and chain_id != str(expected_chain_id):
            raise ValueError("group-owner response changed chain_id")

        status = body.get("status")
        stage = body.get("stage")
        if status not in cls._RELATIONSHIP_STATUSES:
            raise ValueError("group-owner response has an unknown status")
        if stage not in cls._RELATIONSHIP_STAGES:
            raise ValueError("group-owner response has an unknown stage")
        if not isinstance(body.get("retry_required"), bool):
            raise ValueError("group-owner response omitted retry_required")
        expected_status, expected_retry = cls._RELATIONSHIP_STAGE_CONTRACT[stage]
        if status != expected_status or body["retry_required"] is not expected_retry:
            raise ValueError(
                "group-owner response has an inconsistent status/stage tuple"
            )

        for field in ("message_id", "operation_id"):
            value = body.get(field)
            if value is not None:
                cls._canonical_uuid(value, field)
        credential_contract = body.get("credential_contract")
        if credential_contract is not None:
            cls._canonical_address(
                credential_contract, "credential_contract"
            )
        token_id = body.get("token_id")
        if token_id is not None:
            cls._canonical_token_id(token_id, "token_id")
        error = body.get("error")
        if error is not None and not isinstance(error, str):
            raise ValueError("relationship error must be a string or null")

        return {
            "relationship_id": relationship_id,
            "parent_group_id": parent_group_id,
            "child_group_id": child_group_id,
            "chain_id": chain_id,
            "status": status,
            "stage": stage,
            "credential_contract": credential_contract,
            "token_id": token_id,
            "message_id": body.get("message_id"),
            "operation_id": body.get("operation_id"),
            "has_message_id": body.get("message_id") is not None,
            "has_operation_id": body.get("operation_id") is not None,
            "has_credential_contract": credential_contract is not None,
            "has_token_id": token_id is not None,
            "retry_required": bool(body.get("retry_required")),
            "error": body.get("error"),
        }

    def _relationship_mutation(
        self, command: Command, method: str
    ) -> CommandResponse:
        self.log_command_start(command)
        # The lifecycle endpoint is a durable identity mutation and accepts
        # only the human's personal JWT. `user.group` remains a UI/test
        # context hint and is used separately below to poll the group-owned MQ
        # message.
        if command.parameters.get("credential") is not None:
            return self._failure(
                command,
                "group-owner relationship mutations cannot use a named credential",
            )
        token, err = self._acquire_token_or_error(
            command, use_delegation=False
        )
        if err:
            return err
        try:
            personal = self._personal_user_provenance(
                decode_payload(token) or {}
            )
            child_group_id = self._canonical_uuid(
                command.parameters.get("child_group_id"), "child_group_id"
            )
            parent_group_id = self._canonical_uuid(
                command.parameters.get("parent_group_id"), "parent_group_id"
            )
            requested_chain = command.parameters.get("chain_id")
            chain_id = (
                self._canonical_chain_id(str(requested_chain))
                if requested_chain is not None
                else personal["chain_id"]
            )
        except ValueError as exc:
            return self._failure(command, str(exc))
        if child_group_id == parent_group_id:
            return self._failure(
                command,
                "a group cannot own itself",
            )
        if chain_id != personal["chain_id"]:
            return self._failure(
                command,
                "group-owner relationship chain_id must match the personal session",
            )
        result = self.auth_service._request_json_safe(
            method,
            (
                f"/auth/groups/{child_group_id}/group-owners/"
                f"{parent_group_id}"
            ),
            token=token,
            data={"chain_id": str(chain_id)},
        )
        if not result.get("ok"):
            return self._failure(
                command,
                self._error_text(result, f"{command.type} failed"),
            )
        body = result.get("body")
        if not isinstance(body, dict):
            return self._failure(
                command, f"{command.type} response was not an object"
            )
        try:
            outputs = self._relationship_outputs(
                body,
                expected_parent_group_id=str(parent_group_id),
                expected_child_group_id=str(child_group_id),
                expected_chain_id=str(chain_id),
            )
        except ValueError as exc:
            return self._failure(command, str(exc))
        poll_token = token
        if outputs.get("message_id") and self._should_wait(command):
            poll_token = self.get_token(command)
            expected_message_owner = (
                str(parent_group_id)
                if str(outputs.get("stage", "")).startswith("parent_credential_")
                else str(child_group_id)
            )
            if (
                not poll_token
                or extract_claim(poll_token, "acting_as")
                != expected_message_owner
            ):
                return self._failure(
                    command,
                    "could not mint the matching direct group credential "
                    "needed to poll the relationship message",
                )
        wait_error = self._maybe_wait_for_execution(
            command,
            poll_token,
            outputs.get("message_id"),
            outputs,
        )
        if wait_error:
            return self._failure(
                command,
                f"group ownership operation failed: {wait_error}",
            )
        return self._success(
            command,
            outputs,
            f"group ownership relationship is {outputs.get('status')} / {outputs.get('stage')}",
        )

    def _execute_establish_group_owner(
        self, command: Command
    ) -> CommandResponse:
        return self._relationship_mutation(command, "POST")

    def _execute_revoke_group_owner(
        self, command: Command
    ) -> CommandResponse:
        return self._relationship_mutation(command, "DELETE")

    def _execute_list_group_owners(
        self, command: Command
    ) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err
        child_group_id = command.parameters.get("child_group_id")
        chain_id = command.parameters.get("chain_id") or extract_claim(
            token, "default_chain_id"
        )
        if not child_group_id or not chain_id:
            return self._failure(
                command,
                "list_group_owners requires child_group_id and a chain-bound session",
            )
        result = self.auth_service._request_json_safe(
            "GET",
            f"/auth/groups/{child_group_id}/group-owners",
            token=token,
            params={"chain_id": str(chain_id)},
        )
        if not result.get("ok"):
            return self._failure(
                command,
                self._error_text(result, "list_group_owners failed"),
            )
        body = result.get("body")
        if (
            not isinstance(body, dict)
            or set(body) != {"child_group_id", "chain_id", "relationships"}
            or not isinstance(body.get("relationships"), list)
            or body.get("child_group_id") != str(child_group_id)
            or body.get("chain_id") != str(chain_id)
        ):
            return self._failure(
                command, "list_group_owners response omitted relationships"
            )
        relationships = []
        try:
            for item in body["relationships"]:
                if not isinstance(item, dict):
                    raise ValueError(
                        "list_group_owners contained a non-object relationship"
                    )
                relationships.append(
                    self._relationship_outputs(
                        item,
                        expected_child_group_id=str(child_group_id),
                        expected_chain_id=str(chain_id),
                    )
                )
        except ValueError as exc:
            return self._failure(command, str(exc))
        outputs = {
            "child_group_id": body.get("child_group_id"),
            "chain_id": body.get("chain_id"),
            "relationships_count": len(relationships),
            "parent_group_ids": [
                str(item["parent_group_id"])
                for item in relationships
                if item.get("parent_group_id")
            ],
            "parent_group_ids_csv": ",".join(
                str(item["parent_group_id"])
                for item in relationships
                if item.get("parent_group_id")
            ),
            "statuses_csv": ",".join(
                str(item.get("status") or "") for item in relationships
            ),
        }
        return self._success(
            command,
            outputs,
            f"listed {len(relationships)} group-owner relationship(s)",
        )

    def _execute_start_signature_listener(
        self, command: Command
    ) -> CommandResponse:
        self.log_command_start(command)
        if not self.token_manager:
            return self._failure(
                command, "start_signature_listener requires TokenManager"
            )
        credential = command.parameters.get("credential")
        key_file = command.parameters.get("key_file")
        name = str(command.parameters.get("listener_name") or command.name)
        if not key_file:
            return self._failure(
                command,
                "start_signature_listener requires key_file",
            )
        if name in self._signature_listeners:
            return self._failure(command, f"signature listener already exists: {name}")
        if credential:
            token = self.token_manager.get_named_credential(str(credential))
            if not token:
                return self._failure(
                    command, f"named credential unavailable: {credential}"
                )
            token_supplier = self.token_manager.named_credential_supplier(
                str(credential)
            )
        else:
            token, err = self._acquire_token_or_error(command)
            if err:
                return err
            token_supplier = token
        claims = decode_payload(token) or {}
        expected_binding = None
        if credential:
            try:
                provenance = self._owned_group_provenance(claims)
            except ValueError as exc:
                return self._failure(command, str(exc))
            if provenance["signer_custody"] != "external":
                return self._failure(
                    command,
                    "named signature listeners require an external "
                    "nft_membership ECDSA child",
                )
            signer_address = provenance["signer_address"]
            expected_binding = {
                "actor_sub": provenance["actor_sub"],
                "acting_as": provenance["acting_as"],
                "delegation_token_id": provenance["delegation_token_id"],
                "delegation_path": provenance["delegation_path"],
                "authority_source": "nft_membership",
                "membership_edge": provenance["membership_edge"],
                "signer_key_id": provenance["signer_key_id"],
                "signer_address": signer_address,
                "signer_scheme": "account_ecdsa65_v1",
                "signer_custody": "external",
            }
        else:
            if (
                not claims.get("acting_as")
                or claims.get("delegation_path") is not None
                or claims.get("authority_source") is not None
                or claims.get("authority_key_id") is not None
                or claims.get("membership_edge") is not None
            ):
                return self._failure(
                    command,
                    "direct signature listeners require a direct group delegation",
                )
            signer_address = command.parameters.get("signer_address")
            if not signer_address:
                return self._failure(
                    command,
                    "direct signature listeners require signer_address",
                )
        message_owner = claims.get("acting_as")
        if not message_owner or not signer_address:
            return self._failure(
                command, "signature credential omitted signer/message-owner binding"
            )
        try:
            signer = FileBackedSigner(
                str(key_file), expected_address=str(signer_address)
            )
            listener = MessageSignatureListener(
                self.payments_service,
                str(message_owner),
                token_supplier,
                sign_callback=signer,
                interval=float(command.parameters.get("interval", 1.0)),
                expected_authorization_binding=expected_binding,
                debug=self.config.debug,
            )
            listener.start()
            self._signature_listeners[name] = listener
        except Exception as exc:
            return self._failure(command, str(exc))
        return self._success(
            command,
            {
                "listener_name": name,
                "message_owner": message_owner,
                "signer_key_id": claims.get("signer_key_id")
                or command.parameters.get("signer_key_id"),
                "signer_address": str(signer_address).lower(),
            },
            f"external signer listener '{name}' started",
        )

    def _execute_stop_signature_listener(
        self, command: Command
    ) -> CommandResponse:
        self.log_command_start(command)
        name = str(
            command.parameters.get("listener_name")
            or command.parameters.get("name")
            or ""
        )
        listener = self._signature_listeners.pop(name, None)
        if not listener:
            return self._failure(command, f"signature listener not found: {name}")
        try:
            listener.stop()
        except RuntimeError as exc:
            # Retain the handle so a caller can retry the bounded join and
            # inspect final counters once the in-flight poll exits.
            self._signature_listeners[name] = listener
            return self._failure(command, str(exc))
        outputs = {
            "listener_name": name,
            "signed_count": listener.signed_count,
            "errored_count": listener.errored_count,
        }
        if listener.errored_count:
            return self._failure(
                command,
                f"signature listener '{name}' encountered {listener.errored_count} error(s)",
            )
        return self._success(
            command,
            outputs,
            f"signature listener '{name}' signed {listener.signed_count} message(s)",
        )

    def _execute_discover_owned_groups(
        self, command: Command
    ) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err
        try:
            parent = self._direct_parent_provenance(
                decode_payload(token) or {}
            )
        except ValueError as exc:
            return self._failure(command, str(exc))
        source_group_id = self._resolve_group_id(
            command, token, allow_acting_as=True
        )
        if not source_group_id:
            return self._failure(
                command,
                "discover_owned_groups requires parameters.group_id or a group context",
            )
        if str(source_group_id) != parent["acting_as"]:
            return self._failure(
                command,
                "owned-group discovery source does not match the direct parent JWT",
            )

        result = self.auth_service._request_json_safe(
            "GET",
            f"/auth/groups/{source_group_id}/owned-groups",
            token=token,
        )
        if not result.get("ok"):
            return self._failure(
                command,
                self._error_text(result, "owned-group discovery failed"),
            )
        body = result.get("body")
        if (
            not isinstance(body, dict)
            or set(body)
            != {"source_group_id", "chain_id", "owned_groups"}
            or body.get("source_group_id") != parent["acting_as"]
            or body.get("chain_id") != parent["chain_id"]
            or not isinstance(body.get("owned_groups"), list)
        ):
            return self._failure(
                command, "owned-group discovery returned an inconsistent envelope"
            )
        owned_groups = body["owned_groups"]

        group_ids = []
        group_names = []
        relationship_ids = []
        credential_contracts = []
        token_ids = []
        try:
            for item in owned_groups:
                if (
                    not isinstance(item, dict)
                    or set(item)
                    != {
                        "group",
                        "account_address",
                        "relationship_id",
                        "credential_contract",
                        "token_id",
                        "added_at",
                    }
                    or not isinstance(item.get("group"), dict)
                ):
                    raise ValueError(
                        "owned-group discovery contained an invalid projection"
                    )
                group = item["group"]
                group_id = self._canonical_uuid(
                    group.get("id"), "owned group.id"
                )
                account_address = self._canonical_address(
                    item.get("account_address"),
                    "owned group.account_address",
                )
                relationship_id = self._canonical_uuid(
                    item.get("relationship_id"),
                    "owned group.relationship_id",
                )
                credential_contract = self._canonical_address(
                    item.get("credential_contract"),
                    "owned group.credential_contract",
                )
                token_id = self._canonical_token_id(
                    item.get("token_id"), "owned group.token_id"
                )
                added_at = item.get("added_at")
                if not isinstance(added_at, str):
                    raise ValueError("owned group.added_at must be a timestamp")
                try:
                    datetime.fromisoformat(added_at.replace("Z", "+00:00"))
                except ValueError as exc:
                    raise ValueError(
                        "owned group.added_at must be an RFC3339 timestamp"
                    ) from exc
                if (
                    not isinstance(group.get("name"), str)
                    or not group["name"].strip()
                    or group.get("role") is not None
                    or group.get("is_active") is not True
                    or group.get("account_address") != account_address
                    or group.get("account_chain_id") != parent["chain_id"]
                ):
                    raise ValueError(
                        "owned-group discovery projection changed group identity"
                    )
                group_ids.append(group_id)
                group_names.append(group["name"])
                relationship_ids.append(relationship_id)
                credential_contracts.append(credential_contract)
                token_ids.append(token_id)
        except ValueError as exc:
            return self._failure(command, str(exc))

        outputs = {
            "source_group_id": parent["acting_as"],
            "chain_id": parent["chain_id"],
            "owned_groups_count": len(owned_groups),
            "owned_group_ids": group_ids,
            "owned_group_ids_csv": ",".join(group_ids),
            "owned_group_names": group_names,
            "owned_group_names_csv": ",".join(group_names),
            "relationship_ids": relationship_ids,
            "credential_contracts": credential_contracts,
            "token_ids": token_ids,
        }
        return self._success(
            command,
            outputs,
            f"discovered {len(owned_groups)} owned group(s)",
        )

    def _execute_assume_owned_group(
        self, command: Command
    ) -> CommandResponse:
        self.log_command_start(command)
        if not self.token_manager:
            return self._failure(
                command,
                "assume_owned_group requires the shared TokenManager",
            )
        token, err = self._acquire_token_or_error(command)
        if err:
            return err

        try:
            parent = self._direct_parent_provenance(
                decode_payload(token) or {}
            )
            target_group_id = self._canonical_uuid(
                command.parameters.get("group_id"), "group_id"
            )
            signer_key_id = self._canonical_uuid(
                command.parameters.get("signer_key_id"), "signer_key_id"
            )
        except ValueError as exc:
            return self._failure(command, str(exc))
        scope = command.parameters.get("delegation_scope")
        expiry_seconds = command.parameters.get("expiry_seconds", 600)
        if (
            not isinstance(scope, list)
            or not scope
            or any(
                not isinstance(item, str)
                or not item
                or item.strip() != item
                for item in scope
            )
            or len(set(scope)) != len(scope)
        ):
            return self._failure(
                command,
                "assume_owned_group requires a non-empty unique delegation_scope list",
            )
        # No bound here beyond positivity, on purpose. Auth CLAMPS the request
        # (`requested.clamp(60, OWNED_GROUP_MAX_ACCESS_TTL_SECS)`) rather than
        # rejecting it, so BOTH 60 and 900 are properties of the RESPONSE, not
        # constraints on the request. Bounding the request here would make the
        # clamp itself untestable — a suite could never prove that asking for
        # an hour yields 900s, nor that asking for 1s yields 60s. The response
        # check below enforces the clamp from the other side.
        if (
            not isinstance(expiry_seconds, int)
            or isinstance(expiry_seconds, bool)
            or expiry_seconds < 1
        ):
            return self._failure(
                command,
                "assume_owned_group expiry_seconds must be a positive integer",
            )
        asserted_chain = command.parameters.get("chain_id")
        try:
            chain_id = (
                self._canonical_chain_id(str(asserted_chain))
                if asserted_chain is not None
                else parent["chain_id"]
            )
        except ValueError as exc:
            return self._failure(command, str(exc))
        if chain_id != parent["chain_id"]:
            return self._failure(
                command,
                "assume_owned_group chain_id does not match the parent JWT",
            )
        if target_group_id == parent["acting_as"]:
            return self._failure(
                command, "a group cannot assume itself as an owned child"
            )

        payload: Dict[str, Any] = {
            "group_id": target_group_id,
            "delegation_scope": scope,
            "expiry_seconds": expiry_seconds,
            "signer_key_id": signer_key_id,
        }
        if asserted_chain is not None:
            payload["chain_id"] = chain_id

        result = self.auth_service._request_json_safe(
            "POST",
            "/auth/delegation/jwt/assume-owned-group",
            token=token,
            data=payload,
        )
        if not result.get("ok"):
            return self._failure(
                command,
                self._error_text(result, "owned-group exchange failed"),
            )
        body = result.get("body")
        if not isinstance(body, dict):
            return self._failure(
                command, "owned-group exchange response was not an object"
            )
        child = body.get("delegation_jwt")
        if not isinstance(child, str) or not child:
            return self._failure(
                command, "owned-group exchange omitted delegation_jwt"
            )
        expected_response_keys = {
            "delegation_jwt",
            "group_id",
            "delegation_scope",
            "expiry_seconds",
            "chain_id",
            "delegation_path",
            "authority_source",
            "membership_edge",
            "signer_key_id",
            "signer_address",
            "signer_scheme",
            "signer_custody",
        }
        if set(body) != expected_response_keys:
            return self._failure(
                command,
                "owned-group exchange returned an invalid field set",
            )
        claims = decode_payload(child) or {}
        try:
            provenance = self._owned_group_provenance(claims)
        except ValueError as exc:
            return self._failure(command, str(exc))
        response_scope = body.get("delegation_scope")
        response_path = body.get("delegation_path")
        response_edge = body.get("membership_edge")
        response_chain = body.get("chain_id")
        signer_address = body.get("signer_address")
        signer_custody = body.get("signer_custody")
        expiry = body.get("expiry_seconds")
        iat = claims.get("iat")
        exp = claims.get("exp")
        if (
            body.get("group_id") != target_group_id
            or not isinstance(response_scope, list)
            or not response_scope
            or any(
                not isinstance(item, str)
                or not item
                or item.strip() != item
                for item in response_scope
            )
            or len(set(response_scope)) != len(response_scope)
            or response_scope != claims.get("delegation_scope")
            or any(item not in scope for item in response_scope)
            or response_path
            != [parent["acting_as"], target_group_id]
            or response_path != provenance["delegation_path"]
            or body.get("authority_source") != "nft_membership"
            or body.get("signer_key_id") != signer_key_id
            or provenance["signer_key_id"] != signer_key_id
            or body.get("signer_scheme") != "account_ecdsa65_v1"
            or provenance["signer_scheme"] != "account_ecdsa65_v1"
            or signer_custody not in {"custodial", "external"}
            or provenance["signer_custody"] != signer_custody
            or signer_address != provenance["signer_address"]
            or response_chain != chain_id
            or provenance["chain_id"] != chain_id
            or provenance["actor_sub"] != parent["actor_sub"]
            or not isinstance(expiry, int)
            or isinstance(expiry, bool)
            or expiry < 1
            or expiry > self._OWNED_GROUP_TTL_CEILING_SECS
            # "No longer than I asked for" — but only above the floor. Auth
            # clamps a sub-floor request UP to 60s rather than rejecting it, so
            # asking for 1s correctly yields 60s. Comparing against the bare
            # request would reject the documented clamp.
            or expiry > max(expiry_seconds, self._OWNED_GROUP_TTL_FLOOR_SECS)
            or response_edge != provenance["membership_edge"]
            or provenance["acting_as"] != target_group_id
            or not isinstance(iat, int)
            or isinstance(iat, bool)
            or not isinstance(exp, int)
            or isinstance(exp, bool)
            or iat <= 0
            or exp <= iat
            or exp - iat != expiry
            or exp > parent["exp"]
        ):
            return self._failure(
                command,
                "owned-group exchange returned inconsistent NFT/signer provenance",
            )

        credential = str(
            command.parameters.get("credential_name") or command.name
        )
        try:
            self.token_manager.register_named_credential(credential, child)
        except ValueError as exc:
            return self._failure(command, str(exc))

        scope_claim = claims.get("delegation_scope")
        if not isinstance(scope_claim, list):
            scope_claim = body.get("delegation_scope") or []
        path = claims.get("delegation_path")
        if not isinstance(path, list):
            path = body.get("delegation_path") or []

        outputs = {
            # Safe opaque handle only. Never store `child`.
            "credential": credential,
            "group_id": body.get("group_id"),
            "acting_as": claims.get("acting_as"),
            "delegation_scope": scope_claim,
            "delegation_scope_csv": ",".join(map(str, scope_claim)),
            "expiry_seconds": body.get("expiry_seconds"),
            "expires_at": claims.get("exp"),
            "chain_id": body.get("chain_id"),
            "delegation_path": path,
            "delegation_path_csv": ",".join(map(str, path)),
            "authority_source": claims.get("authority_source")
            or body.get("authority_source"),
            "authority_key_id": claims.get("authority_key_id"),
            "has_authority_key_id": claims.get("authority_key_id") is not None
            or body.get("authority_key_id") is not None,
            "signer_key_id": claims.get("signer_key_id")
            or body.get("signer_key_id"),
            "signer_address": claims.get("signer_address")
            or body.get("signer_address"),
            "signer_scheme": claims.get("signer_scheme")
            or body.get("signer_scheme"),
            "signer_custody": claims.get("signer_custody")
            or body.get("signer_custody"),
            "membership_edge": claims.get("membership_edge")
            or body.get("membership_edge"),
            "membership_parent_group_id": (
                claims.get("membership_edge") or {}
            ).get("parent_group_id"),
            "membership_child_group_id": (
                claims.get("membership_edge") or {}
            ).get("child_group_id"),
            "membership_chain_id": (
                claims.get("membership_edge") or {}
            ).get("chain_id"),
            "membership_credential_contract": (
                claims.get("membership_edge") or {}
            ).get("credential_contract"),
            "membership_token_id": (
                claims.get("membership_edge") or {}
            ).get("token_id"),
            "has_refresh_token": bool(
                body.get("refresh_token") or body.get("refreshToken")
            ),
        }
        return self._success(
            command,
            outputs,
            f"owned-group credential retained as '{credential}'",
        )

    def _execute_validate_credential(
        self, command: Command
    ) -> CommandResponse:
        """Hit live validation, including after local hard expiry."""
        self.log_command_start(command)
        if not self.token_manager:
            return self._failure(
                command,
                "validate_credential requires the shared TokenManager",
            )
        credential = command.parameters.get("credential")
        if not credential:
            return self._failure(
                command, "validate_credential requires credential"
            )
        token = self.token_manager.get_named_credential(
            str(credential), allow_expired=True
        )
        if not token:
            return self._failure(
                command, f"named credential not found: {credential}"
            )
        result = self.auth_service._request_json_safe(
            "GET", "/protected/jwt", token=token
        )
        if not result.get("ok"):
            return self._failure(
                command,
                self._error_text(result, "credential validation failed"),
            )
        body = result.get("body")
        if not isinstance(body, dict):
            return self._failure(
                command, "protected JWT response was not an object"
            )
        scope = body.get("delegation_scope") or []
        path = body.get("delegation_path") or []
        outputs = {
            "user_id": body.get("user_id"),
            "acting_as": body.get("acting_as"),
            "delegation_scope": scope,
            "delegation_scope_csv": ",".join(map(str, scope)),
            "delegation_path": path,
            "delegation_path_csv": ",".join(map(str, path)),
            "authority_source": body.get("authority_source"),
            "authority_key_id": body.get("authority_key_id"),
            "membership_edge": body.get("membership_edge"),
            "signer_key_id": body.get("signer_key_id"),
            "signer_address": body.get("signer_address"),
            "signer_scheme": body.get("signer_scheme"),
            "signer_custody": body.get("signer_custody"),
            "group_account_address": body.get("group_account_address"),
            "default_wallet_id": body.get("default_wallet_id"),
            "default_chain_id": body.get("default_chain_id"),
        }
        return self._success(command, outputs, "named credential is valid")

    def _execute_service_request(
        self, command: Command
    ) -> CommandResponse:
        """
        Execute a test-only REST call without storing response secrets.

        It is intentionally service-limited and relative-path-only. A denial
        returns a normal failed CommandResponse, allowing YAML's
        `expect_failure`/`expect_error` contract to assert the boundary.
        """
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command)
        if err:
            return err
        service_name = str(
            command.parameters.get("service") or "auth"
        ).lower()
        service = {
            "auth": self.auth_service,
            "payments": self.payments_service,
        }.get(service_name)
        if service is None:
            return self._failure(
                command, f"unsupported service: {service_name}"
            )
        method = str(command.parameters.get("method") or "GET").upper()
        path = command.parameters.get("path")
        if not isinstance(path, str) or not path.startswith("/"):
            return self._failure(
                command, "service_request path must start with '/'"
            )
        body = command.parameters.get("body")
        if body is not None and not isinstance(body, dict):
            return self._failure(
                command, "service_request body must be an object"
            )
        params = command.parameters.get("query")
        if params is not None and not isinstance(params, dict):
            return self._failure(
                command, "service_request query must be an object"
            )

        result = service._request_json_safe(
            method,
            path,
            token=token,
            data=body,
            params=params,
        )
        if not result.get("ok"):
            return self._failure(
                command,
                self._error_text(result, f"{service_name} request failed"),
            )

        # Do not echo/store the response body: this command tests sensitive
        # denial surfaces such as signing and API-key issuance. If a boundary
        # regresses, `expect_failure` will flag the unexpected success without
        # leaking the newly returned signature/key.
        return self._success(
            command,
            {
                "service": service_name,
                "method": method,
                "path": path,
                "status_code": result.get("status_code"),
            },
            f"{method} {service_name}:{path} returned "
            f"{result.get('status_code')}",
        )
