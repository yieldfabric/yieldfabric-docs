import base64
import json
from unittest.mock import MagicMock, call

from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.output_store import OutputStore
from yieldfabric.executors.owned_group_executor import OwnedGroupExecutor
from yieldfabric.models import Command, CommandParameters
from yieldfabric.models.user import User
from yieldfabric.utils.polling import PollResult


def _jwt(payload: dict) -> str:
    def enc(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{enc({'alg': 'none'})}.{enc(payload)}.signature"


def _config() -> YieldFabricConfig:
    return YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        command_delay=0,
        debug=False,
    )


def _command(command_type: str, params: dict, *, group="Issuer Group"):
    return Command(
        name="step",
        type=command_type,
        user=User(
            id="issuer@yieldfabric.com",
            password="issuer_password",
            group=group,
        ),
        parameters=CommandParameters.from_dict(params),
    )


def _executor():
    auth = MagicMock()
    payments = MagicMock()
    store = OutputStore(debug=False)
    tokens = MagicMock()
    tokens.get_token.return_value = "direct-parent-jwt"
    executor = OwnedGroupExecutor(
        auth, payments, store, _config(), tokens
    )
    return executor, auth, payments, store, tokens


def _personal_claims(
    user_id="77777777-7777-4777-8777-777777777777",
    chain_id="153",
):
    return {
        "sub": user_id,
        "kind": "user",
        "entity_type": "user",
        "auth_method": "jwt",
        "password_change_only": False,
        "default_chain_id": chain_id,
        "exp": 1_800_003_600,
    }


def _direct_group_claims(user_id, group_id, token_id, chain_id):
    return {
        "sub": user_id,
        "kind": "user",
        "entity_type": "user",
        "auth_method": "delegation",
        "password_change_only": False,
        "acting_as": group_id,
        "delegation_token_id": token_id,
        "default_chain_id": chain_id,
        "delegation_scope": ["ReadGroup", "CryptoOperations"],
        "iat": 1_800_000_000,
        "exp": 1_800_003_600,
    }


def test_assume_owned_group_keeps_child_out_of_outputs_and_store():
    executor, auth, _, store, tokens = _executor()
    user_id = "11111111-1111-4111-8111-111111111111"
    parent_group_id = "22222222-2222-4222-8222-222222222222"
    child_group_id = "33333333-3333-4333-8333-333333333333"
    parent_token_id = "44444444-4444-4444-8444-444444444444"
    child_token_id = "55555555-5555-4555-8555-555555555555"
    signer_key_id = "66666666-6666-4666-8666-666666666666"
    parent = _jwt(_direct_group_claims(
        user_id, parent_group_id, parent_token_id, "31337"
    ))
    tokens.get_token.return_value = parent
    child = _jwt({
        "sub": user_id,
        "kind": "user",
        "entity_type": "user",
        "auth_method": "delegation",
        "password_change_only": False,
        "acting_as": child_group_id,
        "delegation_token_id": child_token_id,
        "default_chain_id": "31337",
        "delegation_scope": ["ReadGroup", "CryptoOperations"],
        "delegation_path": [parent_group_id, child_group_id],
        "authority_source": "nft_membership",
        "membership_edge": {
            "parent_group_id": parent_group_id,
            "child_group_id": child_group_id,
            "chain_id": "31337",
            "credential_contract": "0x1111111111111111111111111111111111111111",
            "token_id": "42",
        },
        "signer_key_id": signer_key_id,
        "signer_address": "0x2222222222222222222222222222222222222222",
        "signer_scheme": "account_ecdsa65_v1",
        "signer_custody": "custodial",
        "iat": 1_800_000_000,
        "exp": 1_800_000_600,
    })
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "delegation_jwt": child,
            "group_id": child_group_id,
            "delegation_scope": ["ReadGroup", "CryptoOperations"],
            "expiry_seconds": 600,
            "chain_id": "31337",
            "delegation_path": [parent_group_id, child_group_id],
            "authority_source": "nft_membership",
            "membership_edge": {
                "parent_group_id": parent_group_id,
                "child_group_id": child_group_id,
                "chain_id": "31337",
                "credential_contract": "0x1111111111111111111111111111111111111111",
                "token_id": "42",
            },
            "signer_key_id": signer_key_id,
            "signer_address": "0x2222222222222222222222222222222222222222",
            "signer_scheme": "account_ecdsa65_v1",
            "signer_custody": "custodial",
        },
    }
    command = _command("assume_owned_group", {
        "group_id": child_group_id,
        "delegation_scope": ["ReadGroup", "CryptoOperations"],
        "expiry_seconds": 600,
        "signer_key_id": signer_key_id,
        "credential_name": "owned-b",
    })

    response = executor.execute(command)

    assert response.success is True
    tokens.register_named_credential.assert_called_once_with(
        "owned-b", child
    )
    assert response.data["credential"] == "owned-b"
    assert response.data["acting_as"] == child_group_id
    assert child not in repr(response.data)
    assert child not in repr(store.get_all())
    auth._request_json_safe.assert_called_once_with(
        "POST",
        "/auth/delegation/jwt/assume-owned-group",
        token=parent,
        data={
            "group_id": child_group_id,
            "delegation_scope": ["ReadGroup", "CryptoOperations"],
            "expiry_seconds": 600,
            "signer_key_id": signer_key_id,
        },
    )


