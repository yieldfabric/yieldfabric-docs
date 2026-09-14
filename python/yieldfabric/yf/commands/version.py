"""`yf version` — print the client version (no network, no chain guard)."""

import sys

from ... import __version__
from ..context import Context

NAME = "version"
NEEDS_CHAIN = False


def add_parser(subparsers) -> None:
    subparsers.add_parser(NAME, help="print the client version")


def run(ctx: Context, args) -> int:
    return ctx.ok(
        {
            "version": __version__,
            "python": sys.version.split()[0],
        },
        chain=False,
    )
