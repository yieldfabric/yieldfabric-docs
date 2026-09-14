"""
The `yf` settled-state classifier and the `settle` command.

`assess()` mirrors the payments `wait_for_settlement` state machine and
must agree with `PaymentsService.poll_message_completion`'s predicate on
every observation: the parity test below drives both over the same
fixtures (the shapes used in test_message_completion_polling.py).
"""

from unittest.mock import MagicMock, patch

import pytest

from yieldfabric.config import YieldFabricConfig
from yieldfabric.services.payments_service import PaymentsService
from yieldfabric.yf import errors
from yieldfabric.yf.settlement import assess, is_final

from .yf_helpers import clean_env, message_result, message_results, rest, run, token

EXECUTED = "2026-07-17T05:00:00Z"
PP = "2026-07-17T05:00:01Z"

# (name, observation, expected state, expected retry_after_s)
CASES = [
    ("not executed", {"executed": None, "response": {"status": "validating"}}, "pending", 2),
    ("empty observation", {}, "pending", 2),
    ("canceled before execution", {"executed": None, "response": {"status": "canceled"}}, "failed", None),
    ("post_processing", {"executed": EXECUTED, "response": {"status": "post_processing"}, "post_processed_at": None, "post_processing_attempts": 0}, "executed", 1),
    ("executed, lifecycle present, not yet written", {"executed": EXECUTED, "response": {"status": "completed", "success": True}, "post_processed_at": None, "post_processing_attempts": 0}, "executed", 1),
    ("settled", {"executed": EXECUTED, "response": {"status": "completed", "success": True}, "post_processed_at": PP, "post_processing_attempts": 1}, "settled", None),
    ("legacy: no lifecycle keys ⇒ settled at executed", {"executed": EXECUTED, "response": {"status": "completed", "success": True}}, "settled", None),
    ("legacy: marker nested in response", {"executed": EXECUTED, "response": {"status": "completed", "post_processed_at": PP}}, "settled", None),
    ("failed but not yet recorded ⇒ pending", {"executed": EXECUTED, "response": {"status": "failed", "success": False, "error": "chain attempt failed"}, "post_processed_at": None, "post_processing_attempts": 0, "post_processing_error_kind": None}, "pending", 2),
    ("failed and recorded", {"executed": EXECUTED, "response": {"status": "failed", "success": False, "error": "chain attempt failed"}, "post_processed_at": PP, "post_processing_attempts": 1, "post_processing_error_kind": "chain_failure"}, "failed", None),
    ("error status recorded", {"executed": EXECUTED, "response": {"status": "error", "success": False}, "post_processed_at": PP}, "failed", None),
    ("success false without status, recorded", {"executed": EXECUTED, "response": {"success": False, "message": "reverted"}, "post_processed_at": PP}, "failed", None),
    ("failed, legacy nested marker", {"executed": EXECUTED, "response": {"status": "failed", "success": False, "post_processed_at": PP}}, "failed", None),
    ("post-processing error, transient", {"executed": EXECUTED, "response": {"status": "completed"}, "post_processed_at": None, "post_processing_attempts": 2, "post_processing_error": "db timeout", "post_processing_error_kind": "transient"}, "executed", 1),
    ("post-processing error, unrecoverable", {"executed": EXECUTED, "response": {"status": "completed"}, "post_processed_at": None, "post_processing_attempts": 5, "post_processing_error": "bad row", "post_processing_error_kind": "unrecoverable"}, "executed", None),
]


@pytest.mark.parametrize("name,obs,state,retry", CASES, ids=[c[0] for c in CASES])
def test_assess_state_table(name, obs, state, retry):
    record = assess("m-1", obs)
    assert record["state"] == state
    assert record["retry_after_s"] == retry
    assert record["message_id"] == "m-1"
    assert record["timed_out"] is False
    assert set(record) >= {
        "message_id", "state", "executed_at", "post_processed_at", "error",
        "retry_after_s", "lifecycle_status", "post_processing_error_kind", "timed_out",
    }


def test_assess_error_text_and_kind():
    rec = assess("m", {"executed": EXECUTED, "response": {"success": False, "message": "reverted"}, "post_processed_at": PP})
    assert rec["error"] == "reverted"
    rec = assess("m", {"executed": EXECUTED, "response": {"status": "failed"}, "post_processed_at": PP})
    assert rec["error"] == "operation failed"
    rec = assess("m", {"executed": None, "response": {"status": "canceled"}})
    assert rec["error"] == "canceled before execution"
    rec = assess("m", CASES[-1][1])
    assert rec["error"] == "bad row" and rec["post_processing_error_kind"] == "unrecoverable"
    rec = assess("m", {"executed": EXECUTED, "response": {"status": "failed", "error": {"code": 7}}, "post_processed_at": PP})
    assert rec["error"] == '{"code": 7}'


def _payments() -> PaymentsService:
    return PaymentsService(YieldFabricConfig(
        pay_service_url="https://pay.test.yieldfabric.com",
        auth_service_url="https://auth.yieldfabric.com",
        command_delay=0, debug=False,
    ))


def _poll_done(obs) -> bool:
    """Drive poll_message_completion's predicate over a single observation."""
    payments = _payments()
    payments.get_user_message = lambda *_a: obs
    try:
        payments.poll_message_completion("e", "m", "t", interval=0.001, timeout=0)
        return True
    except TimeoutError:
        return False