def test_user_signing_key_selects_oldest_active_custodial_user_key():
    executor, auth, _, _, tokens = _executor()
    user_id = "11111111-1111-4111-8111-111111111111"
    personal_jwt = _jwt(_personal_claims(user_id))
    tokens.get_token.return_value = personal_jwt
    auth.get_user_keys.return_value = [
            {
                "id": "external",
                "entity_type": "user",
                "entity_id": user_id,
                "key_type": "Signing",
                "provider_type": "External",
                "is_active": True,
                "created_at": "2020-01-01T00:00:00Z",
            },
            {
                "id": "newer",
                "entity_type": "user",
                "entity_id": user_id,
                "key_type": "Signing",
                "provider_type": "OpenSSL",
                "is_active": True,
                "created_at": "2025-01-01T00:00:00Z",
            },
            {
                "id": "oldest",
                "entity_type": "user",
                "entity_id": user_id,
                "key_type": "Signing",
                "provider_type": "HSM",
                "is_active": True,
                "created_at": "2024-01-01T00:00:00Z",
            },
            {
                "id": "inactive",
                "entity_type": "user",
                "entity_id": user_id,
                "key_type": "Signing",
                "provider_type": "OpenSSL",
                "is_active": False,
                "created_at": "2019-01-01T00:00:00Z",
            },
        ]

    response = executor.execute(
        _command("user_signing_key", {"custody": "custodial"}, group=None)
    )

    assert response.success is True
    assert response.data["signer_key_id"] == "oldest"
    assert response.data["signer_custody"] == "custodial"
    auth.get_user_keys.assert_called_once_with(personal_jwt, user_id)


def test_user_signing_key_rejects_named_credential_before_token_or_key_io():
    executor, auth, _, _, tokens = _executor()

    response = executor.execute(_command(
        "user_signing_key",
        {
            "custody": "custodial",
            "credential": "owned-child",
        },
        group=None,
    ))

    assert response.success is False
    assert response.errors == ["user_signing_key cannot use a named credential"]
    tokens.get_token.assert_not_called()
    tokens.get_named_credential.assert_not_called()
    auth.get_user_keys.assert_not_called()


