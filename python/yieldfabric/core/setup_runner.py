"""
Setup runner — system bootstrap from a setup.yaml.

Ports `yieldfabric-docs/scripts/setup_system.sh` to Python: creates
users, groups, tokens, and assets (and optionally fiat accounts) in the
order the shell expects. Every operation is idempotent — 409 Conflict
or "already exists" error messages are treated as success, so this can
be re-run against a partially-seeded environment without damage.

Usage (programmatic):

    config = YieldFabricConfig.from_env()
    with YieldFabricSetupRunner(config) as runner:
        ok = runner.run("../scripts/setup.yaml")

Usage (CLI):

    python -m yieldfabric.cli setup ../scripts/setup.yaml            # full setup
    python -m yieldfabric.cli setup ../scripts/setup.yaml tokens assets
    python -m yieldfabric.cli setup ../scripts/setup.yaml validate   # offline check

Granular phases mirror `setup_system.sh`'s commands one-for-one
(setup/all, users, groups, owners, tokens, assets, fiat, status,
validate). Multiple phases run in the order given, so `tokens assets`
seeds tokens then assets in a single invocation.
"""

import os
import time
from typing import Any, Dict, List, Optional

from ..config import YieldFabricConfig
from ..services import AuthService, PaymentsService
from ..validation import ServiceValidator
from ..utils.jwt import extract_claim, get_sub
from ..utils.logger import get_logger

try:
    import yaml  # type: ignore
except ImportError as _e:  # pragma: no cover — PyYAML is in requirements.txt
    yaml = None  # type: ignore


