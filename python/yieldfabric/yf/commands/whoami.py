"""
`yf whoami` — what the platform says about the current session.

Reads ``GET /protected/jwt`` on the auth host and renders the same shape
the payments ``whoami`` tool reports (``entity_id``, ``sub``, ``kind``,
``role``, ``session_kind``, ``acting_as``, ``chain_id``, ``mode``,
``allowed_chains``, ``wallet``, ``account_address``,
``group_account_address``, ``permissions``, ``gates``). When the auth
host cannot be reached the claims are decoded from the bearer itself and
``source`` says ``jwt`` instead of ``auth``.
"""

from typing import Any, Dict, Optional

from ...utils.jwt import decode_payload
from ..context import Context
from ..output import error_from_rest
from ..settings import mode_for_chain

NAME = "whoami"


def add_parser(subparsers) -> None:
    subparsers.add_parser(NAME, help="show who the session is, its kind, chain and wallet")


def _shape(claims: Dict[str, Any], *, chain_id: str, source: str) -> Dict[str, Any]:
    user_id = claims.get("user_id") or claims.get("sub")
    acting_as = claims.get("acting_as") or None
    account_address = claims.get("account_address")
    group_account_address = claims.get("group_account_address")
    wallet_id = claims.get("default_wallet_id")
    wallet: Optional[Dict[str, Any]] = None
    if wallet_id:
        wallet = {
            "id": wallet_id,
            "address": group_account_address if acting_as else account_address,
        }
    session_chain = claims.get("default_chain_id")
    return {
        "source": source,
        "entity_id": acting_as or user_id,
        "sub": user_id,
        "kind": "service" if str(user_id or "").startswith("service:") else "user",
        "role": claims.get("role"),
        "session_kind": claims.get("session_kind"),
        "acting_as": acting_as,
        "delegation_scope": claims.get("delegation_scope"),
        "chain_id": chain_id,
        "session_chain_id": str(session_chain) if session_chain is not None else None,
        "mode": mode_for_chain(chain_id),
        "allowed_chains": claims.get("allowed_chains"),
        "wallet": wallet,
        "account_address": account_address,
        "group_account_address": group_account_address,
        "permissions": claims.get("permissions"),
        "gates": {
            "billing_gate": claims.get("billing_gate"),
            "billing_gate_payer": claims.get("billing_gate_payer"),
            "billing_gate_payer_id": claims.get("billing_gate_payer_id"),
            "billing_sponsor": claims.get("billing_sponsor"),
            "onboarding_gate": claims.get("onboarding_gate"),
            "verification_profiles": claims.get("verification_profiles"),
        },
        "agent_id": claims.get("agent_id"),
        "mcp_agent_id": claims.get("mcp_agent_id"),
    }


def run(ctx: Context, args) -> int:
    session = ctx.session()
    result = ctx.auth().get_jwt_info(session.access_token)
    if result.get("ok") and isinstance(result.get("body"), dict):
        data = _shape(result["body"], chain_id=ctx.settings.chain_id, source="auth")
    elif int(result.get("status_code") or 0) == 0:
        # Unreachable: fall back to the bearer's own claims.
        claims = decode_payload(session.access_token) or {}
        data = _shape(claims, chain_id=ctx.settings.chain_id, source="jwt")
        data["warning"] = f"{ctx.settings.auth_url} unreachable; showing claims decoded from the bearer"
    else:
        raise error_from_rest(result)
    data["credential_source"] = session.source
    return ctx.ok(data)
