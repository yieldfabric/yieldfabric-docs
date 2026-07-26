"""
Unit tests for the data-policy executor — payload construction + the approval
sign-via-auth-API flow, exercised WITHOUT a live backend (the services are
mocked, exactly like test_executor_payloads.py). These don't prove the on-chain
semantics — the YAML suite (datapolicy_group_suite.yaml) does that against the
live runtime — they pin the wire shapes the harness sends.
"""

import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.output_store import OutputStore
from yieldfabric.executors.policy_executor import PolicyExecutor, _camel, _camel_keys
from yieldfabric.models import Command, CommandParameters, GraphQLResponse, User


@pytest.fixture
def config():
    return YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        command_delay=0,
        debug=False,
    )


@pytest.fixture
def services():
    auth = MagicMock(name="AuthService")
    auth.login.return_value = "user.jwt"
    auth.login_with_group.return_value = "delegation.jwt"
    payments = MagicMock(name="PaymentsService")
    return auth, payments


def _command(name, cmd_type, params, *, group=None):
    params = dict(params)
    params.setdefault("wait", False)  # skip MQ polling in unit tests
    return Command(
        name=name,
        type=cmd_type,
        user=User(id="issuer@yieldfabric.com", password="pw", group=group),
        parameters=CommandParameters.from_dict(params),
    )


def _jwt_with_claims(**claims) -> str:
    """A structurally-valid (unsigned) JWT whose payload carries `claims`."""
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.sig"


# ----------------------------------------------------------------------
# key camelCasing
# ----------------------------------------------------------------------

def test_camel_and_camel_keys():
    assert _camel("token_id") == "tokenId"
    assert _camel("use_owner_of") == "useOwnerOf"
    assert _camel("constraint_commitment") == "constraintCommitment"
    assert _camel("source") == "source"
    assert _camel("tokenId") == "tokenId"  # idempotent for already-camelCase
    assert _camel_keys({"source": 0, "use_owner_of": True}) == {"source": 0, "useOwnerOf": True}


# ----------------------------------------------------------------------
# add_data_policy
# ----------------------------------------------------------------------

def test_add_data_policy_builds_camelcased_group_input(config, services):
    auth, payments = services
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"pipelineGate": {"addDataPolicy": {
            "success": True, "messageId": "msg-9001", "policyId": "9001",
        }}},
    )

    executor = PolicyExecutor(auth, payments, OutputStore(), config)
    response = executor.execute(_command(
        "happy_add_policy", "add_data_policy",
        {
            "account": "0xGROUP",
            "wallet_id": "wallet-uuid",
            "policy_id": "9001",
            "expiry": "12345",
            "max_use": "5",
            "min_signatories": 1,
            "required_signers": ["0xOWNER"],
            "executor_accounts": ["0xMEMBER"],
            "allowed_operations": ["send"],
            "amount_bounds": [{"token": "0xAUD", "lo": "0", "hi": "500"}],
            "requirements": [{"source": 0, "denomination": "0xAUD", "lo": "0", "hi": "999", "use_owner_of": False}],
        },
        group="Issuer Group",
    ))

    assert response.success
    mutation, variables = payments.graphql_mutation.call_args.args[0], payments.graphql_mutation.call_args.args[1]
    assert "pipelineGate" in mutation and "addDataPolicy" in mutation
    inp = variables["input"]
    assert inp["account"] == "0xGROUP"
    assert inp["walletId"] == "wallet-uuid"
    assert inp["policyId"] == "9001"
    assert inp["minSignatories"] == 1
    assert inp["requiredSigners"] == ["0xOWNER"]
    assert inp["executorAccounts"] == ["0xMEMBER"]          # the restricted executor, distinct from approvers
    assert inp["allowedOperations"] == ["send"]
    assert inp["amountBounds"] == [{"token": "0xAUD", "lo": "0", "hi": "500"}]
    # requirement keys camelCased (use_owner_of → useOwnerOf)
    assert inp["requirements"] == [{"source": 0, "denomination": "0xAUD", "lo": "0", "hi": "999", "useOwnerOf": False}]
    assert response.data["message_id"] == "msg-9001"


def test_add_data_policy_requires_an_account(config, services):
    auth, payments = services
    # delegation.jwt is not a decodable JWT → no group_account_address claim → must error.
    executor = PolicyExecutor(auth, payments, OutputStore(), config)
    response = executor.execute(_command(
        "no_account", "add_data_policy",
        {"policy_id": "9001", "required_signers": ["0xO"], "allowed_operations": ["send"],
         "requirements": [{"source": 0}]},
        group="Issuer Group",
    ))
    assert not response.success
    payments.graphql_mutation.assert_not_called()


# ----------------------------------------------------------------------
# execute_under_policy
# ----------------------------------------------------------------------

