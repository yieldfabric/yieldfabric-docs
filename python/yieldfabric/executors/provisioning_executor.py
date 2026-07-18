"""
Provisioning + claims executor.

Adds the *creation* + *compliance* command types the swap/payment suites
never needed — account/group activation, ERC-3643 token + obligation-class
deploy, claim-requirement (CTR/TIR) configuration, and the full claims
lifecycle (issue → accept → revoke → re-issue) plus the `is_verified`
gating read.

Why a dedicated executor: these hit a mix of surfaces the other
executors don't —
  * auth REST (`:3000`)              — group create + explicit chain-account activation,
  * asset-register REST (`:3002`)    — token deploy, is_verified,
                                       claim_requirements, register_identity,
                                       update_claim_requirements,
  * claims-management REST (`:3002`) — issue/accept/decline/revoke/reissue,
  * payments GraphQL (`:3002`)       — deploy_obligation (class).

Chain writes are delegation-aware: `user.group` makes `get_token()` mint a
delegation JWT whose `acting_as` is the group, so a group delegate issues/
manages as the group (the claims handlers key authorization off
`context_entity_id() = acting_as ?? sub`). Group creation/activation is the
intentional exception and uses the human Owner/Admin's personal credential.

NOTE (live-verification): authored against the handlers (asset-register
`router.rs`, claims `flows.rs`, auth routes) — exact field names verified
in code, but the suite needs one live run to shake out env-specific bits
(factory addresses, the deploy_obligation GraphQL field selection). The
`deploy_class` path is the least-certain — `deployObligation` is a workflow
with no REST route, driven here via the documented GraphQL mutation.
"""

from typing import Optional
from urllib.parse import urlencode

from ..models import Command, CommandResponse
from ..utils.jwt import extract_claim, get_sub
from .base import BaseExecutor


