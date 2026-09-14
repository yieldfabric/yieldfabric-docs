"""
`yf obligation create|accept`

    yf obligation create --asset <denomination> (--counterpart-wallet <uuid> | --counterpart <name>)
                         [--obligor-wallet <uuid>] [--expiry <ISO 8601 or epoch seconds>]
                         [--data <JSON>] [--class <obligation address>] [--wait]
    yf obligation accept --contract CONTRACT-OBLIGATION-… [--wait]

``create`` submits ``createObligation``. Prefer ``--counterpart-wallet``
(the counterpart's wallet id, e.g. their ``yf whoami`` ``wallet.id``);
``--counterpart`` is an entity NAME resolved by the platform and never a
``0x…`` address. The contract id is returned immediately, but it can only
be accepted once the operation is settled — with ``--wait`` the result
carries ``acceptable: true`` when it is safe to run ``accept``.

``accept`` submits ``acceptObligation`` for the contract. If the platform
reports the contract is already completed (the self-counterpart case, or
a repeated accept) the command succeeds without submitting new work.
"""

import argparse
import json

from ...utils.graphql import GraphQLMutation
from .. import errors
from ..context import Context
from ._common import (
    add_wait_flags,
    fresh_idempotency_key,
    mutation_payload,
    raise_for_settlement,
    wait_for_message,
)

NAME = "obligation"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="create or accept an obligation")
    sub = p.add_subparsers(dest="subcommand", metavar="<create|accept>")
    sub.required = True

    c = sub.add_parser("create", help="mint an obligation towards a counterpart")
    c.add_argument("--asset", "--denomination", dest="asset", metavar="DENOMINATION", help="asset denomination of the obligation")
    who = c.add_mutually_exclusive_group(required=True)
    who.add_argument("--counterpart-wallet", metavar="WALLET_ID", help="counterpart wallet id (preferred)")
    who.add_argument("--counterpart", metavar="ENTITY", help="counterpart entity name (never an address)")
    c.add_argument("--obligor-wallet", metavar="WALLET_ID", help="issue from this wallet (defaults to the session's)")
    c.add_argument("--expiry", metavar="WHEN", help="expiry, ISO 8601 or epoch seconds, passed through to the platform")
    c.add_argument("--data", metavar="JSON", help="arbitrary JSON attached to the obligation")
    c.add_argument("--class", dest="obligation_address", metavar="ADDRESS", help="obligation class address (default: the chain's default class)")
    c.add_argument("--contract-id", metavar="ID", help="pre-allocated contract id (rarely needed)")
    c.add_argument("--idempotency-key", metavar="KEY", help="reuse a key only to re-submit the SAME obligation")
    add_wait_flags(c, what="the obligation")

    a = sub.add_parser("accept", help="accept an obligation as its counterpart")
    a.add_argument("--contract", required=True, metavar="CONTRACT_ID", help="the CONTRACT-OBLIGATION-… id")
    a.add_argument("--wallet", metavar="WALLET_ID", help="accept as this wallet (defaults to the session's)")
    a.add_argument("--idempotency-key", metavar="KEY", help="reuse a key only to re-submit the SAME accept")
    add_wait_flags(a, what="the acceptance")


def build_create_input(args) -> dict:
    payload = {"idempotencyKey": fresh_idempotency_key(args.idempotency_key)}
    if args.counterpart_wallet:
        payload["counterpartWalletId"] = args.counterpart_wallet
    else:
        if str(args.counterpart).lower().startswith("0x"):
            raise errors.usage(
                "counterpart_is_address",
                "--counterpart takes an entity name, not an address; use --counterpart-wallet with the wallet id",
            )
        payload["counterpart"] = args.counterpart
    if args.asset:
        payload["denomination"] = args.asset
    if args.obligor_wallet:
        payload["obligorWalletId"] = args.obligor_wallet
    if args.expiry:
        payload["expiry"] = str(args.expiry)
    if args.data:
        try:
            payload["data"] = json.loads(args.data)
        except ValueError as exc:
            raise errors.usage("bad_data", f"--data must be valid JSON: {exc}")
    if args.obligation_address:
        payload["obligationAddress"] = args.obligation_address
    if args.contract_id:
        payload["contractId"] = args.contract_id
    return payload


def build_accept_input(args) -> dict:
    payload = {
        "contractId": args.contract,
        "idempotencyKey": fresh_idempotency_key(args.idempotency_key),
    }
    if args.wallet:
        payload["walletId"] = args.wallet
    return payload


def _run_create(ctx: Context, args) -> int:
    payload = build_create_input(args)
    result = mutation_payload(ctx, GraphQLMutation.CREATE_OBLIGATION, payload, "createObligation")
    data = {
        "contract_id": result.get("contractId"),
        "token_id": result.get("tokenId"),
        "message_id": result.get("messageId"),
        "transaction_id": result.get("transactionId"),
        "account_address": result.get("accountAddress"),
        "id_hash": result.get("idHash"),
        "idempotency_key": payload["idempotencyKey"],
        "message": result.get("message"),
        # The contract is acceptable only once the operation is settled.
        "acceptable": False,
    }
    if args.wait and data["message_id"]:
        record = wait_for_message(ctx, data["message_id"], timeout=args.wait_timeout, interval=args.interval)
        data["settlement"] = record
        raise_for_settlement(record, what="obligation")
        data["acceptable"] = record.get("state") == "settled"
    return ctx.ok(data)


def _run_accept(ctx: Context, args) -> int:
    payload = build_accept_input(args)
    result = mutation_payload(ctx, GraphQLMutation.ACCEPT_OBLIGATION, payload, "acceptObligation")
    accept_result = str(result.get("acceptResult") or "")
    already_completed = "already at completed" in accept_result.lower() or "already completed" in accept_result.lower()
    data = {
        "contract_id": args.contract,
        "obligation_id": result.get("obligationId"),
        "message_id": result.get("messageId"),
        "transaction_id": result.get("transactionId"),
        "account_address": result.get("accountAddress"),
        "accept_result": result.get("acceptResult") or None,
        "already_completed": already_completed,
        "idempotency_key": payload["idempotencyKey"],
        "message": result.get("message"),
    }
    if args.wait and data["message_id"] and not already_completed:
        record = wait_for_message(ctx, data["message_id"], timeout=args.wait_timeout, interval=args.interval)
        data["settlement"] = record
        raise_for_settlement(record, what="acceptance")
    return ctx.ok(data)


def run(ctx: Context, args: argparse.Namespace) -> int:
    if args.subcommand == "create":
        return _run_create(ctx, args)
    if args.subcommand == "accept":
        return _run_accept(ctx, args)
    raise errors.usage("unknown_subcommand", f"unknown obligation subcommand {args.subcommand!r}")
