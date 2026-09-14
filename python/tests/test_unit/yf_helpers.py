"""
Shared helpers for the `yf` CLI unit tests.

Everything is offline: service methods are replaced with
``unittest.mock`` objects (the convention across tests/test_unit — no
requests-mock / responses), the session file lives in ``tmp_path`` via
``YF_CONFIG_DIR``, and stdout/stderr are captured with ``capsys``.
"""

import base64
import json
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from yieldfabric.models.response import GraphQLResponse
from yieldfabric.yf.main import main

USER_ID = "11111111-1111-4111-8111-111111111111"
GROUP_ID = "22222222-2222-4222-8222-222222222222"
WALLET_ID = "33333333-3333-4333-8333-333333333333"


def jwt(payload: Dict[str, Any]) -> str:
    def encode(value: Dict[str, Any]) -> str:
        raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(payload)}.sig"


def token(
    chain: str = "153",
    *,
    sub: str = USER_ID,
    session_kind: str = "personal",
    exp_in: int = 900,
    acting_as: Optional[str] = None,
    **extra: Any,
) -> str:
    payload: Dict[str, Any] = {
        "sub": sub,
        "default_chain_id": chain,
        "default_wallet_id": WALLET_ID,
        "session_kind": session_kind,
        "exp": int(time.time()) + exp_in,
        "iat": int(time.time()),
    }
    if acting_as:
        payload["acting_as"] = acting_as
    payload.update(extra)
    return jwt(payload)


def response(body: Any, status_code: int = 200) -> MagicMock:
    """A `requests.Response`-shaped mock for `_post` / `_get`."""
    resp = MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.text = json.dumps(body)
    return resp


def graphql(data: Dict[str, Any]) -> GraphQLResponse:
    return GraphQLResponse.from_response({"data": data})


def graphql_errors(*messages: str, code: Optional[str] = None) -> GraphQLResponse:
    errors: List[Dict[str, Any]] = []
    for message in messages:
        entry: Dict[str, Any] = {"message": message}
        if code:
            entry["extensions"] = {"code": code}
        errors.append(entry)
    return GraphQLResponse.from_response({"data": None, "errors": errors})


def rest(body: Any, status_code: int = 200) -> Dict[str, Any]:
    """A `_request_json_safe` envelope."""
    return {"ok": 200 <= status_code < 300, "status_code": status_code, "body": body}


def message_result(observation: Any) -> Dict[str, Any]:
    """
    An envelope for `PaymentsService.get_user_message_result`: a dict is
    a 200 with that record, ``None`` is a 404, an int is that bare status
    (401/403 for a rejected bearer, 0 for unreachable).
    """
    if observation is None:
        return rest("", 404)
    if isinstance(observation, int):
        return rest({"error": f"status {observation}"} if observation else "connection refused", observation)
    return rest(observation, 200)


def message_results(observations: List[Any]) -> List[Dict[str, Any]]:
    return [message_result(o) for o in observations]


def credential_result(body: Any, status_code: int = 200) -> Dict[str, Any]:
    """
    An envelope for the status-preserving `AuthService` credential calls
    (`exchange_api_key_session` / `refresh_session` / `login_session_result`):
    `{ok, status_code, body, session}` with `session` normalised from a
    2xx body the way the client does it.
    """
    envelope = rest(body, status_code)
    session = None
    if envelope["ok"] and isinstance(body, dict):
        tok = body.get("token") or body.get("access_token") or body.get("jwt")
        if tok:
            session = {
                "access_token": tok,
                "refresh_token": body.get("refresh_token"),
                "expires_in": body.get("expires_in"),
                "raw": body,
            }
    envelope["ok"] = envelope["ok"] and session is not None
    envelope["session"] = session
    return envelope


def run(argv: List[str], capsys, *, env: Optional[Dict[str, str]] = None, monkeypatch=None):
    """
    Run `yf` in-process. Returns (exit_code, parsed_json_or_None, stdout, stderr).
    `env` entries are applied with monkeypatch when given.
    """
    if env and monkeypatch is not None:
        for key, value in env.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
    code = main(argv)
    captured = capsys.readouterr()
    parsed = None
    if "--json" in argv:
        # exactly one JSON document on stdout
        lines = [line for line in captured.out.splitlines() if line.strip()]
        assert len(lines) == 1, f"expected exactly one stdout line, got: {captured.out!r}"
        parsed = json.loads(lines[0])
    return code, parsed, captured.out, captured.err


def clean_env(monkeypatch, tmp_path) -> None:
    """Strip every YF_* variable and isolate the session file."""
    import os

    for key in list(os.environ):
        if key.startswith("YF_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("YF_CONFIG_DIR", str(tmp_path / "cfg"))
