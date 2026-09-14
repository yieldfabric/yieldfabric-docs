"""
Credential redaction for log lines.

The service clients log whole auth responses at debug level. Those
bodies carry bearers (access tokens, delegation JWTs) and single-use
refresh tokens, so anything that echoes them must go through here first.
Two layers:

- ``redact_secrets(value)`` — structural: walks dicts/lists and masks the
  VALUE of every key that names a credential (``token``, ``access_token``,
  ``refresh_token``, ``delegation_jwt``, ``api_key``, ``password`` …).
- ``redact_text(text)`` — textual: masks anything JWT-shaped
  (``xxx.yyy.zzz`` base64url segments) or ``yf_api_…`` shaped inside a
  string, for log lines that were formatted before this module could see
  the structure.
"""

import re
from typing import Any

MASK = "***redacted***"

#: Keys whose values are credentials, matched case-insensitively on the
#: key's lowercase form. ``jwt`` on its own is included because the auth
#: service answers ``{"jwt": …}`` on some routes.
_SECRET_KEYS = frozenset({
    "token",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "delegation_jwt",
    "delegation_token",
    "jwt",
    "id_token",
    "api_key",
    "apikey",
    "password",
    "secret",
    "client_secret",
    "private_key",
    "encrypted_private_key",
    "authorization",
})

#: A JWT: three base64url segments separated by dots. The header is JSON,
#: so its base64url form always starts with ``eyJ`` (``{"``) — that is the
#: discriminator, not segment length, so an ``alg: none`` token with an
#: empty signature is masked too and dotted hostnames are not.
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*")
#: A ``yf_api_…`` key (the API-key secret prefix).
_API_KEY = re.compile(r"\byf_api_[A-Za-z0-9_-]{4,}")
#: ``Bearer <token>`` in a header dump.
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}")


def _is_secret_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.strip().lower()
    if lowered in _SECRET_KEYS:
        return True
    return lowered.endswith("_token") or lowered.endswith("_jwt") or lowered.endswith("_secret")


def redact_secrets(value: Any) -> Any:
    """Return a copy of ``value`` with every credential-bearing value masked."""
    if isinstance(value, dict):
        return {
            key: (MASK if _is_secret_key(key) and item not in (None, "") else redact_secrets(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    """Mask JWT-, API-key- and bearer-shaped substrings in a log line."""
    if not text:
        return text
    text = _BEARER.sub("Bearer " + MASK, text)
    text = _JWT.sub(MASK, text)
    text = _API_KEY.sub(MASK, text)
    return text
