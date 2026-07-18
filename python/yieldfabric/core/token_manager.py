"""
Shared JWT/session manager for YAML execution.

The runner owns one TokenManager and every executor uses it. That gives
each principal one password login, keeps refresh tokens in memory, and
renews group delegation JWTs only when they are close to expiry.
"""

import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

from ..config import YieldFabricConfig
from ..services import AuthService
from ..utils.jwt import extract_claim, get_exp
from ..utils.logger import get_logger


@dataclass
class _UserSession:
    access_token: str
    refresh_token: Optional[str]
    expires_at: float
    issued_at: float
    chain_id: str


@dataclass
class _DelegationSession:
    token: str
    refresh_token: Optional[str]
    group_id: str
    chain_id: str
    expires_at: float
    issued_at: float


class TokenManager:
    """Cache user and group-delegation tokens for one runner process."""

    _DEFAULT_CHAIN_ID = "31337"
    _MAX_REFRESH_MARGIN_SECONDS = 5.0
    _MIN_REFRESH_MARGIN_SECONDS = 0.5

    def __init__(
        self,
        auth_service: AuthService,
        config: YieldFabricConfig,
        *,
        now: Optional[Callable[[], float]] = None,
    ):
        self.auth_service = auth_service
        self.config = config
        self._now = now or time.time
        self._users: Dict[str, _UserSession] = {}
        self._group_ids: Dict[Tuple[str, str], str] = {}
        self._delegations: Dict[Tuple[str, str], _DelegationSession] = {}
        self._lock = threading.RLock()
        self.logger = get_logger(debug=config.debug)

    def get_token(
        self,
        email: str,
        password: str,
        *,
        group_name: Optional[str] = None,
        use_delegation: bool = True,
    ) -> Optional[str]:
        """Return a usable JWT for this command context."""
        if group_name and use_delegation:
            return self.get_delegation_token(email, password, group_name)
        return self.get_user_token(email, password)

    def token_supplier(
        self,
        email: str,
        password: str,
        *,
        group_name: Optional[str] = None,
        use_delegation: bool = True,
    ) -> Callable[[], Optional[str]]:
        """Build a callable for poll loops that may run past token TTL."""
        return lambda: self.get_token(
            email,
            password,
            group_name=group_name,
            use_delegation=use_delegation,
        )

    def refresh_token_for_access_token(self, access_token: str) -> Optional[str]:
        """
        Return the cached refresh token paired with this exact access JWT.

        User and delegation sessions have distinct rotating refresh secrets;
        callers must forward the one paired with the presented access token.
        """
        if not access_token:
            return None
        with self._lock:
            for session in self._delegations.values():
                if session.token == access_token:
                    token = session.refresh_token
                    return token if token and token.strip() else None
            for session in self._users.values():
                if session.access_token == access_token:
                    token = session.refresh_token
                    return token if token and token.strip() else None
        return None

    def get_user_token(self, email: str, password: str) -> Optional[str]:
        with self._lock:
            key = self._user_key(email)
            session = self._users.get(key)

            if session is None:
                return self._login_user(email, password)

            if not self._is_expiring(session.issued_at, session.expires_at):
                return session.access_token

            if not session.refresh_token:
                self.logger.error(
                    f"  ❌ JWT for {email} is expiring and no refresh token is available"
                )
                return None

            refreshed = self.auth_service.refresh_access_token(
                session.refresh_token,
                chain_id=session.chain_id,
            )
            if not refreshed:
                self.logger.warning(
                    f"  ⚠️  Refresh token for {email} was rejected; logging in again"
                )
                self._invalidate_delegations_for_user(key)
                return self._login_user(email, password)

            now = self._now()
            access_token = refreshed.get("access_token")
            if not access_token:
                self.logger.error(
                    f"  ❌ Refresh response for {email} did not contain an access token"
                )
                return None

            refresh_token = refreshed.get("refresh_token") or session.refresh_token
            chain_id = self._chain_id_for_token(access_token) or session.chain_id
            new_session = _UserSession(
                access_token=access_token,
                refresh_token=refresh_token,
                expires_at=self._expires_at(access_token, refreshed.get("expires_in"), now),
                issued_at=now,
                chain_id=chain_id,
            )
            self._users[key] = new_session
            self.logger.debug(f"  🔁 Refreshed JWT for {email}")
            return new_session.access_token

    def get_delegation_token(
        self,
        email: str,
        password: str,
        group_name: str,
    ) -> Optional[str]:
        with self._lock:
            key = (self._user_key(email), group_name)
            delegation = self._delegations.get(key)

            if delegation and not self._is_expiring(delegation.issued_at, delegation.expires_at):
                return delegation.token

            if delegation and delegation.refresh_token:
                refreshed = self.auth_service.refresh_access_token(
                    delegation.refresh_token,
                    chain_id=delegation.chain_id,
                )
                if refreshed and refreshed.get("access_token"):
                    now = self._now()
                    token = refreshed["access_token"]
                    renewed = _DelegationSession(
                        token=token,
                        refresh_token=(
                            refreshed.get("refresh_token")
                            or delegation.refresh_token
                        ),
                        group_id=delegation.group_id,
                        chain_id=str(
                            extract_claim(
                                token,
                                "default_chain_id",
                                "chain_id",
                                "chainId",
                            )
                            or delegation.chain_id
                        ),
                        expires_at=self._expires_at(
                            token, refreshed.get("expires_in"), now
                        ),
                        issued_at=now,
                    )
                    self._delegations[key] = renewed
                    self.logger.debug(
                        f"  🔁 Refreshed delegation JWT for {group_name}"
                    )
                    return renewed.token
                self.logger.warning(
                    f"  ⚠️  Delegation refresh for {group_name} was rejected; "
                    "minting a fresh delegation"
                )

            user_token = self.get_user_token(email, password)
            if not user_token:
                return None

            group_id = self._group_ids.get(key)
            if not group_id:
                self.logger.cyan(f"  🏢 Group delegation requested for: {group_name}")
                group_id = self.auth_service.get_group_id_by_name(user_token, group_name)
                if not group_id:
                    self.logger.warning("    ⚠️  Group not found, using regular token")
                    return user_token
                self._group_ids[key] = group_id

            session = self._create_delegation_session(
                user_token, group_id, group_name
            )
            if not session:
                self.logger.warning("    ⚠️  Delegation failed, using regular token")
                return user_token

            token = session["access_token"]
            now = self._now()
            self._delegations[key] = _DelegationSession(
                token=token,
                refresh_token=session.get("refresh_token"),
                group_id=group_id,
                chain_id=str(
                    session.get("chain_id") or self._chain_id_for_token(token)
                ),
                expires_at=self._expires_at(
                    token,
                    session.get("expires_in") or self.config.jwt_expiry_seconds,
                    now,
                ),
                issued_at=now,
            )
            self.logger.success("    ✅ Group delegation available")
            return token

    def _create_delegation_session(
        self,
        user_token: str,
        group_id: str,
        group_name: str,
    ) -> Optional[dict]:
        """Use the refresh-aware API, falling back to the legacy token API."""
        create_session = getattr(
            self.auth_service, "create_delegation_session", None
        )
        if callable(create_session):
            session = create_session(user_token, group_id, group_name)
            if isinstance(session, dict):
                return session if session.get("access_token") else None
            if session is None:
                return session

        token = self.auth_service.create_delegation_token(
            user_token, group_id, group_name
        )
        if not token:
            return None
        return {
            "access_token": token,
            "refresh_token": None,
            "expires_in": self.config.jwt_expiry_seconds,
            "chain_id": self._chain_id_for_token(token),
        }

    def _login_user(self, email: str, password: str) -> Optional[str]:
        session = self.auth_service.login_session(email, password)
        if not session:
            return None

        access_token = session.get("access_token")
        if not access_token:
            self.logger.error(f"  ❌ Login response for {email} did not contain an access token")
            return None

        now = self._now()
        self._users[self._user_key(email)] = _UserSession(
            access_token=access_token,
            refresh_token=session.get("refresh_token"),
            expires_at=self._expires_at(access_token, session.get("expires_in"), now),
            issued_at=now,
            chain_id=self._chain_id_for_token(access_token),
        )
        return access_token

    def _expires_at(self, token: str, expires_in: object, now: float) -> float:
        exp = get_exp(token)
        if exp is not None:
            return exp
        try:
            seconds = float(expires_in) if expires_in is not None else 0.0
        except (TypeError, ValueError):
            seconds = 0.0
        if seconds <= 0:
            seconds = 900.0
        return now + seconds

    def _is_expiring(self, issued_at: float, expires_at: float) -> bool:
        remaining = expires_at - self._now()
        ttl = max(expires_at - issued_at, 0.0)
        margin = min(
            self._MAX_REFRESH_MARGIN_SECONDS,
            max(self._MIN_REFRESH_MARGIN_SECONDS, ttl * 0.2),
        )
        return remaining <= margin

    def _chain_id_for_token(self, token: str) -> str:
        claim = extract_claim(token, "default_chain_id", "chain_id", "chainId")
        if claim:
            return str(claim)
        return self.config.chain_id or os.getenv("CHAIN_ID", self._DEFAULT_CHAIN_ID)

    @staticmethod
    def _user_key(email: str) -> str:
        return (email or "").strip().lower()

    def _invalidate_delegations_for_user(self, user_key: str) -> None:
        stale_keys = [key for key in self._delegations if key[0] == user_key]
        for key in stale_keys:
            self._delegations.pop(key, None)