def test_execute_under_policy_serializes_operation_data(config, services):
    auth, payments = services
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"pipelineGate": {"executeUnderPolicy": {
            "success": True, "messageId": "msg-x", "collected": 1, "approved": True,
        }}},
    )

    executor = PolicyExecutor(auth, payments, OutputStore(), config)
    op_data = {"token_address": "0xAUD", "destination_id": "collateral@yieldfabric.com", "amount": "100"}
    response = executor.execute(_command(
        "happy_execute", "execute_under_policy",
        {"account": "0xGROUP", "policy_id": "9001", "operation_type": "Send", "operation_data": op_data},
        group="Issuer Group",
    ))

    assert response.success
    inp = payments.graphql_mutation.call_args.args[1]["input"]
    assert inp["account"] == "0xGROUP"
    assert inp["policyId"] == "9001"
    assert inp["operationType"] == "Send"
    # operationData crosses the wire as a JSON string
    assert json.loads(inp["operationData"]) == op_data


# ----------------------------------------------------------------------
# approve_data_policy — digest → auth REST sign → submit (no local key)
# ----------------------------------------------------------------------

def test_approve_data_policy_signs_via_auth_rest_api(config, services):
    auth, payments = services
    payments.graphql_mutation.side_effect = [
        # 1) dataPolicyApproval query → the digest to sign
        GraphQLResponse(success=True, data={"pipelineGate": {"dataPolicyApproval": {
            "registeredDigest": "0x" + "ab" * 32, "minSignatories": 1, "collected": 0, "approved": False,
        }}}),
        # 2) approveDataPolicy mutation → tally
        GraphQLResponse(success=True, data={"pipelineGate": {"approveDataPolicy": {
            "success": True, "signer": "0xSIGNER", "collected": 1, "approved": True,
        }}}),
    ]
    auth.sign_vault.return_value = {"success": True, "result": "deadbeefsig"}

    executor = PolicyExecutor(auth, payments, OutputStore(), config)
    with patch("yieldfabric.executors.policy_executor.eip191_message_hash", return_value="cafefeed") as eip, \
         patch("yieldfabric.executors.policy_executor.get_sub", return_value="issuer-uuid"):
        response = executor.execute(_command(
            "happy_approve", "approve_data_policy",
            {"account": "0xGROUP", "policy_id": "9001"},
        ))

    assert response.success
    # The signature came from the auth REST API over the EIP-191 message-hash of the digest —
    # no private key was used in-process.
    eip.assert_called_once_with("0x" + "ab" * 32)
    auth.sign_vault.assert_called_once()
    _, kwargs = auth.sign_vault.call_args
    assert kwargs["contact_id"] == "issuer-uuid"
    assert kwargs["data"] == "cafefeed"
    assert kwargs["data_format"] == "hex"
    # …and the returned signature was submitted verbatim to approveDataPolicy.
    approve_vars = payments.graphql_mutation.call_args_list[1].args[1]
    assert approve_vars["input"]["signature"] == "deadbeefsig"
    assert response.data["approved"] is True


def test_approve_data_policy_fails_when_signer_rejected(config, services):
    """The restricted member's approval is rejected (not in the caller set)."""
    auth, payments = services
    payments.graphql_mutation.side_effect = [
        GraphQLResponse(success=True, data={"pipelineGate": {"dataPolicyApproval": {
            "registeredDigest": "0x" + "cd" * 32, "minSignatories": 1,
        }}}),
        GraphQLResponse(success=True, data={"pipelineGate": {"approveDataPolicy": {
            "success": False, "message": "recovered signer 0xMEMBER is not in policy 9001's caller set",
        }}}),
    ]
    auth.sign_vault.return_value = {"success": True, "result": "sig"}

    executor = PolicyExecutor(auth, payments, OutputStore(), config)
    with patch("yieldfabric.executors.policy_executor.eip191_message_hash", return_value="aa"), \
         patch("yieldfabric.executors.policy_executor.get_sub", return_value="member-uuid"):
        response = executor.execute(_command(
            "member_approve", "approve_data_policy",
            {"account": "0xGROUP", "policy_id": "9001"},
        ))

    assert not response.success
    assert "caller set" in " ".join(response.errors)


# ----------------------------------------------------------------------
# whoami — resolve addresses from JWT claims
# ----------------------------------------------------------------------

