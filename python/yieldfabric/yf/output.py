"""
Output discipline for `yf`.

- Every log line the service clients emit goes to STDERR (the shared
  ``YieldFabricLogger`` prints to stdout by default — ``StderrLogger``
  overrides that and is installed via ``set_logger`` BEFORE any client is
  built, with ``debug_mode``/``colorize`` matching what ``get_logger``
  would ask for so it is never swapped out).
- The command's result is exactly one JSON document on STDOUT in
  ``--json`` mode, or a flat ``key: value`` rendering otherwise.
- Errors are ``{"ok": false, "error": {code, message, ...}}`` on STDOUT in
  ``--json`` mode and a single ``error: …`` line on STDERR otherwise.
"""

import json
import re
import sys
from typing import Any, Dict, Optional

from ..models.response import GraphQLResponse
from ..utils.logger import YieldFabricLogger, set_logger
from ..utils.redact import redact_text
from . import errors
from .errors import CliError


class StderrLogger(YieldFabricLogger):
    """
    The shared logger, with every level routed to stderr and credentials
    masked.

    ``colorize`` stays at the default ``True`` so ``get_logger(debug=…)``
    (called by every service client) keeps this instance as the
    singleton; ``plain`` is what actually decides whether ANSI colour is
    written.

    Every line passes through ``redact_text`` first: the service clients
    log whole auth responses at debug level, and ``--debug`` / ``YF_DEBUG``
    would otherwise put access tokens, single-use refresh tokens and
    delegation JWTs on stderr — and into CI logs captured with ``2>&1``.
    The clients also mask structurally before formatting; this is the
    backstop for lines that were formatted before the mask could run.
    """

    def __init__(self, debug: bool = False, plain: bool = False):
        super().__init__(debug=debug, colorize=True)
        self.plain = plain

    def _print(self, color: str, message: str, file=None):
        message = redact_text(message)
        if self.plain:
            print(message, file=sys.stderr)
        else:
            super()._print(color, message, file=sys.stderr)


def install_logger(debug: bool, json_mode: bool) -> StderrLogger:
    """
    Install the stderr logger as the process-wide singleton BEFORE any
    service client is constructed. Colour is suppressed when stderr is
    not a TTY or ``--json`` is on.
    """
    logger = StderrLogger(debug=debug, plain=json_mode or not _stderr_is_tty())
    set_logger(logger)
    return logger


