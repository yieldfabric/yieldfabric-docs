import base64
import json
from unittest.mock import MagicMock, call

from yieldfabric.config import YieldFabricConfig
from yieldfabric.core.setup_runner import YieldFabricSetupRunner


ADMIN_ID = "94e52876-6696-4119-a904-312d73037f37"
ACCOUNT = "0x1111111111111111111111111111111111111111"
WALLET_ID = f"WLT-eip155-153-{ACCOUNT}"


def _jwt(*, wallet: bool) -> str:
    def encode(value: dict) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    payload = {
        "sub": ADMIN_ID,
        "default_chain_id": "153",
        "account_address": ACCOUNT if wallet else None,
        "default_wallet_id": WALLET_ID if wallet else None,
    }
    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}.sig"


def _session(*, wallet: bool, refresh_token: str = "refresh-1") -> dict:
    return {
        "access_token": _jwt(wallet=wallet),
        "refresh_token": refresh_token,
        "expires_in": 900,
        "raw": {},
    }


def _config(*, api_key: str = "") -> YieldFabricConfig:
    return YieldFabricConfig(
        pay_service_url="http://localhost:3003",
        auth_service_url="http://localhost:3000",
        chain_id="153",
        api_key=api_key,
        admin_email="admin@yieldfabric.io" if not api_key else "",
        admin_password="bootstrap-password" if not api_key else "",
        command_delay=0,
        debug=False,
    )


def _runner(config: YieldFabricConfig) -> YieldFabricSetupRunner:
    runner = YieldFabricSetupRunner(config)
    runner.auth_service = MagicMock()
    runner.payments_service = MagicMock()
    runner.service_validator = MagicMock()
    runner.service_validator.validate_services.return_value = True
    runner.payments_service.create_token.return_value = {"status": "created"}
    runner.payments_service.create_asset.return_value = {"status": "created"}
    return runner


def _token() -> dict:
    return {
        "id": "AUD",
        "name": "AUD Token",
        "description": "test token",
        "address": "0x2222222222222222222222222222222222222222",
        "chain_id": 153,
    }


def _asset() -> dict:
    return {
        "id": "AUD",
        "name": "AUD Token",
        "description": "test asset",
        "type": "Cash",
        "currency": "AUD",
        "token_id": "AUD-token",
    }


def test_full_setup_without_wallet_bound_items_does_not_activate_admin():
    runner = _runner(_config())
    runner.auth_service.login_session.return_value = _session(wallet=False)

    assert runner._run_full({
        "users": [],
        "groups": [],
        "tokens": [],
        "assets": [],
    })

    runner.auth_service.wait_for_chain_account_activation.assert_not_called()
    runner.auth_service.refresh_access_token.assert_not_called()
    runner.payments_service.create_token.assert_not_called()
    runner.payments_service.create_asset.assert_not_called()


def test_already_walleted_admin_runs_token_without_activation_or_refresh():
    runner = _runner(_config())
    walleted = _session(wallet=True)
    runner.auth_service.login_session.return_value = walleted

    assert runner._run_one_phase("tokens", {"tokens": [_token()]}, "setup.yaml")

    runner.auth_service.wait_for_chain_account_activation.assert_not_called()
    runner.auth_service.refresh_access_token.assert_not_called()
    runner.payments_service.create_token.assert_called_once()
    assert runner.payments_service.create_token.call_args.args[0] == walleted["access_token"]


def test_walletless_credential_admin_activates_and_refreshes_before_token():
    runner = _runner(_config())
    walletless = _session(wallet=False)
    walleted = _session(wallet=True, refresh_token="refresh-2")
    runner.auth_service.login_session.return_value = walletless
    runner.auth_service.wait_for_chain_account_activation.return_value = {
        "status": "ready",
        "chain_id": "153",
        "account_address": ACCOUNT,
        "wallet_id": WALLET_ID,
    }
    runner.auth_service.refresh_access_token.return_value = walleted

    assert runner._run_one_phase("tokens", {"tokens": [_token()]}, "setup.yaml")

    runner.auth_service.wait_for_chain_account_activation.assert_called_once_with(
        walletless["access_token"],
        "user",
        ADMIN_ID,
        "153",
        attempts=60,
        interval=2.0,
    )
    runner.auth_service.refresh_access_token.assert_called_once_with(
        "refresh-1", chain_id="153"
    )
    assert runner.payments_service.create_token.call_args.args[0] == walleted["access_token"]


def test_full_token_asset_setup_activates_admin_without_declared_users():
    runner = _runner(_config())
    walletless = _session(wallet=False)
    walleted = _session(wallet=True, refresh_token="refresh-2")
    runner.auth_service.login_session.return_value = walletless
    runner.auth_service.wait_for_chain_account_activation.return_value = {
        "status": "ready",
        "chain_id": "153",
        "account_address": ACCOUNT,
        "wallet_id": WALLET_ID,
    }
    runner.auth_service.refresh_access_token.return_value = walleted

    assert runner._run_full({
        "users": [],
        "groups": [],
        "tokens": [_token()],
        "assets": [_asset()],
    })

    runner.auth_service.wait_for_chain_account_activation.assert_called_once()
    assert runner.payments_service.create_token.call_args.args[0] == walleted["access_token"]
    assert runner.payments_service.create_asset.call_args.args[0] == walleted["access_token"]