def test_list_group_members_surfaces_only_user_ids():
    executor, auth, _, store, tokens = _executor()
    tokens.get_token.return_value = "group-b-jwt"
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": [
            {
                "user_id": "payer-user",
                "member_role": "owner",
                "user": {"email": "payer@example.com"},
            }
        ],
    }

    response = executor.execute(_command("list_group_members", {
        "group_id": "group-b",
    }, group="Payer Group"))

    assert response.success is True
    assert response.data["member_user_ids"] == ["payer-user"]
    assert response.data["member_user_ids_csv"] == "payer-user"
    assert "payer@example.com" not in repr(response.data)
    assert store.get("step", "members_count") == 1


def test_owned_group_discovery_accepts_only_exact_active_projection():
    executor, auth, _, _, tokens = _executor()
    user_id = "11111111-1111-4111-8111-111111111111"
    parent_id = "22222222-2222-4222-8222-222222222222"
    child_id = "33333333-3333-4333-8333-333333333333"
    parent_token_id = "44444444-4444-4444-8444-444444444444"
    relationship_id = "55555555-5555-4555-8555-555555555555"
    account = "0x1111111111111111111111111111111111111111"
    credential = "0x2222222222222222222222222222222222222222"
    tokens.get_token.return_value = _jwt(_direct_group_claims(
        user_id, parent_id, parent_token_id, "153"
    ))
    projection = {
        "group": {
            "id": child_id,
            "name": "Subsidiary",
            "role": None,
            "is_active": True,
            "account_address": account,
            "account_chain_id": "153",
        },
        "account_address": account,
        "relationship_id": relationship_id,
        "credential_contract": credential,
        "token_id": "42",
        "added_at": "2026-07-24T00:00:00Z",
    }
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "source_group_id": parent_id,
            "chain_id": "153",
            "owned_groups": [projection],
        },
    }
    command = _command("discover_owned_groups", {
        "group_id": parent_id,
    })

    response = executor.execute(command)

    assert response.success is True
    assert response.data["owned_group_ids"] == [child_id]
    assert response.data["relationship_ids"] == [relationship_id]

    auth._request_json_safe.return_value["body"]["owned_groups"][0] = {
        **projection,
        "authority_key_id": parent_token_id,
    }
    rejected = executor.execute(command)
    assert rejected.success is False
    assert "invalid projection" in rejected.errors[0]


def test_service_request_returns_denial_body_as_failure():
    executor, auth, _, store, _ = _executor()
    auth._request_json_safe.return_value = {
        "ok": False,
        "status_code": 403,
        "body": {
            "error": "Ownership-derived credentials cannot use generic signing"
        },
    }

    response = executor.execute(_command("service_request", {
        "credential": "owned-b",
        "service": "auth",
        "method": "POST",
        "path": "/key-operations/sign",
        "body": {"data": "00"},
    }, group=None))

    assert response.success is False
    assert "HTTP 403" in response.errors[0]
    assert "Ownership-derived" in response.errors[0]
    assert store.get_all() == {}


def test_service_request_does_not_store_sensitive_success_body():
    executor, auth, _, store, _ = _executor()
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {"api_key": "yf_api_must_not_leak"},
    }

    response = executor.execute(_command("service_request", {
        "credential": "owned-b",
        "service": "auth",
        "method": "POST",
        "path": "/auth/api-key/generate",
        "body": {"service_name": "forbidden"},
    }, group=None))

    assert response.success is True
    assert "yf_api_must_not_leak" not in repr(response.data)
    assert "yf_api_must_not_leak" not in repr(store.get_all())


