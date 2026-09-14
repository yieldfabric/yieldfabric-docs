"""Credential masking used by the `yf` stderr logger and the auth client."""

from yieldfabric.services.auth_service import AuthService
from yieldfabric.utils.redact import MASK, redact_secrets, redact_text

from .yf_helpers import token


def test_redact_secrets_masks_credential_keys_recursively():
    data = {
        "token": token("153"),
        "refresh_token": "rt-1",
        "user": {"id": "u", "delegation_jwt": token("153"), "email": "a@b.c"},
        "list": [{"api_key": "yf_api_x"}, "plain"],
        "expires_in": 900,
        "empty_token": "",
        "nothing": None,
    }
    out = redact_secrets(data)
    assert out["token"] == MASK and out["refresh_token"] == MASK
    assert out["user"] == {"id": "u", "delegation_jwt": MASK, "email": "a@b.c"}
    assert out["list"] == [{"api_key": MASK}, "plain"]
    assert out["expires_in"] == 900
    assert out["empty_token"] == "" and out["nothing"] is None
    # the input is not mutated
    assert data["token"] != MASK


def test_redact_text_masks_jwt_api_key_and_bearer_shapes_only():
    bearer = token("153")
    line = f"Authorization: Bearer {bearer} key=yf_api_abcdef host=https://pay.test.yieldfabric.com v=1.2.3 id=11111111-1111-4111-8111-111111111111"
    out = redact_text(line)
    assert bearer not in out and "yf_api_abcdef" not in out
    assert "https://pay.test.yieldfabric.com" in out
    assert "v=1.2.3" in out and "11111111-1111-4111-8111-111111111111" in out
    assert redact_text("") == ""


def test_auth_client_debug_lines_are_redacted_before_formatting(capsys):
    from yieldfabric.config import YieldFabricConfig
    from yieldfabric.utils.logger import YieldFabricLogger, set_logger

    set_logger(YieldFabricLogger(debug=True, colorize=False))
    auth = AuthService(YieldFabricConfig(auth_service_url="https://auth.example.test", pay_service_url="https://pay.example.test", chain_id="153", debug=True))
    minted = token("153")
    auth._request_json_safe = lambda *a, **k: {"ok": True, "status_code": 200, "body": {"token": minted, "refresh_token": "rt-secret"}}
    result = auth.exchange_api_key_session("yf_api_k")
    assert result["ok"] and result["session"]["access_token"] == minted
    printed = capsys.readouterr()
    text = printed.out + printed.err
    assert "API-key auth response" in text
    assert minted not in text and "rt-secret" not in text
