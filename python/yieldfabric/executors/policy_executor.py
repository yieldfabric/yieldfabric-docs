"""
Data-policy executor — register / approve / execute data-driven policies on
group ConfidentialAccounts (the `pipelineGate` GraphQL namespace), plus a
`whoami` helper that resolves the account addresses a policy needs.

The feature under test: a RESTRICTED group member (`policymember` role) runs a
group operation under a data policy via `executeUnderPolicy`. The relay→I→G
chain is: G = the group account (the policy account), I = the member's own
account (registered in the policy's `executors_address`). The group's owner is
the APPROVER (in `required_signers`) and signs the policy's reusable M-of-N
digest ONCE; the member EXECUTES but is deliberately absent from the caller set,
so it can never approve. Mirrors the contract's own restricted-member test
(yieldfabric-smart-contracts/test/ConfidentialAccountPolicy.test.ts).

Command types:

    whoami                → resolve & store account_address / group_account_address
                            / default_wallet_id / sub for a user (optionally acting
                            as a group), so the suite can thread addresses by name.
    add_data_policy       → pipelineGate.addDataPolicy   (MQ; register a policy on G)
    approve_data_policy   → pipelineGate.approveDataPolicy (record one reusable
                            approval signature, obtained from the auth REST sign API)
    execute_under_policy  → pipelineGate.executeUnderPolicy (MQ; run a bound op)
    remove_data_policy    → pipelineGate.removeDataPolicy  (MQ; on-chain revocation —
                            deletes the policy struct on G; the settle hook flips the
                            projection row to revoked + deletes the approval artifact.
                            Irreversible for that registration; the freed id may be
                            re-registered)
    data_policies         → pipelineGate.dataPolicies      (read, for asserts;
                            `include_revoked: true` also returns revoked rows, and an
                            optional `policy_id` surfaces `found` / `revoked` outputs
                            for that one policy)
    data_policy_approval  → pipelineGate.dataPolicyApproval (read, for asserts)

Signing note: `approve_data_policy` never touches a private key. It fetches the
policy's registered digest, computes the EIP-191 message-hash for it
(`crypto.eip191_message_hash`, a library call — not a signature), asks the auth
REST API to sign that digest with the approver's server-custodied key
(`POST /key-operations/vault/sign`), and submits the returned signature.
"""

import json
from typing import Any, Dict, List, Optional

from .base import BaseExecutor
from ..models import Command, CommandResponse
from ..utils.crypto import eip191_message_hash, recover_eip191_address
from ..utils.graphql import DataPolicyGraphQL
from ..utils.jwt import decode_payload, get_sub
from ..utils.validators import is_provided


def _camel(snake: str) -> str:
    """`token_id` → `tokenId`. Idempotent for already-camelCase keys."""
    parts = str(snake).split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _camel_keys(d: Dict[str, Any]) -> Dict[str, Any]:
    """camelCase the keys of a flat dict (values untouched)."""
    return {_camel(k): v for k, v in d.items()}


