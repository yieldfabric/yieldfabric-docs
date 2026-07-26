"""Wire contract for the manual-signature client: what it can see, what it sends.

Two shapes a background signature listener depends on, both previously wrong:

- `/messages/awaiting-signature` answers with the `{"messages": [...],
  "count": N}` envelope. A client that only understood a bare list read every
  response as "nothing to sign", so the listener polled forever without
  signing and `poll_signatures_cleared` reported an immediate all-clear —
  both silent by construction.
- `/messages/{id}/submit-signed-message` requires a `0x`-prefixed signature,
  matching a browser wallet's `signMessage`. `sign_message_hash` returns bare
  hex, so every local-signer submission was rejected with 400.
"""

import pytest
import requests
from unittest.mock import MagicMock

from yieldfabric.config import YieldFabricConfig
from yieldfabric.services.payments_service import PaymentsService


def _service(json_body=None, raises=None):
    config = YieldFabricConfig(
        pay_service_url="http://localhost:3002",
        auth_service_url="http://localhost:3000",
        command_delay=0,
        debug=False,
    )
    service = PaymentsService(config)
    if raises is not None:
        service._get = MagicMock(side_effect=raises)
    else:
        response = MagicMock(name="Response")
        response.json.return_value = json_body
        service._get = MagicMock(return_value=response)
    return service


def test_envelope_shape_is_unwrapped():
    service = _service({"messages": [{"id": "m-1"}], "count": 1, "limit": None})
    assert service.get_messages_awaiting_signature("entity-1", "jwt") == [
        {"id": "m-1"}
    ]


def test_empty_envelope_reads_as_nothing_pending():
    service = _service({"messages": [], "count": 0})
    assert service.get_messages_awaiting_signature("entity-1", "jwt") == []


def test_bare_list_still_reads():
    service = _service([{"id": "m-1"}])
    assert service.get_messages_awaiting_signature("entity-1", "jwt") == [
        {"id": "m-1"}
    ]


def test_unrecognised_shape_raises_instead_of_reporting_nothing_to_sign():
    # An empty list is an affirmative claim — "every signature is in".
    # A body the client cannot read must never be able to make it.
    service = _service({"items": [{"id": "m-1"}]})
    with pytest.raises(ValueError, match="awaiting-signature response"):
        service.get_messages_awaiting_signature("entity-1", "jwt")


def test_transport_failure_reports_nothing_pending_and_is_retryable():
    # `_get` raises for any non-2xx, and a caller polls again, so this
    # path stays non-fatal — it just may not stay quiet.
    service = _service(raises=requests.exceptions.ConnectionError("boom"))
    service.logger = MagicMock(name="logger")
    assert service.get_messages_awaiting_signature("entity-1", "jwt") == []
    assert service.logger.warning.called


def test_submitted_signature_is_0x_prefixed():
    # The endpoint rejects a bare hex signature with 400 "signature must be
    # a 0x-prefixed hex string" — the shape a browser wallet produces.
    # `sign_message_hash` returns bare hex, so the boundary normalises.
    service = _service({})
    service._post = MagicMock(return_value=MagicMock(json=lambda: {"success": True}))
    service.submit_signed_message("entity-1", "m-1", "ab" * 65, "utx-1", "jwt")
    assert service._post.call_args.kwargs["data"]["signature"] == "0x" + "ab" * 65


def test_already_prefixed_signature_is_not_double_prefixed():
    service = _service({})
    service._post = MagicMock(return_value=MagicMock(json=lambda: {"success": True}))
    service.submit_signed_message("entity-1", "m-1", "0x" + "cd" * 65, "utx-1", "jwt")
    assert service._post.call_args.kwargs["data"]["signature"] == "0x" + "cd" * 65
