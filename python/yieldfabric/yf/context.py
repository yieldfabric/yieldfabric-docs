"""
Per-invocation context handed to every subcommand: resolved settings,
lazily constructed service clients, and the resolved session.
"""

from typing import Any, Dict, Optional

from ..services.agents_service import AgentsService
from ..services.auth_service import AuthService
from ..services.payments_service import PaymentsService
from . import errors
from .output import emit_ok
from .session import Session, SessionStore, resolve_session
from .settings import Settings

#: Subcommands that submit chain work or mint credentials. A connector
#: session (``session_kind: connector``) is stripped of the permissions
#: these need, so the CLI refuses up front with a precise reason instead
#: of surfacing a bare 403 from the platform. This set is the ONLY place
#: the gate is decided: ``Context.session()`` consults it by the command
#: name (``"<command>"`` or ``"<command> <subcommand>"``, as ``main``
#: names it), so a new write command is gated by being listed here, not
#: by remembering a flag at each call site.
WRITE_COMMANDS = frozenset({
    "send",
    "accept-all",
    "obligation create",
    "obligation accept",
    "group delegate",
})


def is_write_command(command: str) -> bool:
    return command in WRITE_COMMANDS


class Context:
    def __init__(self, settings: Settings, command: str):
        self.settings = settings
        self.command = command
        self._auth: Optional[AuthService] = None
        self._payments: Optional[PaymentsService] = None
        self._agents: Optional[AgentsService] = None
        self._session: Optional[Session] = None
        self.store = SessionStore(settings.session_path)

    # ── clients ───────────────────────────────────────────────────────

    def auth(self, **config_overrides: Any) -> AuthService:
        if config_overrides:
            return AuthService(self.settings.to_config(**config_overrides))
        if self._auth is None:
            self._auth = AuthService(self.settings.to_config())
        return self._auth

    def payments(self) -> PaymentsService:
        if self._payments is None:
            # ``to_config`` tolerates a chain with no payments host so that
            # auth/agents-only commands work; a payments client cannot.
            self.settings.payments_url()
            self._payments = PaymentsService(self.settings.to_config())
        return self._payments

    def agents(self) -> AgentsService:
        if self._agents is None:
            self._agents = AgentsService(self.settings.to_config())
        return self._agents

    # ── session ───────────────────────────────────────────────────────

    def session(self) -> Session:
        """
        The resolved session. For a command in ``WRITE_COMMANDS`` a
        connector session is refused here (``connector_cannot_write``,
        exit 4) before any request is sent.
        """
        if self._session is None:
            self._session = resolve_session(self.settings, self._auth, store=self.store)
        session = self._session
        if is_write_command(self.command) and session.is_connector:
            raise errors.auth(
                "connector_cannot_write",
                f"`yf {self.command}` submits work the platform executes, and this session is a "
                "connector session (read/propose only). Use a personal API key "
                "(POST /auth/api-key/generate, the default kind) or `yf login` with email/password.",
            )
        return session

    @property
    def token(self) -> str:
        return self.session().access_token

    # ── output ────────────────────────────────────────────────────────

    def ok(self, data: Dict[str, Any], *, chain: bool = True) -> int:
        return emit_ok(
            self.command,
            data,
            json_mode=self.settings.json_mode,
            chain_id=self.settings.chain_id if chain else None,
            mode=self.settings.mode if chain else None,
        )
