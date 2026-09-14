"""
`yf settle <message_id> [--timeout S] [--interval S] [--no-wait]`

Polls the message-status endpoint for one submission until it is
settled or failed and prints its state:

- ``pending``   not executed yet (or a failure not yet recorded as final)
- ``executed``  the chain transaction landed; the resulting records are
                still being written — do not read them yet
- ``settled``   the records are readable (final)
- ``failed``    the chain step failed and the failure is recorded (final)

Exit 0 settled · 3 the wait ran out (the last state is in the output) ·
5 failed · 1 the message is unknown to the platform (``message_not_found``,
decided on the FIRST read, with or without a wait) · 4 the bearer was
rejected (before or during the wait). ``--no-wait`` reads once and
reports whatever state it sees (exit 0 unless ``failed``).
"""

from .. import errors
from ..context import Context
from ..settlement import assess
from ._common import DEFAULT_WAIT_INTERVAL, DEFAULT_WAIT_TIMEOUT, observe_message, raise_for_settlement, wait_for_message

NAME = "settle"


def add_parser(subparsers) -> None:
    p = subparsers.add_parser(NAME, help="wait for a submission to settle and report its state")
    p.add_argument("message_id", help="the message id returned by send / accept-all / obligation")
    p.add_argument("--timeout", dest="settle_timeout", type=float, default=DEFAULT_WAIT_TIMEOUT, metavar="S",
                   help=f"seconds to wait (default {int(DEFAULT_WAIT_TIMEOUT)})")
    p.add_argument("--interval", type=float, default=DEFAULT_WAIT_INTERVAL, metavar="S",
                   help=f"seconds between polls (default {DEFAULT_WAIT_INTERVAL:g})")
    p.add_argument("--no-wait", action="store_true", help="read the state once and return")


def run(ctx: Context, args) -> int:
    message_id = str(args.message_id).strip()
    if not message_id:
        raise errors.usage("message_id_required", "a message id is required")

    if args.no_wait:
        observation = observe_message(ctx, message_id)
        if observation is None:
            raise errors.api("message_unobservable", f"message {message_id} could not be read right now; try again")
        record = assess(message_id, observation)
        record["attempts"] = 1
        record["elapsed"] = 0.0
        if record["state"] == "failed":
            raise errors.onchain("onchain_failed", f"message {message_id} failed on chain: {record.get('error')}", details=record)
        return ctx.ok(record)

    record = wait_for_message(ctx, message_id, timeout=args.settle_timeout, interval=args.interval)
    if record.get("timed_out") and record.get("executed_at") is None and record.get("lifecycle_status") is None:
        # Known to the platform (the first read was not a 404) but never
        # executed within the wait.
        raise errors.timeout(
            "settle_timeout",
            f"message {message_id} did not execute in {args.settle_timeout:g}s",
            details=record,
        )
    raise_for_settlement(record, what="message")
    return ctx.ok(record)
