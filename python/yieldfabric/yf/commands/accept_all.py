"""
`yf accept-all --asset <denomination> [--obligor <address>] [--wait]`

Submits the ``acceptAll`` payments mutation: every pending incoming
payment in the asset is accepted, one submission per payment. The
result lists ``message_ids`` (one per accepted payment); ``--wait`` polls
each of them and reports the per-message state (exit 5 if any failed on
chain, 3 if any is still not settled when the wait runs out).
"""

from typing import List

from ...utils.graphql import GraphQLMutation
from .. import errors
from ..context import Context
from ._common import (
    add_wait_flags,
    fresh_idempotency_key,
    mutation_payload,
    wait_for_message,
)

NAME = "accept-all"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="accept every pending incoming payment in one asset")
    p.add_argument("--asset", "--denomination", dest="asset", required=True, metavar="DENOMINATION", help="asset denomination")
    p.add_argument("--obligor", metavar="ADDRESS", help="obligor address, for obligor-scoped assets")
    p.add_argument("--idempotency-key", metavar="KEY", help="reuse a key only to re-submit the SAME batch")
    add_wait_flags(p, what="every accepted payment")


def build_input(args) -> dict:
    payload = {
        "denomination": args.asset,
        "idempotencyKey": fresh_idempotency_key(args.idempotency_key),
    }
    if args.obligor:
        payload["obligor"] = args.obligor
    return payload


def _distinct_message_ids(accepted: list) -> List[str]:
    seen: List[str] = []
    for payment in accepted:
        if not isinstance(payment, dict):
            continue
        message_id = payment.get("messageId")
        if message_id and message_id not in seen:
            seen.append(str(message_id))
    return seen


def run(ctx: Context, args) -> int:
    payload = build_input(args)
    result = mutation_payload(ctx, GraphQLMutation.ACCEPT_ALL, payload, "acceptAll")
    accepted = result.get("acceptedPayments") or []
    failed = result.get("failedPayments") or []
    message_ids = _distinct_message_ids(accepted)
    accepted_count = int(result.get("acceptedCount") or 0)
    if accepted_count != len(message_ids):
        raise errors.api(
            "accept_all_inconsistent",
            f"acceptAll reported {accepted_count} accepted payment(s) but {len(message_ids)} distinct message id(s)",
            details=result,
        )
    data = {
        "total_payments": result.get("totalPayments"),
        "accepted_count": accepted_count,
        "failed_count": result.get("failedCount"),
        "message_ids": message_ids,
        "accepted_payments": accepted,
        "failed_payments": failed,
        "idempotency_key": payload["idempotencyKey"],
        "message": result.get("message"),
    }
    if args.wait and message_ids:
        records = [
            wait_for_message(ctx, message_id, timeout=args.wait_timeout, interval=args.interval)
            for message_id in message_ids
        ]
        data["settlement"] = records
        failed_records = [r for r in records if r.get("state") == "failed"]
        unsettled = [r for r in records if r.get("state") != "settled" and r not in failed_records]
        if failed_records:
            raise errors.onchain(
                "onchain_failed",
                f"{len(failed_records)} of {len(records)} accepted payment(s) failed on chain",
                details=data,
            )
        if unsettled:
            raise errors.timeout(
                "settle_timeout",
                f"{len(unsettled)} of {len(records)} accepted payment(s) not settled in time",
                details=data,
            )
    return ctx.ok(data)
