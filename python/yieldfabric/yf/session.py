"""
Credential resolution and the login session file for `yf`.

Resolution order for one invocation:

1. ``--token`` / ``YF_TOKEN`` — a raw bearer, used as-is (this is how a
   delegation JWT from ``yf group delegate`` is put to work).
2. ``--api-key`` / ``YF_API_KEY`` — exchanged for a short-lived session on
   every invocation (``POST /auth/api-key`` with the resolved chain).
   Stateless; nothing is written to disk.
3. The session file written by ``yf login`` (``$YF_CONFIG_DIR/session.json``,
   default ``~/.config/yf/session.json``, mode 0600, one record per auth
   host). An access token within 60 s of expiry is refreshed through
   ``POST /auth/refresh``; refresh tokens are single-use and rotate, so the
   returned pair is written back before the command runs.

   A delegation saved with ``yf group delegate --save`` lives INSIDE that
   record under ``delegation`` — it never replaces the personal login. While
   it is unexpired it is the active session; once it expires the remedy is
   ``yf group delegate --save`` again (or ``yf logout --delegation`` to go
   back to the personal session), never a fresh login.

Whatever the source, the bearer's ``default_chain_id`` must equal the
resolved chain — payments refuses a session minted for another chain —
so the mismatch is reported here (exit 2, ``chain_mismatch``) before any
request is sent.

Credential calls (API-key exchange, refresh) go through the
status-preserving ``AuthService`` variants, so a rejected credential
(401/403) is exit 4 with the server's reason, a refused chain (the
``409 chain_not_allowed`` a connector key gets outside its
``allowed_chains``) is exit 1 with that code, and a host that could not
be reached is exit 1 ``unreachable`` — never all three collapsed into one
generic failure.
"""

import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..services.auth_service import AuthService
from ..utils.jwt import extract_claim, get_entity_id, get_exp, get_sub
from . import errors
from .output import credential_error
from .settings import Settings

SESSION_FILE_VERSION = 1
#: Refresh when the access token has less than this many seconds left.
REFRESH_SKEW_SECONDS = 60


@dataclass
class Session:
    access_token: str
    chain_id: str
    #: ``token`` | ``api_key`` | ``session``
    source: str
    refresh_token: Optional[str] = None
    entity_id: Optional[str] = None
    user_id: Optional[str] = None
    session_kind: Optional[str] = None
    acting_as: Optional[str] = None
    expires_at: Optional[float] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_token(
        cls,
        token: str,
        *,
        source: str,
        refresh_token: Optional[str] = None,
        chain_id: Optional[str] = None,
        raw: Optional[Dict[str, Any]] = None,
    ) -> "Session":
        claim_chain = extract_claim(token, "default_chain_id", "chain_id")
        acting_as = extract_claim(token, "acting_as")
        return cls(
            access_token=token,
            chain_id=str(chain_id or claim_chain or ""),
            source=source,
            refresh_token=refresh_token,
            entity_id=get_entity_id(token),
            user_id=get_sub(token),
            session_kind=_str_or_none(extract_claim(token, "session_kind")),
            acting_as=_str_or_none(acting_as),
            expires_at=get_exp(token),
            raw=dict(raw or {}),
        )

    @property
    def is_connector(self) -> bool:
        return self.session_kind == "connector"

    @property
    def is_delegated(self) -> bool:
        return bool(self.acting_as) or self.session_kind == "delegated"


def _str_or_none(value: Any) -> Optional[str]:
    return str(value) if value not in (None, "") else None


# ── Session file ──────────────────────────────────────────────────────


