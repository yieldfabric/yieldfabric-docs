"""The service-client additions the `yf` CLI relies on."""

from unittest.mock import MagicMock

import requests

from yieldfabric.config import YieldFabricConfig
from yieldfabric.services.agents_service import AgentsService
from yieldfabric.services.auth_service import AuthService


def _config() -> YieldFabricConfig:
    return YieldFabricConfig(
        pay_service_url="https://pay.test.yieldfabric.com",
        auth_service_url="https://auth.yieldfabric.com",
        agents_service_url="https://agents.yieldfabric.com",
        command_delay=0,
        debug=False,
    )


def _http(status: int, body):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body
    resp.text = str(body)
    return resp


def test_get_jwt_info_hits_protected_jwt_and_keeps_status():
    auth = AuthService(_config())
    auth.session.request = MagicMock(return_value=_http(200, {"user_id": "u", "session_kind": "personal"}))
    result = auth.get_jwt_info("tok")
    assert result == {"ok": True, "status_code": 200, "body": {"user_id": "u", "session_kind": "personal"}}
    verb, url = auth.session.request.call_args.args
    assert (verb, url) == ("GET", "https://auth.yieldfabric.com/protected/jwt")
    assert auth.session.request.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"

    auth.session.request = MagicMock(return_value=_http(401, {"error": "Invalid token"}))
    assert auth.get_jwt_info("bad")["status_code"] == 401

    auth.session.request = MagicMock(side_effect=requests.exceptions.ConnectionError("refused"))
    assert auth.get_jwt_info("tok")["status_code"] == 0


def test_count_documents_posts_the_documented_body():
    agents = AgentsService(_config())
    agents.session.request = MagicMock(return_value=_http(200, {"terms": [], "union_documents": 0}))
    result = agents.count_documents(
        "tok", working_group_id="wg", terms=[{"term": "x", "mode": "phrase"}], kg_ids=["k1"], as_of="2026-01-01T00:00:00Z"
    )
    assert result["ok"] is True
    verb, url = agents.session.request.call_args.args
    assert (verb, url) == ("POST", "https://agents.yieldfabric.com/knowledge/documents/count")
    assert agents.session.request.call_args.kwargs["json"] == {
        "working_group_id": "wg", "terms": [{"term": "x", "mode": "phrase"}], "kg_ids": ["k1"], "as_of": "2026-01-01T00:00:00Z",
    }


def test_retrieve_documents_omits_unset_fields():
    agents = AgentsService(_config())
    agents.session.request = MagicMock(return_value=_http(200, {"query": "q", "results": [], "lanes": {}}))
    agents.retrieve_documents("tok", working_group_id="wg", query="q", top_k=3)
    verb, url = agents.session.request.call_args.args
    assert (verb, url) == ("POST", "https://agents.yieldfabric.com/knowledge/documents/retrieve")
    assert agents.session.request.call_args.kwargs["json"] == {"working_group_id": "wg", "query": "q", "top_k": 3}
