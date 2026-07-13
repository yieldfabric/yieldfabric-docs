"""
Workflow configuration: dataclasses built from env, similar in spirit to nc_acacia.yaml
where each command has a clear type and parameters. Scripts load one config object instead
of scattering os.environ.get().
"""

import os
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .config import (
    ACTION_ISSUE_SWAP,
    ACTION_ISSUE_SWAP_COMPLETE,
    parse_bool_env,
    parse_bool_env_with_mode_default,
)


def _env(key: str, default: str) -> str:
    """Get env var with default; strip whitespace. Single place for common URL/denom defaults."""
    return os.environ.get(key, default).strip()


@dataclass(frozen=True)
class IssueWorkflowConfig:
    """Configuration for the issue (composed contract) workflow (one source of truth from env)."""

    script_dir: Path
    pay_service_url: str
    auth_service_url: str
    user_email: str
    password: str
    csv_file: str
    action_mode: str
    denomination: str
    counterpart: str
    swap_counterparty: str
    payment_denomination: str
    env_payment_amount: str
    env_deadline: str
    acceptor_email: str
    acceptor_password: str
    max_loans: int
    deploy_issuer: bool
    deploy_acceptor: bool
    deploy_per_loan: bool
    mint_before_env: bool
    burn_after_env: bool
    policy_secret: str
    burn_amount: str
    ensure_issuer_key: bool
    issuer_external_key_file: str
    issuer_external_key_name: str
    workflow_poll_timeout_sec: float
    workflow_poll_interval_sec: float
    swap_poll_timeout_sec: float
    swap_poll_interval_sec: float
    require_manual_signature: bool

    @classmethod
    def from_env(
        cls,
        script_dir: Path,
        csv_file: str,
        user_email_override: Optional[str] = None,
        password_override: Optional[str] = None,
        action_mode_override: Optional[str] = None,
    ) -> "IssueWorkflowConfig":
        """Build config from environment; CLI args (user, password, action_mode) override env when provided."""
        pay = _env("PAY_SERVICE_URL", "https://pay.test.yieldfabric.com")
        auth = _env("AUTH_SERVICE_URL", "https://auth.yieldfabric.com")
        denom = _env("DENOMINATION", "aud-token-asset")
        user_email = user_email_override or (
            os.environ.get("ISSUER_EMAIL", "").strip() or os.environ.get("USER_EMAIL", "").strip()
        )
        password = password_override or (
            os.environ.get("ISSUER_PASSWORD", "").strip() or os.environ.get("PASSWORD", "").strip()
        )
        action_mode = action_mode_override or os.environ.get("ACTION_MODE", "").strip().lower() or "issue_only"
        if action_mode not in ("issue_only", "issue_swap", "issue_swap_complete"):
            action_mode = "issue_only"
        try:
            max_loans = int(os.environ.get("LOAN_COUNT", "10").strip())
            if max_loans < 1:
                max_loans = 10
        except ValueError:
            max_loans = 10
        deploy_issuer = parse_bool_env("DEPLOY_ISSUER_ACCOUNT") or parse_bool_env_with_mode_default(
            "DEPLOY_ISSUER_ACCOUNT", action_mode, default_for_swap_complete=True
        )
        acceptor_email = os.environ.get("ACCEPTOR_EMAIL", "").strip()
        acceptor_password = os.environ.get("ACCEPTOR_PASSWORD", "").strip()
        deploy_acceptor = (
            parse_bool_env("DEPLOY_ACCEPTOR_ACCOUNT")
            or parse_bool_env_with_mode_default(
                "DEPLOY_ACCEPTOR_ACCOUNT", action_mode, default_for_swap_complete=True
            )
        ) and bool(acceptor_email and acceptor_password)
        deploy_per_loan = parse_bool_env("DEPLOY_ACCOUNT_PER_LOAN") or (
            action_mode in (ACTION_ISSUE_SWAP, ACTION_ISSUE_SWAP_COMPLETE)
            and os.environ.get("DEPLOY_ACCOUNT_PER_LOAN", "").strip().lower()
            not in ("false", "0", "no")
        )
        key_file = os.environ.get("ISSUER_EXTERNAL_KEY_FILE", "").strip()
        key_name = os.environ.get("ISSUER_EXTERNAL_KEY_NAME", "Issuer script external key").strip()
        try:
            workflow_poll_timeout = float(os.environ.get("WORKFLOW_POLL_TIMEOUT_SEC", "120").strip())
            if workflow_poll_timeout <= 0:
                workflow_poll_timeout = 120.0
        except ValueError:
            workflow_poll_timeout = 120.0
        try:
            workflow_poll_interval = float(os.environ.get("WORKFLOW_POLL_INTERVAL_SEC", "1").strip())
            if workflow_poll_interval <= 0:
                workflow_poll_interval = 1.0
        except ValueError:
            workflow_poll_interval = 1.0
        try:
            swap_poll_timeout = float(os.environ.get("SWAP_POLL_TIMEOUT_SEC", "120").strip())
            if swap_poll_timeout <= 0:
                swap_poll_timeout = 120.0
        except ValueError:
            swap_poll_timeout = 120.0
        try:
            swap_poll_interval = float(os.environ.get("SWAP_POLL_INTERVAL_SEC", "2").strip())
            if swap_poll_interval <= 0:
                swap_poll_interval = 2.0
        except ValueError:
            swap_poll_interval = 2.0
        return cls(
            script_dir=script_dir,
            pay_service_url=pay,
            auth_service_url=auth,
            user_email=user_email or "none",
            password=password or "none",
            csv_file=csv_file,
            action_mode=action_mode,
            denomination=denom,
            counterpart=os.environ.get("COUNTERPART", "issuer@yieldfabric.com").strip(),
            swap_counterparty=os.environ.get("SWAP_COUNTERPARTY", "originator@yieldfabric.com").strip(),
            payment_denomination=os.environ.get("PAYMENT_DENOMINATION", denom).strip(),
            env_payment_amount=os.environ.get("PAYMENT_AMOUNT", "").strip(),
            env_deadline=os.environ.get("DEADLINE", "").strip(),
            acceptor_email=acceptor_email,
            acceptor_password=acceptor_password,
            max_loans=max_loans,
            deploy_issuer=deploy_issuer,
            deploy_acceptor=deploy_acceptor,
            deploy_per_loan=deploy_per_loan,
            mint_before_env=parse_bool_env("MINT_BEFORE_LOANS"),
            burn_after_env=parse_bool_env("BURN_AFTER_LOANS"),
            policy_secret=os.environ.get("POLICY_SECRET", "").strip(),
            burn_amount=os.environ.get("BURN_AMOUNT", "").strip(),
            ensure_issuer_key=parse_bool_env("ENSURE_ISSUER_EXTERNAL_KEY"),
            issuer_external_key_file=key_file or str(script_dir / "issuer_external_key.txt"),
            issuer_external_key_name=key_name,
            workflow_poll_timeout_sec=workflow_poll_timeout,
            workflow_poll_interval_sec=workflow_poll_interval,
            swap_poll_timeout_sec=swap_poll_timeout,
            swap_poll_interval_sec=swap_poll_interval,
            require_manual_signature=parse_bool_env("REQUIRE_MANUAL_SIGNATURE"),
        )


