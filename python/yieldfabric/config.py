"""
Configuration management for YieldFabric
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class YieldFabricConfig:
    """Configuration for YieldFabric services and execution."""
    
    # Service URLs — defaults to LOCALHOST so the CLI works out of the
    # box against a dev backend. Override with env vars (PAY_SERVICE_URL,
    # AUTH_SERVICE_URL) to target a remote environment.
    pay_service_url: str = field(
        default_factory=lambda: os.getenv('PAY_SERVICE_URL', 'http://localhost:3002')
    )
    auth_service_url: str = field(
        default_factory=lambda: os.getenv('AUTH_SERVICE_URL', 'http://localhost:3000')
    )
    # Agents service hosts the federated deal-flow GraphQL (`dealFlow { … }`)
    # at `<agents_url>/graphql` on :3001 — NOT the payments :3002 graphql.
    # Deal-lifecycle commands (propose/sign/automation/periods) target it.
    agents_service_url: str = field(
        default_factory=lambda: os.getenv('AGENTS_SERVICE_URL', 'http://localhost:3001')
    )

    # API key for backend-service authentication (preferred over
    # email/password for non-interactive callers like setup). When set,
    # the runner exchanges it for a short-lived JWT at boot via
    # POST /auth/api-key. Issue one once with POST /auth/api-key/generate
    # and store the returned `yf_api_…` value here / in API_KEY. Empty
    # string means "not configured" — fall back to email/password.
    api_key: str = field(
        default_factory=lambda: os.getenv('API_KEY', '')
    )

    # Explicit admin credentials for provisioning. Since the auth service now
    # rejects elevated roles (SuperAdmin/Admin/…) from unauthenticated
    # callers, creating the privileged users a setup.yaml declares requires an
    # admin JWT. The cleanest stable source is the BOOTSTRAP admin (seeded at
    # auth boot from system.yaml::bootstrap_users + BOOTSTRAP_PASSWORD_*),
    # which survives DB resets and exists on a fresh DB before any setup.yaml
    # user does. Set ADMIN_EMAIL / ADMIN_PASSWORD to those bootstrap creds.
    # Empty means "not configured" — the runner falls back to API key, then
    # to logging in the first setup.yaml user.
    admin_email: str = field(
        default_factory=lambda: os.getenv('ADMIN_EMAIL', '')
    )
    admin_password: str = field(
        default_factory=lambda: os.getenv('ADMIN_PASSWORD', '')
    )

    # Execution settings — default is 0 (no blind sleep between
    # commands). Callers that need sequencing should set `wait: true`
    # on the individual command so the framework polls real state
    # instead of burning wall-clock time. `COMMAND_DELAY` env still
    # honoured for compatibility with the shell harness's config.
    command_delay: int = field(
        default_factory=lambda: int(os.getenv('COMMAND_DELAY', '0'))
    )

    # Debug settings
    debug: bool = field(
        default_factory=lambda: os.getenv('DEBUG', 'false').lower() in ('true', '1', 'yes')
    )

    # Timeout settings — 30s rather than 10s; the dev backend can return
    # transient 5xxs under concurrent load and we'd rather wait than fail
    # spuriously. Production deployments can tighten via REQUEST_TIMEOUT.
    request_timeout: int = field(
        default_factory=lambda: int(os.getenv('REQUEST_TIMEOUT', '30'))
    )
    health_check_timeout: int = field(
        default_factory=lambda: int(os.getenv('HEALTH_CHECK_TIMEOUT', '5'))
    )
    
    # JWT settings
    jwt_expiry_seconds: int = field(
        default_factory=lambda: int(os.getenv('JWT_EXPIRY_SECONDS', '3600'))
    )
    
    # Delegation scopes
    delegation_scopes: list = field(
        default_factory=lambda: [
            "CryptoOperations",
            "ReadGroup",
            "UpdateGroup",
            "ManageGroupMembers"
        ]
    )
    
    @classmethod
    def from_env(cls) -> 'YieldFabricConfig':
        """Create configuration from environment variables."""
        return cls()
    
    @classmethod
    def from_dict(cls, config_dict: dict) -> 'YieldFabricConfig':
        """
        Create configuration from a dictionary.

        Keys absent from `config_dict` fall back to the field defaults
        (which read env vars / built-in defaults), so a partial dict is
        valid. The fields use `default_factory`, so they aren't class
        attributes — build a default instance first and overlay.
        """
        defaults = cls()
        return cls(
            pay_service_url=config_dict.get('pay_service_url', defaults.pay_service_url),
            auth_service_url=config_dict.get('auth_service_url', defaults.auth_service_url),
            agents_service_url=config_dict.get('agents_service_url', defaults.agents_service_url),
            api_key=config_dict.get('api_key', defaults.api_key),
            command_delay=config_dict.get('command_delay', defaults.command_delay),
            debug=config_dict.get('debug', defaults.debug),
            request_timeout=config_dict.get('request_timeout', defaults.request_timeout),
            health_check_timeout=config_dict.get('health_check_timeout', defaults.health_check_timeout),
            jwt_expiry_seconds=config_dict.get('jwt_expiry_seconds', defaults.jwt_expiry_seconds),
            delegation_scopes=config_dict.get('delegation_scopes', defaults.delegation_scopes),
        )
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            'pay_service_url': self.pay_service_url,
            'auth_service_url': self.auth_service_url,
            'agents_service_url': self.agents_service_url,
            'api_key': self.api_key,
            'command_delay': self.command_delay,
            'debug': self.debug,
            'request_timeout': self.request_timeout,
            'health_check_timeout': self.health_check_timeout,
            'jwt_expiry_seconds': self.jwt_expiry_seconds,
            'delegation_scopes': self.delegation_scopes,
        }
    
    def validate(self) -> bool:
        """Validate configuration values."""
        if not self.pay_service_url:
            raise ValueError("pay_service_url is required")
        if not self.auth_service_url:
            raise ValueError("auth_service_url is required")
        if self.command_delay < 0:
            raise ValueError("command_delay must be non-negative")
        if self.request_timeout < 1:
            raise ValueError("request_timeout must be at least 1 second")
        if self.health_check_timeout < 1:
            raise ValueError("health_check_timeout must be at least 1 second")
        if self.jwt_expiry_seconds < 60:
            raise ValueError("jwt_expiry_seconds must be at least 60 seconds")
        return True

