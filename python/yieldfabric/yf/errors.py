"""
Exit codes and the one exception every `yf` command raises.

The exit code is the contract shell scripts and agents branch on; the
``code`` string is the stable machine-readable reason inside the
``--json`` error envelope. Both are documented in the README and must
not be renumbered.
"""

from typing import Any, Optional

EXIT_OK = 0
#: The platform answered and refused, or the operation reported failure
#: (GraphQL errors, ``success: false``, HTTP 4xx/5xx other than auth).
EXIT_API = 1
#: Bad usage or configuration: missing credential, unknown chain, live
#: guard, chain mismatch, malformed flags.
EXIT_USAGE = 2
#: A wait ran out (``settle``, ``--wait``).
EXIT_TIMEOUT = 3
#: The credential was rejected (401/403), the exchange failed, or the
#: session cannot perform the operation (connector sessions cannot write).
EXIT_AUTH = 4
#: The operation reached the chain and failed there (``state: failed``).
EXIT_ONCHAIN = 5


class CliError(Exception):
    """A terminal failure with a stable ``code`` and exit status."""

    def __init__(
        self,
        exit_code: int,
        code: str,
        message: str,
        *,
        http_status: Optional[int] = None,
        details: Any = None,
    ):
        super().__init__(message)
        self.exit_code = exit_code
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details

    def to_dict(self) -> dict:
        error = {"code": self.code, "message": self.message}
        if self.http_status is not None:
            error["http_status"] = self.http_status
        if self.details is not None:
            error["details"] = self.details
        return error


def usage(code: str, message: str, **kw) -> CliError:
    return CliError(EXIT_USAGE, code, message, **kw)


def auth(code: str, message: str, **kw) -> CliError:
    return CliError(EXIT_AUTH, code, message, **kw)


def api(code: str, message: str, **kw) -> CliError:
    return CliError(EXIT_API, code, message, **kw)


def timeout(code: str, message: str, **kw) -> CliError:
    return CliError(EXIT_TIMEOUT, code, message, **kw)


def onchain(code: str, message: str, **kw) -> CliError:
    return CliError(EXIT_ONCHAIN, code, message, **kw)
