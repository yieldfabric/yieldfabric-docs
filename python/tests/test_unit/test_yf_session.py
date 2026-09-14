"""Credential resolution and the session file for `yf`."""

import json
import os
import stat
from unittest.mock import MagicMock, call, patch

import pytest

from yieldfabric.services.auth_service import AuthService
from yieldfabric.yf import errors
from yieldfabric.yf.errors import CliError
from yieldfabric.yf.session import Session, SessionStore, resolve_session, session_record
from yieldfabric.yf.settings import Settings

from .yf_helpers import GROUP_ID, USER_ID, clean_env, credential_result, response, rest, run, token


def _settings(tmp_path, **kw) -> Settings:
    base = dict(chain_id="153", config_dir=str(tmp_path / "cfg"))
    base.update(kw)
    return Settings(**base)


# ── raw token ─────────────────────────────────────────────────────────


def test_raw_token_is_used_as_is_and_never_touches_auth(tmp_path):
    bearer = token("153", acting_as="group-1")
    auth = MagicMock(spec=AuthService)
    session = resolve_session(_settings(tmp_path, token=bearer), auth)
    assert session.access_token == bearer
    assert session.source == "token"
    assert session.entity_id == "group-1"  # acting_as wins for message polling
    assert session.user_id == USER_ID
    assert not auth.method_calls


def test_chain_mismatch_is_reported_before_any_request(tmp_path):
    with pytest.raises(CliError) as exc:
        resolve_session(_settings(tmp_path, token=token("151"), chain_id="153", chain_source="flag"), MagicMock())
    assert exc.value.exit_code == errors.EXIT_USAGE
    assert exc.value.code == "chain_mismatch"


# ── API key ───────────────────────────────────────────────────────────


def test_api_key_is_exchanged_per_invocation_with_the_chain(tmp_path):
    auth = AuthService(_settings(tmp_path, api_key="yf_api_k").to_config())
    minted = token("153", session_kind="personal")
    auth._request_json_safe = MagicMock(return_value=rest({"token": minted, "refresh_token": "r1", "expires_in": 900}))

    session = resolve_session(_settings(tmp_path, api_key="yf_api_k"), auth)

    assert session.access_token == minted
    assert session.source == "api_key"
    assert session.refresh_token == "r1"
    assert auth._request_json_safe.call_args_list == [call("POST", "/auth/api-key", data={"api_key": "yf_api_k", "chain_id": "153"})]
    # stateless: nothing was written
    assert not os.path.exists(_settings(tmp_path).session_path)


def test_api_key_rejection_is_exit_4(tmp_path):
    auth = AuthService(_settings(tmp_path).to_config())
    auth._request_json_safe = MagicMock(return_value=rest({"error": "Invalid API key"}, 401))
    with pytest.raises(CliError) as exc:
        resolve_session(_settings(tmp_path, api_key="yf_api_bad"), auth)
    assert exc.value.exit_code == errors.EXIT_AUTH
    assert exc.value.code == "api_key_rejected"
    assert exc.value.http_status == 401
    assert "Invalid API key" in exc.value.message


def test_api_key_chain_not_allowed_is_exit_1_with_the_server_code(tmp_path):
    """A connector key on a chain outside its allowed_chains: the 409 body reaches the user."""
    auth = AuthService(_settings(tmp_path).to_config())
    body = {"error": "The requested chain is outside this connector credential's allowed chains",
            "code": "chain_not_allowed", "chain_id": "151", "allowed_chains": ["153"]}
    auth._request_json_safe = MagicMock(return_value=rest(body, 409))
    with pytest.raises(CliError) as exc:
        resolve_session(_settings(tmp_path, api_key="yf_api_conn", chain_id="151", live=True), auth)
    assert exc.value.exit_code == errors.EXIT_API
    assert exc.value.code == "chain_not_allowed"
    assert exc.value.http_status == 409
    assert "allowed: 153" in exc.value.message
    assert exc.value.details["allowed_chains"] == ["153"]


def test_api_key_unreachable_host_is_exit_1_not_credential_rejected(tmp_path):
    auth = AuthService(_settings(tmp_path).to_config())
    auth._request_json_safe = MagicMock(return_value=rest("connection refused", 0))
    with pytest.raises(CliError) as exc:
        resolve_session(_settings(tmp_path, api_key="yf_api_k"), auth)
    assert exc.value.exit_code == errors.EXIT_API
    assert exc.value.code == "unreachable"


