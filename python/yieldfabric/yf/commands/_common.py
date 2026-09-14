"""
Helpers shared by the `yf` subcommands.
"""

import argparse
import uuid
from typing import Any, Dict, List, Optional

from ...models.response import GraphQLResponse
from .. import errors
from ..context import Context
from ..output import error_from_graphql, error_from_rest
from ..settlement import assess, is_final

DEFAULT_WAIT_TIMEOUT = 300.0
DEFAULT_WAIT_INTERVAL = 2.0
#: Consecutive 401/403 answers from the message-status endpoint that abort
#: a wait. A rejected bearer does not come back on its own (nothing
#: refreshes it mid-poll), so this only guards against one flaky hop.
AUTH_REJECTIONS_TO_ABORT = 2


def add_wait_flags(parser: argparse.ArgumentParser, *, what: str = "the operation") -> None:
    parser.add_argument(
        "--wait",
        action="store_true",
        help=f"poll until {what} is settled (or failed) before returning",
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=DEFAULT_WAIT_TIMEOUT,
        metavar="S",
        help=f"seconds to wait with --wait (default {int(DEFAULT_WAIT_TIMEOUT)})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_WAIT_INTERVAL,
        metavar="S",
        help=f"seconds between polls with --wait (default {DEFAULT_WAIT_INTERVAL:g})",
    )


def fresh_idempotency_key(explicit: Optional[str] = None) -> str:
    """
    A fresh UUIDv4 per submission unless the caller supplied one. A
    deterministic key on a retry after a stuck submission would hand back
    the stuck message id without re-submitting.
    """
    return explicit.strip() if explicit and explicit.strip() else str(uuid.uuid4())


def asset_decimals_multiplier(ctx: Context, asset: str, obligor: Optional[str], token: str) -> str:
    """
    The asset's decimals MULTIPLIER as ``GET /balance`` reports it
    (``balance.decimals``, e.g. ``"1000000000000000000"`` for 18 places —
    a multiplier, not an exponent; the agents payment bridge reads the
    same field the same way). A failed lookup is an API error: a mutation
    that takes base units must never be sent an unscaled amount.
    """
    response = ctx.payments().get_balance(asset, obligor, None, token)
    if not response.success:
        status = int(response.status_code or 0)
        message = response.get_error_message() or "balance query failed"
        raise errors.api(
            "balance_failed",
            f"could not read the decimals of {asset!r} to scale the amount: {message}",
            http_status=status or None,
            details=response.raw_response,
        )
    balance = response.data.get("balance") if isinstance(response.data, dict) else None
    decimals = balance.get("decimals") if isinstance(balance, dict) else None
    if decimals is None:
        raise errors.api(
            "balance_failed",
            f"the balance response for {asset!r} carries no decimals; refusing to submit an unscaled amount",
            details=response.raw_response,
        )
    return str(decimals).strip()


def to_base_units(amount: str, decimals_multiplier: str) -> str:
    """
    Exact conversion of a human-readable decimal amount to the integer
    base-unit string the payments mutations take (``"12.50"`` with the
    multiplier ``"1000000"`` → ``"12500000"``). Refuses a non-positive,
    non-numeric or over-precise amount BEFORE anything is submitted — the
    platform truncates nothing on our behalf, and neither does this.
    """
    from decimal import Decimal, InvalidOperation

    text = str(amount).strip().replace(",", "")
    if not text:
        raise errors.usage("bad_amount", "--amount must not be empty")
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise errors.usage("bad_amount", f"--amount must be a decimal number, got {amount!r}") from None
    if not value.is_finite() or value <= 0:
        raise errors.usage("bad_amount", f"--amount must be a positive decimal number, got {amount!r}")
    multiplier = str(decimals_multiplier).strip()
    if not multiplier.isdigit() or multiplier.strip("0") != "1" or not multiplier.startswith("1"):
        raise errors.api("balance_failed", f"the asset's decimals multiplier is not a power of ten: {decimals_multiplier!r}")
    places = len(multiplier) - 1
    # Decimal construction is exact, but normalize() and multiplication
    # round under the caller's context. Scale the unrounded coefficient
    # instead, dropping only insignificant trailing zeros.
    parts = value.as_tuple()
    coefficient = "".join(str(digit) for digit in parts.digits)
    significant = coefficient.rstrip("0")
    exponent = parts.exponent + len(coefficient) - len(significant)
    fractional_digits = max(0, -exponent)
    if fractional_digits > places:
        raise errors.usage(
            "bad_amount",
            f"--amount {amount} has {fractional_digits} fractional digits; this asset carries at most {places}",
        )
    return significant + "0" * (exponent + places)


def mutation_payload(ctx: Context, mutation: str, input_dict: Dict[str, Any], root: str) -> Dict[str, Any]:
    """
    Run a payments GraphQL mutation with ``{input: …}`` variables and
    return the ``data.<root>`` object. Transport errors, GraphQL errors
    and ``success: false`` all raise ``CliError``.
    """
    session = ctx.session()
    response: GraphQLResponse = ctx.payments().graphql_mutation(
        mutation, {"input": input_dict}, session.access_token
    )
    if not response.success:
        raise error_from_graphql(response)
    payload = response.get_data(root)
    if not isinstance(payload, dict):
        raise errors.api("empty_response", f"the platform returned no `{root}` payload", details=response.raw_response)
    if payload.get("success") is False:
        raise errors.api(
            f"{root}_failed",
            str(payload.get("message") or f"{root} reported failure"),
            details=payload,
        )
    return payload


