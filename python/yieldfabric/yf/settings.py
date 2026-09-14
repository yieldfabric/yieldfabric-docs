"""
Configuration resolution for `yf`.

Everything comes from ``YF_*`` environment variables and command-line
flags. The harness's ``PAY_SERVICE_URL`` / ``AUTH_SERVICE_URL`` /
``API_KEY`` namespace and its ``./.env`` auto-load are deliberately NOT
consulted: a public CLI must not pick up a local dev key from whatever
directory it happens to run in. Only an explicit ``--env-file`` is read.

Chain precedence: ``--chain`` > ``YF_CHAIN`` > the bearer's own
``default_chain_id`` (when ``--token``/``YF_TOKEN`` is used) > the stored
login session's chain > ``153`` (the public test chain).
"""

import json
import os
from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional
from urllib.parse import urlsplit

from ..config import YieldFabricConfig
from ..utils.jwt import extract_claim
from .errors import usage

DEFAULT_AUTH_URL = "https://auth.yieldfabric.com"
DEFAULT_AGENTS_URL = "https://agents.yieldfabric.com"
DEFAULT_PAYMENTS_URLS: Dict[str, str] = {
    "153": "https://pay.test.yieldfabric.com",
    "151": "https://pay.live.yieldfabric.com",
}
DEFAULT_CHAIN = "153"
#: Chains on which real value moves. Acting here needs ``--live``.
LIVE_CHAINS = frozenset({"151"})
#: The production live payments host. Pointing ANY chain at it (via
#: ``--payments-url`` / ``YF_PAYMENTS_URLS``) needs ``--live`` too.
LIVE_PAYMENTS_HOSTS = frozenset({"pay.live.yieldfabric.com"})
DEFAULT_TIMEOUT = 30
DEFAULT_CONFIG_DIR = os.path.join("~", ".config", "yf")


def mode_for_chain(chain_id: Optional[str]) -> str:
    """``LIVE`` for a live chain, ``TEST`` otherwise — the same word the
    payments ``whoami`` tool reports for its instance."""
    return "LIVE" if str(chain_id or "") in LIVE_CHAINS else "TEST"


def load_env_file(path: str, env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """
    Load ``KEY=VALUE`` lines from an explicit file into ``env`` (default:
    ``os.environ``) without overriding values already set. Only called
    for ``--env-file`` — never implicitly.
    """
    target = os.environ if env is None else env
    try:
        with open(os.path.expanduser(path), "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        raise usage("env_file_unreadable", f"cannot read --env-file {path}: {exc}")
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key and key not in target:
            target[key] = value
    return target


def parse_payments_urls(raw: Optional[str]) -> Dict[str, str]:
    """
    ``YF_PAYMENTS_URLS`` is a JSON object ``{chain_id: url}`` merged OVER
    the defaults, so overriding one chain keeps the other.
    """
    urls = dict(DEFAULT_PAYMENTS_URLS)
    if not raw or not raw.strip():
        return urls
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise usage("bad_payments_urls", f"YF_PAYMENTS_URLS is not valid JSON: {exc}")
    if not isinstance(parsed, dict):
        raise usage("bad_payments_urls", "YF_PAYMENTS_URLS must be a JSON object {chain_id: url}")
    for chain, url in parsed.items():
        if not isinstance(url, str) or not url.strip():
            raise usage("bad_payments_urls", f"YF_PAYMENTS_URLS[{chain!r}] must be a URL string")
        urls[str(chain).strip()] = url.strip().rstrip("/")
    return urls


@dataclass
class Settings:
    """Resolved configuration for one `yf` invocation."""

    auth_url: str = DEFAULT_AUTH_URL
    agents_url: str = DEFAULT_AGENTS_URL
    payments_urls: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PAYMENTS_URLS))
    #: Explicit ``--payments-url`` override for the resolved chain.
    payments_url_override: Optional[str] = None
    chain_id: str = DEFAULT_CHAIN
    #: Where the chain came from — surfaced in errors so a surprising
    #: chain is explainable (``flag`` | ``env`` | ``token`` | ``session`` | ``default``).
    chain_source: str = "default"
    api_key: Optional[str] = None
    token: Optional[str] = None
    config_dir: str = DEFAULT_CONFIG_DIR
    timeout: int = DEFAULT_TIMEOUT
    live: bool = False
    json_mode: bool = False
    debug: bool = False

    @property
    def is_live(self) -> bool:
        return self.chain_id in LIVE_CHAINS

    @property
    def mode(self) -> str:
        return mode_for_chain(self.chain_id)

    @property
    def session_path(self) -> str:
        return os.path.join(os.path.expanduser(self.config_dir), "session.json")

    def payments_url_or_none(self) -> Optional[str]:
        """The payments host for the resolved chain, or ``None`` when no
        host is configured for it (no error — for callers that may not
        need payments at all)."""
        if self.payments_url_override:
            return self.payments_url_override.rstrip("/")
        url = self.payments_urls.get(self.chain_id)
        return url or None

    def payments_url(self) -> str:
        """The payments host for the resolved chain (``unknown_chain``,
        exit 2, when none is configured)."""
        url = self.payments_url_or_none()
        if not url:
            raise usage(
                "unknown_chain",
                f"no payments host configured for chain {self.chain_id}; "
                f"known chains: {', '.join(sorted(self.payments_urls))}. "
                "Set YF_PAYMENTS_URLS or pass --payments-url.",
            )
        return url

    def payments_host_is_live(self) -> bool:
        """
        True when the payments host the resolved chain maps to is a LIVE
        host: the production live host itself, or any host that
        ``payments_urls`` maps to a live chain. Keys on the HOST, not the
        chain, so ``--chain 153 --payments-url https://pay.live…`` is
        caught by the live guard too.
        """
        url = self.payments_url_or_none()
        if not url:
            return False
        host = _host_of(url)
        if host in LIVE_PAYMENTS_HOSTS:
            return True
        live_hosts = {_host_of(self.payments_urls[c]) for c in LIVE_CHAINS if self.payments_urls.get(c)}
        return bool(host) and host in live_hosts

    def to_config(
        self,
        *,
        delegation_scopes: Optional[list] = None,
        jwt_expiry_seconds: Optional[int] = None,
    ) -> YieldFabricConfig:
        """
        Build the service-client config EXPLICITLY — never
        ``YieldFabricConfig.from_env()``, whose localhost defaults and
        harness env names must not leak into the public CLI.

        The payments URL is resolved lazily: a command that only talks to
        auth or agents (``kg …``) must not fail on ``unknown_chain``, so an
        unconfigured chain yields an empty ``pay_service_url`` here and
        ``Context.payments()`` raises the usage error when — and only when
        — a payments client is actually built.
        """
        kwargs = dict(
            pay_service_url=self.payments_url_or_none() or "",
            auth_service_url=self.auth_url,
            agents_service_url=self.agents_url,
            chain_id=self.chain_id,
            api_key=self.api_key or "",
            command_delay=0,
            debug=self.debug,
            request_timeout=max(1, int(self.timeout)),
        )
        if delegation_scopes is not None:
            kwargs["delegation_scopes"] = list(delegation_scopes)
        if jwt_expiry_seconds is not None:
            kwargs["jwt_expiry_seconds"] = int(jwt_expiry_seconds)
        return YieldFabricConfig(**kwargs)


