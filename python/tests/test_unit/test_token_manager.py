import base64
import json
from unittest.mock import MagicMock

from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.token_manager import TokenManager
from yieldfabric.services.payments_service import PaymentsService
from yieldfabric.utils.graphql import GraphQLMutation


def _jwt(payload: dict) -> str:
    def _enc(obj: dict) -> str:
        raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{_enc({'alg': 'none', 'typ': 'JWT'})}.{_enc(payload)}.sig"


def _config() -> YieldFabricConfig:
    return YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        command_delay=0,
        debug=False,
    )


def test_user_token_logs_in_once_and_reuses_cached_token():
    auth = MagicMock()
    token = _jwt({"sub": "user-1", "exp": 2000, "chain_id": "31337"})
    auth.login_session.return_value = {
        "access_token": token,
        "refresh_token": "refresh-1",
        "expires_in": 1000,
    }

    now = [1000.0]
    manager = TokenManager(auth, _config(), now=lambda: now[0])

    assert manager.get_user_token("User@Example.com", "pw") == token
    assert manager.get_user_token("user@example.com", "pw") == token
    auth.login_session.assert_called_once_with("User@Example.com", "pw")
    auth.refresh_access_token.assert_not_called()


def test_user_token_refreshes_with_refresh_token_instead_of_password_login():
    auth = MagicMock()
    first = _jwt({"sub": "user-1", "exp": 1002, "default_chain_id": "31337"})
    refreshed = _jwt({"sub": "user-1", "exp": 2000, "default_chain_id": "31337"})
    auth.login_session.return_value = {
        "access_token": first,
        "refresh_token": "refresh-1",
        "expires_in": 2,
    }
    auth.refresh_access_token.return_value = {
        "access_token": refreshed,
        "refresh_token": "refresh-2",
        "expires_in": 998,
    }

    now = [1000.0]
    manager = TokenManager(auth, _config(), now=lambda: now[0])

    assert manager.get_user_token("u@example.com", "pw") == first
    now[0] = 1001.6
    assert manager.get_user_token("u@example.com", "pw") == refreshed

    auth.login_session.assert_called_once_with("u@example.com", "pw")
    auth.refresh_access_token.assert_called_once_with("refresh-1", chain_id="31337")


def test_user_token_falls_back_to_login_when_refresh_token_was_rotated_elsewhere():
    auth = MagicMock()
    first = _jwt({"sub": "user-1", "exp": 1002, "chain_id": "31337"})
    relogged = _jwt({"sub": "user-1", "exp": 2000, "chain_id": "31337"})
    auth.login_session.side_effect = [
        {
            "access_token": first,
            "refresh_token": "refresh-1",
            "expires_in": 2,
        },
        {
            "access_token": relogged,
            "refresh_token": "refresh-2",
            "expires_in": 998,
        },
    ]
    auth.refresh_access_token.return_value = None

    now = [1000.0]
    manager = TokenManager(auth, _config(), now=lambda: now[0])

    assert manager.get_user_token("u@example.com", "pw") == first
    now[0] = 1001.6
    assert manager.get_user_token("u@example.com", "pw") == relogged

    auth.refresh_access_token.assert_called_once_with("refresh-1", chain_id="31337")
    assert auth.login_session.call_count == 2


def test_refresh_token_lookup_returns_the_token_paired_with_each_access_token():
    auth = MagicMock()
    user_token = _jwt({"sub": "user-1", "exp": 2000, "chain_id": "31337"})
    delegation_token = _jwt({
        "sub": "user-1",
        "acting_as": "group-1",
        "exp": 2000,
    })
    auth.login_session.return_value = {
        "access_token": user_token,
        "refresh_token": "refresh-1",
        "expires_in": 1000,
    }
    auth.get_group_id_by_name.return_value = "group-1"
    auth.create_delegation_session.return_value = {
        "access_token": delegation_token,
        "refresh_token": "delegation-refresh-1",
        "expires_in": 1000,
        "chain_id": "31337",
    }

    manager = TokenManager(auth, _config(), now=lambda: 1000.0)

    assert manager.get_user_token("u@example.com", "pw") == user_token
    assert manager.get_delegation_token("u@example.com", "pw", "Issuer Group") == delegation_token
    assert manager.refresh_token_for_access_token(user_token) == "refresh-1"
    assert (
        manager.refresh_token_for_access_token(delegation_token)
        == "delegation-refresh-1"
    )