@pytest.mark.parametrize("name,obs,state,retry", CASES, ids=[c[0] for c in CASES])
def test_assess_agrees_with_poll_message_completion(name, obs, state, retry):
    """
    The wait is over exactly when the classifier says the state is final,
    except for the one case the classifier knows better: a message
    canceled before it ran can never settle.
    """
    final = is_final(assess("m", obs))
    done = _poll_done(obs)
    if name == "canceled before execution":
        assert final and not done
    else:
        assert final == done, name


# ── `yf settle` ───────────────────────────────────────────────────────


def _run_settle(argv, capsys, observations):
    with patch.object(PaymentsService, "get_user_message_result", side_effect=message_results(observations)):
        return run(["--json", "--token", token("153")] + argv, capsys)


def test_settle_polls_until_settled(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    observations = [
        {"executed": None, "response": {"status": "executing"}},
        CASES[4][1],  # executed
        CASES[5][1],  # settled
    ]
    code, out, _, _ = _run_settle(["settle", "m-1", "--interval", "0.001", "--timeout", "5"], capsys, observations)
    assert code == 0
    assert out["data"]["state"] == "settled"
    assert out["data"]["attempts"] == 3
    assert out["data"]["post_processed_at"] == PP


def test_settle_failed_is_exit_5(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = _run_settle(["settle", "m-1", "--interval", "0.001", "--timeout", "5"], capsys, [CASES[9][1]])
    assert code == errors.EXIT_ONCHAIN
    assert out["error"]["code"] == "onchain_failed"
    assert out["error"]["details"]["state"] == "failed"
    assert "chain attempt failed" in out["error"]["message"]


def test_settle_timeout_is_exit_3_with_last_state(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    pending = CASES[4][1]
    code, out, _, _ = _run_settle(["settle", "m-1", "--interval", "0.001", "--timeout", "0.01"], capsys, [pending] * 50)
    assert code == errors.EXIT_TIMEOUT
    assert out["error"]["code"] == "settle_timeout"
    assert out["error"]["details"]["state"] == "executed"
    assert out["error"]["details"]["timed_out"] is True


def test_settle_canceled_before_execution_is_failed_not_timeout(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    canceled = CASES[2][1]
    code, out, _, _ = _run_settle(["settle", "m-1", "--interval", "0.001", "--timeout", "0.01"], capsys, [canceled] * 50)
    assert code == errors.EXIT_ONCHAIN
    assert out["error"]["details"]["state"] == "failed"


def test_settle_no_wait_reads_once(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = _run_settle(["settle", "m-1", "--no-wait"], capsys, [CASES[3][1]])
    assert code == 0
    assert out["data"]["state"] == "executed"
    assert out["data"]["attempts"] == 1


def test_settle_no_wait_unknown_message_is_exit_1(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = _run_settle(["settle", "m-404", "--no-wait"], capsys, [None])
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "message_not_found"


def test_settle_addresses_the_acting_as_entity(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    probe = MagicMock(return_value=message_result(CASES[5][1]))
    with patch.object(PaymentsService, "get_user_message_result", probe):
        code, out, _, _ = run(["--json", "--token", token("153", acting_as="group-9"), "settle", "m-1", "--no-wait"], capsys)
    assert code == 0
    assert probe.call_args[0][0] == "group-9"


def test_settle_unknown_message_with_default_wait_is_exit_1_at_once(monkeypatch, tmp_path, capsys):
    """A 404 on the first read is `message_not_found` (exit 1) — not a 300 s spin ending in exit 3."""
    clean_env(monkeypatch, tmp_path)
    probe = MagicMock(return_value=message_result(None))
    with patch.object(PaymentsService, "get_user_message_result", probe):
        code, out, _, _ = run(["--json", "--token", token("153"), "settle", "m-404"], capsys)
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "message_not_found"
    assert out["error"]["http_status"] == 404
    assert probe.call_count == 1


def test_settle_rejected_bearer_before_wait_is_exit_4(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(PaymentsService, "get_user_message_result", return_value=rest({"error": "Invalid token"}, 401)):
        code, out, _, _ = run(["--json", "--token", token("153"), "settle", "m-1"], capsys)
    assert code == errors.EXIT_AUTH
    assert out["error"]["http_status"] == 401
    assert "Invalid token" in out["error"]["message"]


def test_settle_bearer_rejected_during_wait_aborts_with_exit_4(monkeypatch, tmp_path, capsys):
    """An expired delegation / revoked key mid-poll: exit 4, not the full timeout as exit 3."""
    clean_env(monkeypatch, tmp_path)
    pending = CASES[4][1]
    observations = [pending, pending, 403, 403] + [pending] * 50
    code, out, _, _ = _run_settle(["settle", "m-1", "--interval", "0.001", "--timeout", "30"], capsys, observations)
    assert code == errors.EXIT_AUTH
    assert out["error"]["http_status"] == 403


def test_settle_one_flaky_403_does_not_abort_the_wait(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    pending = CASES[4][1]
    observations = [pending, 403, pending, CASES[5][1]]
    code, out, _, _ = _run_settle(["settle", "m-1", "--interval", "0.001", "--timeout", "30"], capsys, observations)
    assert code == 0
    assert out["data"]["state"] == "settled"


def test_settle_unreachable_host_is_exit_1(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = _run_settle(["settle", "m-1"], capsys, [0])
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "unreachable"


def test_settle_malformed_id_is_exit_2(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = _run_settle(["settle", "not-an-id", "--no-wait"], capsys, [400])
    assert code == errors.EXIT_USAGE
    assert out["error"]["code"] == "bad_message_id"
