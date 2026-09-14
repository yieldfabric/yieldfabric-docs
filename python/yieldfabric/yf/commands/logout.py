"""
`yf logout [--delegation]` — forget the stored session for the auth host
(no network).

Without a flag the whole record goes: the personal login and any
delegation saved beside it. ``--delegation`` drops only the saved
delegation and keeps the personal login, which is the way back to acting
as yourself after ``yf group delegate --save``.
"""

from ..context import Context

NAME = "logout"
NEEDS_CHAIN = False


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="forget the stored session for the auth host")
    p.add_argument(
        "--delegation",
        action="store_true",
        help="forget only the saved delegation (from `group delegate --save`); keep the personal login",
    )


def run(ctx: Context, args) -> int:
    if getattr(args, "delegation", False):
        removed = ctx.store.clear_delegation(ctx.settings.auth_url)
        return ctx.ok(
            {"auth_url": ctx.settings.auth_url, "removed": removed, "scope": "delegation", "session_file": ctx.store.path},
            chain=False,
        )
    removed = ctx.store.delete(ctx.settings.auth_url)
    return ctx.ok(
        {"auth_url": ctx.settings.auth_url, "removed": removed, "scope": "all", "session_file": ctx.store.path},
        chain=False,
    )
