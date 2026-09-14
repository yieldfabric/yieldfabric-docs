"""
Per-command tests for `yf`: the exact request each command sends, the
JSON envelope it prints, and the exit code on one failure each.
"""

import uuid
from unittest.mock import MagicMock, call, patch

from yieldfabric.models.response import RESTResponse
from yieldfabric.services.agents_service import AgentsService
from yieldfabric.services.auth_service import AuthService
from yieldfabric.services.payments_service import PaymentsService
from yieldfabric.utils.graphql import GraphQLMutation
from yieldfabric.yf import errors

from .yf_helpers import GROUP_ID, USER_ID, WALLET_ID, clean_env, credential_result, graphql, graphql_errors, message_results, response, rest, run, token

BEARER = token("153")
SETTLED = {"executed": "2026-07-17T05:00:00Z", "response": {"status": "completed", "success": True}, "post_processed_at": "2026-07-17T05:00:01Z", "post_processing_attempts": 1}
FAILED = {"executed": "2026-07-17T05:00:00Z", "response": {"status": "failed", "success": False, "error": "reverted: bad counterpart"}, "post_processed_at": "2026-07-17T05:00:01Z"}


def _base(*argv):
    return ["--json", "--token", BEARER] + list(argv)


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except (ValueError, AttributeError, TypeError):
        return False


# ── whoami ────────────────────────────────────────────────────────────


