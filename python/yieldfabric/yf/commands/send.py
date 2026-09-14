"""
`yf send --asset <denomination> --amount <n> (--to-wallet <uuid> | --to <entity> | --contract <id>) [--wait]`

Submits the ``instant`` payments mutation. Exactly one destination:

- ``--to-wallet``  the recipient's wallet id (what ``yf whoami`` shows as
  ``wallet.id`` for them; preferred — unambiguous);
- ``--to``         the recipient's entity name or id (resolved by the
  platform; a raw ``0x…`` address is NOT a name);
- ``--contract``   pay into an obligation contract.

``--amount`` is the human-readable decimal (``12.50``). The ``instant``
mutation takes integer base units, so the command reads the asset's
decimals from ``GET /balance`` first and converts exactly — an amount
finer than the asset carries is refused before submission, never
truncated. A fresh UUIDv4 ``idempotencyKey`` is generated for every
submission unless ``--idempotency-key`` is given. The mutation returns
as soon as the platform has accepted the submission; ``--wait`` polls
until it is settled (exit 3 on timeout, 5 if it failed on chain).
"""

from ...utils.graphql import GraphQLMutation
from .. import errors
from ..context import Context
from ._common import (
    add_wait_flags,
    asset_decimals_multiplier,
    fresh_idempotency_key,
    mutation_payload,
    raise_for_settlement,
    to_base_units,
    wait_for_message,
)

NAME = "send"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="send an instant payment")
    p.add_argument("--asset", "--denomination", dest="asset", required=True, metavar="DENOMINATION", help="asset denomination")
    p.add_argument("--amount", required=True, help="amount, as a human-readable decimal string (e.g. 12.50); scaled to base units for you")
    dest = p.add_mutually_exclusive_group(required=True)
    dest.add_argument("--to-wallet", metavar="WALLET_ID", help="recipient wallet id (preferred)")
    dest.add_argument("--to", metavar="ENTITY", help="recipient entity name or id")
    dest.add_argument("--contract", metavar="CONTRACT_ID", help="pay into this obligation contract")
    p.add_argument("--obligor", metavar="ADDRESS", help="obligor address, for obligor-scoped assets")
    p.add_argument("--idempotency-key", metavar="KEY", help="reuse a key only to re-submit the SAME payment")
    add_wait_flags(p, what="the payment")


def build_input(args, decimals_multiplier: str) -> dict:
    payload = {
        "assetId": args.asset,
        "amount": to_base_units(args.amount, decimals_multiplier),
        "idempotencyKey": fresh_idempotency_key(args.idempotency_key),
    }
    if args.to_wallet:
        payload["destinationWalletId"] = args.to_wallet
    elif args.contract:
        payload["contractId"] = args.contract
    else:
        if str(args.to).lower().startswith("0x"):
            raise errors.usage(
                "destination_is_address",
                "--to takes an entity name or id, not an address; use --to-wallet with the recipient's wallet id",
            )
        payload["destinationId"] = args.to
    if args.obligor:
        payload["obligor"] = args.obligor
    return payload


def run(ctx: Context, args) -> int:
    session = ctx.session()
    decimals = asset_decimals_multiplier(ctx, args.asset, args.obligor, session.access_token)
    payload = build_input(args, decimals)
    result = mutation_payload(ctx, GraphQLMutation.INSTANT, payload, "instant")
    data = {
        "message_id": result.get("messageId"),
        "payment_id": result.get("paymentId"),
        "id_hash": result.get("idHash"),
        "account_address": result.get("accountAddress"),
        "destination_id": result.get("destinationId"),
        "idempotency_key": payload["idempotencyKey"],
        "message": result.get("message"),
    }
    if args.wait and data["message_id"]:
        record = wait_for_message(ctx, data["message_id"], timeout=args.wait_timeout, interval=args.interval)
        data["settlement"] = record
        raise_for_settlement(record, what="payment")
    return ctx.ok(data)
