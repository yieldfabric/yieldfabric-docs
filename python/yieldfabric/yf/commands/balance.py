"""
`yf balance --asset <denomination> [--obligor <address>]`

Reads ``GET /balance`` on the payments host for the resolved chain. The
entity whose balance is reported is the session's — a delegation JWT
(``yf group delegate`` → ``--token``) reports the group's.
"""

from .. import errors
from ..context import Context
from ..output import is_auth_message

NAME = "balance"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="show the session's balance in one asset")
    p.add_argument("--asset", "--denomination", dest="asset", required=True, metavar="DENOMINATION", help="asset denomination")
    p.add_argument("--obligor", metavar="ADDRESS", help="obligor address, for obligor-scoped assets")


def run(ctx: Context, args) -> int:
    session = ctx.session()
    response = ctx.payments().get_balance(args.asset, args.obligor, None, session.access_token)
    if not response.success:
        status = int(response.status_code or 0)
        message = response.get_error_message() or "balance query failed"
        if status in (401, 403) or is_auth_message(message):
            raise errors.auth("unauthorized", message, http_status=status, details=response.raw_response)
        raise errors.api("balance_failed", message, http_status=status or None, details=response.raw_response)
    balance = response.data.get("balance") if isinstance(response.data, dict) else None
    data = {"asset": args.asset, "obligor": args.obligor, "entity_id": session.entity_id}
    if isinstance(balance, dict):
        data["balance"] = balance
    else:
        data["balance"] = response.data
    return ctx.ok(data)
