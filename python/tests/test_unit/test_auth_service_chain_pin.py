import base64
import json
from unittest.mock import MagicMock, call
from typing import Optional

from yieldfabric.config import YieldFabricConfig
from yieldfabric.services.auth_service import AuthService


def _jwt(payload: dict) -> str:
    def encode(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}.sig"


def _response(body: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = body
    return response


def _config(chain_id: Optional[str] = None) -> YieldFabricConfig:
    return YieldFabricConfig(
        pay_service_url="http://localhost:3003",
        auth_service_url="http://localhost:3000",
        chain_id=chain_id,
        command_delay=0,
        debug=False,
    )


def test_login_refreshes_onto_configured_chain_before_returning_token():
    service = AuthService(_config("153"))
    default_token = _jwt({"sub": "user-1", "default_chain_id": "31337"})
    test_token = _jwt({"sub": "user-1", "default_chain_id": "153"})
    service._post = MagicMock(
        side_effect=[
            _response({
                "token": default_token,
                "refresh_token": "refresh-default",
                "expires_in": 900,
            }),
            _response({
                "access_token": test_token,
                "refresh_token": "refresh-test",
                "expires_in": 900,
            }),
        ]
    )

    session = service.login_session("user@example.com", "password")

    assert session is not None
    assert session["access_token"] == test_token
    assert session["refresh_token"] == "refresh-test"
    assert service._post.call_args_list == [
        call(
            "/auth/login/with-services",
            {
                "email": "user@example.com",
                "password": "password",
                "services": ["vault", "payments"],
            },
        ),
        call(
            "/auth/refresh",
            {"refresh_token": "refresh-default", "chain_id": "153"},
        ),
    ]


def test_login_does_not_rotate_when_token_is_already_on_target_chain():
    service = AuthService(_config("153"))
    token = _jwt({"sub": "user-1", "default_chain_id": "153"})
    service._post = MagicMock(
        return_value=_response({
            "token": token,
            "refresh_token": "refresh-test",
            "expires_in": 900,
        })
    )

    session = service.login_session("user@example.com", "password")

    assert session is not None
    assert session["access_token"] == token
    assert service._post.call_count == 1


def test_api_key_exchange_carries_the_configured_chain():
    service = AuthService(_config("153"))
    token = _jwt({"sub": "user-1", "default_chain_id": "153"})
    service._post = MagicMock(return_value=_response({
        "token": token,
        "refresh_token": "refresh-test",
        "expires_in": 900,
    }))

    assert service.authenticate_api_key("yf_api_test") == token
    service._post.assert_called_once_with(
        "/auth/api-key",
        {"api_key": "yf_api_test", "chain_id": "153"},
    )


def test_api_key_session_retains_refresh_token_for_lazy_account_activation():
    service = AuthService(_config("153"))
    token = _jwt({"sub": "user-1", "default_chain_id": "153"})
    service._post = MagicMock(return_value=_response({
        "token": token,
        "refresh_token": "refresh-test",
        "expires_in": 900,
    }))

    session = service.authenticate_api_key_session("yf_api_test")

    assert session is not None
    assert session["access_token"] == token
    assert session["refresh_token"] == "refresh-test"
    assert session["expires_in"] == 900


def test_delegation_session_retains_its_distinct_refresh_token():
    service = AuthService(_config("153"))
    delegation = _jwt({
        "sub": "user-1",
        "acting_as": "group-1",
        "default_chain_id": "153",
    })
    service._post = MagicMock(return_value=_response({
        "delegation_jwt": delegation,
        "refresh_token": "delegation-refresh-1",
        "expiry_seconds": 3600,
        "group_id": "group-1",
        "chain_id": "153",
    }))

    session = service.create_delegation_session(
        "user-token", "group-1", "Issuer Group"
    )

    assert session is not None
    assert session["access_token"] == delegation
    assert session["refresh_token"] == "delegation-refresh-1"
    assert session["expires_in"] == 3600
    assert session["chain_id"] == "153"
    assert service.create_delegation_token(
        "user-token", "group-1", "Issuer Group"
    ) == delegation


def test_create_group_is_off_chain_before_explicit_activation():
    service = AuthService(_config("153"))
    response = _response({"id": "group-1", "account_activation": None})
    response.status_code = 200
    service.session.post = MagicMock(return_value=response)

    result = service.create_group(
        "creator-token",
        name="Issuer Group",
        description="Issuer",
        group_type="project",
    )

    assert result["status"] == "created"
    service.session.post.assert_called_once_with(
        "http://localhost:3000/auth/groups",
        json={
            "name": "Issuer Group",
            "description": "Issuer",
            "group_type": "project",
            "deploy": False,
        },
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer creator-token",
        },
        timeout=30,
    )


def test_group_account_mutations_assert_the_jwt_chain():
    service = AuthService(_config())
    token = _jwt({"sub": "user-1", "default_chain_id": "31337"})
    service._post = MagicMock(
        return_value=_response({"success": True, "status": "confirmed"})
    )

    service.add_group_owner(token, "group-1", "owner-1")
    service.remove_group_owner(token, "group-1", "0x" + "11" * 20)
    service.add_account_member(
        token, "group-1", "credit_token_1", "0x" + "22" * 20
    )
    service.remove_account_member(token, "group-1", "credit_token_1")

    assert service._post.call_args_list == [
        call(
            "/auth/groups/group-1/add-owner",
            {"new_owner": "owner-1", "chain_id": "31337"},
            token=token,
        ),
        call(
            "/auth/groups/group-1/remove-owner",
            {"old_owner": "0x" + "11" * 20, "chain_id": "31337"},
            token=token,
        ),
        call(
            "/auth/groups/group-1/add-account-member",
            {
                "obligation_id": "credit_token_1",
                "chain_id": "31337",
                "obligation_address": "0x" + "22" * 20,
            },
            token=token,
        ),
        call(
            "/auth/groups/group-1/remove-account-member",
            {"obligation_id": "credit_token_1", "chain_id": "31337"},
            token=token,
        ),
    ]


def test_group_account_mutation_fails_closed_without_a_jwt_chain():
    service = AuthService(_config("31337"))
    service._post = MagicMock()

    result = service.add_account_member(
        _jwt({"sub": "user-1"}), "group-1", "credit_token_1"
    )

    assert result == {
        "status": "error",
        "message": (
            "add_account_member requires an authenticated JWT with a valid "
            "default_chain_id"
        ),
    }
    service._post.assert_not_called()
