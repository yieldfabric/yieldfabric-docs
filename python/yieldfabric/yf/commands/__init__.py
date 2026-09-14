"""
Subcommand registry for `yf`.

Each module exposes ``NAME``, ``add_parser(subparsers)`` and
``run(ctx, args) -> int``. ``main.py`` stays a thin dispatcher.
"""

from . import (
    accept_all,
    balance,
    group,
    kg,
    login,
    logout,
    obligation,
    send,
    settle,
    version,
    whoami,
)

COMMANDS = [
    login,
    logout,
    whoami,
    balance,
    send,
    accept_all,
    obligation,
    settle,
    group,
    kg,
    version,
]

__all__ = ["COMMANDS"]