def test_relationship_stage_uses_exact_three_actor_saga_route_and_body():
    executor, auth, _, _, tokens = _executor()
    parent = "11111111-1111-4111-8111-111111111111"
    child = "22222222-2222-4222-8222-222222222222"
    relationship = "33333333-3333-4333-8333-333333333333"
    message = "44444444-4444-4444-8444-444444444444"
    personal = _jwt(_personal_claims())
    tokens.get_token.return_value = personal
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "relationship_id": relationship,
            "parent_group_id": parent,
            "child_group_id": child,
            "chain_id": "153",
            "status": "provisioning",
            "stage": "parent_credential_pending",
            "credential_contract": "0x1111111111111111111111111111111111111111",
            "token_id": "42",
            "message_id": message,
            "operation_id": None,
            "retry_required": False,
            "error": None,
        },
    }

    response = executor.execute(_command("establish_group_owner", {
        "parent_group_id": parent,
        "child_group_id": child,
        "chain_id": "153",
        "wait": False,
    }))

    assert response.success is True
    assert response.data["stage"] == "parent_credential_pending"
    assert response.data["message_id"] == message
    auth._request_json_safe.assert_called_once_with(
        "POST",
        f"/auth/groups/{child}/group-owners/{parent}",
        token=personal,
        data={"chain_id": "153"},
    )


def test_relationship_mutation_uses_personal_jwt_then_group_jwt_only_for_poll():
    executor, auth, payments, _, tokens = _executor()
    parent = "11111111-1111-4111-8111-111111111111"
    child = "22222222-2222-4222-8222-222222222222"
    relationship = "33333333-3333-4333-8333-333333333333"
    message = "44444444-4444-4444-8444-444444444444"
    user_id = "55555555-5555-4555-8555-555555555555"
    personal = _jwt(_personal_claims(user_id))
    parent_delegation = _jwt(_direct_group_claims(
        user_id,
        parent,
        "66666666-6666-4666-8666-666666666666",
        "153",
    ))
    tokens.get_token.side_effect = [personal, parent_delegation]
    tokens.token_supplier.return_value = lambda: parent_delegation
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "relationship_id": relationship,
            "parent_group_id": parent,
            "child_group_id": child,
            "chain_id": "153",
            "status": "provisioning",
            "stage": "parent_credential_pending",
            "credential_contract": "0x1111111111111111111111111111111111111111",
            "token_id": "42",
            "message_id": message,
            "operation_id": None,
            "retry_required": False,
            "error": None,
        },
    }
    payments.poll_message_completion.return_value = PollResult(
        observation={"executed": "2026-07-24T00:00:00Z", "response": {"ok": True}},
        attempts=1,
        elapsed=0.1,
    )

    response = executor.execute(_command("establish_group_owner", {
        "parent_group_id": parent,
        "child_group_id": child,
        "chain_id": "153",
        "wait": True,
    }))

    assert response.success is True
    assert tokens.get_token.call_args_list == [
        call(
            "issuer@yieldfabric.com",
            "issuer_password",
            group_name="Issuer Group",
            use_delegation=False,
        ),
        call(
            "issuer@yieldfabric.com",
            "issuer_password",
            group_name="Issuer Group",
            use_delegation=True,
        ),
    ]
    auth._request_json_safe.assert_called_once_with(
        "POST",
        f"/auth/groups/{child}/group-owners/{parent}",
        token=personal,
        data={"chain_id": "153"},
    )
    poll_args = payments.poll_message_completion.call_args.args
    assert poll_args[0] == parent
    assert poll_args[1] == message
    assert callable(poll_args[2])
    assert poll_args[2]() == parent_delegation


def test_relationship_response_rejects_legacy_raw_owner_fields():
    executor, auth, _, _, tokens = _executor()
    parent = "11111111-1111-4111-8111-111111111111"
    child = "22222222-2222-4222-8222-222222222222"
    tokens.get_token.return_value = _jwt(_personal_claims())
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "relationship_id": "33333333-3333-4333-8333-333333333333",
            "parent_group_id": parent,
            "child_group_id": child,
            "chain_id": "153",
            "status": "provisioning",
            "stage": "parent_credential_authorization_required",
            "retry_required": False,
            "authority_key_id": "44444444-4444-4444-8444-444444444444",
        },
    }

    response = executor.execute(_command("establish_group_owner", {
        "parent_group_id": parent,
        "child_group_id": child,
        "chain_id": "153",
    }))

    assert response.success is False
    assert "invalid field set" in response.errors[0]