def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def resolve_settings(
    args,
    env: Optional[Mapping[str, str]] = None,
    *,
    stored_session_chain: Optional[str] = None,
) -> Settings:
    """
    Merge flags over ``YF_*`` env over defaults. ``args`` is the parsed
    argparse namespace (global flags only are read here).
    ``stored_session_chain`` is the chain recorded by ``yf login``, when a
    session file exists — passed in so this module never touches disk.
    """
    env = os.environ if env is None else env

    token = _clean(getattr(args, "token", None)) or _clean(env.get("YF_TOKEN"))
    api_key = _clean(getattr(args, "api_key", None)) or _clean(env.get("YF_API_KEY"))

    chain_source = "default"
    chain = _clean(getattr(args, "chain", None))
    if chain:
        chain_source = "flag"
    else:
        chain = _clean(env.get("YF_CHAIN"))
        if chain:
            chain_source = "env"
        elif token:
            claim = extract_claim(token, "default_chain_id", "chain_id")
            chain = _clean(str(claim)) if claim is not None else None
            if chain:
                chain_source = "token"
        if not chain and stored_session_chain:
            chain = _clean(stored_session_chain)
            chain_source = "session"
        if not chain:
            chain = DEFAULT_CHAIN
            chain_source = "default"
    if not chain.isdigit() or int(chain) <= 0:
        raise usage("bad_chain", f"chain must be a positive decimal chain id, got {chain!r}")

    timeout_raw = getattr(args, "timeout", None)
    if timeout_raw is None:
        timeout_raw = env.get("YF_TIMEOUT")
    try:
        timeout = int(timeout_raw) if timeout_raw not in (None, "") else DEFAULT_TIMEOUT
    except (TypeError, ValueError):
        raise usage("bad_timeout", f"timeout must be an integer number of seconds, got {timeout_raw!r}")
    if timeout < 1:
        raise usage("bad_timeout", "timeout must be at least 1 second")

    return Settings(
        auth_url=(_clean(getattr(args, "auth_url", None)) or _clean(env.get("YF_AUTH_URL")) or DEFAULT_AUTH_URL).rstrip("/"),
        agents_url=(_clean(getattr(args, "agents_url", None)) or _clean(env.get("YF_AGENTS_URL")) or DEFAULT_AGENTS_URL).rstrip("/"),
        payments_urls=parse_payments_urls(env.get("YF_PAYMENTS_URLS")),
        payments_url_override=_clean(getattr(args, "payments_url", None)),
        chain_id=chain,
        chain_source=chain_source,
        api_key=api_key,
        token=token,
        config_dir=_clean(env.get("YF_CONFIG_DIR")) or DEFAULT_CONFIG_DIR,
        timeout=timeout,
        live=bool(getattr(args, "live", False)),
        json_mode=bool(getattr(args, "json", False)),
        debug=bool(getattr(args, "debug", False)) or str(env.get("YF_DEBUG", "")).lower() in ("1", "true", "yes"),
    )


def enforce_live_guard(settings: Settings) -> None:
    """
    Refuse to touch a live chain unless ``--live`` was passed. Runs
    BEFORE any network call. This is a courtesy against accidents, not a
    security boundary: the platform still requires a session minted for
    that chain (and, for connector keys, a key allowed on it).
    """
    if settings.live:
        return
    if settings.is_live:
        raise usage(
            "live_requires_flag",
            f"chain {settings.chain_id} is LIVE (source: {settings.chain_source}); "
            "pass --live to act on it, or choose the test chain with --chain 153.",
        )
    if settings.payments_host_is_live():
        # The chain says TEST but the host is the live one (``--payments-url``
        # or ``YF_PAYMENTS_URLS`` re-pointed it). The platform would refuse a
        # test-chain session there anyway; refuse first, and say why.
        raise usage(
            "live_requires_flag",
            f"the payments host for chain {settings.chain_id} is {settings.payments_url_or_none()}, "
            "a LIVE host; pass --live to act on it, or point the chain at its test host.",
        )
