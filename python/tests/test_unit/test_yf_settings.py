"""Settings, chain precedence, the live guard and --json output purity for `yf`."""

import argparse
import json
from unittest.mock import patch

import pytest

from yieldfabric.services.agents_service import AgentsService
from yieldfabric.services.auth_service import AuthService
from yieldfabric.services.payments_service import PaymentsService
from yieldfabric.yf import errors
from yieldfabric.yf.context import WRITE_COMMANDS, Context
from yieldfabric.yf.errors import CliError
from yieldfabric.yf.settings import (
    DEFAULT_PAYMENTS_URLS,
    Settings,
    enforce_live_guard,
    load_env_file,
    mode_for_chain,
    parse_payments_urls,
    resolve_settings,
)

from .yf_helpers import GROUP_ID, clean_env, rest, run, token


def _args(**kw) -> argparse.Namespace:
    base = dict(
        token=None, api_key=None, chain=None, auth_url=None, agents_url=None,
        payments_url=None, timeout=None, live=False, json=False, debug=False, env_file=None,
    )
    base.update(kw)
    return argparse.Namespace(**base)


# ── YF_PAYMENTS_URLS ──────────────────────────────────────────────────


def test_payments_urls_partial_override_merges_over_defaults():
    urls = parse_payments_urls(json.dumps({"153": "https://pay.example.test/"}))
    assert urls["153"] == "https://pay.example.test"
    assert urls["151"] == DEFAULT_PAYMENTS_URLS["151"]


def test_payments_urls_rejects_non_object():
    with pytest.raises(CliError) as exc:
        parse_payments_urls("[1,2]")
    assert exc.value.exit_code == errors.EXIT_USAGE
    assert exc.value.code == "bad_payments_urls"


def test_unknown_chain_is_a_usage_error():
    settings = resolve_settings(_args(chain="99999"), {})
    with pytest.raises(CliError) as exc:
        settings.payments_url()
    assert exc.value.exit_code == 2
    assert exc.value.code == "unknown_chain"


def test_payments_url_override_wins_for_any_chain():
    settings = resolve_settings(_args(chain="99999", payments_url="https://pay.override.test/"), {})
    assert settings.payments_url() == "https://pay.override.test"


# ── chain precedence ──────────────────────────────────────────────────


def test_chain_flag_beats_env_beats_session_beats_default():
    assert resolve_settings(_args(chain="151"), {"YF_CHAIN": "153"}, stored_session_chain="31337").chain_id == "151"
    assert resolve_settings(_args(), {"YF_CHAIN": "153"}, stored_session_chain="31337").chain_id == "153"
    s = resolve_settings(_args(), {}, stored_session_chain="31337")
    assert (s.chain_id, s.chain_source) == ("31337", "session")
    s = resolve_settings(_args(), {})
    assert (s.chain_id, s.chain_source) == ("153", "default")


def test_raw_token_chain_is_used_when_nothing_else_says():
    s = resolve_settings(_args(token=token("151")), {}, stored_session_chain="153")
    assert (s.chain_id, s.chain_source) == ("151", "token")


def test_defaults_are_production_hosts():
    s = resolve_settings(_args(), {})
    assert s.auth_url == "https://auth.yieldfabric.com"
    assert s.agents_url == "https://agents.yieldfabric.com"
    assert s.payments_url() == "https://pay.test.yieldfabric.com"
    assert s.mode == "TEST"
    assert mode_for_chain("151") == "LIVE"
    assert mode_for_chain("31337") == "TEST"


def test_to_config_is_explicit_not_from_env(monkeypatch):
    # The harness env names must not leak into the CLI's config.
    monkeypatch.setenv("PAY_SERVICE_URL", "http://localhost:3002")
    monkeypatch.setenv("AUTH_SERVICE_URL", "http://localhost:3000")
    monkeypatch.setenv("API_KEY", "yf_api_harness")
    config = resolve_settings(_args(), {}).to_config()
    assert config.pay_service_url == "https://pay.test.yieldfabric.com"
    assert config.auth_service_url == "https://auth.yieldfabric.com"
    assert config.api_key == ""
    assert config.chain_id == "153"


def test_bad_timeout_is_usage_error():
    with pytest.raises(CliError) as exc:
        resolve_settings(_args(), {"YF_TIMEOUT": "soon"})
    assert exc.value.code == "bad_timeout"


# ── live guard ────────────────────────────────────────────────────────


def test_live_guard_refuses_151_without_flag():
    with pytest.raises(CliError) as exc:
        enforce_live_guard(Settings(chain_id="151", live=False))
    assert exc.value.exit_code == 2
    assert exc.value.code == "live_requires_flag"
    enforce_live_guard(Settings(chain_id="151", live=True))
    enforce_live_guard(Settings(chain_id="153", live=False))


