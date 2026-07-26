"""External key files remain usable after a clean auth database rebuild."""

import stat
from unittest.mock import MagicMock

import pytest

from yieldfabric.core import key_manager as key_manager_module
from yieldfabric.core.key_manager import KeyManager


def test_existing_key_file_is_re_registered_when_auth_row_is_missing(
    monkeypatch,
    tmp_path,
):
    key_file = tmp_path / "operator.key"
    key_file.write_text("11" * 32 + "\n")
    auth = MagicMock()
    auth.get_key_id_by_address.return_value = None
    auth.verify_external_key_ownership.return_value = {"valid": True}
    auth.register_external_key.return_value = {
        "id": "11111111-1111-4111-8111-111111111111"
    }
    monkeypatch.setattr(
        key_manager_module,
        "address_from_private_key",
        lambda _private: "0x2222222222222222222222222222222222222222",
    )
    monkeypatch.setattr(
        key_manager_module,
        "sign_ownership_message",
        lambda _address, _private: ("proof", "signature"),
    )

    result = KeyManager(
        auth,
        token="personal-jwt",
        user_id="33333333-3333-4333-8333-333333333333",
    ).ensure_external_key(key_file, key_name="operator")

    assert result.newly_created is False
    assert result.key_id == "11111111-1111-4111-8111-111111111111"
    assert result.address == "0x2222222222222222222222222222222222222222"
    auth.verify_external_key_ownership.assert_called_once()
    auth.register_external_key.assert_called_once_with(
        "personal-jwt",
        user_id="33333333-3333-4333-8333-333333333333",
        key_name="operator",
        public_key="0x2222222222222222222222222222222222222222",
        register_with_wallet=False,
    )


def test_signer_key_path_rejects_symlinks(tmp_path):
    target = tmp_path / "target.key"
    target.write_text("11" * 32 + "\n")
    link = tmp_path / "operator.key"
    link.symlink_to(target)

    manager = KeyManager(
        MagicMock(),
        token="personal-jwt",
        user_id="33333333-3333-4333-8333-333333333333",
    )
    with pytest.raises(ValueError, match="regular file"):
        manager.ensure_external_key(link)


def test_new_signer_key_file_is_created_owner_only(monkeypatch, tmp_path):
    key_file = tmp_path / "operator.key"
    auth = MagicMock()
    auth.verify_external_key_ownership.return_value = {"valid": True}
    auth.register_external_key.return_value = {
        "id": "11111111-1111-4111-8111-111111111111"
    }
    manager = KeyManager(
        auth,
        token="personal-jwt",
        user_id="33333333-3333-4333-8333-333333333333",
    )
    monkeypatch.setattr(
        key_manager_module,
        "generate_ethereum_key",
        lambda: (
            "11" * 32,
            "0x2222222222222222222222222222222222222222",
        ),
    )
    monkeypatch.setattr(
        key_manager_module,
        "sign_ownership_message",
        lambda _address, _private: ("proof", "signature"),
    )

    manager.ensure_external_key(key_file)

    assert key_file.read_text().strip() == "11" * 32
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_registration_failure_retains_recoverable_key_file(monkeypatch, tmp_path):
    key_file = tmp_path / "operator.key"
    auth = MagicMock()
    auth.verify_external_key_ownership.return_value = {"valid": True}
    auth.register_external_key.side_effect = RuntimeError("auth unavailable")
    manager = KeyManager(
        auth,
        token="personal-jwt",
        user_id="33333333-3333-4333-8333-333333333333",
    )
    monkeypatch.setattr(
        key_manager_module,
        "generate_ethereum_key",
        lambda: (
            "11" * 32,
            "0x2222222222222222222222222222222222222222",
        ),
    )
    monkeypatch.setattr(
        key_manager_module,
        "sign_ownership_message",
        lambda _address, _private: ("proof", "signature"),
    )

    with pytest.raises(RuntimeError, match="auth unavailable"):
        manager.ensure_external_key(key_file)

    assert key_file.read_text().strip() == "11" * 32
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
