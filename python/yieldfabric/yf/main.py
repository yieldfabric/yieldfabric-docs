"""
`yf` entry point.

    yf [global flags] <command> [command flags]

Global flags come before the command. Exit codes: 0 ok · 1 the platform
refused or the operation failed · 2 usage/configuration · 3 a wait timed
out · 4 credential rejected or session cannot perform the operation ·
5 the operation failed on chain.
"""

import argparse
import os
import sys
from typing import List, Optional

from .. import __version__
from . import errors
from .context import Context
from .errors import CliError
from .output import emit_error, install_logger
from .session import SessionStore
from .settings import (
    DEFAULT_AGENTS_URL,
    DEFAULT_AUTH_URL,
    DEFAULT_CHAIN,
    DEFAULT_CONFIG_DIR,
    enforce_live_guard,
    load_env_file,
    resolve_settings,
)

PROG = "yf"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="YieldFabric command-line client.",
        epilog=(
            "Environment: YF_API_KEY, YF_TOKEN, YF_CHAIN (default 153), "
            f"YF_AUTH_URL (default {DEFAULT_AUTH_URL}), "
            f"YF_AGENTS_URL (default {DEFAULT_AGENTS_URL}), "
            'YF_PAYMENTS_URLS (JSON {chain_id: url}; defaults cover 153 and 151), '
            f"YF_CONFIG_DIR (default {DEFAULT_CONFIG_DIR}), YF_TIMEOUT, YF_DEBUG. "
            "Chain 151 is LIVE and needs --live."
        ),
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output: one JSON document on stdout")
    parser.add_argument("--live", action="store_true",
                        help="allow acting on a live chain (151) or a live payments host (pay.live.yieldfabric.com)")
    parser.add_argument("--chain", metavar="ID", help=f"chain id (default: YF_CHAIN, the session's chain, else {DEFAULT_CHAIN})")
    parser.add_argument("--api-key", metavar="KEY", help="yf_api_… key, exchanged for a session on every call (or YF_API_KEY)")
    parser.add_argument("--token", metavar="JWT", help="raw bearer to use as-is, e.g. a delegation JWT (or YF_TOKEN)")
    parser.add_argument("--auth-url", metavar="URL", help=f"auth host (default: YF_AUTH_URL or {DEFAULT_AUTH_URL})")
    parser.add_argument("--agents-url", metavar="URL", help=f"agents host (default: YF_AGENTS_URL or {DEFAULT_AGENTS_URL})")
    parser.add_argument("--payments-url", metavar="URL", help="payments host for the resolved chain (overrides YF_PAYMENTS_URLS)")
    parser.add_argument("--timeout", type=int, metavar="S", help="HTTP request timeout in seconds (default: YF_TIMEOUT or 30)")
    parser.add_argument("--debug", action="store_true",
                        help="verbose request logging on stderr (or YF_DEBUG=1); credentials in logged "
                             "responses are masked, but treat the output as sensitive and keep it out of shared logs")
    parser.add_argument("--env-file", metavar="PATH", help="load KEY=VALUE lines from this file (never ./.env implicitly)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    from .commands import COMMANDS

    for module in COMMANDS:
        module.add_parser(subparsers)
    _accept_trailing_flags(parser)
    return parser


# Global flags a caller naturally puts LAST (`yf whoami --json`,
# `yf send … --live`). argparse only accepts them before the command, so
# every (sub)command also accepts the same switches; `SUPPRESS` keeps the
# sub-parser from writing its own default over the top-level value.
_TRAILING_FLAGS = ("--json", "--live")


def _accept_trailing_flags(parser: argparse.ArgumentParser) -> None:
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for sub in action.choices.values():
            for flag in _TRAILING_FLAGS:
                sub.add_argument(flag, action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
            _accept_trailing_flags(sub)


def _command_name(args: argparse.Namespace) -> str:
    sub = getattr(args, "subcommand", None)
    return f"{args.command} {sub}" if sub else str(args.command)


def _stored_chain(args: argparse.Namespace, env) -> Optional[str]:
    """Cheap pre-read of the session file's chain for chain precedence."""
    auth_url = (getattr(args, "auth_url", None) or env.get("YF_AUTH_URL") or DEFAULT_AUTH_URL).strip().rstrip("/")
    config_dir = (env.get("YF_CONFIG_DIR") or DEFAULT_CONFIG_DIR).strip() or DEFAULT_CONFIG_DIR
    path = os.path.join(os.path.expanduser(config_dir), "session.json")
    return SessionStore(path).stored_chain(auth_url)


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    json_mode = bool(args.json)
    install_logger(debug=bool(args.debug), json_mode=json_mode)
    command = _command_name(args)

    try:
        if args.env_file:
            load_env_file(args.env_file)
        env = os.environ
        settings = resolve_settings(args, env, stored_session_chain=_stored_chain(args, env))
        # Debug may also come from YF_DEBUG; re-install so clients agree.
        if settings.debug != bool(args.debug):
            install_logger(debug=settings.debug, json_mode=json_mode)
    except CliError as exc:
        return emit_error(command, exc, json_mode=json_mode)

    from .commands import COMMANDS

    module = next((m for m in COMMANDS if m.NAME == args.command), None)
    if module is None:  # pragma: no cover — argparse already rejects this
        return emit_error(command, errors.usage("unknown_command", f"unknown command {args.command!r}"), json_mode=json_mode)

    try:
        if getattr(module, "NEEDS_CHAIN", True):
            enforce_live_guard(settings)
        ctx = Context(settings, command)
        return int(module.run(ctx, args))
    except CliError as exc:
        return emit_error(command, exc, json_mode=json_mode, chain_id=settings.chain_id)
    except TimeoutError as exc:
        return emit_error(
            command,
            errors.timeout("timeout", str(exc)),
            json_mode=json_mode,
            chain_id=settings.chain_id,
        )
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
