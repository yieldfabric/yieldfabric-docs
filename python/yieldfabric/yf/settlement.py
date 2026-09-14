"""
Settled-state classifier for one message-status observation.

A pure Python mirror of the state machine the payments MCP
``wait_for_settlement`` tool reports (``pending`` | ``executed`` |
``settled`` | ``failed``), built on the SAME predicate as
``PaymentsService.poll_message_completion`` — the two must never
disagree about whether a wait is over. It is mirrored, not shared code;
``tests/test_unit/test_yf_settlement.py`` pins the parity.

The observation is the JSON body of
``GET /api/users/{entity_id}/messages/{message_id}``:

    executed null                                   → pending
    response.status == post_processing              → executed
    terminal failure (status ∈ {failed, error, canceled}
                      ∨ success == false ∨ error)   → failed once post_processed_at is set,
                                                      else pending (not final yet)
    no post-processing lifecycle keys at all        → settled at executed (older server)
    post_processed_at set                           → settled
    otherwise                                       → executed

One case beyond the polling predicate: a message canceled BEFORE
execution (``status == canceled`` with ``executed`` null) can never
settle, so it is reported ``failed`` rather than parking the caller
until the timeout.
"""

from typing import Any, Dict, Optional

STATE_PENDING = "pending"
STATE_EXECUTED = "executed"
STATE_SETTLED = "settled"
STATE_FAILED = "failed"

FINAL_STATES = frozenset({STATE_SETTLED, STATE_FAILED})

#: Seconds between probes while the chain step has not run yet.
PENDING_RETRY_S = 2
#: Seconds between probes once the chain step landed and only the final
#: write remains.
EXECUTED_RETRY_S = 1

_LIFECYCLE_KEYS = (
    "post_processed_at",
    "post_processing_attempts",
    "post_processing_error_kind",
)


def _first(obs: Dict[str, Any], response: Optional[Dict[str, Any]], key: str) -> Any:
    """Top-level first, then the older nested-in-response placement."""
    value = obs.get(key)
    if value is None and response is not None:
        value = response.get(key)
    return value


def _stringify(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        import json

        return json.dumps(value)
    except Exception:
        return str(value)


def assess(message_id: str, observation: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Classify one observation. Returns the settlement record::

        {message_id, state, executed_at, post_processed_at, error,
         retry_after_s, lifecycle_status, post_processing_error_kind,
         timed_out}

    ``retry_after_s`` is ``None`` when there is nothing further to wait
    for. ``timed_out`` is always ``False`` here — the caller sets it when a
    wait ran out.
    """
    obs: Dict[str, Any] = observation if isinstance(observation, dict) else {}
    raw_response = obs.get("response")
    response: Optional[Dict[str, Any]] = raw_response if isinstance(raw_response, dict) else None

    lifecycle_status = None
    if response is not None and response.get("status") is not None:
        lifecycle_status = str(response.get("status")).lower()
    response_error = _stringify(response.get("error")) if response is not None else None

    has_lifecycle = any(
        key in source
        for source in (obs, response or {})
        for key in _LIFECYCLE_KEYS
    )
    post_processed_at = _first(obs, response, "post_processed_at")
    post_processing_error = _stringify(_first(obs, response, "post_processing_error"))
    post_processing_error_kind = _first(obs, response, "post_processing_error_kind")
    executed_at = obs.get("executed")

    out: Dict[str, Any] = {
        "message_id": message_id,
        "state": STATE_PENDING,
        "executed_at": executed_at,
        "post_processed_at": post_processed_at,
        "error": response_error,
        "retry_after_s": PENDING_RETRY_S,
        "lifecycle_status": lifecycle_status,
        "post_processing_error_kind": None,
        "timed_out": False,
    }

    if not executed_at:
        if lifecycle_status == "canceled":
            out["state"] = STATE_FAILED
            out["retry_after_s"] = None
            out["error"] = out["error"] or "canceled before execution"
        return out

    if lifecycle_status == "post_processing":
        out["state"] = STATE_EXECUTED
        out["retry_after_s"] = EXECUTED_RETRY_S
        return out

    terminal_failure = (
        lifecycle_status in ("failed", "error", "canceled")
        or (response is not None and response.get("success") is False)
        or bool(response_error)
    )
    if terminal_failure:
        # A failure is final only once the platform has recorded it.
        if post_processed_at:
            out["state"] = STATE_FAILED
            out["retry_after_s"] = None
            if not out["error"]:
                message = response.get("message") if response is not None else None
                out["error"] = message if isinstance(message, str) and message else "operation failed"
        else:
            out["state"] = STATE_PENDING
            out["retry_after_s"] = PENDING_RETRY_S
        return out

    if not has_lifecycle:
        # Older server: nothing more to observe past `executed`.
        out["state"] = STATE_SETTLED
        out["retry_after_s"] = None
        return out

    if post_processed_at:
        out["state"] = STATE_SETTLED
        out["retry_after_s"] = None
        return out

    out["state"] = STATE_EXECUTED
    out["retry_after_s"] = EXECUTED_RETRY_S
    if post_processing_error:
        # The chain step succeeded; the final write failed. Transient
        # causes are retried by the platform, unrecoverable ones wait for
        # an operator — nothing for the caller to wait on.
        out["error"] = post_processing_error
        out["post_processing_error_kind"] = post_processing_error_kind
        if str(post_processing_error_kind or "") == "unrecoverable":
            out["retry_after_s"] = None
    return out


def is_final(record: Dict[str, Any]) -> bool:
    return record.get("state") in FINAL_STATES
