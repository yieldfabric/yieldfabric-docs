"""Settlement semantics for PaymentsService message polling."""

import pytest

from yieldfabric.config import YieldFabricConfig
from yieldfabric.services.payments_service import PaymentsService


def _service() -> PaymentsService:
    return PaymentsService(
        YieldFabricConfig(
            pay_service_url="http://localhost:3002",
            auth_service_url="http://localhost:3000",
            command_delay=0,
            debug=False,
        )
    )


@pytest.mark.parametrize("terminal_status", ["failed", "error", "canceled"])
def test_terminal_failure_waits_for_top_level_post_processing_marker(terminal_status):
    payments = _service()
    observations = [
        {
            "executed": "2026-07-17T05:00:00Z",
            "response": {
                "status": terminal_status,
                "success": False,
                "error": "chain attempt failed",
            },
            "post_processed_at": None,
            "post_processing_attempts": 0,
            "post_processing_error_kind": None,
        },
        {
            "executed": "2026-07-17T05:00:00Z",
            "response": {
                "status": terminal_status,
                "success": False,
                "error": "chain attempt failed",
            },
            "post_processed_at": "2026-07-17T05:00:01Z",
            "post_processing_attempts": 1,
            "post_processing_error_kind": "chain_failure",
        },
    ]
    payments.get_user_message = lambda *_args: observations.pop(0)

    result = payments.poll_message_completion(
        "entity-1",
        "message-1",
        "token-1",
        interval=0.001,
        timeout=1.0,
    )

    assert result.attempts == 2
    assert result.observation["post_processed_at"] == "2026-07-17T05:00:01Z"


def test_terminal_failure_without_lifecycle_marker_keeps_polling():
    payments = _service()
    observations = [
        {
            "executed": "2026-07-17T05:00:00Z",
            "response": {"status": "failed", "success": False},
        },
        {
            "executed": "2026-07-17T05:00:00Z",
            "response": {
                "status": "failed",
                "success": False,
                # Compatibility with an older status payload that nested the
                # marker inside response rather than merging it at top level.
                "post_processed_at": "2026-07-17T05:00:01Z",
            },
        },
    ]
    payments.get_user_message = lambda *_args: observations.pop(0)

    result = payments.poll_message_completion(
        "entity-1",
        "message-1",
        "token-1",
        interval=0.001,
        timeout=1.0,
    )

    assert result.attempts == 2


def test_success_uses_canonical_top_level_settlement_marker():
    payments = _service()
    observations = [
        {
            "executed": "2026-07-17T05:00:00Z",
            "response": {"status": "completed", "success": True},
            "post_processed_at": None,
            "post_processing_attempts": 0,
        },
        {
            "executed": "2026-07-17T05:00:00Z",
            "response": {"status": "completed", "success": True},
            "post_processed_at": "2026-07-17T05:00:01Z",
            "post_processing_attempts": 1,
        },
    ]
    payments.get_user_message = lambda *_args: observations.pop(0)

    result = payments.poll_message_completion(
        "entity-1",
        "message-1",
        "token-1",
        interval=0.001,
        timeout=1.0,
    )

    assert result.attempts == 2
