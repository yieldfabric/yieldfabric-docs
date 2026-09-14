"""
`yf login` — obtain a session and store it for later invocations.

    yf login --email you@example.com            # password prompted
    yf login --api-key yf_api_…                 # exchanged once, stored
    yf --chain 151 --live login --email …       # a LIVE session

The session (access + refresh token) is written to
``$YF_CONFIG_DIR/session.json`` (default ``~/.config/yf/session.json``)
with mode 0600, one record per auth host. A fresh login replaces the
whole record, including any delegation saved with ``group delegate
--save``. Tokens are never printed unless ``--json --show-tokens`` is
given.

Failures keep the platform's answer: 401/403 → exit 4 with the server's
code; a connector key on a chain outside its ``allowed_chains`` → exit 1
``chain_not_allowed`` with the allowed chains; host unreachable → exit 1
``unreachable``.

`yf logout` removes the stored record for the auth host.
"""

import getpass
import os

from .. import errors
from ..context import Context
from ..output import credential_error
from ..session import Session, SessionStore, session_record
from ..settings import mode_for_chain

NAME = "login"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="sign in and store the session (email/password or API key)")
    p.add_argument("--email", help="sign in with email + password (password: --password, YF_PASSWORD, or a prompt)")
    p.add_argument("--password", help="password (prefer YF_PASSWORD or the prompt — argv is visible to other processes)")
    p.add_argument("--api-key", dest="login_api_key", metavar="KEY", help="exchange a yf_api_… key and store the session")
    p.add_argument("--show-tokens", action="store_true", help="include access/refresh tokens in --json output")


def _resolve_password(args) -> str:
    password = args.password or os.environ.get("YF_PASSWORD")
    if password:
        return password
    try:
        password = getpass.getpass("Password: ")
    except (EOFError, KeyboardInterrupt):
        password = ""
    if not password:
        raise errors.usage("password_required", "a password is required (use --password, YF_PASSWORD, or the prompt)")
    return password


def run(ctx: Context, args) -> int:
    settings = ctx.settings
    store: SessionStore = ctx.store

    email = (args.email or "").strip()
    api_key = (args.login_api_key or "").strip()
    if api_key and email:
        raise errors.usage("login_method_conflict", "pass either --email or --api-key, not both")
    if not api_key and not email:
        # Fall back to the global --api-key / YF_API_KEY only when no
        # password login was asked for.
        api_key = settings.api_key or ""
    if not api_key and not email:
        raise errors.usage("login_method_required", "pass --email (password login) or --api-key")

    auth = ctx.auth()
    if api_key:
        result = auth.exchange_api_key_session(api_key)
        if not result.get("ok"):
            raise credential_error(
                result,
                fallback_code="api_key_rejected",
                what=f"the API key was not accepted by {settings.auth_url} for chain {settings.chain_id}",
                host=settings.auth_url,
            )
        kind = "personal"
    else:
        password = _resolve_password(args)
        result = auth.login_session_result(email, password)
        if not result.get("ok"):
            raise credential_error(
                result,
                fallback_code="login_failed",
                what=f"login as {email} was rejected by {settings.auth_url}",
                host=settings.auth_url,
            )
        kind = "personal"
    bundle = result["session"]

    session = Session.from_token(
        bundle["access_token"],
        source="session",
        refresh_token=bundle.get("refresh_token"),
        raw=bundle.get("raw") or {},
    )
    token_chain = session.chain_id or settings.chain_id
    if token_chain != settings.chain_id:
        raise errors.usage(
            "chain_mismatch",
            f"the platform minted the session for chain {token_chain}, not {settings.chain_id}; "
            "for a connector API key, the chain must be one the key allows",
        )
    session.chain_id = settings.chain_id

    user_id = session.user_id
    profile_id = auth.get_user_id_from_profile(session.access_token)
    if profile_id:
        user_id = profile_id

    record = session_record(session, kind=kind)
    record["user_id"] = user_id
    store.put(settings.auth_url, record)

    data = {
        "user_id": user_id,
        "chain_id": settings.chain_id,
        "mode": mode_for_chain(settings.chain_id),
        "session_kind": session.session_kind,
        "auth_url": settings.auth_url,
        "session_file": store.path,
        "expires_at": session.expires_at,
        "refreshable": bool(session.refresh_token),
    }
    if session.is_connector:
        data["note"] = (
            "connector session: reads only — send, accept-all, obligation and group delegate "
            "need a personal key or a password login"
        )
    if settings.json_mode and args.show_tokens:
        data["access_token"] = session.access_token
        data["refresh_token"] = session.refresh_token
    return ctx.ok(data)