def test_relationship_response_rejects_missing_or_inconsistent_contract_fields():
    executor, _, _, _, _ = _executor()
    base = {
        "relationship_id": "33333333-3333-4333-8333-333333333333",
        "parent_group_id": "11111111-1111-4111-8111-111111111111",
        "child_group_id": "22222222-2222-4222-8222-222222222222",
        "chain_id": "153",
        "status": "provisioning",
        "stage": "parent_credential_pending",
        "credential_contract": "0x1111111111111111111111111111111111111111",
        "token_id": "42",
        "message_id": "44444444-4444-4444-8444-444444444444",
        "operation_id": None,
        "retry_required": False,
        "error": None,
    }

    missing = dict(base)
    missing.pop("operation_id")
    inconsistent_status = dict(base, status="active")
    inconsistent_retry = dict(base, retry_required=True)

    for body in (missing, inconsistent_status, inconsistent_retry):
        try:
            executor._relationship_outputs(body)
        except ValueError as exc:
            assert "invalid field set" in str(exc) or "inconsistent" in str(exc)
        else:
            raise AssertionError("invalid relationship response was accepted")


def test_group_signing_key_is_named_apart_from_the_nested_signer():
    """A group key must never be mistakable for a bindable nested signer.

    The nested model binds the actor's own HUMAN key; this lookup exists only
    so a suite can prove `assume-owned-group` REJECTS a real group key. Emitting
    `signer_key_id` here would let a copy-paste turn that negative test into a
    positive one, so the output is deliberately `signing_key_id`.
    """
    executor, auth, _, store, tokens = _executor()
    tokens.get_token.return_value = "group-a-jwt"
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": [
            {
                "id": "group-signing-key",
                "is_active": True,
                "key_type": "signing",
                "provider_type": "OpenSSL",
                "created_at": "2026-01-01T00:00:00Z",
                "public_key": "0x" + "ab" * 20,
            }
        ],
    }

    response = executor.execute(_command("group_signing_key", {
        "group_id": "group-a",
    }, group="Issuer Group"))

    assert response.success is True
    assert response.data["signing_key_id"] == "group-signing-key"
    assert "signer_key_id" not in response.data
    auth._request_json_safe.assert_called_once_with(
        "GET",
        "/auth/groups/group-a/keypairs",
        token="group-a-jwt",
    )
    assert store.get("step", "signing_key_id") == "group-signing-key"


def test_group_signing_key_ignores_inactive_and_non_signing_keypairs():
    executor, auth, _, _, tokens = _executor()
    tokens.get_token.return_value = "group-a-jwt"
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": [
            {
                "id": "encryption-key",
                "is_active": True,
                "key_type": "encryption",
                "created_at": "2026-01-01T00:00:00Z",
            },
            {
                "id": "revoked-signing-key",
                "is_active": False,
                "key_type": "signing",
                "created_at": "2026-01-02T00:00:00Z",
            },
            {
                "id": "live-signing-key",
                "is_active": True,
                "key_type": "signing",
                "created_at": "2026-01-03T00:00:00Z",
            },
        ],
    }

    response = executor.execute(_command("group_signing_key", {
        "group_id": "group-a",
    }, group="Issuer Group"))

    assert response.success is True
    assert response.data["signing_key_id"] == "live-signing-key"


def test_group_signing_key_fails_when_the_group_has_no_signing_keypair():
    executor, auth, _, _, tokens = _executor()
    tokens.get_token.return_value = "group-a-jwt"
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": [{"id": "enc", "is_active": True, "key_type": "encryption"}],
    }

    response = executor.execute(_command("group_signing_key", {
        "group_id": "group-a",
    }, group="Issuer Group"))

    assert response.success is False
    assert any("no active signing keypair" in error for error in response.errors)