def test_whoami_mirrors_protected_jwt(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    body = {
        "user_id": USER_ID, "role": "User", "account_address": "0xabc", "group_account_address": None,
        "acting_as": None, "delegation_scope": None, "default_wallet_id": WALLET_ID, "default_chain_id": "153",
        "permissions": ["CryptoOperations"], "billing_gate": None, "session_kind": "personal", "allowed_chains": None,
    }
    info = MagicMock(return_value=rest(body))
    with patch.object(AuthService, "get_jwt_info", info):
        code, out, _, _ = run(_base("whoami"), capsys)
    assert code == 0
    data = out["data"]
    assert info.call_args == call(BEARER)
    assert data["source"] == "auth"
    assert data["entity_id"] == USER_ID and data["sub"] == USER_ID and data["kind"] == "user"
    assert data["session_kind"] == "personal"
    assert data["mode"] == "TEST" and data["chain_id"] == "153" and data["session_chain_id"] == "153"
    assert data["wallet"] == {"id": WALLET_ID, "address": "0xabc"}
    assert data["permissions"] == ["CryptoOperations"]
    assert "gates" in data and data["gates"]["billing_gate"] is None


def test_whoami_under_delegation_reports_group_wallet(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    body = {"user_id": USER_ID, "role": "User", "acting_as": GROUP_ID, "account_address": "0xuser",
            "group_account_address": "0xgroup", "default_wallet_id": "gw", "default_chain_id": "153",
            "session_kind": "delegated", "delegation_scope": ["ReadGroup"]}
    with patch.object(AuthService, "get_jwt_info", return_value=rest(body)):
        code, out, _, _ = run(_base("whoami"), capsys)
    assert code == 0
    assert out["data"]["entity_id"] == GROUP_ID
    assert out["data"]["wallet"] == {"id": "gw", "address": "0xgroup"}
    assert out["data"]["delegation_scope"] == ["ReadGroup"]


def test_whoami_rejected_token_is_exit_4(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(AuthService, "get_jwt_info", return_value=rest({"error": "Invalid token"}, 401)):
        code, out, _, _ = run(_base("whoami"), capsys)
    assert code == errors.EXIT_AUTH
    assert out["error"]["http_status"] == 401


def test_whoami_offline_falls_back_to_jwt_claims(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(AuthService, "get_jwt_info", return_value=rest("connection refused", 0)):
        code, out, _, _ = run(_base("whoami"), capsys)
    assert code == 0
    assert out["data"]["source"] == "jwt"
    assert out["data"]["sub"] == USER_ID
    assert "warning" in out["data"]


# ── balance ───────────────────────────────────────────────────────────


def test_balance_reads_get_balance(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    body = {"status": "success", "balance": {"private_balance": "10", "public_balance": "0", "denomination": "USDx"}}
    get_balance = MagicMock(return_value=RESTResponse.from_response(200, body))
    with patch.object(PaymentsService, "get_balance", get_balance):
        code, out, _, _ = run(_base("balance", "--asset", "USDx", "--obligor", "0xob"), capsys)
    assert code == 0
    assert get_balance.call_args == call("USDx", "0xob", None, BEARER)
    assert out["data"]["balance"]["private_balance"] == "10"
    assert out["data"]["entity_id"] == USER_ID


def test_balance_error_is_exit_1(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(PaymentsService, "get_balance", return_value=RESTResponse.from_response(500, {"error": "boom"})):
        code, out, _, _ = run(_base("balance", "--asset", "USDx"), capsys)
    assert code == errors.EXIT_API
    assert out["error"]["message"] == "boom"


def test_balance_auth_error_is_exit_4(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(PaymentsService, "get_balance", return_value=RESTResponse(success=False, status_code=0, errors=["403 Client Error: Forbidden for url"])):
        code, out, _, _ = run(_base("balance", "--asset", "USDx"), capsys)
    assert code == errors.EXIT_AUTH


# ── send ──────────────────────────────────────────────────────────────

DECIMALS_18 = "1000000000000000000"
DECIMALS_6 = "1000000"


def _balance_with_decimals(multiplier: str) -> MagicMock:
    """`GET /balance` as `yf send` reads it for the asset's decimals multiplier."""
    body = {"status": "success", "balance": {"private_balance": "0", "public_balance": "0", "decimals": multiplier}}
    return MagicMock(return_value=RESTResponse.from_response(200, body))



def test_send_to_wallet_builds_instant_input_with_fresh_uuid4_key(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    mutation = MagicMock(return_value=graphql({"instant": {
        "success": True, "message": "queued", "accountAddress": "0xme", "destinationId": "0xthem",
        "idHash": "0xhash", "messageId": "msg-1", "paymentId": "pay-1", "sendResult": None, "timestamp": "t",
    }}))
    get_balance = _balance_with_decimals(DECIMALS_18)
    with patch.object(PaymentsService, "graphql_mutation", mutation), \
         patch.object(PaymentsService, "get_balance", get_balance):
        code, out, _, _ = run(_base("send", "--asset", "USDx", "--amount", "12.50", "--to-wallet", WALLET_ID), capsys)
    assert code == 0
    # The decimals are read for THIS asset under the session's token, once.
    assert get_balance.call_args == call("USDx", None, None, BEARER)
    (sent_mutation, variables, sent_token), _ = mutation.call_args
    assert sent_mutation is GraphQLMutation.INSTANT
    assert sent_token == BEARER
    inp = variables["input"]
    # The README's `12.50` reaches `instant` as base units (review F4).
    assert inp["assetId"] == "USDx" and inp["amount"] == "12500000000000000000" and inp["destinationWalletId"] == WALLET_ID
    assert "destinationId" not in inp and "contractId" not in inp
    assert _is_uuid4(inp["idempotencyKey"])
    assert out["data"]["message_id"] == "msg-1" and out["data"]["payment_id"] == "pay-1"
    assert out["data"]["idempotency_key"] == inp["idempotencyKey"]


def test_send_two_submissions_never_share_a_key(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    mutation = MagicMock(return_value=graphql({"instant": {"success": True, "messageId": "m"}}))
    with patch.object(PaymentsService, "graphql_mutation", mutation), \
         patch.object(PaymentsService, "get_balance", _balance_with_decimals(DECIMALS_18)):
        run(_base("send", "--asset", "A", "--amount", "1", "--to", "alice@example.com"), capsys)
        run(_base("send", "--asset", "A", "--amount", "1", "--to", "alice@example.com"), capsys)
    keys = {c.args[1]["input"]["idempotencyKey"] for c in mutation.call_args_list}
    assert len(keys) == 2
    assert mutation.call_args_list[0].args[1]["input"]["destinationId"] == "alice@example.com"


def test_send_to_raw_address_is_refused_before_submission(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    mutation = MagicMock()
    with patch.object(PaymentsService, "graphql_mutation", mutation), \
         patch.object(PaymentsService, "get_balance", _balance_with_decimals(DECIMALS_18)):
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to", "0xdeadbeef"), capsys)
    assert code == errors.EXIT_USAGE
    assert out["error"]["code"] == "destination_is_address"
    assert not mutation.called


def test_send_graphql_error_is_exit_1_and_forbidden_is_exit_4(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    decimals = patch.object(PaymentsService, "get_balance", _balance_with_decimals(DECIMALS_18))
    with patch.object(PaymentsService, "graphql_mutation", return_value=graphql_errors("No entity found with name 'bob'")), decimals:
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to", "bob"), capsys)
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "graphql_error"
    assert "No entity found" in out["error"]["message"]

    with patch.object(PaymentsService, "graphql_mutation", return_value=graphql_errors("403 Client Error: Forbidden for url")), decimals:
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to", "bob"), capsys)
    assert code == errors.EXIT_AUTH

    with patch.object(PaymentsService, "graphql_mutation", return_value=graphql({"instant": {"success": False, "message": "insufficient balance"}})), decimals:
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to", "bob"), capsys)
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "instant_failed"


def test_send_wait_settles_then_fails_on_chain(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    ok = graphql({"instant": {"success": True, "messageId": "msg-1", "paymentId": "p"}})
    with patch.object(PaymentsService, "graphql_mutation", return_value=ok), \
         patch.object(PaymentsService, "get_balance", _balance_with_decimals(DECIMALS_18)), \
         patch.object(PaymentsService, "get_user_message_result", side_effect=message_results([SETTLED])):
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to-wallet", WALLET_ID, "--wait", "--interval", "0.001"), capsys)
    assert code == 0
    assert out["data"]["settlement"]["state"] == "settled"

    with patch.object(PaymentsService, "graphql_mutation", return_value=ok), \
         patch.object(PaymentsService, "get_balance", _balance_with_decimals(DECIMALS_18)), \
         patch.object(PaymentsService, "get_user_message_result", side_effect=message_results([FAILED])):
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to-wallet", WALLET_ID, "--wait", "--interval", "0.001"), capsys)
    assert code == errors.EXIT_ONCHAIN
    assert out["error"]["details"]["state"] == "failed"


def test_send_scales_by_the_assets_decimals_and_refuses_overprecision(monkeypatch, tmp_path, capsys):
    """Review F4: whole and fractional amounts on 6- and 18-decimal assets
    reach `instant` as exact base units; an over-precise or non-positive
    amount is refused before any mutation; a failed decimals lookup never
    submits an unscaled amount."""
    clean_env(monkeypatch, tmp_path)
    ok = graphql({"instant": {"success": True, "messageId": "m"}})
    for multiplier, amount, expected in [
        (DECIMALS_6, "12.50", "12500000"),
        (DECIMALS_6, "7", "7000000"),
        (DECIMALS_6, "0.000001", "1"),
        (DECIMALS_18, "1,000.5", "1000500000000000000000"),
        (DECIMALS_18, "0.000000000000000001", "1"),
        ("1", "3", "3"),
    ]:
        mutation = MagicMock(return_value=ok)
        with patch.object(PaymentsService, "graphql_mutation", mutation), \
             patch.object(PaymentsService, "get_balance", _balance_with_decimals(multiplier)):
            code, _, _, _ = run(_base("send", "--asset", "A", "--amount", amount, "--to-wallet", WALLET_ID), capsys)
        assert code == 0, (multiplier, amount)
        assert mutation.call_args.args[1]["input"]["amount"] == expected, (multiplier, amount)

    for multiplier, amount, code_expected in [
        (DECIMALS_6, "12.1234567", "bad_amount"),
        ("1", "3.5", "bad_amount"),
        (DECIMALS_18, "0", "bad_amount"),
        (DECIMALS_18, "-1", "bad_amount"),
        (DECIMALS_18, "abc", "bad_amount"),
        (DECIMALS_18, " ", "bad_amount"),
    ]:
        mutation = MagicMock(return_value=ok)
        with patch.object(PaymentsService, "graphql_mutation", mutation), \
             patch.object(PaymentsService, "get_balance", _balance_with_decimals(multiplier)):
            code, out, _, _ = run(_base("send", "--asset", "A", "--amount", amount, "--to-wallet", WALLET_ID), capsys)
        assert code == errors.EXIT_USAGE, (multiplier, amount)
        assert out["error"]["code"] == code_expected, (multiplier, amount)
        assert not mutation.called, (multiplier, amount)

    mutation = MagicMock(return_value=ok)
    with patch.object(PaymentsService, "graphql_mutation", mutation), \
         patch.object(PaymentsService, "get_balance", return_value=RESTResponse.from_response(500, {"error": "boom"})):
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to-wallet", WALLET_ID), capsys)
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "balance_failed"
    assert not mutation.called

    mutation = MagicMock(return_value=ok)
    no_decimals = RESTResponse.from_response(200, {"status": "success", "balance": {"private_balance": "0"}})
    with patch.object(PaymentsService, "graphql_mutation", mutation), \
         patch.object(PaymentsService, "get_balance", return_value=no_decimals):
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to-wallet", WALLET_ID), capsys)
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "balance_failed"
    assert not mutation.called


def test_send_conversion_is_exact_independent_of_decimal_context(monkeypatch, tmp_path, capsys):
    from decimal import Inexact, Rounded, localcontext

    clean_env(monkeypatch, tmp_path)
    ok = graphql({"instant": {"success": True, "messageId": "m"}})
    for precision in (6, 28):
        with localcontext() as context:
            context.prec = precision
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            for amount, expected in [
                ("12345678901.123456789012345678", "12345678901123456789012345678"),
                ("12.50000000000000000000000000000", "12500000000000000000"),
                ("1e-18", "1"),
                ("1e3", "1000000000000000000000"),
            ]:
                mutation = MagicMock(return_value=ok)
                with patch.object(PaymentsService, "graphql_mutation", mutation), \
                     patch.object(PaymentsService, "get_balance", _balance_with_decimals(DECIMALS_18)):
                    code, _, _, _ = run(_base("send", "--asset", "A", "--amount", amount, "--to-wallet", WALLET_ID), capsys)
                assert code == 0, (precision, amount)
                assert mutation.call_args.args[1]["input"]["amount"] == expected

            mutation = MagicMock(return_value=ok)
            with patch.object(PaymentsService, "graphql_mutation", mutation), \
                 patch.object(PaymentsService, "get_balance", _balance_with_decimals(DECIMALS_18)):
                code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1.00000000000000000000000000001", "--to-wallet", WALLET_ID), capsys)
            assert code == errors.EXIT_USAGE
            assert out["error"]["code"] == "bad_amount"
            mutation.assert_not_called()
            assert context.prec == precision

    mutation = MagicMock(return_value=ok)
    with patch.object(PaymentsService, "graphql_mutation", mutation), \
         patch.object(PaymentsService, "get_balance", _balance_with_decimals("1001")):
        code, out, _, _ = run(_base("send", "--asset", "A", "--amount", "1", "--to-wallet", WALLET_ID), capsys)
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "balance_failed"
    mutation.assert_not_called()


# ── accept-all ────────────────────────────────────────────────────────


def test_accept_all_lists_one_message_per_accepted_payment(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    mutation = MagicMock(return_value=graphql({"acceptAll": {
        "success": True, "message": "ok", "totalPayments": 3, "acceptedCount": 2, "failedCount": 1,
        "acceptedPayments": [{"paymentId": "p1", "amount": "1", "messageId": "m1", "transactionId": "t1"},
                             {"paymentId": "p2", "amount": "2", "messageId": "m2", "transactionId": "t2"}],
        "failedPayments": [{"paymentId": "p3", "amount": "3", "error": "expired"}], "timestamp": "t",
    }}))
    with patch.object(PaymentsService, "graphql_mutation", mutation):
        code, out, _, _ = run(_base("accept-all", "--asset", "USDx", "--obligor", "0xob"), capsys)
    assert code == 0
    inp = mutation.call_args.args[1]["input"]
    assert mutation.call_args.args[0] is GraphQLMutation.ACCEPT_ALL
    assert inp["denomination"] == "USDx" and inp["obligor"] == "0xob" and _is_uuid4(inp["idempotencyKey"])
    assert out["data"]["message_ids"] == ["m1", "m2"]
    assert out["data"]["accepted_count"] == 2 and out["data"]["failed_count"] == 1


def test_accept_all_wait_polls_every_message(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    ok = graphql({"acceptAll": {"success": True, "totalPayments": 2, "acceptedCount": 2, "failedCount": 0,
                                "acceptedPayments": [{"paymentId": "p1", "messageId": "m1"}, {"paymentId": "p2", "messageId": "m2"}],
                                "failedPayments": []}})
    probe = MagicMock(side_effect=message_results([SETTLED, SETTLED]))
    with patch.object(PaymentsService, "graphql_mutation", return_value=ok), patch.object(PaymentsService, "get_user_message_result", probe):
        code, out, _, _ = run(_base("accept-all", "--asset", "USDx", "--wait", "--interval", "0.001"), capsys)
    assert code == 0
    assert [c.args[1] for c in probe.call_args_list] == ["m1", "m2"]
    assert [r["state"] for r in out["data"]["settlement"]] == ["settled", "settled"]

    probe = MagicMock(side_effect=message_results([SETTLED, FAILED]))
    with patch.object(PaymentsService, "graphql_mutation", return_value=ok), patch.object(PaymentsService, "get_user_message_result", probe):
        code, out, _, _ = run(_base("accept-all", "--asset", "USDx", "--wait", "--interval", "0.001"), capsys)
    assert code == errors.EXIT_ONCHAIN


def test_accept_all_business_failure_is_exit_1(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(PaymentsService, "graphql_mutation", return_value=graphql({"acceptAll": {
        "success": False, "message": "nothing to accept", "failedPayments": [{"paymentId": "p", "error": "x"}]}})):
        code, out, _, _ = run(_base("accept-all", "--asset", "USDx"), capsys)
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "acceptAll_failed"


# ── obligation ────────────────────────────────────────────────────────


def test_obligation_create_prefers_counterpart_wallet(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    mutation = MagicMock(return_value=graphql({"createObligation": {
        "success": True, "message": "queued", "accountAddress": "0xme", "contractId": "CONTRACT-OBLIGATION-1",
        "tokenId": "1", "messageId": "msg-c", "transactionId": "tx", "idHash": "h",
    }}))
    with patch.object(PaymentsService, "graphql_mutation", mutation):
        code, out, _, _ = run(_base(
            "obligation", "create", "--asset", "USDx", "--counterpart-wallet", WALLET_ID,
            "--expiry", "2026-12-31T00:00:00Z", "--data", '{"memo": "rent"}', "--class", "0xclass",
        ), capsys)
    assert code == 0
    assert mutation.call_args.args[0] is GraphQLMutation.CREATE_OBLIGATION
    inp = mutation.call_args.args[1]["input"]
    assert inp["counterpartWalletId"] == WALLET_ID and "counterpart" not in inp
    assert inp["denomination"] == "USDx" and inp["expiry"] == "2026-12-31T00:00:00Z"
    assert inp["data"] == {"memo": "rent"} and inp["obligationAddress"] == "0xclass"
    assert _is_uuid4(inp["idempotencyKey"])
    assert out["data"]["contract_id"] == "CONTRACT-OBLIGATION-1"
    assert out["data"]["acceptable"] is False  # not waited for


def test_obligation_create_counterpart_address_is_refused(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    mutation = MagicMock()
    with patch.object(PaymentsService, "graphql_mutation", mutation):
        code, out, _, _ = run(_base("obligation", "create", "--asset", "A", "--counterpart", "0xabc"), capsys)
    assert code == errors.EXIT_USAGE and out["error"]["code"] == "counterpart_is_address"
    assert not mutation.called


def test_obligation_create_wait_marks_acceptable_after_settlement(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    ok = graphql({"createObligation": {"success": True, "contractId": "CONTRACT-OBLIGATION-2", "messageId": "msg-c"}})
    executed_only = {"executed": "2026-07-17T05:00:00Z", "response": {"status": "post_processing"}, "post_processed_at": None, "post_processing_attempts": 0}
    with patch.object(PaymentsService, "graphql_mutation", return_value=ok), \
         patch.object(PaymentsService, "get_user_message_result", side_effect=message_results([executed_only, SETTLED])):
        code, out, _, _ = run(_base("obligation", "create", "--counterpart", "alice", "--wait", "--interval", "0.001"), capsys)
    assert code == 0
    assert out["data"]["acceptable"] is True
    assert out["data"]["settlement"]["attempts"] == 2


def test_obligation_accept_and_idempotent_no_op(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    mutation = MagicMock(return_value=graphql({"acceptObligation": {
        "success": True, "message": "queued", "obligationId": "7", "acceptResult": None, "messageId": "msg-a", "transactionId": "tx",
    }}))
    with patch.object(PaymentsService, "graphql_mutation", mutation):
        code, out, _, _ = run(_base("obligation", "accept", "--contract", "CONTRACT-OBLIGATION-2"), capsys)
    assert code == 0
    assert mutation.call_args.args[0] is GraphQLMutation.ACCEPT_OBLIGATION
    inp = mutation.call_args.args[1]["input"]
    assert inp["contractId"] == "CONTRACT-OBLIGATION-2" and _is_uuid4(inp["idempotencyKey"])
    assert out["data"]["already_completed"] is False and out["data"]["message_id"] == "msg-a"

    noop = graphql({"acceptObligation": {"success": True, "obligationId": "7", "messageId": "msg-old",
                                         "acceptResult": "Contract already at COMPLETED status; no on-chain action required"}})
    probe = MagicMock()
    with patch.object(PaymentsService, "graphql_mutation", return_value=noop), patch.object(PaymentsService, "get_user_message_result", probe):
        code, out, _, _ = run(_base("obligation", "accept", "--contract", "CONTRACT-OBLIGATION-2", "--wait"), capsys)
    assert code == 0
    assert out["data"]["already_completed"] is True
    assert not probe.called  # nothing new to wait for


def test_obligation_accept_error_is_exit_1(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(PaymentsService, "graphql_mutation", return_value=graphql_errors("Contract not found")):
        code, out, _, _ = run(_base("obligation", "accept", "--contract", "CONTRACT-OBLIGATION-9"), capsys)
    assert code == errors.EXIT_API


# ── group delegate ────────────────────────────────────────────────────


def _delegation_body(scope):
    return {"delegation_jwt": token("153", acting_as=GROUP_ID, session_kind="delegated"), "refresh_token": "dr",
            "group_id": GROUP_ID, "delegation_scope": scope, "expiry_seconds": 1800, "chain_id": "153"}


def test_group_delegate_by_name_resolves_and_prints_server_scope(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    gets = MagicMock(return_value=response([{"id": GROUP_ID, "name": "Treasury"}]))
    posts = MagicMock(return_value=response(_delegation_body(["ReadGroup"])))
    with patch.object(AuthService, "_get", gets), patch.object(AuthService, "_post", posts):
        code, out, _, _ = run(_base("group", "delegate", "--group", "Treasury", "--scope", "ReadGroup", "--scope", "CryptoOperations", "--ttl", "1800"), capsys)
    assert code == 0
    assert gets.call_args == call("/auth/groups/user", token=BEARER)
    assert posts.call_args == call(
        "/auth/delegation/jwt",
        {"group_id": GROUP_ID, "delegation_scope": ["ReadGroup", "CryptoOperations"], "expiry_seconds": 1800},
        token=BEARER,
    )
    # the platform's effective scope, not the requested one
    assert out["data"]["delegation_scope"] == ["ReadGroup"]
    assert out["data"]["group_id"] == GROUP_ID and out["data"]["entity_id"] == GROUP_ID
    assert out["data"]["delegation_jwt"].count(".") == 2
    assert "hint" not in out["data"]


def test_group_delegate_by_id_skips_lookup_and_uses_default_scopes(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    gets = MagicMock()
    posts = MagicMock(return_value=response(_delegation_body(["CryptoOperations"])))
    with patch.object(AuthService, "_get", gets), patch.object(AuthService, "_post", posts):
        code, out, _, _ = run(_base("group", "delegate", "--group", GROUP_ID), capsys)
    assert code == 0
    assert not gets.called
    body = posts.call_args.args[1]
    assert body["delegation_scope"] == ["CryptoOperations", "ReadGroup", "UpdateGroup", "ManageGroupMembers"]
    assert body["expiry_seconds"] == 3600


def test_group_delegate_unknown_name_and_refusal(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(AuthService, "_get", return_value=response([{"id": GROUP_ID, "name": "Other"}])):
        code, out, _, _ = run(_base("group", "delegate", "--group", "Treasury"), capsys)
    assert code == errors.EXIT_USAGE and out["error"]["code"] == "group_not_found"

    with patch.object(AuthService, "_post", side_effect=Exception("403 Client Error: Forbidden")):
        code, out, _, _ = run(_base("group", "delegate", "--group", GROUP_ID), capsys)
    assert code == errors.EXIT_AUTH and out["error"]["code"] == "delegation_refused"


def test_group_delegate_refuses_a_delegated_session(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    delegated = token("153", acting_as=GROUP_ID, session_kind="delegated")
    posts = MagicMock()
    with patch.object(AuthService, "_post", posts):
        code, out, _, _ = run(["--json", "--token", delegated, "group", "delegate", "--group", GROUP_ID], capsys)
    assert code == errors.EXIT_AUTH and out["error"]["code"] == "direct_user_session_required"
    assert not posts.called


# ── kg ────────────────────────────────────────────────────────────────


def test_kg_count_posts_terms_and_warns_on_caps(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    body = {"as_of": None, "terms": [
        {"term": "ACN 123", "mode": "exact", "frames": 4, "frames_capped": False, "documents": 3, "documents_capped": False},
        {"term": "lease", "mode": "exact", "frames": 10000, "frames_capped": True, "documents": 10000, "documents_capped": True},
    ], "union_documents": None, "union_capped": True, "frame_cap": 10000, "document_cap": 10000}
    req = MagicMock(return_value=rest(body))
    with patch.object(AgentsService, "_request_json_safe", req):
        code, out, _, _ = run(_base("kg", "count", "--workspace", GROUP_ID, "--term", "ACN 123", "--term", "lease", "--mode", "exact", "--kg", "kg-1"), capsys)
    assert code == 0
    assert req.call_args == call(
        "POST", "/knowledge/documents/count", token=BEARER,
        data={"working_group_id": GROUP_ID, "terms": [{"term": "ACN 123", "mode": "exact"}, {"term": "lease", "mode": "exact"}], "kg_ids": ["kg-1"]},
    )
    assert out["data"]["terms"][1]["documents_capped"] is True
    assert "floor" in out["data"]["warning"] and "lease" in out["data"]["warning"]
    assert "chain_id" not in out  # knowledge is not chain-scoped


def test_kg_count_forbidden_is_exit_4(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(AgentsService, "_request_json_safe", return_value=rest({"error": "not a member"}, 403)):
        code, out, _, _ = run(_base("kg", "count", "--workspace", GROUP_ID, "--term", "x"), capsys)
    assert code == errors.EXIT_AUTH and out["error"]["http_status"] == 403


def test_kg_retrieve_posts_scope_and_flags_degraded_lanes(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    body = {"query": "rent review", "results": [{"document_id": "d1", "score": 0.9, "text": "…"}],
            "lanes": {"vector_degraded": True, "keyword_degraded": False, "graph_degraded": False, "any_degraded": True, "effort": "standard"}}
    req = MagicMock(return_value=rest(body))
    with patch.object(AgentsService, "_request_json_safe", req):
        code, out, _, _ = run(_base("kg", "retrieve", "--workspace", GROUP_ID, "--query", "rent review", "--set", "set-1", "--top-k", "5", "--min-score", "0.2"), capsys)
    assert code == 0
    assert req.call_args == call(
        "POST", "/knowledge/documents/retrieve", token=BEARER,
        data={"working_group_id": GROUP_ID, "query": "rent review", "set_id": "set-1", "top_k": 5, "min_score": 0.2},
    )
    assert out["data"]["results"][0]["document_id"] == "d1"
    assert "partial" in out["data"]["warning"]


def test_kg_retrieve_kg_and_set_are_exclusive_and_500_is_exit_1(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = run(_base("kg", "retrieve", "--workspace", GROUP_ID, "--query", "q", "--set", "s", "--kg", "k"), capsys)
    assert code == errors.EXIT_USAGE and out["error"]["code"] == "scope_conflict"
    with patch.object(AgentsService, "_request_json_safe", return_value=rest({"error": "retriever unavailable"}, 503)):
        code, out, _, _ = run(_base("kg", "retrieve", "--workspace", GROUP_ID, "--query", "q"), capsys)
    assert code == errors.EXIT_API and out["error"]["http_status"] == 503


# ── human output ──────────────────────────────────────────────────────


def test_human_mode_renders_flat_keys_on_stdout(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(AuthService, "get_jwt_info", return_value=rest({"user_id": USER_ID, "role": "User", "default_chain_id": "153", "session_kind": "personal"})):
        code, _, stdout, _ = run(["--token", BEARER, "whoami"], capsys)
    assert code == 0
    assert f"sub: {USER_ID}" in stdout
    assert "mode: TEST" in stdout