def test_api_key_5xx_is_exit_1_with_http_status(tmp_path):
    auth = AuthService(_settings(tmp_path).to_config())
    auth._request_json_safe = MagicMock(return_value=rest({"error": "upstream"}, 503))
    with pytest.raises(CliError) as exc:
        resolve_session(_settings(tmp_path, api_key="yf_api_k"), auth)
    assert exc.value.exit_code == errors.EXIT_API
    assert exc.value.http_status == 503


def test_connector_key_session_cannot_write(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    minted = token("153", session_kind="connector", allowed_chains=["153"])
    with patch.object(AuthService, "_request_json_safe", return_value=rest({"token": minted, "refresh_token": "r", "expires_in": 900})):
        code, out, _, _ = run(
            ["--json", "--api-key", "yf_api_conn", "send", "--asset", "USD", "--amount", "1", "--to-wallet", "w"],
            capsys,
        )
    assert code == errors.EXIT_AUTH
    assert out["error"]["code"] == "connector_cannot_write"


# ── session file ──────────────────────────────────────────────────────


def test_session_file_round_trip_is_private(tmp_path):
    store = SessionStore(str(tmp_path / "cfg" / "session.json"))
    session = Session.from_token(token("153"), source="session", refresh_token="r1")
    store.put("https://auth.yieldfabric.com", session_record(session))

    mode = stat.S_IMODE(os.stat(store.path).st_mode)
    assert mode == 0o600
    record = store.get("https://auth.yieldfabric.com/")  # trailing slash normalised
    assert record["refresh_token"] == "r1"
    assert record["chain_id"] == "153"
    assert store.stored_chain("https://auth.yieldfabric.com") == "153"
    assert store.delete("https://auth.yieldfabric.com") is True
    assert store.get("https://auth.yieldfabric.com") is None


def test_no_credentials_is_usage_error(tmp_path):
    with pytest.raises(CliError) as exc:
        resolve_session(_settings(tmp_path), MagicMock())
    assert exc.value.exit_code == 2
    assert exc.value.code == "no_credentials"


def test_stored_session_is_used_without_refresh_while_fresh(tmp_path):
    settings = _settings(tmp_path)
    store = SessionStore(settings.session_path)
    bearer = token("153", exp_in=600)
    store.put(settings.auth_url, session_record(Session.from_token(bearer, source="session", refresh_token="r1")))
    auth = MagicMock(spec=AuthService)

    session = resolve_session(settings, auth, store=store)

    assert session.access_token == bearer
    assert session.source == "session"
    assert not auth.method_calls


def test_expiring_session_is_refreshed_and_rotated_refresh_token_persisted(tmp_path):
    settings = _settings(tmp_path)
    store = SessionStore(settings.session_path)
    old = token("153", exp_in=30)  # inside the 60 s skew
    store.put(settings.auth_url, session_record(Session.from_token(old, source="session", refresh_token="r-old")))
    fresh = token("153", exp_in=900)
    auth = AuthService(settings.to_config())
    auth._request_json_safe = MagicMock(return_value=rest({"access_token": fresh, "refresh_token": "r-new", "expires_in": 900}))

    session = resolve_session(settings, auth, store=store)

    assert session.access_token == fresh
    assert session.refresh_token == "r-new"
    assert auth._request_json_safe.call_args_list == [call("POST", "/auth/refresh", data={"refresh_token": "r-old", "chain_id": "153"})]
    # single-use: the rotated secret replaced the old one on disk
    assert store.get(settings.auth_url)["refresh_token"] == "r-new"
    assert store.get(settings.auth_url)["access_token"] == fresh


def test_requesting_another_chain_re_mints_via_refresh(tmp_path):
    settings = _settings(tmp_path, chain_id="151", live=True)
    store = SessionStore(settings.session_path)
    store.put(settings.auth_url, session_record(Session.from_token(token("153"), source="session", refresh_token="r1")))
    auth = AuthService(settings.to_config())
    auth._request_json_safe = MagicMock(return_value=rest({"access_token": token("151"), "refresh_token": "r2"}))

    session = resolve_session(settings, auth, store=store)

    assert session.chain_id == "151"
    assert auth._request_json_safe.call_args_list == [call("POST", "/auth/refresh", data={"refresh_token": "r1", "chain_id": "151"})]
    assert store.get(settings.auth_url)["chain_id"] == "151"


def test_failed_refresh_is_exit_4(tmp_path):
    settings = _settings(tmp_path)
    store = SessionStore(settings.session_path)
    store.put(settings.auth_url, session_record(Session.from_token(token("153", exp_in=1), source="session", refresh_token="r1")))
    auth = AuthService(settings.to_config())
    auth._request_json_safe = MagicMock(return_value=rest({"error": "refresh token revoked"}, 401))
    with pytest.raises(CliError) as exc:
        resolve_session(settings, auth, store=store)
    assert exc.value.exit_code == errors.EXIT_AUTH
    assert exc.value.code == "session_expired"
    assert exc.value.http_status == 401
    assert "revoked" in exc.value.message


def test_failed_refresh_on_a_disallowed_chain_keeps_the_server_code(tmp_path):
    settings = _settings(tmp_path, chain_id="151", live=True)
    store = SessionStore(settings.session_path)
    store.put(settings.auth_url, session_record(Session.from_token(token("153", session_kind="connector"), source="session", refresh_token="r1")))
    auth = AuthService(settings.to_config())
    auth._request_json_safe = MagicMock(return_value=rest({"error": "outside allowed chains", "code": "chain_not_allowed", "chain_id": "151", "allowed_chains": ["153"]}, 409))
    with pytest.raises(CliError) as exc:
        resolve_session(settings, auth, store=store)
    assert exc.value.exit_code == errors.EXIT_API
    assert exc.value.code == "chain_not_allowed"
    assert exc.value.http_status == 409


def test_refresh_unreachable_is_exit_1(tmp_path):
    settings = _settings(tmp_path)
    store = SessionStore(settings.session_path)
    store.put(settings.auth_url, session_record(Session.from_token(token("153", exp_in=1), source="session", refresh_token="r1")))
    auth = AuthService(settings.to_config())
    auth._request_json_safe = MagicMock(return_value=rest("name resolution failed", 0))
    with pytest.raises(CliError) as exc:
        resolve_session(settings, auth, store=store)
    assert exc.value.exit_code == errors.EXIT_API
    assert exc.value.code == "unreachable"


def test_expired_session_without_refresh_token_is_exit_4(tmp_path):
    settings = _settings(tmp_path)
    store = SessionStore(settings.session_path)
    store.put(settings.auth_url, session_record(Session.from_token(token("153", exp_in=1), source="session")))
    with pytest.raises(CliError) as exc:
        resolve_session(settings, MagicMock(spec=AuthService), store=store)
    assert exc.value.code == "session_expired"


# ── login / logout commands ───────────────────────────────────────────


def test_login_with_api_key_writes_session_file(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    minted = token("153")
    posts = MagicMock(return_value=rest({"token": minted, "refresh_token": "r1", "expires_in": 900}))
    gets = MagicMock(return_value=response({"user": {"id": USER_ID, "email": "a@b.c"}}))
    with patch.object(AuthService, "_request_json_safe", posts), patch.object(AuthService, "_get", gets):
        code, out, stdout, _ = run(["--json", "login", "--api-key", "yf_api_k"], capsys)
    assert code == 0
    assert out["data"]["user_id"] == USER_ID
    assert out["data"]["mode"] == "TEST"
    assert out["data"]["session_kind"] == "personal"
    assert "access_token" not in out["data"]  # never echoed without --show-tokens
    path = tmp_path / "cfg" / "session.json"
    saved = json.loads(path.read_text())["sessions"]["https://auth.yieldfabric.com"]
    assert saved["access_token"] == minted and saved["refresh_token"] == "r1"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert posts.call_args_list == [call("POST", "/auth/api-key", data={"api_key": "yf_api_k", "chain_id": "153"})]


def test_login_with_password_from_env_pins_chain(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("YF_PASSWORD", "pw")
    default_chain = token("31337")
    pinned = token("153")
    posts = MagicMock(side_effect=[
        rest({"token": default_chain, "refresh_token": "r0", "expires_in": 900}),
        rest({"access_token": pinned, "refresh_token": "r1", "expires_in": 900}),
    ])
    gets = MagicMock(return_value=response({"user": {"id": USER_ID}}))
    with patch.object(AuthService, "_request_json_safe", posts), patch.object(AuthService, "_get", gets):
        code, out, _, _ = run(["--json", "login", "--email", "a@b.c"], capsys)
    assert code == 0
    assert posts.call_args_list[0] == call(
        "POST", "/auth/login/with-services", data={"email": "a@b.c", "password": "pw", "services": ["vault", "payments"]}
    )
    assert posts.call_args_list[1] == call("POST", "/auth/refresh", data={"refresh_token": "r0", "chain_id": "153"})
    assert out["data"]["chain_id"] == "153"


def test_login_failure_is_exit_4(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(AuthService, "_request_json_safe", return_value=rest({"error": "Invalid credentials"}, 401)):
        code, out, _, _ = run(["--json", "login", "--email", "a@b.c", "--password", "bad"], capsys)
    assert code == errors.EXIT_AUTH
    assert out["error"]["code"] == "login_failed"
    assert out["error"]["http_status"] == 401


def test_login_unreachable_is_exit_1_and_5xx_keeps_status(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    with patch.object(AuthService, "_request_json_safe", return_value=rest("connection refused", 0)):
        code, out, _, _ = run(["--json", "login", "--email", "a@b.c", "--password", "pw"], capsys)
    assert code == errors.EXIT_API and out["error"]["code"] == "unreachable"
    with patch.object(AuthService, "_request_json_safe", return_value=rest({"error": "db down"}, 503)):
        code, out, _, _ = run(["--json", "login", "--api-key", "yf_api_k"], capsys)
    assert code == errors.EXIT_API and out["error"]["http_status"] == 503


def test_login_with_connector_key_on_disallowed_chain_reports_chain_not_allowed(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    body = {"error": "outside allowed chains", "code": "chain_not_allowed", "chain_id": "151", "allowed_chains": ["153"]}
    with patch.object(AuthService, "_request_json_safe", return_value=rest(body, 409)):
        code, out, _, _ = run(["--json", "--chain", "151", "--live", "login", "--api-key", "yf_api_conn"], capsys)
    assert code == errors.EXIT_API
    assert out["error"]["code"] == "chain_not_allowed" and out["error"]["http_status"] == 409


def test_logout_removes_the_record(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    store = SessionStore(str(tmp_path / "cfg" / "session.json"))
    store.put("https://auth.yieldfabric.com", session_record(Session.from_token(token("153"), source="session")))
    code, out, _, _ = run(["--json", "logout"], capsys)
    assert code == 0 and out["data"]["removed"] is True
    code, out, _, _ = run(["--json", "logout"], capsys)
    assert code == 0 and out["data"]["removed"] is False


# ── saved delegations ─────────────────────────────────────────────────


def _delegation_body(scope):
    return {"delegation_jwt": token("153", acting_as=GROUP_ID, session_kind="delegated", exp_in=1800), "refresh_token": "dr",
            "group_id": GROUP_ID, "delegation_scope": scope, "expiry_seconds": 1800, "chain_id": "153"}


def _personal_login(store: SessionStore, auth_url="https://auth.yieldfabric.com", **kw):
    bearer = token("153", exp_in=900, **kw)
    store.put(auth_url, session_record(Session.from_token(bearer, source="session", refresh_token="r-personal")))
    return bearer


def test_group_delegate_save_keeps_the_personal_login_beside_it(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    store = SessionStore(str(tmp_path / "cfg" / "session.json"))
    personal = _personal_login(store)
    with patch.object(AuthService, "_post", return_value=response(_delegation_body(["ReadGroup"]))):
        code, out, _, _ = run(["--json", "group", "delegate", "--group", GROUP_ID, "--save"], capsys)
    assert code == 0
    record = store.get("https://auth.yieldfabric.com")
    # the personal access + refresh pair survives
    assert record["access_token"] == personal and record["refresh_token"] == "r-personal"
    assert record["kind"] == "personal"
    # the delegation is the active session
    delegation = record["delegation"]
    assert delegation["kind"] == "delegated" and delegation["acting_as"] == GROUP_ID and delegation["group_id"] == GROUP_ID
    assert delegation["refresh_token"] is None
    assert store.stored_chain("https://auth.yieldfabric.com") == "153"

    # subsequent commands run as the group…
    with patch.object(AuthService, "get_jwt_info", return_value=rest({"user_id": USER_ID, "acting_as": GROUP_ID, "default_chain_id": "153", "session_kind": "delegated"})):
        code, out, _, _ = run(["--json", "whoami"], capsys)
    assert code == 0 and out["data"]["entity_id"] == GROUP_ID and out["data"]["credential_source"] == "session"

    # …and `logout --delegation` returns to the person without a new login
    code, out, _, _ = run(["--json", "logout", "--delegation"], capsys)
    assert code == 0 and out["data"]["removed"] is True and out["data"]["scope"] == "delegation"
    record = store.get("https://auth.yieldfabric.com")
    assert record["access_token"] == personal and "delegation" not in record


def test_expired_saved_delegation_names_the_right_remedy(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    store = SessionStore(str(tmp_path / "cfg" / "session.json"))
    _personal_login(store)
    expired = Session.from_token(token("153", acting_as=GROUP_ID, session_kind="delegated", exp_in=-5), source="token")
    record = session_record(expired, kind="delegated")
    record["refresh_token"] = None
    store.put_delegation("https://auth.yieldfabric.com", record)

    code, out, _, _ = run(["--json", "whoami"], capsys)
    assert code == errors.EXIT_AUTH
    assert out["error"]["code"] == "delegation_expired"
    assert "group delegate --save" in out["error"]["message"]
    assert "logout --delegation" in out["error"]["message"]
    assert "yf login" not in out["error"]["message"]
    # nothing was refreshed or lost
    assert store.get("https://auth.yieldfabric.com")["refresh_token"] == "r-personal"


def test_saved_delegation_without_personal_login_works_and_clears_cleanly(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    store = SessionStore(str(tmp_path / "cfg" / "session.json"))
    delegation = Session.from_token(token("153", acting_as=GROUP_ID, session_kind="delegated", exp_in=600), source="token")
    store.put_delegation("https://auth.yieldfabric.com", session_record(delegation, kind="delegated"))
    with patch.object(AuthService, "get_jwt_info", return_value=rest({"user_id": USER_ID, "acting_as": GROUP_ID, "default_chain_id": "153"})):
        code, out, _, _ = run(["--json", "whoami"], capsys)
    assert code == 0 and out["data"]["entity_id"] == GROUP_ID
    assert store.clear_delegation("https://auth.yieldfabric.com") is True
    assert store.get("https://auth.yieldfabric.com") is None
    assert store.clear_delegation("https://auth.yieldfabric.com") is False


def test_saved_delegation_chain_mismatch_points_at_group_delegate(monkeypatch, tmp_path):
    settings = _settings(tmp_path, chain_id="151", live=True, chain_source="flag")
    store = SessionStore(settings.session_path)
    delegation = Session.from_token(token("153", acting_as=GROUP_ID, session_kind="delegated", exp_in=600), source="token")
    store.put_delegation(settings.auth_url, session_record(delegation, kind="delegated"))
    with pytest.raises(CliError) as exc:
        resolve_session(settings, MagicMock(spec=AuthService), store=store)
    assert exc.value.code == "chain_mismatch"
    assert "group delegate --save" in exc.value.message


def test_fresh_login_replaces_the_whole_record_including_a_saved_delegation(monkeypatch, tmp_path, capsys):
    clean_env(monkeypatch, tmp_path)
    store = SessionStore(str(tmp_path / "cfg" / "session.json"))
    _personal_login(store)
    delegation = Session.from_token(token("153", acting_as=GROUP_ID, session_kind="delegated", exp_in=600), source="token")
    store.put_delegation("https://auth.yieldfabric.com", session_record(delegation, kind="delegated"))
    minted = token("153")
    with patch.object(AuthService, "_request_json_safe", return_value=rest({"token": minted, "refresh_token": "r2"})), \
         patch.object(AuthService, "_get", return_value=response({"user": {"id": USER_ID}})):
        code, _, _, _ = run(["--json", "login", "--api-key", "yf_api_k"], capsys)
    assert code == 0
    record = store.get("https://auth.yieldfabric.com")
    assert record["access_token"] == minted and "delegation" not in record