class PolicyExecutor(BaseExecutor):
    """Executor for data-driven policies on group accounts."""

    def execute(self, command: Command) -> CommandResponse:
        command_type = command.type.lower()
        dispatch = {
            "whoami": self._execute_whoami,
            "add_data_policy": self._execute_add_data_policy,
            "approve_data_policy": self._execute_approve_data_policy,
            "execute_under_policy": self._execute_execute_under_policy,
            "remove_data_policy": self._execute_remove_data_policy,
            "commit_oracle_document": self._execute_commit_oracle_document,
            "sign_oracle_document": self._execute_sign_oracle_document,
            "data_policies": self._execute_data_policies,
            "data_policy_approval": self._execute_data_policy_approval,
        }
        handler = dispatch.get(command_type)
        if handler is None:
            return CommandResponse.error_response(
                command.name, command.type,
                [f"Unknown policy command type: {command_type}"],
            )
        return handler(command)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _claim(self, token: str, *names: str) -> Optional[str]:
        """First non-empty claim from the (unverified) JWT payload."""
        payload = decode_payload(token) or {}
        for n in names:
            v = payload.get(n)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    def _graphql(self, query: str, variables: dict, token: str):
        """Post a GraphQL operation (mutation or query) to payments /graphql."""
        return self.payments_service.graphql_mutation(query, variables, token)

    # ------------------------------------------------------------------
    # whoami — resolve the addresses a policy is wired from.
    # ------------------------------------------------------------------

    def _execute_whoami(self, command: Command) -> CommandResponse:
        """
        Log in (as the user, or acting as `user.group`) and surface the
        identity claims downstream policy commands need:

            <cmd>.account_address         the caller's own smart-account address
                                          (the unit registered as a policy
                                          approver/executor; = on-chain `I`)
            <cmd>.group_account_address   the acting group's account (= `G`,
                                          the policy account) — only when a
                                          group was requested
            <cmd>.default_wallet_id       the acting wallet id (the group's when
                                          delegating) — the `walletId` the policy
                                          off-chain projection lists under
            <cmd>.sub / <cmd>.user_id     the user UUID (the sign API `contact_id`)
        """
        self.log_command_start(command)
        # use_delegation honours user.group: with a group we get a delegation
        # JWT carrying group_account_address; without, a plain self token.
        token, err = self._acquire_token_or_error(
            command, use_delegation=bool(command.user.group)
        )
        if err:
            return err

        account_address = self._claim(token, "account_address")
        group_account_address = self._claim(token, "group_account_address")
        default_wallet_id = self._claim(token, "default_wallet_id")
        sub = get_sub(token)

        # Resolve the acting group's UUID whenever a group context is given —
        # callers that mint a group delegation (e.g. loan-collect arming) need it.
        # Also doubles as the fallback for a group account address the delegation
        # claim didn't carry.
        group_id = None
        if command.user.group:
            group_id = self.auth_service.get_user_group_id_by_name(token, command.user.group)
            if group_id and not group_account_address:
                info = self.auth_service.group_account_info(token, group_id)
                group_account_address = info.get("account_address") or None
                default_wallet_id = default_wallet_id or info.get("wallet_id")

        outputs = {
            "account_address": account_address,
            "group_account_address": group_account_address,
            # The acting group's UUID (for callers that mint a group delegation).
            "group_id": group_id,
            # Lowercased variants for case-robust on-chain address comparisons
            # (on-chain reads come back in mixed case).
            "account_address_lc": (account_address or "").lower() or None,
            "group_account_address_lc": (group_account_address or "").lower() or None,
            "default_wallet_id": default_wallet_id,
            "sub": sub,
            "user_id": sub,
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ whoami {command.user.id}"
            + (f" as {command.user.group}" if command.user.group else "")
            + f": account={account_address} group_account={group_account_address}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # add_data_policy — register a policy on the group account (MQ).
    # ------------------------------------------------------------------

    def _execute_add_data_policy(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        # Registering a policy requires acting AS the group (require_group_policy_account).
        token, err = self._acquire_token_or_error(command, use_delegation=True)
        if err:
            return err

        p = command.parameters
        account = p.get("account") or self._claim(token, "group_account_address")
        wallet_id = p.get("wallet_id") or self._claim(token, "default_wallet_id")
        if not account:
            return self._fail(
                command,
                "add_data_policy requires `account` (the group account) — "
                "none provided and the JWT carries no group_account_address; submit while "
                "acting as the group (set user.group).",
            )

        policy_id = p.get("policy_id")
        if not policy_id:
            return self._fail(command, "add_data_policy requires `policy_id`")

        required_signers = p.get("required_signers") or []
        allowed_operations = p.get("allowed_operations") or []
        requirements = p.get("requirements") or []
        if not required_signers:
            return self._fail(command, "add_data_policy requires at least one `required_signers` entry")
        if not allowed_operations:
            return self._fail(command, "add_data_policy requires at least one `allowed_operations` entry")
        if not requirements:
            return self._fail(command, "add_data_policy requires at least one `requirements` entry")

        gql_input: Dict[str, Any] = {
            "account": account,
            "policyId": str(policy_id),
            "expiry": str(p.get("expiry", "0")),
            "maxUse": str(p.get("max_use", "1")),
            "minSignatories": int(p.get("min_signatories", 1)),
            "requiredSigners": list(required_signers),
            "allowedOperations": list(allowed_operations),
            "requirements": [_camel_keys(r) for r in requirements],
        }
        if wallet_id:
            gql_input["walletId"] = wallet_id
        for key, field in (
            ("start", "start"),
            ("policy_type", "policyType"),
        ):
            if is_provided(p.get(key)):
                gql_input[field] = str(p.get(key))
        if p.get("caller_ids"):
            gql_input["callerIds"] = [str(c) for c in p.get("caller_ids")]
        if p.get("executor_accounts"):
            gql_input["executorAccounts"] = list(p.get("executor_accounts"))
        # #B NFT-holder executor: the per-executor token id, parallel to executor_accounts.
        # Omitting this leaves executors_id defaulting to "0" server-side, which makes the
        # slot an ADDRESS executor (the collection address) rather than an NFT slot — so the
        # off-chain ownerOf gate (valid_nft_executor_slots) finds nothing and denies. Must be
        # threaded for the agency-NFT model to work.
        if p.get("executor_ids"):
            gql_input["executorIds"] = [str(e) for e in p.get("executor_ids")]
        if p.get("required_signer_entity_ids"):
            gql_input["requiredSignerEntityIds"] = list(p.get("required_signer_entity_ids"))
        if p.get("amount_bounds"):
            gql_input["amountBounds"] = [_camel_keys(b) for b in p.get("amount_bounds")]

        self.log_parameters({
            "account": account,
            "policy_id": policy_id,
            "min_signatories": gql_input["minSignatories"],
            "required_signers": required_signers,
            "executor_accounts": p.get("executor_accounts"),
            "executor_ids": p.get("executor_ids"),
            "allowed_operations": allowed_operations,
            "max_use": gql_input["maxUse"],
            "expiry": gql_input["expiry"],
        })

        response = self._graphql(DataPolicyGraphQL.ADD_DATA_POLICY, {"input": gql_input}, token)
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="AddDataPolicy")

        data = response.get_data("pipelineGate.addDataPolicy", {}) or {}
        if not data.get("success"):
            return self._finalize_business_error(
                command, data.get("message", "addDataPolicy not successful"),
                operation_name="AddDataPolicy",
            )

        outputs = {
            "policy_id": data.get("policyId") or str(policy_id),
            "account": account,
            "message": data.get("message"),
            "message_id": data.get("messageId"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message=f"Data policy {outputs['policy_id']} registration submitted",
        )

    # ------------------------------------------------------------------
    # approve_data_policy — record one reusable M-of-N approval signature.
    # The signature comes from the auth REST sign API (no local key).
    # ------------------------------------------------------------------

    def _execute_approve_data_policy(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        # Approve AS the approver themselves: the off-chain eligibility gate matches
        # the approver's own account_address against the policy's caller set, and the
        # signature must recover to one of the approver's own owner EOAs.
        token, err = self._acquire_token_or_error(command, use_delegation=False)
        if err:
            return err

        p = command.parameters
        account = p.get("account")
        policy_id = p.get("policy_id")
        if not account or not policy_id:
            return self._fail(command, "approve_data_policy requires `account` and `policy_id`")

        # 1. Fetch the operation-independent digest the approver must sign.
        approval = self._graphql(
            DataPolicyGraphQL.DATA_POLICY_APPROVAL,
            {"account": account, "policyId": str(policy_id)},
            token,
        )
        if not approval.success:
            return self._finalize_graphql_error(command, approval, operation_name="GetDataPolicyApproval")
        info = approval.get_data("pipelineGate.dataPolicyApproval", {}) or {}
        registered_digest = info.get("registeredDigest")
        if not registered_digest:
            return self._fail(command, "approve_data_policy: could not resolve the policy's registered digest")

        # 2. Ask the auth REST API to sign the EIP-191 message-hash of the digest
        #    with the approver's server-custodied key. `contact_id` = the approver.
        contact_id = p.get("signer_contact_id") or get_sub(token)
        if not contact_id:
            return self._fail(command, "approve_data_policy: could not resolve the approver's id for signing")
        try:
            eip191_hash = eip191_message_hash(registered_digest)
        except Exception as e:  # pragma: no cover — bad digest is a backend bug
            return self._fail(command, f"approve_data_policy: failed to prepare digest: {e}")

        self.log_parameters({
            "account": account,
            "policy_id": policy_id,
            "registered_digest": registered_digest,
            "signer_contact_id": contact_id,
        })

        sign = self.auth_service.sign_vault(token, contact_id=contact_id, data=eip191_hash, data_format="hex")
        signature = sign.get("result") if isinstance(sign, dict) else None
        if not signature:
            return self._fail(
                command,
                f"approve_data_policy: vault/sign returned no signature ({sign.get('message') or sign})",
            )

        # 3. Submit the signature; the backend recovers the signer and tallies the M-of-N.
        response = self._graphql(
            DataPolicyGraphQL.APPROVE_DATA_POLICY,
            {"input": {"account": account, "policyId": str(policy_id), "signature": signature}},
            token,
        )
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="ApproveDataPolicy")
        data = response.get_data("pipelineGate.approveDataPolicy", {}) or {}
        if not data.get("success"):
            return self._finalize_business_error(
                command, data.get("message", "approveDataPolicy not successful"),
                operation_name="ApproveDataPolicy",
            )

        outputs = {
            "account": account,
            "policy_id": str(policy_id),
            "signer": data.get("signer"),
            "collected": data.get("collected"),
            "approved": data.get("approved"),
            "message": data.get("message"),
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ approve_data_policy {policy_id}: "
            f"collected={outputs['collected']} approved={outputs['approved']} signer={outputs['signer']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------
    # execute_under_policy — run a bound op under the approved policy (MQ).
    # ------------------------------------------------------------------

    def _execute_execute_under_policy(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        # Executing requires acting AS the group (require_group_policy_account); the
        # PolicyMember's delegation is force-scoped to [PolicyExecution, CryptoOperations].
        token, err = self._acquire_token_or_error(command, use_delegation=True)
        if err:
            return err

        p = command.parameters
        account = p.get("account") or self._claim(token, "group_account_address")
        policy_id = p.get("policy_id")
        operation_type = p.get("operation_type")
        operation_data = p.get("operation_data")
        if not account:
            return self._fail(
                command,
                "execute_under_policy requires `account` (the group account) — "
                "submit while acting as the group (set user.group).",
            )
        if not policy_id or not operation_type:
            return self._fail(command, "execute_under_policy requires `policy_id` and `operation_type`")
        if not isinstance(operation_data, dict):
            return self._fail(command, "execute_under_policy requires `operation_data` (a mapping)")

        self.log_parameters({
            "account": account,
            "policy_id": policy_id,
            "operation_type": operation_type,
            "operation_data": operation_data,
        })

        gql_input = {
            "account": account,
            "policyId": str(policy_id),
            "operationType": str(operation_type),
            # The backend takes operationData as a JSON string (the inner op's Data shape).
            "operationData": json.dumps(operation_data),
        }
        response = self._graphql(DataPolicyGraphQL.EXECUTE_UNDER_POLICY, {"input": gql_input}, token)
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="ExecuteUnderPolicy")
        data = response.get_data("pipelineGate.executeUnderPolicy", {}) or {}
        if not data.get("success"):
            return self._finalize_business_error(
                command, data.get("message", "executeUnderPolicy not successful"),
                operation_name="ExecuteUnderPolicy",
            )

        outputs = {
            "account": account,
            "policy_id": str(policy_id),
            "operation_type": str(operation_type),
            "collected": data.get("collected"),
            "approved": data.get("approved"),
            "message": data.get("message"),
            "message_id": data.get("messageId"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message=f"executeUnderPolicy {policy_id} ({operation_type}) submitted",
        )

    # ------------------------------------------------------------------
    # remove_data_policy — on-chain revocation (MQ). Deletes the policy
    # struct on G (DataPolicyLib.removePolicy via the relay self-call);
    # on settle the backend flips the projection row to revoked and
    # deletes the reusable approval artifact. A revoked policy can never
    # be approved or executed again — the freed id may be re-registered.
    # ------------------------------------------------------------------

    def _execute_remove_data_policy(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        # Retiring requires acting AS the group (require_group_policy_account) —
        # the same guard as add/execute. Without `user.group` this falls back to a
        # plain self token, which the resolver rejects (group-accounts-only).
        token, err = self._acquire_token_or_error(command, use_delegation=True)
        if err:
            return err

        p = command.parameters
        account = p.get("account") or self._claim(token, "group_account_address")
        wallet_id = p.get("wallet_id") or self._claim(token, "default_wallet_id")
        policy_id = p.get("policy_id")
        if not account:
            return self._fail(
                command,
                "remove_data_policy requires `account` (the group account) — "
                "none provided and the JWT carries no group_account_address; submit while "
                "acting as the group (set user.group).",
            )
        if not policy_id:
            return self._fail(command, "remove_data_policy requires `policy_id`")

        gql_input: Dict[str, Any] = {
            "account": account,
            "policyId": str(policy_id),
        }
        if wallet_id:
            gql_input["walletId"] = wallet_id

        self.log_parameters({
            "account": account,
            "wallet_id": wallet_id,
            "policy_id": policy_id,
        })

        response = self._graphql(DataPolicyGraphQL.REMOVE_DATA_POLICY, {"input": gql_input}, token)
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="RemoveDataPolicy")
        data = response.get_data("pipelineGate.removeDataPolicy", {}) or {}
        if not data.get("success"):
            return self._finalize_business_error(
                command, data.get("message", "removeDataPolicy not successful"),
                operation_name="RemoveDataPolicy",
            )

        outputs = {
            "policy_id": data.get("policyId") or str(policy_id),
            "account": account,
            "message": data.get("message"),
            "message_id": data.get("messageId"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message=f"Data policy {outputs['policy_id']} removal submitted",
        )

    # ------------------------------------------------------------------
    # commit_oracle_document — publish a confidential document to the oracle
    # (MQ). The committing account becomes the `obligor` an oracle data
    # requirement names; `getCommitment(obligor, key)` reads it on-chain.
    # ------------------------------------------------------------------

    def _execute_commit_oracle_document(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=bool(command.user.group))
        if err:
            return err

        p = command.parameters
        obligor = p.get("obligor") or self._claim(token, "group_account_address")
        key = p.get("key")
        value = p.get("value")
        document_json = p.get("document_json")
        if not obligor:
            return self._fail(command, "commit_oracle_document requires `obligor` (the committing account)")
        if not key:
            return self._fail(command, "commit_oracle_document requires `key`")
        if value is None and document_json is None:
            return self._fail(
                command,
                "commit_oracle_document requires `value` (numeric oracle) and/or `document_json` (credential oracle)",
            )
        # document_json may be authored as a YAML mapping or a JSON string; normalise to a string.
        if isinstance(document_json, (dict, list)):
            document_json = json.dumps(document_json)

        gql_input = {
            "obligor": obligor,
            "key": str(key),
            # value XOR document_json: send "" for the one omitted (the backend treats empty as absent —
            # value-only ⇒ numeric oracle/setValue; document-only ⇒ credential oracle/setValueWithCommitment).
            "value": "" if value is None else str(value),
            "documentJson": "" if document_json is None else str(document_json),
        }
        if is_provided(p.get("oracle_address")):
            gql_input["oracleAddress"] = p.get("oracle_address")
        # Optional issuer signature over the document idHash (from `sign_oracle_document`). Stored
        # on-chain by setValueWithCommitment so a policy's `required_signer` can enforce the issuer.
        if is_provided(p.get("signature")):
            gql_input["signature"] = p.get("signature")

        self.log_parameters({
            "obligor": obligor,
            "key": key,
            "value": value,
            "document_json": document_json,
        })

        response = self._graphql(DataPolicyGraphQL.COMMIT_ORACLE_DOCUMENT, {"input": gql_input}, token)
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="CommitOracleDocument")
        data = response.get_data("pipelineGate.commitOracleDocument", {}) or {}
        if not data.get("success"):
            return self._finalize_business_error(
                command, data.get("message", "commitOracleDocument not successful"),
                operation_name="CommitOracleDocument",
            )

        outputs = {
            "obligor": obligor,
            "oracle_address": data.get("oracleAddress"),
            "key": data.get("key") or str(key),
            "message": data.get("message"),
            "message_id": data.get("messageId"),
        }
        return self._finalize_success(
            command, token, outputs,
            success_message=f"oracle document committed for key {outputs['key']}",
        )

    # ------------------------------------------------------------------
    # sign_oracle_document — produce the issuer signature for a document
    # (the value a policy `required_signer` enforces). Fetches the
    # message-to-sign (`documentSignerMessage`), EIP-191-signs it with the
    # caller's server-custodied key via the auth vault/sign API (exactly
    # like `approve_data_policy`), and recovers the signer EOA so a policy
    # can name it. Run AS the issuer for a valid signature; AS any other
    # entity for a wrong-key negative case.
    # ------------------------------------------------------------------

    def _execute_sign_oracle_document(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=bool(command.user.group))
        if err:
            return err

        p = command.parameters
        document_json = p.get("document_json")
        if document_json is None:
            return self._fail(command, "sign_oracle_document requires `document_json`")
        if isinstance(document_json, (dict, list)):
            document_json = json.dumps(document_json)

        # 1. Fetch the canonical message an issuer signs (keccak of the document's idHash).
        msg_resp = self._graphql(
            DataPolicyGraphQL.DOCUMENT_SIGNER_MESSAGE,
            {"input": {"documentJson": str(document_json)}},
            token,
        )
        if not msg_resp.success:
            return self._finalize_graphql_error(command, msg_resp, operation_name="DocumentSignerMessage")
        message = (msg_resp.get_data("oracleFlow.documentSignerMessage", {}) or {}).get("message")
        if not message:
            return self._fail(command, "sign_oracle_document: could not resolve the document signer message")

        # 2. EIP-191-sign it with the caller's server-custodied key (same path as approve_data_policy).
        contact_id = p.get("signer_contact_id") or get_sub(token)
        if not contact_id:
            return self._fail(command, "sign_oracle_document: could not resolve the signer id for signing")
        try:
            eip191_hash = eip191_message_hash(message)
        except Exception as e:
            return self._fail(command, f"sign_oracle_document: failed to prepare message: {e}")

        sign = self.auth_service.sign_vault(token, contact_id=contact_id, data=eip191_hash, data_format="hex")
        signature = sign.get("result") if isinstance(sign, dict) else None
        if not signature:
            return self._fail(
                command,
                f"sign_oracle_document: vault/sign returned no signature ({sign.get('message') or sign})",
            )
        signature = signature if str(signature).startswith("0x") else f"0x{signature}"

        # 3. Recover the signer EOA — the exact address on-chain `recoverDocumentSigner` yields, so a
        #    policy can set `required_signer` to it.
        try:
            signer_address = recover_eip191_address(message, signature)
        except Exception as e:
            return self._fail(command, f"sign_oracle_document: failed to recover signer address: {e}")

        self.log_parameters({
            "signer_contact_id": contact_id,
            "message": message,
            "signer_address": signer_address,
        })

        outputs = {"message": message, "signature": signature, "signer_address": signer_address}
        return self._finalize_success(
            command, token, outputs,
            success_message=f"oracle document signed by {signer_address}",
        )

    # ------------------------------------------------------------------
    # Read helpers (for asserts).
    # ------------------------------------------------------------------

    def _execute_data_policies(self, command: Command) -> CommandResponse:
        """
        List a wallet's registered data policies. Optional parameters:

            include_revoked: true  → also return revoked rows (flagged `revoked`)
            policy_id: <id>        → surface assert-friendly outputs for ONE policy:
                                       <cmd>.found    "True"/"False" — id in the result set
                                       <cmd>.revoked  that row's revoked flag (when found)
        """
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=bool(command.user.group))
        if err:
            return err
        p = command.parameters
        wallet_id = p.get("wallet_id") or self._claim(token, "default_wallet_id")
        if not wallet_id:
            return self._fail(command, "data_policies requires `wallet_id` (or a group delegation token)")
        include_revoked = bool(p.get("include_revoked"))
        response = self._graphql(
            DataPolicyGraphQL.DATA_POLICIES,
            {"walletId": wallet_id, "includeRevoked": include_revoked},
            token,
        )
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="DataPolicies")
        policies = response.get_data("pipelineGate.dataPolicies", []) or []
        outputs: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "policies": policies,
            "policy_count": len(policies),
        }
        lookup_id = p.get("policy_id")
        if is_provided(lookup_id):
            match = next(
                (pol for pol in policies if str(pol.get("policyId")) == str(lookup_id)), None
            )
            outputs["found"] = match is not None
            if match is not None:
                outputs["revoked"] = match.get("revoked")
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ data_policies: {len(policies)} policy(ies)"
            + (f" (include_revoked={include_revoked})" if include_revoked else "")
            + (
                f" — policy {lookup_id}: found={outputs.get('found')} revoked={outputs.get('revoked')}"
                if is_provided(lookup_id)
                else ""
            )
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    def _execute_data_policy_approval(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        token, err = self._acquire_token_or_error(command, use_delegation=bool(command.user.group))
        if err:
            return err
        p = command.parameters
        account = p.get("account") or self._claim(token, "group_account_address")
        policy_id = p.get("policy_id")
        if not account or not policy_id:
            return self._fail(command, "data_policy_approval requires `account` and `policy_id`")
        response = self._graphql(
            DataPolicyGraphQL.DATA_POLICY_APPROVAL,
            {"account": account, "policyId": str(policy_id)},
            token,
        )
        if not response.success:
            return self._finalize_graphql_error(command, response, operation_name="DataPolicyApproval")
        info = response.get_data("pipelineGate.dataPolicyApproval", {}) or {}
        outputs = {
            "account": account,
            "policy_id": str(policy_id),
            "registered_digest": info.get("registeredDigest"),
            "min_signatories": info.get("minSignatories"),
            "collected": info.get("collected"),
            "approved": info.get("approved"),
        }
        self.store_outputs(command.name, outputs)
        self.logger.success(
            f"    ✅ data_policy_approval {policy_id}: "
            f"collected={outputs['collected']} approved={outputs['approved']}"
        )
        self.log_command_success(command)
        return CommandResponse.success_response(command.name, command.type, outputs)

    # ------------------------------------------------------------------

    def _fail(self, command: Command, message: str) -> CommandResponse:
        self.log_command_failure(command)
        return CommandResponse.error_response(command.name, command.type, [message])