def test_assume_owned_group_may_request_more_than_the_cap_and_reports_the_capped_ttl():
    """Auth clamps the TTL; it does not reject an over-long request.

    900 is a property of the RESPONSE. A client-side ceiling on the REQUEST
    would make the cap untestable — no suite could prove that asking for an
    hour yields 900 seconds. What must hold is the response check: the returned
    TTL is 1..=900 and never exceeds what was asked.
    """
    executor, auth, _, _, tokens = _executor()
    user_id = "11111111-1111-4111-8111-111111111111"
    parent_group_id = "22222222-2222-4222-8222-222222222222"
    child_group_id = "33333333-3333-4333-8333-333333333333"
    signer_key_id = "66666666-6666-4666-8666-666666666666"
    edge = {
        "parent_group_id": parent_group_id,
        "child_group_id": child_group_id,
        "chain_id": "31337",
        "credential_contract": "0x1111111111111111111111111111111111111111",
        "token_id": "42",
    }
    parent = _jwt(_direct_group_claims(
        user_id, parent_group_id, "44444444-4444-4444-8444-444444444444", "31337"
    ))
    tokens.get_token.return_value = parent
    child = _jwt({
        "sub": user_id,
        "kind": "user",
        "entity_type": "user",
        "auth_method": "delegation",
        "password_change_only": False,
        "acting_as": child_group_id,
        "delegation_token_id": "55555555-5555-4555-8555-555555555555",
        "default_chain_id": "31337",
        "delegation_scope": ["ReadGroup", "CryptoOperations"],
        "delegation_path": [parent_group_id, child_group_id],
        "authority_source": "nft_membership",
        "membership_edge": edge,
        "signer_key_id": signer_key_id,
        "signer_address": "0x2222222222222222222222222222222222222222",
        "signer_scheme": "account_ecdsa65_v1",
        "signer_custody": "custodial",
        "iat": 1_800_000_000,
        # Clamped to the 900s ceiling even though 3600 was requested.
        "exp": 1_800_000_900,
    })
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "delegation_jwt": child,
            "group_id": child_group_id,
            "delegation_scope": ["ReadGroup", "CryptoOperations"],
            "expiry_seconds": 900,
            "chain_id": "31337",
            "delegation_path": [parent_group_id, child_group_id],
            "authority_source": "nft_membership",
            "membership_edge": edge,
            "signer_key_id": signer_key_id,
            "signer_address": "0x2222222222222222222222222222222222222222",
            "signer_scheme": "account_ecdsa65_v1",
            "signer_custody": "custodial",
        },
    }

    response = executor.execute(_command("assume_owned_group", {
        "group_id": child_group_id,
        "delegation_scope": ["ReadGroup", "CryptoOperations"],
        "expiry_seconds": 3600,
        "signer_key_id": signer_key_id,
        "credential_name": "owned-b-capped",
    }))

    assert response.success is True
    # The reported TTL is the server's, not the request's.
    assert response.data["expiry_seconds"] == 900
    assert auth._request_json_safe.call_args.kwargs["data"]["expiry_seconds"] == 3600