def observe_message(ctx: Context, message_id: str) -> Optional[Dict[str, Any]]:
    """
    One status-preserving read of the message-status endpoint, with the
    outcomes a caller must not confuse mapped onto the exit table:

    - 404 → ``message_not_found`` (exit 1): the id is unknown to the
      platform for this session's entity;
    - 401 / 403 → exit 4 with the server's reason (bearer rejected);
    - 400 → ``bad_message_id`` (exit 2): not a message id at all;
    - host not reached → ``unreachable`` (exit 1).

    Any other non-2xx (a 5xx, say) is treated as "nothing observable yet"
    and returns ``None``; a 2xx returns the record.
    """
    session = ctx.session()
    entity_id = session.entity_id
    if not entity_id:
        raise errors.usage("no_entity", "the bearer carries no subject; cannot address the message-status endpoint")
    result = ctx.payments().get_user_message_result(entity_id, message_id, session.access_token)
    return _body_or_raise(result, message_id)


def _body_or_raise(result: Dict[str, Any], message_id: str) -> Optional[Dict[str, Any]]:
    status = int(result.get("status_code") or 0)
    if status == 404:
        raise errors.api(
            "message_not_found",
            f"message {message_id} is not known to the platform for this session's entity — check the id and the session",
            http_status=status,
        )
    if status in (401, 403) or status == 0:
        raise error_from_rest(result)
    if status == 400:
        raise errors.usage("bad_message_id", f"{message_id!r} is not a message id", http_status=status)
    body = result.get("body")
    if result.get("ok") and isinstance(body, dict):
        return body
    return None


def wait_for_message(
    ctx: Context,
    message_id: str,
    *,
    timeout: float,
    interval: float,
) -> Dict[str, Any]:
    """
    Poll the message-status endpoint until the operation is settled or
    failed, then classify the last observation. On timeout the last
    state is returned with ``timed_out: true`` (no exception).

    The first read is status-preserving (``observe_message``): an unknown
    id is exit 1 and a rejected bearer exit 4 at once, instead of a
    300 s spin ending in exit 3. During the wait a bearer that stops being
    accepted (an expired delegation, a revoked key) aborts the wait with
    exit 4 after ``AUTH_REJECTIONS_TO_ABORT`` consecutive refusals.
    """
    session = ctx.session()
    entity_id = session.entity_id
    if not entity_id:
        raise errors.usage("no_entity", "the bearer carries no subject; cannot address the message-status endpoint")
    payments = ctx.payments()
    token = session.access_token

    # Reused by the poll's first tick so the pre-check costs no extra call.
    first: List[Optional[Dict[str, Any]]] = [observe_message(ctx, message_id)]
    rejections = [0]

    def probe() -> Optional[Dict[str, Any]]:
        if first:
            return first.pop()
        result = payments.get_user_message_result(entity_id, message_id, token)
        status = int(result.get("status_code") or 0)
        if status in (401, 403):
            rejections[0] += 1
            if rejections[0] >= AUTH_REJECTIONS_TO_ABORT:
                raise error_from_rest(result)
            return None
        rejections[0] = 0
        body = result.get("body")
        return body if result.get("ok") and isinstance(body, dict) else None

    try:
        result = payments.poll_message_completion(
            entity_id,
            message_id,
            token,
            interval=interval,
            timeout=timeout,
            probe=probe,
        )
    except TimeoutError:
        last_result = payments.get_user_message_result(entity_id, message_id, token)
        if int(last_result.get("status_code") or 0) in (401, 403):
            raise error_from_rest(last_result)
        last_body = last_result.get("body")
        last = last_body if last_result.get("ok") and isinstance(last_body, dict) else None
        record = assess(message_id, last)
        # The polling predicate parks on a message canceled before it ran;
        # the classifier knows that can never settle and reports `failed`.
        record["timed_out"] = not is_final(record)
        record["attempts"] = None
        record["elapsed"] = timeout
        return record
    record = assess(message_id, result.observation)
    record["attempts"] = result.attempts
    record["elapsed"] = round(result.elapsed, 3)
    return record


def raise_for_settlement(record: Dict[str, Any], *, what: str = "operation") -> None:
    """Exit 3 on a timed-out wait, 5 on an on-chain failure."""
    if record.get("timed_out"):
        raise errors.timeout(
            "settle_timeout",
            f"{what} {record.get('message_id')} not settled in time (last state: {record.get('state')})",
            details=record,
        )
    if record.get("state") == "failed":
        raise errors.onchain(
            "onchain_failed",
            f"{what} {record.get('message_id')} failed on chain: {record.get('error') or 'no error text'}",
            details=record,
        )
    if not is_final(record):
        raise errors.timeout(
            "settle_timeout",
            f"{what} {record.get('message_id')} is {record.get('state')}",
            details=record,
        )