def test_group_delegation_rotates_its_own_refresh_token():
    auth = MagicMock()
    user_token = _jwt({"sub": "user-1", "exp": 2000, "chain_id": "31337"})
    first_delegation = _jwt({
        "sub": "user-1",
        "acting_as": "group-1",
        "exp": 1002,
    })
    second_delegation = _jwt({
        "sub": "user-1",
        "acting_as": "group-1",
        "exp": 2000,
    })
    auth.login_session.return_value = {
        "access_token": user_token,
        "refresh_token": "refresh-1",
        "expires_in": 1000,
    }
    auth.get_group_id_by_name.return_value = "group-1"
    auth.create_delegation_session.return_value = {
        "access_token": first_delegation,
        "refresh_token": "delegation-refresh-1",
        "expires_in": 2,
        "chain_id": "31337",
    }
    auth.refresh_access_token.return_value = {
        "access_token": second_delegation,
        "refresh_token": "delegation-refresh-2",
        "expires_in": 998,
    }

    now = [1000.0]
    manager = TokenManager(auth, _config(), now=lambda: now[0])

    assert manager.get_delegation_token("u@example.com", "pw", "Issuer Group") == first_delegation
    now[0] = 1001.6
    assert manager.get_delegation_token("u@example.com", "pw", "Issuer Group") == second_delegation

    auth.login_session.assert_called_once_with("u@example.com", "pw")
    auth.get_group_id_by_name.assert_called_once_with(user_token, "Issuer Group")
    auth.create_delegation_session.assert_called_once_with(
        user_token, "group-1", "Issuer Group"
    )
    auth.refresh_access_token.assert_called_once_with(
        "delegation-refresh-1", chain_id="31337"
    )
    assert (
        manager.refresh_token_for_access_token(second_delegation)
        == "delegation-refresh-2"
    )


def test_rejected_delegation_refresh_mints_a_fresh_delegation():
    auth = MagicMock()
    user_token = _jwt({"sub": "user-1", "exp": 2000, "chain_id": "31337"})
    first_delegation = _jwt({
        "sub": "user-1",
        "acting_as": "group-1",
        "exp": 1002,
    })
    second_delegation = _jwt({
        "sub": "user-1",
        "acting_as": "group-1",
        "exp": 2000,
    })
    auth.login_session.return_value = {
        "access_token": user_token,
        "refresh_token": "user-refresh-1",
        "expires_in": 1000,
    }
    auth.get_group_id_by_name.return_value = "group-1"
    auth.create_delegation_session.side_effect = [
        {
            "access_token": first_delegation,
            "refresh_token": "delegation-refresh-1",
            "expires_in": 2,
            "chain_id": "31337",
        },
        {
            "access_token": second_delegation,
            "refresh_token": "delegation-refresh-2",
            "expires_in": 998,
            "chain_id": "31337",
        },
    ]
    auth.refresh_access_token.return_value = None

    now = [1000.0]
    manager = TokenManager(auth, _config(), now=lambda: now[0])

    assert manager.get_delegation_token(
        "u@example.com", "pw", "Issuer Group"
    ) == first_delegation
    now[0] = 1001.6
    assert manager.get_delegation_token(
        "u@example.com", "pw", "Issuer Group"
    ) == second_delegation

    auth.login_session.assert_called_once_with("u@example.com", "pw")
    auth.get_group_id_by_name.assert_called_once_with(user_token, "Issuer Group")
    assert auth.create_delegation_session.call_count == 2
    auth.refresh_access_token.assert_called_once_with(
        "delegation-refresh-1", chain_id="31337"
    )


def test_legacy_auth_client_without_session_api_still_mints_delegation_token():
    auth = MagicMock(spec=[
        "login_session",
        "get_group_id_by_name",
        "create_delegation_token",
        "refresh_access_token",
    ])
    user_token = _jwt({"sub": "user-1", "exp": 2000, "chain_id": "31337"})
    delegation_token = _jwt({
        "sub": "user-1",
        "acting_as": "group-1",
        "exp": 2000,
    })
    auth.login_session.return_value = {
        "access_token": user_token,
        "refresh_token": "user-refresh-1",
        "expires_in": 1000,
    }
    auth.get_group_id_by_name.return_value = "group-1"
    auth.create_delegation_token.return_value = delegation_token

    manager = TokenManager(auth, _config(), now=lambda: 1000.0)

    assert manager.get_delegation_token(
        "u@example.com", "pw", "Issuer Group"
    ) == delegation_token
    auth.create_delegation_token.assert_called_once_with(
        user_token, "group-1", "Issuer Group"
    )
    assert manager.refresh_token_for_access_token(delegation_token) is None


def test_message_poll_resolves_token_supplier_for_each_probe():
    payments = PaymentsService(_config())
    seen_tokens = []
    observations = [
        {},
        {"executed": "2026-05-28T00:00:00Z"},
    ]

    def supplier():
        return f"token-{len(seen_tokens) + 1}"

    def fake_get_user_message(user_id, message_id, token):
        seen_tokens.append(token)
        return observations.pop(0)

    payments.get_user_message = fake_get_user_message

    result = payments.poll_message_completion(
        "user-1",
        "message-1",
        supplier,
        interval=0.001,
        timeout=1.0,
    )

    assert result.observation["executed"] == "2026-05-28T00:00:00Z"
    assert seen_tokens == ["token-1", "token-2"]


def test_graphql_mutation_forwards_refresh_token_header_when_resolver_matches():
    payments = PaymentsService(_config())
    payments.refresh_token_resolver = lambda token: "refresh-1"

    response = MagicMock()
    response.json.return_value = {"data": {"deposit": {"success": True}}}
    payments._post = MagicMock(return_value=response)

    result = payments.graphql_mutation(GraphQLMutation.DEPOSIT, {"input": {}}, "access-1")

    assert result.success is True
    payments._post.assert_called_once()
    assert payments._post.call_args.kwargs["token"] == "access-1"
    assert payments._post.call_args.kwargs["refresh_token"] == "refresh-1"
