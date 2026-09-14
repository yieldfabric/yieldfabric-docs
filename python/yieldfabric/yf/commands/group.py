"""
`yf group delegate --group <id or name> [--scope S ...] [--ttl SECONDS] [--save]`

Mints a delegation JWT to act as a group (``POST /auth/delegation/jwt``).
The group is given by id, or by name resolved against the groups the
session's user is a member of (``GET /auth/groups/user``).

This needs a DIRECT personal session — a password login or a personal
API key. Connector sessions and delegation JWTs are refused by the
platform. The effective ``delegation_scope`` is whatever the platform
granted (it may be narrower than requested); it is the value printed.

The delegation JWT is used with ``--token`` / ``YF_TOKEN``; ``--save``
stores it as the active session for the auth host instead — BESIDE the
personal login it was minted from, never over it. It is not refreshable:
when it expires the CLI says so (``delegation_expired``, exit 4) and the
remedy is ``group delegate --save`` again, or ``yf logout --delegation``
to go back to the personal session — not a fresh login.
"""

import re
from typing import List, Optional, Tuple

from .. import errors
from ..context import Context
from ..session import Session, session_record

NAME = "group"
DEFAULT_SCOPES = ["CryptoOperations", "ReadGroup", "UpdateGroup", "ManageGroupMembers"]
DEFAULT_TTL = 3600
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="group operations")
    sub = p.add_subparsers(dest="subcommand", metavar="<delegate>")
    sub.required = True
    d = sub.add_parser("delegate", help="mint a delegation JWT to act as a group")
    d.add_argument("--group", required=True, metavar="ID_OR_NAME", help="group id, or a group name you are a member of")
    d.add_argument("--scope", action="append", metavar="SCOPE",
                   help=f"delegation scope (repeatable; default {' '.join(DEFAULT_SCOPES)})")
    d.add_argument("--ttl", type=int, default=DEFAULT_TTL, metavar="SECONDS", help=f"requested lifetime (default {DEFAULT_TTL})")
    d.add_argument("--save", action="store_true",
                   help="store the delegation as the active session for this auth host (beside the personal login; "
                        "`yf logout --delegation` switches back)")


def _resolve_group(ctx: Context, token: str, ref: str) -> Tuple[str, Optional[str]]:
    ref = ref.strip()
    if _UUID.match(ref):
        return ref, None
    groups = ctx.auth().get_user_groups(token)
    matches = [g for g in groups if isinstance(g, dict) and str(g.get("name") or "") == ref]
    if not matches:
        names = sorted({str(g.get("name")) for g in groups if isinstance(g, dict) and g.get("name")})
        raise errors.usage(
            "group_not_found",
            f"no group named {ref!r} among your memberships" + (f"; known: {', '.join(names)}" if names else ""),
        )
    if len(matches) > 1:
        raise errors.usage("group_ambiguous", f"{len(matches)} groups are named {ref!r}; pass the group id")
    return str(matches[0].get("id")), ref


def run(ctx: Context, args) -> int:
    if args.subcommand != "delegate":
        raise errors.usage("unknown_subcommand", f"unknown group subcommand {args.subcommand!r}")
    if args.ttl < 1:
        raise errors.usage("bad_ttl", "--ttl must be a positive number of seconds")
    scopes: List[str] = [s for s in (args.scope or []) if s] or list(DEFAULT_SCOPES)

    session = ctx.session()
    if session.is_delegated:
        raise errors.auth(
            "direct_user_session_required",
            "a delegation JWT cannot mint another delegation; use your personal session",
        )
    group_id, group_name = _resolve_group(ctx, session.access_token, args.group)

    auth = ctx.auth(delegation_scopes=scopes, jwt_expiry_seconds=args.ttl)
    bundle = auth.create_delegation_session(session.access_token, group_id, group_name or group_id)
    if not bundle or not bundle.get("access_token"):
        raise errors.auth(
            "delegation_refused",
            f"the platform did not mint a delegation for group {group_id}; "
            "this needs a direct personal session and membership of the group",
        )
    raw = bundle.get("raw") or {}
    delegation = Session.from_token(bundle["access_token"], source="token", raw=raw)
    data = {
        "group_id": bundle.get("group_id") or group_id,
        "group_name": group_name,
        "chain_id": bundle.get("chain_id") or delegation.chain_id or ctx.settings.chain_id,
        "delegation_scope": raw.get("delegation_scope"),
        "expires_in": bundle.get("expires_in"),
        "expires_at": delegation.expires_at,
        "entity_id": delegation.entity_id,
        "delegation_jwt": bundle["access_token"],
        "refresh_token": bundle.get("refresh_token"),
    }
    if args.save:
        record = session_record(delegation, kind="delegated")
        # The delegation's refresh token is not the regular refresh
        # secret; the stored session is used until it expires.
        record["refresh_token"] = None
        record["chain_id"] = str(data["chain_id"])
        record["group_id"] = data["group_id"]
        record["group_name"] = group_name
        # Beside the personal login, never over it: the access/refresh pair
        # that minted this delegation is what `group delegate` needs again
        # when it expires.
        ctx.store.put_delegation(ctx.settings.auth_url, record)
        data["saved_to"] = ctx.store.path
    if not ctx.settings.json_mode:
        data["hint"] = f"export YF_TOKEN={bundle['access_token']}"
    return ctx.ok(data)