@dataclass(frozen=True)
class PaymentWorkflowConfig:
    """Configuration for the payment workflow (one source of truth from env)."""

    script_dir: Path
    pay_service_url: str
    auth_service_url: str
    denomination: str
    acceptor_email: str
    acceptor_password: str
    issuer_email: str
    issuer_password: str
    csv_file: str
    payment_count: int
    swap_deadline: str
    accept_all_poll_interval_sec: float
    accept_all_timeout_sec: float
    require_manual_signature: bool
    ensure_issuer_key: bool
    issuer_external_key_file: str
    issuer_external_key_name: str
    investor_external_key_file: str
    investor_external_key_name: str

    @classmethod
    def from_env(cls, script_dir: Path, csv_file: str) -> "PaymentWorkflowConfig":
        """Build config from environment (and default csv path)."""
        pay = _env("PAY_SERVICE_URL", "https://pay.test.yieldfabric.com")
        auth = _env("AUTH_SERVICE_URL", "https://auth.yieldfabric.com")
        denom = _env("DENOMINATION", "aud-token-asset")
        try:
            count = int(os.environ.get("PAYMENT_COUNT", "100").strip())
            if count < 1:
                count = 100
        except ValueError:
            count = 100
        swap_deadline_raw = os.environ.get("SWAP_DEADLINE", "").strip()
        if swap_deadline_raw:
            swap_deadline = swap_deadline_raw
        else:
            swap_deadline = (
                (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            )
        try:
            poll_interval = float(os.environ.get("ACCEPT_ALL_POLL_INTERVAL_SEC", "2").strip())
            if poll_interval <= 0:
                poll_interval = 2.0
        except ValueError:
            poll_interval = 2.0
        try:
            poll_timeout = float(os.environ.get("ACCEPT_ALL_TIMEOUT_SEC", "90").strip())
            if poll_timeout <= 0:
                poll_timeout = 90.0
        except ValueError:
            poll_timeout = 90.0
        issuer_key_file = os.environ.get("ISSUER_EXTERNAL_KEY_FILE", "").strip()
        if not issuer_key_file:
            issuer_key_file = str(script_dir / "issuer_external_key.txt")
        key_name = os.environ.get("ISSUER_EXTERNAL_KEY_NAME", "Issuer script external key").strip()
        investor_key_file = os.environ.get("INVESTOR_EXTERNAL_KEY_FILE", "").strip()
        if not investor_key_file:
            investor_key_file = str(script_dir / "investor_external_key.txt")
        investor_key_name = os.environ.get("INVESTOR_EXTERNAL_KEY_NAME", "Investor script external key").strip()
        return cls(
            script_dir=script_dir,
            pay_service_url=pay,
            auth_service_url=auth,
            denomination=denom,
            acceptor_email=os.environ.get("ACCEPTOR_EMAIL", "").strip(),
            acceptor_password=os.environ.get("ACCEPTOR_PASSWORD", "").strip(),
            issuer_email=os.environ.get("ISSUER_EMAIL", "").strip(),
            issuer_password=os.environ.get("ISSUER_PASSWORD", "").strip(),
            csv_file=csv_file,
            payment_count=count,
            swap_deadline=swap_deadline,
            accept_all_poll_interval_sec=poll_interval,
            accept_all_timeout_sec=poll_timeout,
            require_manual_signature=parse_bool_env("REQUIRE_MANUAL_SIGNATURE"),
            ensure_issuer_key=parse_bool_env("ENSURE_ISSUER_EXTERNAL_KEY"),
            issuer_external_key_file=issuer_key_file,
            issuer_external_key_name=key_name,
            investor_external_key_file=investor_key_file,
            investor_external_key_name=investor_key_name,
        )