class YieldFabricSetupRunner:
    """Orchestrator for the system-bootstrap phase.

    The shell performs these steps in order and we mirror them exactly.
    Steps are idempotent: re-running against a seeded env will skip
    items that already exist and only create what's missing.

    1. Validate services (auth + payments reachable).
    2. Parse setup.yaml.
    3. Create users (in order they appear).
    4. For each group:
         a. Login as the group's `user` (creator).
         b. Create the group (409 = exists, skip).
         c. Explicitly activate its account on the creator JWT's chain.
         d. Add any declared members via the creator's owner credential.
    5. If wallet-bound sections exist, lazily activate the provisioning
       principal and refresh its JWT wallet snapshot.
    6. Create tokens and assets under that refreshed admin JWT.
    7. Create fiat accounts (US/UK/AU) if the section exists.

    Each step is also runnable on its own via :meth:`run_phases`, which
    is how the CLI exposes `setup_system.sh`'s granular commands.
    """

    # Canonical phase names — one per `setup_system.sh` command.
    ALL_PHASE = "all"
    PHASES = (
        "all", "users", "groups", "owners",
        "tokens", "assets", "fiat", "status", "validate",
    )
    # Accept a few friendly synonyms (CLI ergonomics + bash parity).
    _PHASE_ALIASES = {
        "setup": "all",
        "fiat_accounts": "fiat",
        "relationships": "owners",
        "user": "users",
        "group": "groups",
        "token": "tokens",
        "asset": "assets",
    }

    def __init__(self, config: Optional[YieldFabricConfig] = None):
        self.config = config or YieldFabricConfig.from_env()
        self.logger = get_logger(debug=self.config.debug)
        self.auth_service = AuthService(self.config)
        self.payments_service = PaymentsService(self.config)
        self.service_validator = ServiceValidator(
            self.auth_service, self.payments_service,
            debug=self.config.debug,
        )

        # user_email → user_id, populated as we create users. Needed for
        # adding members to groups (the auth service requires user IDs,
        # not emails).
        self._user_ids: Dict[str, str] = {}

        # Lazy, cached prerequisites so running several phases in one
        # invocation (e.g. `tokens assets`) doesn't re-validate services,
        # re-create users, or re-acquire the admin token for each phase.
        self._services_ok: Optional[bool] = None
        self._users_ensured: bool = False
        self._admin_session: Optional[Dict[str, Any]] = None
        # Record the exact credential source that succeeded. Refresh tokens are
        # preferred, but this lets us re-authenticate the same principal if an
        # older auth deployment omits one; we must never activate one user and
        # silently fall through to a different admin afterward.
        self._admin_auth_source: Optional[Dict[str, str]] = None
        self._admin_account_failed: bool = False

    # ------------------------------------------------------------------

    @classmethod
    def normalize_phase(cls, name: str) -> str:
        """Lower-case a phase name and resolve any alias (setup→all, …)."""
        n = (name or "").strip().lower()
        return cls._PHASE_ALIASES.get(n, n)

    @classmethod
    def is_known_phase(cls, name: str) -> bool:
        """True if `name` (after alias resolution) is a runnable phase."""
        return cls.normalize_phase(name) in cls.PHASES

    def run(self, setup_file: str) -> bool:
        """
        Full setup from `setup_file` (the `all` phase). Back-compat thin
        wrapper over :meth:`run_phases`. Returns True iff every step
        succeeded (or was idempotently skipped because it already
        existed).
        """
        return self.run_phases(setup_file, [self.ALL_PHASE])

    def run_phases(self, setup_file: str, phases: List[str]) -> bool:
        """
        Run one or more named phases against `setup_file`, in order.

        `phases` is a list of `setup_system.sh`-equivalent command names
        (see :attr:`PHASES`). An empty list defaults to the full setup.
        Phases share cached prerequisites (service validation, admin
        token, user creation) so `["tokens", "assets"]` validates once
        and reuses the same admin token for both.

        Returns True iff every requested phase succeeded.
        """
        if yaml is None:
            self.logger.error("❌ PyYAML is not installed (see requirements.txt)")
            return False

        # Normalise + validate the requested phases up front so a typo
        # fails fast instead of half-running a multi-phase sequence.
        normalized: List[str] = []
        for raw in (phases or [self.ALL_PHASE]):
            name = self.normalize_phase(raw)
            if name not in self.PHASES:
                self.logger.error(
                    f"❌ unknown phase: {raw!r} "
                    f"(valid: {', '.join(self.PHASES)})"
                )
                return False
            normalized.append(name)
        if not normalized:
            normalized = [self.ALL_PHASE]

        setup = self._parse_setup_file(setup_file)
        if setup is None:
            return False

        self.logger.cyan(f"📄 Config file: {setup_file}")
        self.logger.cyan(f"▶  Phases: {', '.join(normalized)}")
        if self.config.chain_id:
            self.logger.cyan(
                f"⛓️  Target chain: {self.config.chain_id} "
                f"(payments: {self.config.pay_service_url})"
            )
        self.logger.separator()

        all_ok = True
        for phase in normalized:
            all_ok &= self._run_one_phase(phase, setup, setup_file)
        return all_ok

    def _run_one_phase(self, phase: str, setup: Dict[str, Any], setup_file: str) -> bool:
        """Dispatch a single normalized phase. Acquires only the
        prerequisites that phase needs (validate/status/owners differ)."""
        # Offline / read-only phases — no services or admin token needed.
        if phase == "validate":
            return self._validate(setup, setup_file)
        if phase == "status":
            return self._status(setup, setup_file)
        if phase == self.ALL_PHASE:
            return self._run_full(setup)

        # Every mutating phase needs the services up.
        if not self._ensure_services():
            return False

        if phase == "users":
            # Provision under the admin JWT when one is available, so elevated
            # roles are accepted. Falls back to None (public path → consumer
            # role only) when no admin credential is configured.
            admin_token = self._ensure_admin(setup)
            ok = self._setup_users(setup.get("users") or [], admin_token)
            self._users_ensured = True
            return ok

        # groups/owners need user_ids to resolve members; tokens/assets/fiat
        # only need users when there's no API key (so first-user admin login
        # works). This mirrors `setup_system.sh` calling create_initial_users
        # before each of those commands.
        needs_user_ids = phase in ("groups", "owners")
        if needs_user_ids or not self.config.api_key:
            self._ensure_users(setup)

        admin_token = self._ensure_admin(setup)
        if not admin_token:
            self.logger.error("❌ Could not acquire an admin token; aborting phase")
            return False

        wallet_items = {
            "tokens": setup.get("tokens") or [],
            "assets": setup.get("assets") or [],
            "fiat": setup.get("fiat_accounts") or [],
        }
        if phase in wallet_items and wallet_items[phase]:
            admin_token = self._ensure_admin_chain_account(setup)
            if not admin_token:
                self.logger.error(
                    f"❌ Skipping {phase}: provisioning account is not ready"
                )
                return False

        if phase == "groups":
            return self._setup_groups(setup.get("groups") or [], admin_token)
        if phase == "owners":
            return self._setup_owners(setup.get("groups") or [], admin_token)
        if phase == "tokens":
            return self._setup_tokens(setup.get("tokens") or [], admin_token)
        if phase == "assets":
            return self._setup_assets(setup.get("assets") or [], admin_token)
        if phase == "fiat":
            return self._setup_fiat_accounts(setup.get("fiat_accounts") or [], admin_token)
        # Unreachable — phase was validated above.
        return False

    def _run_full(self, setup: Dict[str, Any]) -> bool:
        """The complete bootstrap (the `all` phase): users → groups →
        owners → tokens → assets → fiat, in the order the shell expects."""
        self.logger.cyan("🚀 Running system setup")
        if not self._ensure_services():
            return False

        all_ok = True

        # Acquire the admin token FIRST. The public POST /auth/users path no
        # longer accepts elevated roles (SuperAdmin/Admin/…) from an
        # unauthenticated caller, so provisioning the setup.yaml admins — and
        # everything after (groups, tokens, assets, fiat) — needs an admin JWT.
        admin_token = self._ensure_admin(setup)
        if not admin_token:
            self.logger.error(
                "❌ Could not acquire an admin token; aborting. Provisioning "
                "privileged users now requires admin auth — set ADMIN_EMAIL/"
                "ADMIN_PASSWORD to the bootstrap admin (system.yaml "
                "bootstrap_users + BOOTSTRAP_PASSWORD_*), or a valid API_KEY."
            )
            return False

        # 1. Users (created UNDER the admin JWT so elevated roles are allowed).
        self.logger.subsection("👥 Users")
        all_ok &= self._setup_users(setup.get("users") or [], admin_token)
        self._users_ensured = True

        # 2. Groups (create + per-creator login + explicit activation + members).
        self.logger.subsection("🏢 Groups")
        all_ok &= self._setup_groups(setup.get("groups") or [], admin_token)

        # 2b. On-chain account owners / relationships. No-op when no group
        # declares members (the common case for the current setup.yaml),
        # so existing token/asset-only files are unaffected.
        groups = setup.get("groups") or []
        if any((g.get("members") for g in groups)):
            self.logger.subsection("🔗 Group owners")
            all_ok &= self._setup_owners(groups, admin_token)

        tokens = setup.get("tokens") or []
        assets = setup.get("assets") or []
        fiat_accounts = setup.get("fiat_accounts") or []
        wallet_admin_token: Optional[str] = admin_token
        if tokens or assets or fiat_accounts:
            wallet_admin_token = self._ensure_admin_chain_account(setup)
            if not wallet_admin_token:
                all_ok = False

        # 3. Tokens.
        self.logger.subsection("🪙 Tokens")
        if tokens and not wallet_admin_token:
            self.logger.error(
                "  ❌ skipped: provisioning account is not ready"
            )
        else:
            all_ok &= self._setup_tokens(tokens, wallet_admin_token or admin_token)

        # 4. Assets.
        self.logger.subsection("💎 Assets")
        if assets and not wallet_admin_token:
            self.logger.error(
                "  ❌ skipped: provisioning account is not ready"
            )
        else:
            all_ok &= self._setup_assets(assets, wallet_admin_token or admin_token)

        # 5. Fiat accounts (optional — section may be commented out).
        if fiat_accounts:
            self.logger.subsection("🏦 Fiat accounts")
            if not wallet_admin_token:
                self.logger.error(
                    "  ❌ skipped: provisioning account is not ready"
                )
            else:
                all_ok &= self._setup_fiat_accounts(
                    fiat_accounts, wallet_admin_token
                )

        self.logger.separator()
        if all_ok:
            self.logger.success("✅ Setup completed")
        else:
            self.logger.warning("⚠️  Setup completed with some failures")
        return all_ok

    # ------------------------------------------------------------------
    # Cached prerequisites (shared across phases in one invocation).
    # ------------------------------------------------------------------

    def _ensure_services(self) -> bool:
        """Validate auth + payments are reachable (once per runner)."""
        if self._services_ok is None:
            self._services_ok = self.service_validator.validate_services()
        return self._services_ok

    def _ensure_users(self, setup: Dict[str, Any]) -> None:
        """Idempotently create the declared users (once per runner),
        populating `_user_ids` for downstream member resolution. Creates them
        under the admin JWT so elevated roles are accepted."""
        if not self._users_ensured:
            admin_token = self._ensure_admin(setup)
            self._setup_users(setup.get("users") or [], admin_token)
            self._users_ensured = True

    def _ensure_admin(self, setup: Dict[str, Any]) -> Optional[str]:
        """Acquire and cache the admin token bundle (API key or password)."""
        if self._admin_session is None:
            self._admin_session = self._acquire_admin_session(
                setup.get("users") or []
            )
        if not self._admin_session:
            return None
        token = self._admin_session.get("access_token")
        return token if isinstance(token, str) and token else None

    def _renew_admin_session(self, chain_id: str) -> Optional[Dict[str, Any]]:
        """Refresh the same provisioning principal after lazy activation."""
        session = self._admin_session or {}
        refresh_token = session.get("refresh_token")
        if isinstance(refresh_token, str) and refresh_token:
            refreshed = self.auth_service.refresh_access_token(
                refresh_token, chain_id=chain_id
            )
            if refreshed:
                return refreshed
            self.logger.warning(
                "  ⚠️  Provisioning refresh token was unavailable; "
                "re-authenticating the same principal"
            )

        # Compatibility fallback for an older response without a refresh token
        # or a token rotated by another session. Re-present only the credential
        # source that originally won; do not run the preference/fallback chain
        # and risk switching users.
        source = self._admin_auth_source or {}
        if source.get("kind") == "api_key":
            return self.auth_service.authenticate_api_key_session(
                source.get("api_key", "")
            )
        if source.get("kind") == "password":
            return self.auth_service.login_session(
                source.get("email", ""), source.get("password", "")
            )
        return None

    def _ensure_admin_chain_account(
        self, setup: Dict[str, Any]
    ) -> Optional[str]:
        """Lazily activate and refresh the wallet-bound setup principal.

        Token, asset, and fiat registration create auditable transaction
        records signed by the effective JWT account. Login/API-key exchange
        only selects a chain; it intentionally does not deploy an account.
        This preflight performs that activation exactly when a wallet-bound
        setup phase is about to run, then refreshes the JWT because wallet
        claims are immutable snapshots.
        """
        if self._admin_account_failed:
            return None

        token = self._ensure_admin(setup)
        if not token:
            self._admin_account_failed = True
            self.logger.error(
                "❌ Cannot activate provisioning account: admin session unavailable"
            )
            return None

        entity_id = get_sub(token)
        token_chain = extract_claim(
            token, "default_chain_id", "chain_id", "chainId"
        )
        chain_id = self.config.chain_id or (
            str(token_chain) if token_chain is not None else None
        )
        if not entity_id or entity_id.startswith("service:"):
            self._admin_account_failed = True
            self.logger.error(
                "❌ Provisioning credential did not resolve to an activatable user"
            )
            return None
        if not chain_id or str(token_chain or "") != str(chain_id):
            self._admin_account_failed = True
            self.logger.error(
                "❌ Provisioning JWT is not pinned to the configured target chain"
            )
            return None

        account_address = extract_claim(token, "account_address")
        wallet_id = extract_claim(token, "default_wallet_id")
        if (
            isinstance(account_address, str)
            and account_address
            and account_address.lower() != self._ZERO_ADDRESS
            and isinstance(wallet_id, str)
            and wallet_id
        ):
            return token

        self.logger.info(
            f"  🏦 Activating provisioning principal on chain {chain_id}"
        )
        activation = self.auth_service.wait_for_chain_account_activation(
            token,
            "user",
            entity_id,
            str(chain_id),
            attempts=self._ACCT_POLL_ATTEMPTS,
            interval=self._ACCT_POLL_INTERVAL,
        )
        if activation.get("status") != "ready":
            self._admin_account_failed = True
            detail = activation.get("error") or repr(activation)
            self.logger.error(
                f"❌ Provisioning account activation failed on chain {chain_id}: {detail}"
            )
            return None

        refreshed = self._renew_admin_session(str(chain_id))
        if not refreshed:
            self._admin_account_failed = True
            self.logger.error(
                "❌ Provisioning account activated, but its JWT could not be refreshed"
            )
            return None

        fresh_token = refreshed.get("access_token")
        fresh_entity = get_sub(fresh_token) if isinstance(fresh_token, str) else None
        fresh_chain = (
            extract_claim(fresh_token, "default_chain_id", "chain_id", "chainId")
            if isinstance(fresh_token, str)
            else None
        )
        fresh_address = (
            extract_claim(fresh_token, "account_address")
            if isinstance(fresh_token, str)
            else None
        )
        fresh_wallet_id = (
            extract_claim(fresh_token, "default_wallet_id")
            if isinstance(fresh_token, str)
            else None
        )
        if (
            fresh_entity != entity_id
            or str(fresh_chain or "") != str(chain_id)
            or not isinstance(fresh_address, str)
            or not fresh_address
            or fresh_address.lower() == self._ZERO_ADDRESS
            or not isinstance(fresh_wallet_id, str)
            or not fresh_wallet_id
        ):
            self._admin_account_failed = True
            self.logger.error(
                "❌ Refreshed provisioning JWT does not contain the activated "
                f"chain-{chain_id} wallet"
            )
            return None

        self._admin_session = refreshed
        self.logger.success(
            f"  ✅ Provisioning account ready on chain {chain_id}: {fresh_address}"
        )
        return fresh_token

    # ------------------------------------------------------------------
    # Internals.
    # ------------------------------------------------------------------

    def _parse_setup_file(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            with open(path, "r") as fh:
                return yaml.safe_load(fh) or {}
        except FileNotFoundError:
            self.logger.error(f"❌ setup file not found: {path}")
            return None
        except yaml.YAMLError as e:
            self.logger.error(f"❌ YAML parse error: {e}")
            return None

    def _setup_users(
        self,
        users: List[Dict[str, Any]],
        admin_token: Optional[str] = None,
    ) -> bool:
        if not users:
            self.logger.info("  (no users declared)")
            return True

        ok = True
        for user in users:
            email = user.get("id")
            password = user.get("password")
            role = user.get("role", "Operator")
            if not email or not password:
                self.logger.error(f"  ❌ user entry missing id or password: {user}")
                ok = False
                continue

            # Pass the admin JWT so elevated roles (SuperAdmin/Admin/…) are
            # accepted. The public path only allows the consumer default; an
            # unauthenticated create of a privileged role now returns 403.
            result = self.auth_service.create_user(
                email, password, role, admin_token=admin_token
            )
            status = result.get("status")
            user_id = None
            if status == "created":
                user_id = result.get("user_id")
                self.logger.success(f"  ✅ {email} ({role}) created")
            elif status == "exists":
                # Already there — log in to learn the user_id so we can
                # still add them to groups downstream.
                self.logger.info(f"  ⚠️  {email} already exists; logging in to recover user_id")
                user_id = self._login_and_extract_user_id(email, password)
            else:
                self.logger.error(f"  ❌ {email}: {result.get('message')}")
                ok = False
                continue

            if user_id:
                self._user_ids[email] = user_id
                # Setup needs funded/on-chain users, so activate the selected
                # chain explicitly and print the resulting account address.
                if not self._print_user_account_address(user_id, email, password):
                    ok = False
            else:
                self.logger.warning(
                    f"  ⚠️  {email}: no user_id resolved; cannot show account address"
                )
        return ok

    def _login_and_extract_user_id(self, email: str, password: str) -> Optional[str]:
        """
        When a user already exists we can't re-create them to learn their
        ID. Instead log in and decode the JWT `sub` claim.
        """
        jwt = self.auth_service.login(email, password)
        if not jwt:
            return None
        return get_sub(jwt)

    def _acquire_admin_session(
        self, users: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Acquire the admin token bundle used to provision users and perform
        wallet-bound setup. Preference order:

          1. `config.api_key` (API_KEY env) — the canonical backend-service
             auth path. Exchanged for a short-lived JWT via POST /auth/api-key.
             The key owner must have enough permissions (SuperAdmin/Admin)
             for the create-* mutations downstream.
          2. `config.admin_email` / `config.admin_password` (ADMIN_EMAIL /
             ADMIN_PASSWORD env) — the BOOTSTRAP admin. This is the robust
             path: it exists on a fresh DB (seeded at auth boot) before any
             setup.yaml user does, and survives DB resets, so it can mint the
             setup.yaml SuperAdmins on the very first run.
          3. The first user in setup.yaml (conventionally a SuperAdmin),
             logged in with email/password — only works once that user
             already exists.
        """
        if self.config.api_key:
            self.logger.info("  🔑 Using API key for admin token")
            session = self.auth_service.authenticate_api_key_session(
                self.config.api_key
            )
            if session:
                self._admin_auth_source = {
                    "kind": "api_key",
                    "api_key": self.config.api_key,
                }
                return session
            self.logger.warning(
                "  ⚠️  API-key auth failed; trying ADMIN_EMAIL/ADMIN_PASSWORD"
            )

        if self.config.admin_email and self.config.admin_password:
            self.logger.info(
                f"  🔑 Acquiring admin token as {self.config.admin_email} (bootstrap admin)"
            )
            session = self.auth_service.login_session(
                self.config.admin_email, self.config.admin_password
            )
            if session:
                self._admin_auth_source = {
                    "kind": "password",
                    "email": self.config.admin_email,
                    "password": self.config.admin_password,
                }
                return session
            self.logger.warning(
                "  ⚠️  Admin-credential login failed; falling back to first-user login"
            )

        if not users:
            return None
        first = users[0]
        email = first.get("id")
        password = first.get("password")
        if not email or not password:
            return None
        session = self.auth_service.login_session(email, password)
        if session:
            self._admin_auth_source = {
                "kind": "password",
                "email": email,
                "password": password,
            }
        return session

    def _setup_groups(
        self,
        groups: List[Dict[str, Any]],
        admin_token: str,
    ) -> bool:
        if not groups:
            self.logger.info("  (no groups declared)")
            return True

        ok = True
        for group in groups:
            name = group.get("name")
            description = group.get("description") or ""
            group_type = group.get("group_type", "project")
            creator = group.get("user") or {}
            creator_email = creator.get("id")
            creator_password = creator.get("password")

            if not name:
                self.logger.error(f"  ❌ group missing name: {group}")
                ok = False
                continue

            # A group needs a creator identity. If `user` is declared, log
            # in as that user (the group's initial owner). Otherwise fall
            # back to the admin token — works when setup runs under an
            # API key and the key owner is the intended group owner.
            if creator_email and creator_password:
                creator_token = self.auth_service.login(creator_email, creator_password)
                if not creator_token:
                    self.logger.error(
                        f"  ❌ could not log in creator {creator_email} for group {name}"
                    )
                    ok = False
                    continue
            else:
                self.logger.info(
                    f"  ℹ️  group {name} has no user.id/user.password; "
                    f"creating as admin principal"
                )
                creator_token = admin_token

            result = self.auth_service.create_group(
                creator_token, name=name, description=description, group_type=group_type
            )
            status = result.get("status")
            group_id = result.get("group_id")

            if status == "created":
                self.logger.success(f"  ✅ group {name} created (id: {group_id[:8] if group_id else 'N/A'}...)")
            elif status == "exists":
                # Recover the group id by listing.
                group_id = self.auth_service.get_group_id_by_name(creator_token, name)
                self.logger.info(f"  ⚠️  group {name} already exists")
            else:
                self.logger.error(f"  ❌ group {name}: {result.get('message')}")
                ok = False
                continue

            if not group_id:
                self.logger.error(f"  ❌ cannot resolve group_id for {name}; skipping deploy/members")
                ok = False
                continue

            # The creator is the initial owner and therefore the canonical
            # principal for activation and membership changes. An API-key or
            # bootstrap-admin token can identify a different entity.
            ok &= self._activate_group_if_needed(creator_token, name, group_id)

            # Print the deployed group account address — shell parity.
            self._print_group_account_address(creator_token, group_id, name)

            # Add any declared members (optional — commented out in current setup.yaml).
            members = group.get("members") or []
            for m in members:
                m_email = m.get("id")
                m_role = m.get("role", "member")
                if not m_email:
                    continue
                m_user_id = self._user_ids.get(m_email)
                if not m_user_id:
                    # Best-effort login to recover.
                    m_pw = m.get("password")
                    if m_pw:
                        m_user_id = self._login_and_extract_user_id(m_email, m_pw)
                if not m_user_id:
                    self.logger.error(
                        f"  ❌ member {m_email}: unknown user_id (was the user created?)"
                    )
                    ok = False
                    continue
                res = self.auth_service.add_group_member(
                    creator_token, group_id, m_user_id, m_role
                )
                if res.get("status") in ("added", "exists"):
                    self.logger.success(f"    ✅ member {m_email} ({m_role})")
                else:
                    self.logger.error(f"    ❌ member {m_email}: {res.get('message')}")
                    ok = False
        return ok

    def _activate_group_if_needed(
        self, creator_token: str, name: str, group_id: str
    ) -> bool:
        chain_id = extract_claim(creator_token, "default_chain_id")
        if not isinstance(chain_id, str) or not chain_id:
            self.logger.error(
                f"  ❌ group {name}: creator session has no active chain"
            )
            return False

        state = self.auth_service.wait_for_chain_account_activation(
            creator_token,
            "group",
            group_id,
            chain_id,
            attempts=self._ACCT_POLL_ATTEMPTS,
            interval=self._ACCT_POLL_INTERVAL,
        )
        status = state.get("status")
        if status == "ready":
            self.logger.success(
                f"  ✅ group {name} account ready on chain {chain_id}"
            )
            return True
        if status == "pending_signature":
            self.logger.warning(
                f"  ⚠️  group {name} activation awaits a wallet signature"
            )
        elif status == "failed_retryable":
            self.logger.error(
                f"  ❌ group {name} activation failed: "
                f"{state.get('error', 'unknown error')}"
            )
        else:
            self.logger.error(
                f"  ❌ group {name} activation did not become ready: {state!r}"
            )
        return False

    # ------------------------------------------------------------------
    # Deployed account-address reporting — parity with setup_system.sh's
    # print_user_account_address / print_group_account_address.
    #
    # User login is intentionally off-chain. Setup explicitly activates the
    # JWT-selected chain because later setup phases fund/use these accounts.
    # Groups use the same explicit, chain-qualified activation lifecycle.
    # ------------------------------------------------------------------

    _ACCT_POLL_ATTEMPTS = 60       # ~120s reconciliation window after POST returns
    _ACCT_POLL_INTERVAL = 2.0
    _ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

    def _print_user_account_address(
        self, user_id: str, email: str, password: str
    ) -> bool:
        """
        Log in as the user, explicitly activate the JWT-selected chain, and
        print the resulting smart-account address.

        The chain-accounts endpoint forbids reading another user's
        accounts, so this reads with the user's OWN token — exactly as
        the shell does.
        """
        token = self.auth_service.login(email, password)
        if not token:
            self.logger.warning("      🏦 account: (login failed; cannot read address)")
            return False
        chain_id = extract_claim(token, "default_chain_id")
        if not isinstance(chain_id, str) or not chain_id:
            self.logger.warning("      🏦 account: (session has no active chain)")
            return False
        activation = self.auth_service.wait_for_chain_account_activation(
            token,
            "user",
            user_id,
            chain_id,
            attempts=self._ACCT_POLL_ATTEMPTS,
            interval=self._ACCT_POLL_INTERVAL,
        )
        addr = activation.get("account_address")
        chain = activation.get("chain_id") or chain_id
        if addr:
            self.logger.purple(f"      🏦 account: {addr} (chain {chain})")
            return True
        if activation.get("status") == "failed_retryable":
            self.logger.warning(
                f"      🏦 activation failed: {activation.get('error', 'unknown error')}"
            )
        self.logger.warning("      🏦 account: (not on chain yet)")
        return False

    def _print_group_account_address(
        self, token: str, group_id: str, name: str
    ) -> None:
        """Print the group account from its chain-qualified activation resource."""
        chain_id = extract_claim(token, "default_chain_id")
        if not isinstance(chain_id, str) or not chain_id:
            self.logger.warning("      🏦 account: (session has no active chain)")
            return
        for attempt in range(self._ACCT_POLL_ATTEMPTS):
            info = self.auth_service.get_chain_account_activation(
                token, "group", group_id, chain_id
            )
            addr = info.get("account_address")
            status = info.get("status")
            if addr and addr != self._ZERO_ADDRESS:
                suffix = f" ({status})" if status else ""
                self.logger.purple(f"      🏦 account: {addr}{suffix}")
                return
            if attempt < self._ACCT_POLL_ATTEMPTS - 1:
                time.sleep(self._ACCT_POLL_INTERVAL)
        self.logger.warning("      🏦 account: (not on chain yet)")

    @staticmethod
    def _normalize_eth_address(value: Any) -> str:
        """
        Coerce a YAML-parsed address back to canonical 0x + 40-hex.

        PyYAML's safe_load parses an unquoted `0x03420F…` as a Python int
        (it's a valid hex literal), so by the time we see it the `0x`
        prefix and any leading zeros are gone and the value is an int.
        Rebuild the 20-byte (40 hex char) representation. Strings are
        passed through (lower-cased, 0x-prefixed) so a quoted YAML value
        still works.
        """
        if value is None:
            return ""
        if isinstance(value, int):
            # 20-byte address → 40 hex chars, zero-padded.
            return "0x" + format(value, "040x")
        s = str(value).strip()
        if not s:
            return ""
        if s.lower().startswith("0x"):
            return "0x" + s[2:]
        return "0x" + s

    def _setup_tokens(self, tokens: List[Dict[str, Any]], admin_token: str) -> bool:
        ok = True
        for t in tokens:
            token_id = t.get("id")
            name = t.get("name")
            description = t.get("description") or ""
            address = self._normalize_eth_address(t.get("address"))
            chain_id = str(t.get("chain_id") or "")
            if not (token_id and name and address and chain_id):
                self.logger.error(f"  ❌ token entry missing required fields: {t}")
                ok = False
                continue
            res = self.payments_service.create_token(
                admin_token,
                token_id=token_id,
                name=name,
                description=description,
                chain_id=chain_id,
                address=address,
            )
            status = res.get("status")
            if status in ("created", "exists"):
                icon = "✅" if status == "created" else "⚠️ "
                self.logger.success(f"  {icon} token {name} ({token_id}) {status}")
            else:
                self.logger.error(f"  ❌ token {token_id}: {res.get('message')}")
                ok = False
        return ok

    def _setup_assets(self, assets: List[Dict[str, Any]], admin_token: str) -> bool:
        ok = True
        for a in assets:
            name = a.get("name")
            description = a.get("description") or ""
            asset_type = a.get("type") or a.get("asset_type")
            currency = a.get("currency")
            token_id = a.get("token_id")
            if not (name and asset_type and currency and token_id):
                self.logger.error(f"  ❌ asset entry missing required fields: {a}")
                ok = False
                continue
            res = self.payments_service.create_asset(
                admin_token,
                name=name,
                description=description,
                asset_type=asset_type,
                currency=currency,
                token_id=token_id,
            )
            status = res.get("status")
            if status in ("created", "exists"):
                icon = "✅" if status == "created" else "⚠️ "
                self.logger.success(f"  {icon} asset {name} {status}")
            else:
                self.logger.error(f"  ❌ asset {name}: {res.get('message')}")
                ok = False
        return ok

    def _setup_fiat_accounts(
        self,
        accounts: List[Dict[str, Any]],
        admin_token: str,
    ) -> bool:
        """
        Accounts are keyed by currency/country to pick the right mutation:
          currency=USD                       → create_us_bank_account (routing_number + account_number)
          currency=GBP                       → create_uk_bank_account (sort_code + account_number)
          currency=AUD (or country starts AU)→ create_au_bank_account (bsb + account_number)

        This is a minimum-viable port; the shell has more permutations.
        """
        ok = True
        for acct in accounts:
            currency = (acct.get("currency") or "").upper()
            inputs = {
                "account_id": acct.get("id"),
                "asset_id": acct.get("asset"),
                "country": acct.get("country"),
                "currency": currency,
                "account_holder_name": acct.get("holder"),
                "iban": acct.get("iban"),
                "account_number": acct.get("account_number"),
            }
            if currency == "USD":
                inputs["routing_number"] = acct.get("routing_number")
                inputs["country"] = inputs["country"] or "US"
                res = self.payments_service.create_us_bank_account(admin_token, **inputs)
            elif currency == "GBP":
                inputs["sort_code"] = acct.get("sort_code")
                inputs["country"] = inputs["country"] or "GB"
                res = self.payments_service.create_uk_bank_account(admin_token, **inputs)
            elif currency == "AUD":
                inputs["bsb"] = acct.get("bsb")
                inputs["country"] = inputs["country"] or "AU"
                res = self.payments_service.create_au_bank_account(admin_token, **inputs)
            else:
                self.logger.error(f"  ❌ fiat_account currency {currency!r} not supported")
                ok = False
                continue

            status = res.get("status")
            if status in ("created", "exists"):
                icon = "✅" if status == "created" else "⚠️ "
                self.logger.success(f"  {icon} fiat account {inputs['account_id']} {status}")
            else:
                self.logger.error(f"  ❌ fiat account {inputs['account_id']}: {res.get('message')}")
                ok = False
        return ok

    def _setup_owners(
        self,
        groups: List[Dict[str, Any]],
        admin_token: str,
    ) -> bool:
        """
        The `owners` phase — port of `setup_system.sh`'s
        `setup_group_relationships`.

        For each declared group: resolve its real UUID by name (YAML ids
        are human labels, not UUIDs), explicitly activate the creator JWT's
        chain account, then for every declared member add them BOTH as a group
        member (role-scoped) AND as an on-chain account owner. The
        add-owner call uses a group-scoped delegation JWT, matching the
        shell's `add_member_as_owner`.

        Idempotent: re-adding an existing member/owner is a no-op on the
        backend. Safe to run standalone (assumes groups already exist;
        creates a missing group on the fly to mirror the shell).
        """
        if not groups:
            self.logger.info("  (no groups declared)")
            return True

        ok = True
        for group in groups:
            name = group.get("name")
            if not name:
                self.logger.error(f"  ❌ group missing name: {group}")
                ok = False
                continue

            members = group.get("members") or []

            # Resolve the initial owner's credential before any create or
            # activation call. The bootstrap/API-key token is only a fallback
            # when the YAML intentionally omits a creator.
            creator = group.get("user") or {}
            member_token = admin_token
            if creator.get("id") and creator.get("password"):
                ct = self.auth_service.login(creator["id"], creator["password"])
                if not ct:
                    self.logger.error(
                        f"  ❌ could not log in creator {creator['id']} for {name}"
                    )
                    ok = False
                    continue
                member_token = ct

            # Resolve the real group UUID by name.
            group_id = self.auth_service.get_group_id_by_name(admin_token, name)
            if not group_id:
                # Mirror the shell: try to create it, then re-resolve.
                self.auth_service.create_group(
                    member_token,
                    name=name,
                    description=group.get("description") or "",
                    group_type=group.get("group_type", "project"),
                )
                group_id = self.auth_service.get_group_id_by_name(admin_token, name)
            if not group_id:
                self.logger.error(f"  ❌ could not resolve group id for {name}; skipping")
                ok = False
                continue

            # The account must be ready before owners can be added.
            if not self._activate_group_if_needed(member_token, name, group_id):
                ok = False
                continue

            if not members:
                self.logger.info(f"  ℹ️  group {name} has no members; nothing to own")
                continue

            # add-owner expects a group-scoped delegation JWT.
            delegation = self.auth_service.create_delegation_token(
                member_token, group_id, name
            )
            owner_token = delegation or member_token

            for m in members:
                m_email = m.get("id")
                m_role = m.get("role", "member")
                if not m_email:
                    continue
                m_user_id = self._user_ids.get(m_email)
                if not m_user_id and m.get("password"):
                    m_user_id = self._login_and_extract_user_id(m_email, m["password"])
                if not m_user_id:
                    self.logger.error(
                        f"    ❌ member {m_email}: unknown user_id (was the user created?)"
                    )
                    ok = False
                    continue

                # 1. Group membership (role-scoped, idempotent).
                self.auth_service.add_group_member(
                    member_token, group_id, m_user_id, m_role
                )
                # 2. On-chain account owner.
                res = self.auth_service.add_group_owner(owner_token, group_id, m_user_id)
                if res.get("status") == "error":
                    self.logger.warning(
                        f"    ⚠️  owner {m_email}: {res.get('message')}"
                    )
                    ok = False
                else:
                    self.logger.success(f"    ✅ owner {m_email} ({m_role})")
        return ok

    # ------------------------------------------------------------------
    # Read-only / offline phases (validate, status).
    # ------------------------------------------------------------------

    def validate(self, setup_file: str) -> bool:
        """Public entry: parse + structurally validate a setup file
        (offline). Returns True iff the structure is valid."""
        setup = self._parse_setup_file(setup_file)
        if setup is None:
            return False
        return self._validate(setup, setup_file)

    def show_status(self, setup_file: str) -> bool:
        """Public entry: parse + print a status summary."""
        setup = self._parse_setup_file(setup_file)
        if setup is None:
            return False
        return self._status(setup, setup_file)

    def _validate(self, setup: Dict[str, Any], setup_file: str) -> bool:
        """
        Offline structural validation — port of `validate_setup_file`.
        Checks required fields per item across every section. No network
        calls. Returns True iff there are no errors.
        """
        self.logger.cyan(f"🔍 Validating {os.path.basename(setup_file)}...")

        users = setup.get("users") or []
        groups = setup.get("groups") or []
        tokens = setup.get("tokens") or []
        assets = setup.get("assets") or []
        fiat = setup.get("fiat_accounts") or []

        errors: List[str] = []
        valid_member_roles = {"owner", "admin", "member", "viewer", "policymember"}
        valid_fiat_currencies = {"USD", "GBP", "AUD"}

        if not (users or groups or tokens or assets or fiat):
            errors.append(
                "file declares none of: users, groups, tokens, assets, fiat_accounts"
            )

        for i, u in enumerate(users):
            if not u.get("id"):
                errors.append(f"users[{i}]: missing id (email)")
            if not u.get("password"):
                errors.append(f"users[{i}]: missing password")

        for i, g in enumerate(groups):
            if not g.get("name"):
                errors.append(f"groups[{i}]: missing name")
            for j, m in enumerate(g.get("members") or []):
                if not m.get("id"):
                    errors.append(f"groups[{i}].members[{j}]: missing id")
                role = (m.get("role") or "").lower()
                if role and role not in valid_member_roles:
                    errors.append(
                        f"groups[{i}].members[{j}]: invalid role {m.get('role')!r} "
                        f"(valid: {', '.join(sorted(valid_member_roles))})"
                    )

        for i, t in enumerate(tokens):
            for field in ("id", "name", "chain_id", "address"):
                if t.get(field) in (None, ""):
                    errors.append(f"tokens[{i}]: missing {field}")

        for i, a in enumerate(assets):
            if not (a.get("type") or a.get("asset_type")):
                errors.append(f"assets[{i}]: missing type")
            for field in ("name", "currency", "token_id"):
                if a.get(field) in (None, ""):
                    errors.append(f"assets[{i}]: missing {field}")

        for i, fa in enumerate(fiat):
            if not fa.get("id"):
                errors.append(f"fiat_accounts[{i}]: missing id")
            currency = (fa.get("currency") or "").upper()
            if currency not in valid_fiat_currencies:
                errors.append(
                    f"fiat_accounts[{i}]: unsupported currency {fa.get('currency')!r} "
                    f"(supported: USD, GBP, AUD)"
                )

        self.logger.info(
            f"  users={len(users)} groups={len(groups)} tokens={len(tokens)} "
            f"assets={len(assets)} fiat={len(fiat)}"
        )
        if errors:
            self.logger.error(f"  ❌ {len(errors)} validation error(s):")
            for err in errors:
                self.logger.error(f"    - {err}")
            return False
        self.logger.success("  ✅ setup file is structurally valid")
        return True

    def _status(self, setup: Dict[str, Any], setup_file: str) -> bool:
        """
        Read-only status summary — port of `show_setup_status`. Reports
        service reachability (best-effort, non-fatal) plus a count of
        each section. Always returns True (informational).
        """
        self.logger.cyan("📊 Setup status")

        # Service reachability — informational, never fails the phase, and
        # uses the validator directly so it doesn't poison the cached flag.
        self.service_validator.validate_services()

        users = setup.get("users") or []
        groups = setup.get("groups") or []
        tokens = setup.get("tokens") or []
        assets = setup.get("assets") or []
        fiat = setup.get("fiat_accounts") or []

        self.logger.info(f"  📄 file: {setup_file}")
        self.logger.info(f"  👥 users:  {len(users)}")
        self.logger.info(f"  🏢 groups: {len(groups)}")
        for g in groups:
            members = g.get("members") or []
            self.logger.info(f"     - {g.get('name')} ({len(members)} member(s))")
        self.logger.info(f"  🪙 tokens: {len(tokens)}")
        self.logger.info(f"  💎 assets: {len(assets)}")
        self.logger.info(f"  🏦 fiat:   {len(fiat)}")
        self.logger.info(f"  🔑 API key configured: {bool(self.config.api_key)}")
        return True

    def close(self):
        self.auth_service.close()
        self.payments_service.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