class SessionStore:
    """The ``session.json`` written by ``yf login`` — one record per auth host."""

    def __init__(self, path: str):
        self.path = path

    def _read_all(self) -> Dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return {"version": SESSION_FILE_VERSION, "sessions": {}}
        except (OSError, ValueError) as exc:
            raise errors.usage(
                "session_file_unreadable",
                f"cannot read session file {self.path}: {exc}; delete it and run `yf login` again",
            )
        if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
            return {"version": SESSION_FILE_VERSION, "sessions": {}}
        return data

    def _write_all(self, data: Dict[str, Any]) -> None:
        directory = os.path.dirname(self.path)
        os.makedirs(directory, mode=0o700, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".session-", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
                fh.write("\n")
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        os.chmod(self.path, 0o600)

    def get(self, auth_url: str) -> Optional[Dict[str, Any]]:
        record = self._read_all()["sessions"].get(auth_url.rstrip("/"))
        return record if isinstance(record, dict) else None

    def put(self, auth_url: str, record: Dict[str, Any]) -> None:
        data = self._read_all()
        data["version"] = SESSION_FILE_VERSION
        data["sessions"][auth_url.rstrip("/")] = record
        self._write_all(data)

    def delete(self, auth_url: str) -> bool:
        data = self._read_all()
        removed = data["sessions"].pop(auth_url.rstrip("/"), None) is not None
        if removed:
            self._write_all(data)
        return removed

    # ── delegation sub-record ─────────────────────────────────────────

    def put_delegation(self, auth_url: str, delegation: Dict[str, Any]) -> None:
        """
        Store a delegation as the ACTIVE session for the auth host without
        touching the personal login it was minted from. When there is no
        personal record (the delegation was minted with ``--api-key`` /
        ``--token``), a record holding only the delegation is created.
        """
        data = self._read_all()
        data["version"] = SESSION_FILE_VERSION
        key = auth_url.rstrip("/")
        record = data["sessions"].get(key)
        if not isinstance(record, dict):
            record = {}
        record["delegation"] = delegation
        data["sessions"][key] = record
        self._write_all(data)

    def get_delegation(self, auth_url: str) -> Optional[Dict[str, Any]]:
        record = self.get(auth_url)
        delegation = record.get("delegation") if record else None
        return delegation if isinstance(delegation, dict) and delegation.get("access_token") else None

    def clear_delegation(self, auth_url: str) -> bool:
        """Drop the active delegation; the personal login (if any) stays.
        A record that held nothing else is removed entirely."""
        data = self._read_all()
        key = auth_url.rstrip("/")
        record = data["sessions"].get(key)
        if not isinstance(record, dict) or "delegation" not in record:
            return False
        record.pop("delegation", None)
        if not record.get("access_token"):
            data["sessions"].pop(key, None)
        self._write_all(data)
        return True

    def stored_chain(self, auth_url: str, now: Optional[float] = None) -> Optional[str]:
        """
        The chain the stored session was minted for, without validating
        it. An unexpired saved delegation is the active session, so its
        chain wins over the personal login's.
        """
        try:
            record = self.get(auth_url)
        except errors.CliError:
            return None
        if not record:
            return None
        delegation = record.get("delegation")
        if isinstance(delegation, dict) and delegation.get("access_token") and not _is_expired(delegation, now):
            chain = delegation.get("chain_id")
            if chain:
                return str(chain)
        chain = record.get("chain_id")
        return str(chain) if chain else None


def _is_expired(record: Dict[str, Any], now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    exp = get_exp(record.get("access_token") or "")
    if exp is None:
        exp = record.get("expires_at")
    if exp is None:
        return False
    try:
        return float(exp) <= now
    except (TypeError, ValueError):
        return False


def session_record(
    session: Session,
    *,
    kind: str = "personal",
) -> Dict[str, Any]:
    """The on-disk shape for one login."""
    return {
        "kind": kind,
        "chain_id": session.chain_id,
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": session.expires_at,
        "session_kind": session.session_kind,
        "user_id": session.user_id,
        "acting_as": session.acting_as,
        "obtained_at": time.time(),
    }


# ── Resolution ────────────────────────────────────────────────────────


def _assert_chain(session: Session, settings: Settings, *, remedy: Optional[str] = None) -> Session:
    claim = extract_claim(session.access_token, "default_chain_id", "chain_id")
    token_chain = str(claim) if claim is not None else None
    if token_chain and token_chain != settings.chain_id:
        remedy = remedy or f"Re-run with --chain {token_chain}, or `yf login --chain {settings.chain_id}`."
        raise errors.usage(
            "chain_mismatch",
            f"the session is minted for chain {token_chain} but chain {settings.chain_id} "
            f"was requested (source: {settings.chain_source}); payments would refuse it. {remedy}",
        )
    session.chain_id = settings.chain_id
    return session


def _needs_refresh(record: Dict[str, Any], now: float) -> bool:
    token = record.get("access_token") or ""
    exp = get_exp(token)
    if exp is None:
        exp = record.get("expires_at")
    if exp is None:
        return False
    try:
        return float(exp) - now < REFRESH_SKEW_SECONDS
    except (TypeError, ValueError):
        return False


def resolve_session(
    settings: Settings,
    auth: Optional[AuthService] = None,
    *,
    store: Optional[SessionStore] = None,
    now: Optional[float] = None,
) -> Session:
    """
    Produce the bearer for this invocation (see module docstring).

    ``auth`` is constructed lazily so the token/API-key paths never build
    one when they do not need to; tests inject a mocked client.
    """
    now = time.time() if now is None else now

    # 1. Raw bearer.
    if settings.token:
        return _assert_chain(Session.from_token(settings.token, source="token"), settings)

    # 2. API key, exchanged per invocation.
    if settings.api_key:
        auth = auth or AuthService(settings.to_config())
        result = auth.exchange_api_key_session(settings.api_key)
        if not result.get("ok"):
            raise credential_error(
                result,
                fallback_code="api_key_rejected",
                what=f"the API key was not accepted by {settings.auth_url} for chain {settings.chain_id}",
                host=settings.auth_url,
            )
        bundle = result["session"]
        session = Session.from_token(
            bundle["access_token"],
            source="api_key",
            refresh_token=bundle.get("refresh_token"),
            raw=bundle.get("raw") or {},
        )
        return _assert_chain(session, settings)

    # 3. Stored login — an active saved delegation first, then the personal
    #    login it sits beside.
    store = store or SessionStore(settings.session_path)
    record = store.get(settings.auth_url)
    delegation = record.get("delegation") if record else None
    if isinstance(delegation, dict) and delegation.get("access_token"):
        if _is_expired(delegation, now):
            raise errors.auth(
                "delegation_expired",
                f"the saved delegation for group {delegation.get('acting_as') or delegation.get('group_id') or '?'} "
                f"has expired (delegations are not refreshable) — run `yf group delegate --save` again, "
                "or `yf logout --delegation` to go back to your personal session",
            )
        session = Session.from_token(
            delegation["access_token"],
            source="session",
            chain_id=str(delegation.get("chain_id") or "") or None,
        )
        return _assert_chain(
            session,
            settings,
            remedy=(
                f"Re-run with --chain {session.chain_id}, mint the delegation on chain {settings.chain_id} "
                "with `yf --chain … group delegate --save`, or `yf logout --delegation`."
            ),
        )

    if not record or not record.get("access_token"):
        raise errors.usage(
            "no_credentials",
            "no credentials: run `yf login`, or pass --api-key / YF_API_KEY, or --token / YF_TOKEN",
        )

    stored_chain = str(record.get("chain_id") or "")
    refresh_token = record.get("refresh_token")
    must_refresh = _needs_refresh(record, now) or (stored_chain and stored_chain != settings.chain_id)
    if must_refresh:
        if not refresh_token:
            raise errors.auth(
                "session_expired",
                "the stored session cannot be renewed (no refresh token) — run `yf login` again",
            )
        auth = auth or AuthService(settings.to_config())
        result = auth.refresh_session(refresh_token, chain_id=settings.chain_id)
        if not result.get("ok"):
            raise credential_error(
                result,
                fallback_code="session_expired",
                what=(
                    f"the stored session for {settings.auth_url} could not be refreshed "
                    f"on chain {settings.chain_id} — run `yf login` again"
                ),
                host=settings.auth_url,
            )
        renewed = result["session"]
        session = Session.from_token(
            renewed["access_token"],
            source="session",
            # Refresh tokens are single-use: keep the rotated one, and fall
            # back to the old one only if the server did not rotate.
            refresh_token=renewed.get("refresh_token") or refresh_token,
            raw=renewed.get("raw") or {},
        )
        session = _assert_chain(session, settings)
        store.put(settings.auth_url, session_record(session, kind=str(record.get("kind") or "personal")))
        return session

    session = Session.from_token(
        record["access_token"],
        source="session",
        refresh_token=refresh_token,
        chain_id=stored_chain or None,
    )
    return _assert_chain(session, settings)