class ProvisioningExecutor(BaseExecutor):
    """Account/group/token/class creation + claims lifecycle + gating."""

    # command type -> handler method
    _DISPATCH = {
        "create_group": "_create_group",
        "deploy_account": "_deploy_account",
        "deploy_token": "_deploy_token",
        "deploy_class": "_deploy_class",
        "update_claim_requirements": "_update_claim_requirements",
        "claim_requirements": "_claim_requirements",
        "is_verified": "_is_verified",
        "register_identity": "_register_identity",
        "issue_claim": "_issue_claim",
        "accept_claim": "_accept_claim",
        "decline_claim": "_decline_claim",
        "revoke_claim": "_revoke_claim",
        "reissue_claim": "_reissue_claim",
        "issued_by_me": "_issued_by_me",
        "issued_to_me": "_issued_to_me",
    }

    def execute(self, command: Command) -> CommandResponse:
        self.log_command_start(command)
        method = self._DISPATCH.get(command.type.lower())
        if method is None:
            return CommandResponse.error_response(
                command.name, command.type, [f"Unsupported type: {command.type}"]
            )
        # Creating/activating a group is authorized by its human Owner/Admin.
        # A delegation JWT cannot exist before that group's first account and
        # must never be used to activate a different target group.
        personal_account_command = command.type.lower() in (
            "create_group",
            "deploy_account",
        )
        token, err = self._acquire_token_or_error(
            command, use_delegation=not personal_account_command
        )
        if err:
            return err
        try:
            return getattr(self, method)(command, token)
        except Exception as e:  # surface as a normal command failure
            self.log_command_failure(command)
            return CommandResponse.error_response(command.name, command.type, [str(e)])

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _p(self, command: Command, key: str, default=None):
        return command.parameters.get(key, default)

    def _rest_ok(self, body) -> bool:
        """A claims/asset-register JSON body is `{status, timestamp, error}`."""
        return isinstance(body, dict) and str(body.get("status", "")).lower() == "ok"

    def _rest_err(self, body) -> str:
        if isinstance(body, dict):
            return str(body.get("error") or body.get("message") or body)
        return str(body)

    def _claims_post(self, path: str, params: dict, token: str):
        """POST a claims-management endpoint (query-param style, empty body)."""
        endpoint = f"/claims_management/{path}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        return self.payments_service._post_json_safe(endpoint, {}, token=token, description=path)

    def _ar_post(self, path: str, params: dict, token: str):
        """POST an asset-register endpoint (query-param style, empty body)."""
        endpoint = f"/asset_register/{path}?{urlencode({k: v for k, v in params.items() if v is not None})}"
        return self.payments_service._post_json_safe(endpoint, {}, token=token, description=path)

    def _ar_get(self, path: str, params: dict, token: str):
        return self.payments_service._get_json_safe(
            f"/asset_register/{path}", params={k: v for k, v in params.items() if v is not None},
            token=token, description=path, default={"status": "error", "error": "no response"},
        )

    def _finish(self, command: Command, ok: bool, outputs: dict, body, op: str) -> CommandResponse:
        if ok:
            self.store_outputs(command.name, outputs)
            self.logger.success(f"    ✅ {op} ok")
            for k, v in outputs.items():
                if v not in (None, "", []):
                    self.logger.info(f"      {k}: {v}")
            self.log_command_success(command)
            return CommandResponse.success_response(command.name, command.type, outputs)
        msg = self._rest_err(body)
        self.logger.error(f"    ❌ {op} failed: {msg}")
        self.log_command_failure(command)
        return CommandResponse.error_response(command.name, command.type, [msg])

    # ------------------------------------------------------------------
    # group + account creation
    # ------------------------------------------------------------------

    def _create_group(self, command: Command, token: str) -> CommandResponse:
        """Create a group and explicitly activate its selected-chain account.

        Idempotent: an existing group is recovered by name. Mirrors the
        proven setup_runner group-bootstrap path.
        """
        name = self._p(command, "name")
        if not name:
            return CommandResponse.error_response(command.name, command.type, ["`name` is required"])
        description = self._p(command, "description", "")
        group_type = self._p(command, "group_type", "project")

        res = self.auth_service.create_group(token, name=name, description=description, group_type=group_type)
        status = res.get("status")
        group_id = res.get("group_id") or self.auth_service.get_group_id_by_name(token, name)
        if status not in ("created", "exists") or not group_id:
            return self._finish(command, False, {}, res, "create_group")

        chain_id = self._p(command, "chain_id") or extract_claim(
            token, "default_chain_id"
        )
        if not chain_id:
            return CommandResponse.error_response(
                command.name,
                command.type,
                ["could not resolve chain_id from creator JWT"],
            )
        activation = self.auth_service.wait_for_chain_account_activation(
            token,
            "group",
            group_id,
            str(chain_id),
            attempts=60,
            interval=2.0,
        )
        if activation.get("status") != "ready":
            return self._finish(
                command, False, {}, activation, "activate_group_account"
            )
        outputs = {
            "group_id": group_id,
            "chain_id": activation.get("chain_id") or str(chain_id),
            "account_address": activation.get("account_address"),
            "wallet_id": activation.get("wallet_id"),
            "created": status == "created",
        }
        return self._finish(command, True, outputs, res, "create_group")

    def _deploy_account(self, command: Command, token: str) -> CommandResponse:
        """Explicitly activate the CALLER's account on the selected chain.

        Both user and group targets use the canonical per-chain activation
        resource. Group activation deliberately uses the human caller's
        personal Owner/Admin credential, acquired by `execute` above.
        """
        entity_kind = "user"
        entity_id = self._p(command, "user_id") or get_sub(token)
        if command.user.group:
            entity_kind = "group"
            entity_id = self.auth_service.get_group_id_by_name(
                token, command.user.group
            )
        if not entity_id:
            return CommandResponse.error_response(
                command.name,
                command.type,
                [f"could not resolve {entity_kind}_id"],
            )
        chain_id = self._p(command, "chain_id") or extract_claim(token, "default_chain_id")
        if not chain_id:
            return CommandResponse.error_response(
                command.name, command.type, ["could not resolve chain_id from JWT"]
            )

        body = self.auth_service.wait_for_chain_account_activation(
            token,
            entity_kind,
            entity_id,
            str(chain_id),
            attempts=60,
            interval=2.0,
        )

        ok = body.get("status") == "ready" and bool(body.get("account_address"))
        outputs = {
            f"{entity_kind}_id": entity_id,
            "chain_id": body.get("chain_id") or str(chain_id),
            "wallet_id": body.get("wallet_id"),
            "account_address": body.get("account_address"),
            "deployed": body.get("deployed"),
        }
        return self._finish(command, ok, outputs, body, "deploy_account")

    # ------------------------------------------------------------------
    # token + obligation-class deploy
    # ------------------------------------------------------------------

    def _deploy_token(self, command: Command, token: str) -> CommandResponse:
        """Deploy an ERC-3643 compliant token via the CompliantTokenFactory.

        `POST /asset_register/deploy` (synchronous). `factory_address` /
        `identity_registry` fall back to chain config server-side.
        """
        params = {
            "name": self._p(command, "name"),
            "symbol": self._p(command, "symbol"),
            "decimals": self._p(command, "decimals"),
            "factory_address": self._p(command, "factory_address"),
            "identity_registry": self._p(command, "identity_registry"),
            "asset_id": self._p(command, "asset_id"),
            "asset_type": self._p(command, "asset_type"),
            "asset_name": self._p(command, "asset_name"),
        }
        if not params["name"] or not params["symbol"]:
            return CommandResponse.error_response(
                command.name, command.type, ["`name` and `symbol` are required"]
            )
        body = self._ar_post("deploy", params, token)
        ok = self._rest_ok(body)
        outputs = {}
        if isinstance(body, dict):
            outputs = {
                "token_address": body.get("token_address"),
                "asset_id": body.get("asset_id"),
                "token_id": body.get("token_id"),
                "chain_id": body.get("chain_id"),
                "factory_address": body.get("factory_address"),
            }
        return self._finish(command, ok, outputs, body, "deploy_token")

    def _deploy_class(self, command: Command, token: str) -> CommandResponse:
        """Deploy a ConfidentialObligation class via ConfidentialObligationFactory.

        `POST /api/asset_register/deploy_obligation_workflow` enqueues the deploy;
        the deploy_obligation workflow lands the EIP-1167 proxy and records its
        address. We poll the workflow to a terminal state and read
        `result.obligation_address`. `identity_registry` is a backend chain
        constant (optional).
        """
        if not self._p(command, "name"):
            return CommandResponse.error_response(command.name, command.type, ["`name` is required"])
        body = {
            "name": self._p(command, "name"),
            "symbol": self._p(command, "symbol", self._p(command, "name")),
            "open_minting": bool(self._p(command, "open_minting", True)),
            "transferable": bool(self._p(command, "transferable", True)),
        }
        for k in ("identity_registry", "class_owner", "idempotency_key", "claim_topics", "trusted_issuers"):
            v = self._p(command, k)
            if v is not None:
                body[k] = v

        resp = self.payments_service._post_json_safe(
            "/api/asset_register/deploy_obligation_workflow", body, token=token, description="deploy_class",
        )
        workflow_id = resp.get("workflow_id") if isinstance(resp, dict) else None
        if not workflow_id:
            return self._finish(command, False, {}, resp, "deploy_class")

        try:
            poll = self.payments_service.poll_workflow_status(
                workflow_id, self._token_for_polling(command, token), interval=1.0, timeout=180.0,
            )
        except TimeoutError as e:
            return self._finish(command, False, {"workflow_id": workflow_id}, {"error": str(e)}, "deploy_class")

        obs = getattr(poll, "observation", poll) or {}
        wf_result = obs.get("result") or {}
        outputs = {
            "workflow_id": workflow_id,
            "workflow_status": obs.get("workflow_status"),
            "obligation_address": wf_result.get("obligation_address"),
            # The class's OWN per-token IdentityRegistry. Surfaced so the
            # group-trusted-issuer check can target an IR payer OWNS (owner-managed,
            # no ManageCompliance needed) instead of the chain's shared IR.
            "identity_registry": wf_result.get("identity_registry"),
        }
        ok = str(obs.get("workflow_status", "")).lower() == "completed" and bool(outputs["obligation_address"])
        return self._finish(command, ok, outputs, obs, "deploy_class")

    # ------------------------------------------------------------------
    # claim requirements (CTR/TIR) + reads
    # ------------------------------------------------------------------

    def _update_claim_requirements(self, command: Command, token: str) -> CommandResponse:
        """Add/remove CTR claim topics + TIR trusted issuers on an IR.

        This is what makes gating active: with topics configured, an
        unverified account fails `is_verified`. Requires `ManageCompliance`
        when targeting the shared IR (see the resolver gate).
        """
        # identity_registry_address + chain_id are backend chain constants — both
        # OPTIONAL; the handler defaults them from chain config when omitted.
        body = {}
        ir = self._p(command, "identity_registry_address")
        if ir:
            body["identity_registry_address"] = ir
        chain_id = self._p(command, "chain_id")
        if chain_id is not None:
            body["chain_id"] = str(chain_id)
        for k in ("add_claim_topics", "remove_claim_topics", "remove_trusted_issuers"):
            v = self._p(command, k)
            if v is not None:
                body[k] = v
        # Trusted issuers: the handler wants a `{issuer_address: [topics]}` map,
        # but YAML `$ref`s don't substitute into map KEYS — so also accept the
        # list form `[{address, topics}]` (values DO substitute) and normalise.
        for k in ("add_trusted_issuers", "update_trusted_issuers"):
            v = self._p(command, k)
            if v is None:
                continue
            if isinstance(v, list):
                v = {e["address"]: e.get("topics", []) for e in v if e.get("address")}
            body[k] = v
        resp = self.payments_service._post_json_safe(
            "/asset_register/update_claim_requirements", body, token=token,
            description="update_claim_requirements",
        )
        # The handler may return either a synchronous status or a
        # message/workflow id to poll. Honour a message_id if present.
        outputs = {}
        if isinstance(resp, dict):
            outputs = {
                "message_id": resp.get("message_id"),
                "workflow_id": resp.get("workflow_id"),
            }
        if outputs.get("message_id"):
            return self._finalize_success(command, token, outputs, success_message="update_claim_requirements")
        ok = self._rest_ok(resp) or (isinstance(resp, dict) and resp.get("status") in ("accepted", "ok"))
        return self._finish(command, ok, outputs, resp, "update_claim_requirements")

    def _claim_requirements(self, command: Command, token: str) -> CommandResponse:
        ir = self._p(command, "identity_registry_address")
        body = self._ar_get("claim_requirements", {"identity_registry_address": ir}, token)
        ok = self._rest_ok(body)
        outputs = {}
        if isinstance(body, dict):
            topics = body.get("claim_topics") or []
            issuers = body.get("trusted_issuers") or []
            outputs = {
                "claim_topics": topics,
                "claim_topic_count": len(topics),
                "trusted_issuers": issuers,
                "trusted_issuer_count": len(issuers),
                # Lowercased trusted-issuer addresses for case-robust membership
                # checks (on-chain addresses come back in mixed case).
                "trusted_issuer_addresses_lc": [
                    str(ti.get("address", "")).lower()
                    for ti in issuers
                    if isinstance(ti, dict)
                ],
            }
        return self._finish(command, ok, outputs, body, "claim_requirements")

    def _is_verified(self, command: Command, token: str) -> CommandResponse:
        """The gating read: does `user_address` pass the IR's `isVerified`?

        Returns `is_verified` AND `ir_has_claim_topics` — when the latter is
        False, gating is vacuous (isVerified is true for any registered
        identity) so a revoke can't flip it; the suite asserts accordingly.
        """
        user_address = self._p(command, "user_address")
        if not user_address:
            return CommandResponse.error_response(
                command.name, command.type, ["`user_address` is required"]
            )
        # identity_registry_address is OPTIONAL — it's a backend chain constant,
        # so the handler defaults it to the chain's configured IR when omitted.
        body = self._ar_get(
            "is_verified",
            {
                "identity_registry_address": self._p(command, "identity_registry_address"),
                "user_address": user_address,
            },
            token,
        )
        ok = self._rest_ok(body)
        outputs = {}
        if isinstance(body, dict):
            outputs = {
                "is_verified": body.get("is_verified"),
                "ir_has_claim_topics": body.get("ir_has_claim_topics"),
            }
        return self._finish(command, ok, outputs, body, "is_verified")

    def _register_identity(self, command: Command, token: str) -> CommandResponse:
        """Register an identity in the IR (IR agent only).

        `identity_registry_address` + `chain_id` are OPTIONAL (backend chain
        constants); pass `user_address` or `target_user_id` for the subject.
        """
        params = {
            "identity_registry_address": self._p(command, "identity_registry_address"),
            "chain_id": self._p(command, "chain_id"),
            "user_address": self._p(command, "user_address"),
            "target_user_id": self._p(command, "target_user_id"),
        }
        body = self._ar_post("register_identity", params, token)
        return self._finish(command, self._rest_ok(body), {}, body, "register_identity")

    # ------------------------------------------------------------------
    # claims lifecycle
    # ------------------------------------------------------------------

    def _issue_claim(self, command: Command, token: str) -> CommandResponse:
        """Issuer issues a claim to `target_user_id` (stored pending).

        The endpoint returns only `{status}` — no id — so after a success we
        read `issued_by_me` and surface the just-issued claim's `id` as
        `issued_claim_id` for the accept/revoke/reissue steps to `$ref`.
        """
        target = self._p(command, "target_user_id")
        if not target:
            return CommandResponse.error_response(
                command.name, command.type, ["`target_user_id` is required"]
            )
        params = {
            "target_user_id": target,
            "claim_type": self._p(command, "claim_type"),
            "claim_value": self._p(command, "claim_value"),
            "chain_id": self._p(command, "chain_id"),
            "wallet_id": self._p(command, "wallet_id"),
            "topic": self._p(command, "topic"),
            "scheme": self._p(command, "scheme"),
            "data": self._p(command, "data"),
            "uri": self._p(command, "uri"),
        }
        body = self._claims_post("issue_claim", params, token)
        if not self._rest_ok(body):
            return self._finish(command, False, {}, body, "issue_claim")

        # The endpoint returns no id; read it back (plus the on-chain
        # claim_issuer_address + target_account_address + topic) so the suite
        # can `$ref` them to drive accept/revoke/reissue AND self-configure
        # gating (add the claim's own issuer as a trusted issuer).
        claim = self._latest_issued_claim(token, target) or {}
        # topic/scheme are ints on the row; stringify so a YAML `$ref` lands as a
        # string (update_claim_requirements wants `Vec<String>` topics).
        topic = claim.get("topic")
        scheme = claim.get("scheme")
        ci_addr = claim.get("claim_issuer_address")
        outputs = {
            "issued_claim_id": claim.get("id"),
            "target_user_id": target,
            "claim_issuer_address": ci_addr,
            # Lowercased for case-robust membership checks against
            # `claim_requirements.trusted_issuer_addresses_lc` (on-chain
            # addresses come back in mixed case). This is the POSITIVE proof a
            # trusted-issuer registration landed the right ClaimIssuer.
            "claim_issuer_address_lc": str(ci_addr).lower() if ci_addr else None,
            "target_account_address": claim.get("target_account_address"),
            "topic": str(topic) if topic is not None else None,
            "scheme": str(scheme) if scheme is not None else None,
        }
        return self._finish(command, True, outputs, body, "issue_claim")

    def _latest_issued_claim(self, token: str, target_user_id: str) -> Optional[dict]:
        """Return the newest pending claim this caller issued to `target`."""
        body = self.payments_service._get_json_safe(
            "/claims_management/issued_by_me", token=token, description="issued_by_me", default={}
        )
        claims = (body or {}).get("claims") or []
        candidates = [
            c for c in claims
            if c.get("target_user_id") == target_user_id and c.get("status") == "pending"
        ]
        candidates.sort(key=lambda c: c.get("created_at") or "", reverse=True)
        if candidates:
            return candidates[0]
        any_to_target = [c for c in claims if c.get("target_user_id") == target_user_id]
        any_to_target.sort(key=lambda c: c.get("created_at") or "", reverse=True)
        return any_to_target[0] if any_to_target else None

    def _claim_by_id(self, command: Command, token: str, path: str) -> CommandResponse:
        issued_claim_id = self._p(command, "issued_claim_id")
        if not issued_claim_id:
            return CommandResponse.error_response(
                command.name, command.type, ["`issued_claim_id` is required"]
            )
        body = self._claims_post(path, {"issued_claim_id": issued_claim_id}, token)
        return self._finish(command, self._rest_ok(body), {"issued_claim_id": issued_claim_id}, body, path)

    def _accept_claim(self, command: Command, token: str) -> CommandResponse:
        return self._claim_by_id(command, token, "accept_claim")

    def _decline_claim(self, command: Command, token: str) -> CommandResponse:
        return self._claim_by_id(command, token, "decline_claim")

    def _revoke_claim(self, command: Command, token: str) -> CommandResponse:
        return self._claim_by_id(command, token, "revoke_claim")

    def _reissue_claim(self, command: Command, token: str) -> CommandResponse:
        return self._claim_by_id(command, token, "reissue_claim")

    def _issued_by_me(self, command: Command, token: str) -> CommandResponse:
        body = self.payments_service._get_json_safe(
            "/claims_management/issued_by_me", token=token, description="issued_by_me", default={}
        )
        claims = (body or {}).get("claims") or []
        outputs = {"claim_count": len(claims), "latest_issued_id": claims[0].get("id") if claims else None}
        return self._finish(command, self._rest_ok(body), outputs, body, "issued_by_me")

    def _issued_to_me(self, command: Command, token: str) -> CommandResponse:
        body = self.payments_service._get_json_safe(
            "/claims_management/issued_to_me", token=token, description="issued_to_me", default={}
        )
        claims = (body or {}).get("claims") or []
        outputs = {"claim_count": len(claims), "latest_received_id": claims[0].get("id") if claims else None}
        return self._finish(command, self._rest_ok(body), outputs, body, "issued_to_me")