def test_assume_owned_group_accepts_the_floor_clamp_on_a_sub_minute_request():
    """Auth clamps a too-SHORT request UP to the 60s floor.

    `requested.clamp(60, OWNED_GROUP_MAX_ACCESS_TTL_SECS)` has two ends. The
    response check used to read `expiry > expiry_seconds` — "never longer than
    asked" — which is only true above the floor, so asking for 1s and being
    handed the documented 60s was rejected as inconsistent provenance.
    """
    executor, auth, _, _, tokens = _executor()
    user_id = "11111111-1111-4111-8111-111111111111"
    parent_group_id = "22222222-2222-4222-8222-222222222222"
    child_group_id = "33333333-3333-4333-8333-333333333333"
    signer_key_id = "66666666-6666-4666-8666-666666666666"
    edge = {
        "parent_group_id": parent_group_id,
        "child_group_id": child_group_id,
        "chain_id": "31337",
        "credential_contract": "0x1111111111111111111111111111111111111111",
        "token_id": "42",
    }
    parent = _jwt(_direct_group_claims(
        user_id, parent_group_id, "44444444-4444-4444-8444-444444444444", "31337"
    ))
    tokens.get_token.return_value = parent
    child = _jwt({
        "sub": user_id,
        "kind": "user",
        "entity_type": "user",
        "auth_method": "delegation",
        "password_change_only": False,
        "acting_as": child_group_id,
        "delegation_token_id": "55555555-5555-4555-8555-555555555555",
        "default_chain_id": "31337",
        "delegation_scope": ["ReadGroup"],
        "delegation_path": [parent_group_id, child_group_id],
        "authority_source": "nft_membership",
        "membership_edge": edge,
        "signer_key_id": signer_key_id,
        "signer_address": "0x2222222222222222222222222222222222222222",
        "signer_scheme": "account_ecdsa65_v1",
        "signer_custody": "custodial",
        "iat": 1_800_000_000,
        # Clamped UP to the 60s floor even though 1 was requested.
        "exp": 1_800_000_060,
    })
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "delegation_jwt": child,
            "group_id": child_group_id,
            "delegation_scope": ["ReadGroup"],
            "expiry_seconds": 60,
            "chain_id": "31337",
            "delegation_path": [parent_group_id, child_group_id],
            "authority_source": "nft_membership",
            "membership_edge": edge,
            "signer_key_id": signer_key_id,
            "signer_address": "0x2222222222222222222222222222222222222222",
            "signer_scheme": "account_ecdsa65_v1",
            "signer_custody": "custodial",
        },
    }

    response = executor.execute(_command("assume_owned_group", {
        "group_id": child_group_id,
        "delegation_scope": ["ReadGroup"],
        "expiry_seconds": 1,
        "signer_key_id": signer_key_id,
        "credential_name": "owned-b-floored",
    }))

    assert response.success is True
    assert response.data["expiry_seconds"] == 60
    assert auth._request_json_safe.call_args.kwargs["data"]["expiry_seconds"] == 1


def test_assume_owned_group_rejects_a_server_ttl_above_the_floor_and_the_request():
    """The floor permits 60s, not anything the server feels like.

    Asking for 1s and being handed 120s is still inconsistent: above the floor
    the "no longer than asked" rule applies again.
    """
    executor, auth, _, _, tokens = _executor()
    user_id = "11111111-1111-4111-8111-111111111111"
    parent_group_id = "22222222-2222-4222-8222-222222222222"
    child_group_id = "33333333-3333-4333-8333-333333333333"
    signer_key_id = "66666666-6666-4666-8666-666666666666"
    edge = {
        "parent_group_id": parent_group_id,
        "child_group_id": child_group_id,
        "chain_id": "31337",
        "credential_contract": "0x1111111111111111111111111111111111111111",
        "token_id": "42",
    }
    parent = _jwt(_direct_group_claims(
        user_id, parent_group_id, "44444444-4444-4444-8444-444444444444", "31337"
    ))
    tokens.get_token.return_value = parent
    child = _jwt({
        "sub": user_id,
        "kind": "user",
        "entity_type": "user",
        "auth_method": "delegation",
        "password_change_only": False,
        "acting_as": child_group_id,
        "delegation_token_id": "55555555-5555-4555-8555-555555555555",
        "default_chain_id": "31337",
        "delegation_scope": ["ReadGroup"],
        "delegation_path": [parent_group_id, child_group_id],
        "authority_source": "nft_membership",
        "membership_edge": edge,
        "signer_key_id": signer_key_id,
        "signer_address": "0x2222222222222222222222222222222222222222",
        "signer_scheme": "account_ecdsa65_v1",
        "signer_custody": "custodial",
        "iat": 1_800_000_000,
        "exp": 1_800_000_120,
    })
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "delegation_jwt": child,
            "group_id": child_group_id,
            "delegation_scope": ["ReadGroup"],
            "expiry_seconds": 120,
            "chain_id": "31337",
            "delegation_path": [parent_group_id, child_group_id],
            "authority_source": "nft_membership",
            "membership_edge": edge,
            "signer_key_id": signer_key_id,
            "signer_address": "0x2222222222222222222222222222222222222222",
            "signer_scheme": "account_ecdsa65_v1",
            "signer_custody": "custodial",
        },
    }

    response = executor.execute(_command("assume_owned_group", {
        "group_id": child_group_id,
        "delegation_scope": ["ReadGroup"],
        "expiry_seconds": 1,
        "signer_key_id": signer_key_id,
        "credential_name": "owned-b-overfloored",
    }))

    assert response.success is False