def test_walletless_api_key_admin_activates_once_and_reuses_refreshed_jwt():
    runner = _runner(_config(api_key="yf_api_test"))
    walletless = _session(wallet=False)
    walleted = _session(wallet=True, refresh_token="refresh-2")
    runner.auth_service.authenticate_api_key_session.return_value = walletless
    runner.auth_service.wait_for_chain_account_activation.return_value = {
        "status": "ready",
        "chain_id": "153",
        "account_address": ACCOUNT,
        "wallet_id": WALLET_ID,
    }
    runner.auth_service.refresh_access_token.return_value = walleted
    setup = {"tokens": [_token()], "assets": [_asset()]}

    assert runner._run_one_phase("tokens", setup, "setup.yaml")
    assert runner._run_one_phase("assets", setup, "setup.yaml")

    runner.auth_service.authenticate_api_key_session.assert_called_once_with(
        "yf_api_test"
    )
    runner.auth_service.wait_for_chain_account_activation.assert_called_once()
    runner.auth_service.refresh_access_token.assert_called_once_with(
        "refresh-1", chain_id="153"
    )
    assert runner.payments_service.create_token.call_args.args[0] == walleted["access_token"]
    assert runner.payments_service.create_asset.call_args.args[0] == walleted["access_token"]


def test_activation_failure_is_cached_and_blocks_wallet_bound_mutations():
    runner = _runner(_config(api_key="yf_api_test"))
    runner.auth_service.authenticate_api_key_session.return_value = _session(wallet=False)
    runner.auth_service.wait_for_chain_account_activation.return_value = {
        "status": "failed_retryable",
        "chain_id": "153",
        "error": "relay unavailable",
    }
    setup = {"tokens": [_token()], "assets": [_asset()]}

    assert not runner._run_one_phase("tokens", setup, "setup.yaml")
    assert not runner._run_one_phase("assets", setup, "setup.yaml")

    runner.auth_service.wait_for_chain_account_activation.assert_called_once()
    runner.auth_service.refresh_access_token.assert_not_called()
    runner.payments_service.create_token.assert_not_called()
    runner.payments_service.create_asset.assert_not_called()


def test_refreshed_walletless_jwt_fails_closed_before_graphql_mutation():
    runner = _runner(_config())
    runner.auth_service.login_session.return_value = _session(wallet=False)
    runner.auth_service.wait_for_chain_account_activation.return_value = {
        "status": "ready",
        "chain_id": "153",
        "account_address": ACCOUNT,
        "wallet_id": WALLET_ID,
    }
    runner.auth_service.refresh_access_token.return_value = _session(
        wallet=False, refresh_token="refresh-2"
    )

    assert not runner._run_one_phase("tokens", {"tokens": [_token()]}, "setup.yaml")

    runner.payments_service.create_token.assert_not_called()


def test_missing_refresh_token_reauthenticates_only_the_successful_source():
    runner = _runner(_config(api_key="yf_api_test"))
    walletless = _session(wallet=False, refresh_token="")
    walleted = _session(wallet=True, refresh_token="refresh-2")
    runner.auth_service.authenticate_api_key_session.side_effect = [
        walletless,
        walleted,
    ]
    runner.auth_service.wait_for_chain_account_activation.return_value = {
        "status": "ready",
        "chain_id": "153",
        "account_address": ACCOUNT,
        "wallet_id": WALLET_ID,
    }

    assert runner._run_one_phase("tokens", {"tokens": [_token()]}, "setup.yaml")

    assert runner.auth_service.authenticate_api_key_session.call_args_list == [
        call("yf_api_test"),
        call("yf_api_test"),
    ]
    runner.auth_service.login_session.assert_not_called()


def test_failed_refresh_reauthenticates_only_the_successful_password_source():
    runner = _runner(_config())
    walletless = _session(wallet=False)
    walleted = _session(wallet=True, refresh_token="refresh-2")
    runner.auth_service.login_session.side_effect = [walletless, walleted]
    runner.auth_service.wait_for_chain_account_activation.return_value = {
        "status": "ready",
        "chain_id": "153",
        "account_address": ACCOUNT,
        "wallet_id": WALLET_ID,
    }
    runner.auth_service.refresh_access_token.return_value = None

    assert runner._run_one_phase("tokens", {"tokens": [_token()]}, "setup.yaml")

    assert runner.auth_service.login_session.call_args_list == [
        call("admin@yieldfabric.io", "bootstrap-password"),
        call("admin@yieldfabric.io", "bootstrap-password"),
    ]
    runner.auth_service.authenticate_api_key_session.assert_not_called()