def test_live_guard_runs_before_any_client_is_built(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(AuthService, "__init__", side_effect=AssertionError("AuthService built")), \
         patch.object(PaymentsService, "__init__", side_effect=AssertionError("PaymentsService built")):
        code, out, _, _ = run(["--json", "--chain", "151", "--api-key", "yf_api_x", "whoami"], capsys)
    assert code == 2
    assert out["ok"] is False
    assert out["error"]["code"] == "live_requires_flag"
    assert out["chain_id"] == "151"


def test_global_flags_are_accepted_after_the_command_too(monkeypatch, tmp_path, capsys):
    """`yf whoami --json` and `yf … send --live` are what people type; both
    orderings must reach the same verdict (no usage error from argparse)."""
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = run(["whoami", "--json"], capsys)
    assert code == 2 and out["ok"] is False and out["error"]["code"] == "no_credentials"

    code, out, _, _ = run(["--chain", "151", "--api-key", "yf_api_x", "whoami", "--json"], capsys)
    assert code == 2 and out["error"]["code"] == "live_requires_flag" and out["chain_id"] == "151"

    # a trailing --live must not be overwritten by the sub-parser's default
    code, out, _, _ = run(["--chain", "151", "send", "--to", "alice", "--amount", "1", "--asset", "USDx", "--live", "--json"], capsys)
    assert code == 2 and out["error"]["code"] == "no_credentials"

    # nested sub-commands accept them as well
    code, out, _, _ = run(["obligation", "accept", "--contract", "CONTRACT-OBLIGATION-1", "--json"], capsys)
    assert code == 2 and out["error"]["code"] == "no_credentials"


def test_live_guard_applies_to_login_too(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = run(["--json", "--chain", "151", "login", "--api-key", "yf_api_x"], capsys)
    assert code == 2
    assert out["error"]["code"] == "live_requires_flag"


def test_live_guard_keys_on_the_payments_host_too(monkeypatch, tmp_path, capsys):
    """`--chain 153 --payments-url https://pay.live…` must not slip past the guard."""
    clean_env(monkeypatch, tmp_path)
    with patch.object(PaymentsService, "__init__", side_effect=AssertionError("PaymentsService built")):
        code, out, _, _ = run(["--json", "--chain", "153", "--payments-url", "https://pay.live.yieldfabric.com",
                               "--token", token("153"), "balance", "--asset", "USDx"], capsys)
    assert code == 2 and out["error"]["code"] == "live_requires_flag"
    assert "pay.live.yieldfabric.com" in out["error"]["message"]

    # the same through YF_PAYMENTS_URLS
    monkeypatch.setenv("YF_PAYMENTS_URLS", json.dumps({"153": "https://pay.live.yieldfabric.com"}))
    code, out, _, _ = run(["--json", "--chain", "153", "--token", token("153"), "balance", "--asset", "USDx"], capsys)
    assert code == 2 and out["error"]["code"] == "live_requires_flag"

    # a host that YF_PAYMENTS_URLS maps to a live chain counts as live as well
    monkeypatch.setenv("YF_PAYMENTS_URLS", json.dumps({"151": "https://pay.example.test", "153": "https://pay.example.test"}))
    code, out, _, _ = run(["--json", "--chain", "153", "--token", token("153"), "balance", "--asset", "USDx"], capsys)
    assert code == 2 and out["error"]["code"] == "live_requires_flag"

    # --live lets it through to the (mocked) client
    monkeypatch.delenv("YF_PAYMENTS_URLS")
    from yieldfabric.models.response import RESTResponse
    with patch.object(PaymentsService, "get_balance", return_value=RESTResponse.from_response(200, {"balance": {}})):
        code, out, _, _ = run(["--json", "--live", "--chain", "153", "--payments-url", "https://pay.live.yieldfabric.com",
                               "--token", token("153"), "balance", "--asset", "USDx"], capsys)
    assert code == 0


def test_payments_host_is_live_predicate():
    assert Settings(chain_id="153", payments_url_override="https://pay.live.yieldfabric.com/").payments_host_is_live()
    assert Settings(chain_id="153", payments_url_override="HTTPS://PAY.LIVE.YIELDFABRIC.COM").payments_host_is_live()
    assert not Settings(chain_id="153").payments_host_is_live()
    assert Settings(chain_id="151").payments_host_is_live()
    assert not Settings(chain_id="99999").payments_host_is_live()  # unknown chain: nothing to key on


# ── commands that are not chain-scoped ────────────────────────────────


def test_kg_runs_without_live_flag_on_a_live_session_and_without_a_payments_host(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    body = {"as_of": None, "terms": [{"term": "x", "mode": "exact", "frames": 1, "frames_capped": False, "documents": 1, "documents_capped": False}]}
    with patch.object(AgentsService, "_request_json_safe", return_value=rest(body)), \
         patch.object(PaymentsService, "__init__", side_effect=AssertionError("PaymentsService built")):
        # a session last minted on the live chain, no --live
        code, out, _, _ = run(["--json", "--token", token("151"), "kg", "count", "--workspace", GROUP_ID, "--term", "x"], capsys)
        assert code == 0 and "chain_id" not in out
        # a chain with no payments host configured at all
        code, out, _, _ = run(["--json", "--chain", "99999", "--token", token("99999"), "kg", "count", "--workspace", GROUP_ID, "--term", "x"], capsys)
        assert code == 0


def test_payments_client_still_needs_a_host_for_the_chain(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, out, _, _ = run(["--json", "--chain", "99999", "--token", token("99999"), "balance", "--asset", "USDx"], capsys)
    assert code == 2 and out["error"]["code"] == "unknown_chain"
    settings = resolve_settings(_args(chain="99999"), {})
    assert settings.to_config().pay_service_url == ""  # tolerated for auth/agents-only commands
    with pytest.raises(CliError) as exc:
        Context(settings, "balance").payments()
    assert exc.value.code == "unknown_chain"


# ── connector write gate is decided in one place ──────────────────────


@pytest.mark.parametrize("command", sorted(WRITE_COMMANDS))
def test_every_write_command_refuses_a_connector_session_before_any_request(monkeypatch, tmp_path, capsys, command):
    clean_env(monkeypatch, tmp_path)
    argv = {
        "send": ["send", "--asset", "USDx", "--amount", "1", "--to-wallet", "w"],
        "accept-all": ["accept-all", "--asset", "USDx"],
        "obligation create": ["obligation", "create", "--asset", "USDx", "--counterpart", "alice"],
        "obligation accept": ["obligation", "accept", "--contract", "CONTRACT-OBLIGATION-1"],
        "group delegate": ["group", "delegate", "--group", GROUP_ID],
    }[command]
    connector = token("153", session_kind="connector", allowed_chains=["153"])
    with patch.object(PaymentsService, "graphql_mutation", side_effect=AssertionError("request sent")), \
         patch.object(AuthService, "_post", side_effect=AssertionError("request sent")), \
         patch.object(AuthService, "_get", side_effect=AssertionError("request sent")):
        code, out, _, _ = run(["--json", "--token", connector] + argv, capsys)
    assert code == errors.EXIT_AUTH
    assert out["error"]["code"] == "connector_cannot_write"


def test_read_commands_accept_a_connector_session(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    connector = token("153", session_kind="connector", allowed_chains=["153"])
    with patch.object(AuthService, "get_jwt_info", return_value=rest({"user_id": "u", "default_chain_id": "153", "session_kind": "connector"})):
        code, out, _, _ = run(["--json", "--token", connector, "whoami"], capsys)
    assert code == 0 and out["data"]["session_kind"] == "connector"


# ── --debug never echoes credentials ──────────────────────────────────


def test_debug_output_masks_tokens_in_auth_responses(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    minted = token("153")
    body = {"token": minted, "refresh_token": "rt_secret_value_123", "expires_in": 900}

    def noisy(self, method, endpoint, **kw):
        # what the real client does: log the response body at debug level
        self.logger.debug(f"    📡 API-key auth response: {body}")
        return rest(body)

    with patch.object(AuthService, "_request_json_safe", noisy), \
         patch.object(AuthService, "_get", return_value=rest({"user": {"id": "u"}})), \
         patch.object(AuthService, "get_user_id_from_profile", return_value="u"):
        code, _, stdout, stderr = run(["--json", "--debug", "login", "--api-key", "yf_api_k_secret"], capsys)
    assert code == 0
    assert "API-key auth response" in stderr  # the line is still logged…
    assert minted not in stderr and minted not in stdout  # …without the bearer
    assert "yf_api_k_secret" not in stderr
    assert "***redacted***" in stderr


# ── --json purity ─────────────────────────────────────────────────────


def test_json_mode_prints_exactly_one_document_and_logs_go_to_stderr(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    bearer = token("153")
    with patch.object(AuthService, "get_jwt_info", return_value=rest({"user_id": "u", "role": "User", "default_chain_id": "153", "session_kind": "personal"})):
        # Force a log line from the shared logger through a real client.
        def noisy(self, tok):
            self.logger.info("a progress line that must not reach stdout")
            return rest({"user_id": "u", "role": "User", "default_chain_id": "153", "session_kind": "personal"})

        with patch.object(AuthService, "get_jwt_info", noisy):
            code, out, stdout, stderr = run(["--json", "--debug", "--token", bearer, "whoami"], capsys)
    assert code == 0
    assert out["ok"] is True and out["command"] == "whoami"
    assert json.loads(stdout.strip()) == out
    assert "progress line" in stderr
    assert "progress line" not in stdout


def test_human_mode_error_goes_to_stderr_only(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    code, _, stdout, stderr = run(["whoami"], capsys)
    assert code == 2
    assert stdout == ""
    assert "no_credentials" in stderr


# ── --env-file (explicit only) ────────────────────────────────────────


def test_env_file_is_only_read_when_asked(monkeypatch, tmp_path):
    clean_env(monkeypatch, tmp_path)
    env_file = tmp_path / "prod.env"
    env_file.write_text('export YF_CHAIN="31337"\nYF_AUTH_URL=https://auth.example.test\n# comment\n')
    env = {}
    load_env_file(str(env_file), env)
    assert env == {"YF_CHAIN": "31337", "YF_AUTH_URL": "https://auth.example.test"}
    # A ./.env in the cwd is never consulted: nothing here reads it.
    with pytest.raises(CliError) as exc:
        load_env_file(str(tmp_path / "missing.env"), {})
    assert exc.value.code == "env_file_unreadable"