def test_assume_owned_group_still_rejects_a_non_positive_or_non_integer_ttl():
    executor, _, _, _, _ = _executor()
    for bad in [0, -1, True, "900", 1.5, None]:
        response = executor.execute(_command("assume_owned_group", {
            "group_id": "33333333-3333-4333-8333-333333333333",
            "delegation_scope": ["ReadGroup"],
            "expiry_seconds": bad,
            "signer_key_id": "66666666-6666-4666-8666-666666666666",
        }))
        assert response.success is False, f"{bad!r} must be rejected"


def test_assume_owned_group_rejects_a_server_ttl_above_the_cap():
    """The cap is enforced on the response — that check must not be weakened."""
    executor, auth, _, _, tokens = _executor()
    user_id = "11111111-1111-4111-8111-111111111111"
    parent_group_id = "22222222-2222-4222-8222-222222222222"
    child_group_id = "33333333-3333-4333-8333-333333333333"
    signer_key_id = "66666666-6666-4666-8666-666666666666"
    edge = {
        "parent_group_id": parent_group_id,
        "child_group_id": child_group_id,
        "chain_id": "31337",
        "credential_contract": "0x1111111111111111111111111111111111111111",
        "token_id": "42",
    }
    parent = _jwt(_direct_group_claims(
        user_id, parent_group_id, "44444444-4444-4444-8444-444444444444", "31337"
    ))
    tokens.get_token.return_value = parent
    child = _jwt({
        "sub": user_id,
        "kind": "user",
        "entity_type": "user",
        "auth_method": "delegation",
        "password_change_only": False,
        "acting_as": child_group_id,
        "delegation_token_id": "55555555-5555-4555-8555-555555555555",
        "default_chain_id": "31337",
        "delegation_scope": ["ReadGroup", "CryptoOperations"],
        "delegation_path": [parent_group_id, child_group_id],
        "authority_source": "nft_membership",
        "membership_edge": edge,
        "signer_key_id": signer_key_id,
        "signer_address": "0x2222222222222222222222222222222222222222",
        "signer_scheme": "account_ecdsa65_v1",
        "signer_custody": "custodial",
        "iat": 1_800_000_000,
        "exp": 1_800_000_901,
    })
    auth._request_json_safe.return_value = {
        "ok": True,
        "status_code": 200,
        "body": {
            "delegation_jwt": child,
            "group_id": child_group_id,
            "delegation_scope": ["ReadGroup", "CryptoOperations"],
            "expiry_seconds": 901,
            "chain_id": "31337",
            "delegation_path": [parent_group_id, child_group_id],
            "authority_source": "nft_membership",
            "membership_edge": edge,
            "signer_key_id": signer_key_id,
            "signer_address": "0x2222222222222222222222222222222222222222",
            "signer_scheme": "account_ecdsa65_v1",
            "signer_custody": "custodial",
        },
    }

    response = executor.execute(_command("assume_owned_group", {
        "group_id": child_group_id,
        "delegation_scope": ["ReadGroup", "CryptoOperations"],
        "expiry_seconds": 3600,
        "signer_key_id": signer_key_id,
    }))

    assert response.success is False