def _stderr_is_tty() -> bool:
    try:
        return bool(sys.stderr.isatty())
    except Exception:
        return False


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _render_human(value: Any, indent: str = "") -> str:
    lines = []
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (dict, list)) and item:
                lines.append(f"{indent}{key}:")
                lines.append(_render_human(item, indent + "  "))
            else:
                rendered = json.dumps(item, default=_json_default) if isinstance(item, (dict, list)) else item
                if rendered is None:
                    rendered = "-"
                lines.append(f"{indent}{key}: {rendered}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.append(f"{indent}-")
                lines.append(_render_human(item, indent + "  "))
            else:
                lines.append(f"{indent}- {item}")
    else:
        lines.append(f"{indent}{value}")
    return "\n".join(line for line in lines if line != "")


def emit_ok(
    command: str,
    data: Dict[str, Any],
    *,
    json_mode: bool,
    chain_id: Optional[str] = None,
    mode: Optional[str] = None,
    out=None,
) -> int:
    """Print the success envelope and return exit code 0."""
    out = out or sys.stdout
    if json_mode:
        envelope: Dict[str, Any] = {"ok": True, "command": command}
        if chain_id is not None:
            envelope["chain_id"] = chain_id
            envelope["mode"] = mode
        envelope["data"] = data
        out.write(json.dumps(envelope, default=_json_default, sort_keys=False) + "\n")
    else:
        out.write(_render_human(data) + "\n")
    out.flush()
    return errors.EXIT_OK


def emit_error(
    command: Optional[str],
    err: CliError,
    *,
    json_mode: bool,
    chain_id: Optional[str] = None,
    out=None,
    err_out=None,
) -> int:
    """Print the error envelope and return its exit code."""
    out = out or sys.stdout
    err_out = err_out or sys.stderr
    if json_mode:
        envelope: Dict[str, Any] = {"ok": False}
        if command:
            envelope["command"] = command
        if chain_id is not None:
            envelope["chain_id"] = chain_id
        envelope["error"] = err.to_dict()
        out.write(json.dumps(envelope, default=_json_default) + "\n")
        out.flush()
    else:
        suffix = f" (http {err.http_status})" if err.http_status else ""
        err_out.write(f"error [{err.code}]{suffix}: {err.message}\n")
        if err.details:
            err_out.write(f"  details: {json.dumps(err.details, default=_json_default)}\n")
        err_out.flush()
    return err.exit_code


# ── Classification helpers ────────────────────────────────────────────

_AUTH_HINT = re.compile(
    r"\b(401|403)\b|unauthori[sz]ed|forbidden|insufficient permissions|"
    r"invalid token|token expired|connector_read_only|direct_user_session_required",
    re.IGNORECASE,
)


def is_auth_message(message: str) -> bool:
    return bool(_AUTH_HINT.search(message or ""))


def error_from_graphql(response: GraphQLResponse, *, code: str = "graphql_error") -> CliError:
    """
    Map a GraphQL failure (transport error, HTTP status, or ``errors[]``)
    onto a ``CliError``. Auth-shaped messages become exit 4.
    """
    message = response.get_error_message() or "GraphQL request failed"
    extensions_code = None
    if response.errors:
        first = response.errors[0] or {}
        ext = first.get("extensions") if isinstance(first, dict) else None
        if isinstance(ext, dict):
            extensions_code = ext.get("code")
    details = {"errors": response.errors} if response.errors else None
    if is_auth_message(message) or str(extensions_code or "").upper() in ("FORBIDDEN", "UNAUTHENTICATED", "UNAUTHORIZED"):
        return errors.auth("unauthorized", message, details=details)
    if extensions_code:
        return errors.api(str(extensions_code), message, details=details)
    return errors.api(code, message, details=details)


def error_from_rest(result: Dict[str, Any], *, code: str = "http_error") -> CliError:
    """
    Map a ``_request_json_safe`` envelope (``{ok, status_code, body}``)
    onto a ``CliError``. 401/403 → exit 4; a transport failure
    (``status_code == 0``) → exit 1 with ``code: unreachable``.
    """
    status = int(result.get("status_code") or 0)
    body = result.get("body")
    message = _message_from_body(body) or f"HTTP {status}"
    server_code = body.get("code") if isinstance(body, dict) else None
    details = body if isinstance(body, (dict, list)) else None
    if status in (401, 403):
        return errors.auth(str(server_code or "unauthorized"), message, http_status=status, details=details)
    if status == 0:
        return errors.api("unreachable", message, details=details)
    return errors.api(str(server_code or code), message, http_status=status, details=details)


def credential_error(
    result: Dict[str, Any],
    *,
    fallback_code: str,
    what: str,
    host: str,
) -> CliError:
    """
    Map a failed status-preserving credential call (``AuthService.
    exchange_api_key_session`` / ``refresh_session`` /
    ``login_session_result``: ``{ok, status_code, body, session}``) onto
    the exit table:

    - ``status_code == 0`` → exit 1 ``unreachable`` (the host was not
      reached — DNS, TLS, refused, timeout);
    - 401 / 403 → exit 4, ``code`` = the server's ``code`` when it sends
      one, else ``fallback_code``;
    - 409 ``chain_not_allowed`` (a connector key or lineage asked for a
      chain outside its ``allowed_chains``) → exit 1 with that code and
      the allowed chains in the message;
    - any other status → exit 1 with the server's ``code`` or
      ``http_error``;
    - a 2xx that carried no token → exit 4 ``fallback_code``.
    """
    status = int(result.get("status_code") or 0)
    body = result.get("body")
    server_code = body.get("code") if isinstance(body, dict) else None
    server_message = _message_from_body(body)
    details = body if isinstance(body, (dict, list)) else None

    if status == 0:
        reason = server_message or "no response"
        return errors.api("unreachable", f"{host} could not be reached: {reason}", details=details)
    if status in (401, 403):
        message = f"{what}" + (f": {server_message}" if server_message else "")
        return errors.auth(str(server_code or fallback_code), message, http_status=status, details=details)
    if status == 409 and str(server_code or "") == "chain_not_allowed" and isinstance(body, dict):
        allowed = body.get("allowed_chains")
        allowed_text = ", ".join(str(c) for c in allowed) if isinstance(allowed, list) and allowed else "none"
        reason = server_message or "the requested chain is outside this credential's allowed chains"
        return errors.api(
            "chain_not_allowed",
            f"{reason} (requested {body.get('chain_id')}; allowed: {allowed_text}) — re-run with --chain <an allowed chain>",
            http_status=status,
            details=details,
        )
    if 200 <= status < 300:
        return errors.auth(fallback_code, f"{what}: the platform answered without a session token", details=details)
    message = f"{what}" + (f": {server_message}" if server_message else f": HTTP {status}")
    return errors.api(str(server_code or "http_error"), message, http_status=status, details=details)


def _message_from_body(body: Any) -> Optional[str]:
    if isinstance(body, dict):
        for key in ("error", "message", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
            if isinstance(value, dict):
                nested = _message_from_body(value)
                if nested:
                    return nested
        return None
    if isinstance(body, str) and body.strip():
        return body.strip()[:500]
    return None