def test_add_data_policy_oracle_requirement_camelcased(config, services):
    """An oracle (source=3) requirement's keys + nested constraint_commitment survive."""
    auth, payments = services
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"pipelineGate": {"addDataPolicy": {"success": True, "messageId": "m", "policyId": "9020"}}},
    )
    executor = PolicyExecutor(auth, payments, OutputStore(), config)
    response = executor.execute(_command(
        "oracle_add", "add_data_policy",
        {
            "account": "0xGROUP", "wallet_id": "w", "policy_id": "9020",
            "expiry": "1", "max_use": "5", "min_signatories": 1,
            "required_signers": ["0xOWNER"], "executor_accounts": ["0xMEMBER"],
            "allowed_operations": ["send"],
            "requirements": [{
                "source": 3,
                "obligor": "0xGROUP",
                "token_id": "credit-9020",
                "constraint_commitment": ["111", "222"],
                "oracle_query": "[700,1000000]",
                "oracle_query_salt": "1",
            }],
        },
        group="Issuer Group",
    ))
    assert response.success
    req = payments.graphql_mutation.call_args.args[1]["input"]["requirements"][0]
    assert req == {
        "source": 3,
        "obligor": "0xGROUP",
        "tokenId": "credit-9020",
        "constraintCommitment": ["111", "222"],   # nested list passes through untouched
        "oracleQuery": "[700,1000000]",
        "oracleQuerySalt": "1",
    }


def test_commit_oracle_document_builds_input(config, services):
    auth, payments = services
    payments.graphql_mutation.return_value = GraphQLResponse(
        success=True,
        data={"pipelineGate": {"commitOracleDocument": {
            "success": True, "messageId": "msg-c", "oracleAddress": "0xORACLE", "key": "credit-9020",
        }}},
    )
    executor = PolicyExecutor(auth, payments, OutputStore(), config)
    response = executor.execute(_command(
        "o_commit", "commit_oracle_document",
        {"obligor": "0xGROUP", "key": "credit-9020", "value": "750", "document_json": {"score": 750}},
        group="Issuer Group",
    ))
    assert response.success
    mutation, variables = payments.graphql_mutation.call_args.args[0], payments.graphql_mutation.call_args.args[1]
    assert "commitOracleDocument" in mutation
    inp = variables["input"]
    assert inp["obligor"] == "0xGROUP"
    assert inp["key"] == "credit-9020"
    assert inp["value"] == "750"
    # a YAML mapping document is normalised to a JSON string
    assert json.loads(inp["documentJson"]) == {"score": 750}
    assert response.data["message_id"] == "msg-c"


def test_approval_signature_chain_parity():
    """
    Runtime crypto-equivalence proof (not a lineage argument): the harness's
    `eip191_message_hash`, the auth sign endpoint's RAW signing of that digest,
    and the backend's `recover_personal_sign_address_bytes` (EIP-191 personal_sign
    recover over the registered digest) must all agree — i.e. the address the
    backend recovers from the produced signature is the original signer.

      harness  : h = keccak256("\\x19Ethereum Signed Message:\\n32" || digest)
      auth API : sign(h) directly  (yieldfabric-encryption sign_bytes, no re-hash)
      backend  : recover personal_sign(digest)  == recover over h
    """
    eth_account = pytest.importorskip("eth_account")
    from eth_account import Account
    from eth_account.messages import encode_defunct
    from yieldfabric.utils.crypto import eip191_message_hash

    digest = "0x" + "11" * 32
    h = eip191_message_hash(digest)
    assert len(h) == 64  # 32-byte hash, bare hex

    acct = Account.create()
    sign_hash = (
        getattr(Account, "unsafe_sign_hash", None)
        or getattr(Account, "_sign_hash", None)
        or Account.signHash
    )
    signed = sign_hash(bytes.fromhex(h), acct.key)  # server signs the 32-byte digest directly
    recovered = Account.recover_message(encode_defunct(hexstr=digest), signature=signed.signature)
    assert recovered.lower() == acct.address.lower()


def test_whoami_resolves_addresses_from_claims(config, services):
    auth, payments = services
    auth.login_with_group.return_value = _jwt_with_claims(
        sub="issuer-uuid",
        acting_as="issuer-group-uuid",
        account_address="0xOWNER",
        group_account_address="0xGROUP",
        default_wallet_id="wallet-uuid",
    )

    store = OutputStore()
    executor = PolicyExecutor(auth, payments, store, config)
    response = executor.execute(_command("owner_ctx", "whoami", {}, group="Issuer Group"))

    assert response.success
    assert store.get("owner_ctx", "group_account_address") == "0xGROUP"
    assert store.get("owner_ctx", "account_address") == "0xOWNER"
    assert store.get("owner_ctx", "default_wallet_id") == "wallet-uuid"
    assert store.get("owner_ctx", "group_id") == "issuer-group-uuid"
    assert store.get("owner_ctx", "sub") == "issuer-uuid"
    # Group identity and account data came from signed delegation claims.
    auth.get_user_group_id_by_name.assert_not_called()
    auth.group_account_info.assert_not_called()
