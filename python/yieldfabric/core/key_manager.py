"""
External-key management — orchestration layer.

Stitches together:

  - `yieldfabric.utils.crypto` (pure crypto)
  - `AuthService` (REST endpoints /keys/external, /keys/...)
  - local filesystem (key file persistence)

Two primary entry points:

  * `KeyManager.ensure_external_key(...)` — idempotent "have a key,
    registered to this user, persisted to a file" operation. Port of
    `loan_management/modules/register_external_key.py::ensure_issuer_external_key`.
    First run generates + registers + saves. Subsequent runs load from
    file and resolve the key_id from the auth service.

  * `KeyManager.generate_and_register(...)` — one-shot generate +
    verify-ownership + register. Used when you want a fresh key
    without file persistence (rare; usually ensure_external_key is
    what you want).

Companion: `FileBackedSigner` — a callable compatible with
`MessageSignatureListener`'s `sign_callback` signature. Loads a
private key from a file and signs the `message_hash` field of
whatever unsigned-tx dict the backend returns.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from ..services import AuthService
from ..utils.crypto import (
    address_from_private_key,
    generate_ethereum_key,
    sign_message_hash,
    sign_ownership_message,
    verify_unsigned_transaction_digest,
)
from ..utils.logger import get_logger


@dataclass
class EnsureKeyResult:
    """
    Outcome of `ensure_external_key`.

    - `address`: 0x-prefixed Ethereum address of the key.
    - `private_key_hex`: private key (hex, no 0x prefix) — KEEP SECRET.
    - `key_id`: backend's UUID for the key pair. A pre-existing file whose
      database row was removed is re-proved and re-registered with the same
      EOA; the method fails rather than returning an unbound key.
    - `newly_created`: True if this run generated and registered a
      new key; False if we reused an existing file.
    """

    address: str
    private_key_hex: str
    key_id: Optional[str]
    newly_created: bool


def _validated_private_key_hex(value: str, path: Path) -> str:
    private_key_hex = value.strip().removeprefix("0x").strip()
    if (
        len(private_key_hex) != 64
        or any(char not in "0123456789abcdefABCDEF" for char in private_key_hex)
    ):
        raise ValueError(f"invalid private key file: {path}")
    return private_key_hex


def _read_private_key_file(path: Path) -> str:
    """Open once, without following a final symlink, then verify/read that fd."""
    if path.is_symlink():
        raise ValueError(f"signer key path must be a regular file: {path}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags)
    except OSError as exc:
        raise ValueError(f"could not securely open signer key file: {path}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError(f"signer key path must be a regular file: {path}")
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "r", encoding="ascii") as key_file:
            descriptor = -1
            return _validated_private_key_hex(key_file.read(), path)
    except OSError as exc:
        raise RuntimeError(
            f"could not securely read signer key file: {path}"
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _create_private_key_file(path: Path, private_key_hex: str) -> None:
    """Atomically create an owner-only key file before remote registration."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(str(path), flags, 0o600)
    except FileExistsError as exc:
        raise RuntimeError(
            f"signer key path appeared during secure creation: {path}"
        ) from exc
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="ascii") as key_file:
            descriptor = -1
            key_file.write(
                _validated_private_key_hex(private_key_hex, path) + "\n"
            )
            key_file.flush()
            os.fsync(key_file.fileno())
    except Exception:
        try:
            path.unlink()
        except OSError:
            pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


class KeyManager:
    """
    Orchestrator for external-key registration + persistence.

    Instantiate with an AuthService and a logged-in user's JWT + id;
    call `ensure_external_key(path, key_name, ...)` to guarantee a
    registered key exists on disk.
    """

    def __init__(
        self,
        auth_service: AuthService,
        *,
        token: str,
        user_id: str,
        debug: bool = False,
    ):
        self.auth_service = auth_service
        self.token = token
        self.user_id = user_id
        self.logger = get_logger(debug=debug)

    # ------------------------------------------------------------------

    def ensure_external_key(
        self,
        key_file_path: Union[str, Path],
        *,
        key_name: str = "External key (Python CLI)",
        register_with_wallet: bool = False,
        verify_ownership: bool = True,
    ) -> EnsureKeyResult:
        """
        Idempotent key provisioning.

        If `key_file_path` exists:
            - Load the private key, derive the address.
            - Resolve key_id via auth service (may be None if backend
              doesn't have it — that's the caller's problem to surface).
            - Return with newly_created=False.

        If `key_file_path` does NOT exist:
            - Generate a new key and atomically persist it owner-only.
            - If verify_ownership: POST /keys/external/verify-ownership
              to sanity-check the signature before registering.
            - POST /keys/external to register.
            - Return with newly_created=True.

        Persistence precedes remote registration so a local write failure can
        never leave an auth/on-chain authority whose private half was lost.
        If registration fails, the key file is retained for a safe retry.

        `register_with_wallet` passes through to the POST /keys/external
        payload; set True to also link this key as an owner of the
        user's default wallet on creation.
        """
        path = Path(key_file_path)

        if path.exists():
            private_key_hex = _read_private_key_file(path)
            address = address_from_private_key(private_key_hex)
            key_id = self.auth_service.get_key_id_by_address(
                self.token, self.user_id, address
            )
            if not key_id:
                # The test/operator key file can legitimately outlive a clean
                # auth database. Re-prove the same EOA and recreate only this
                # user's external-key row; never generate a replacement behind
                # the caller's back because that would change on-chain
                # authority.
                key_id = self._prove_and_register(
                    private_key_hex,
                    address,
                    key_name=key_name,
                    register_with_wallet=register_with_wallet,
                    verify_ownership=verify_ownership,
                )
                if not key_id:
                    raise RuntimeError(
                        "auth recreated the external key without returning id"
                    )
            self.logger.info(
                f"  🔑 reusing external key from {path} address={address}"
                + f" key_id={key_id[:8]}..."
            )
            return EnsureKeyResult(
                address=address,
                private_key_hex=private_key_hex,
                key_id=key_id,
                newly_created=False,
            )

        # Fresh key path.
        self.logger.info(f"  🔑 generating new external key for {path}")
        private_key_hex, address = generate_ethereum_key()
        # Persist before the remote mutation. If registration fails, the same
        # EOA remains recoverable and the next run re-proves it; no unowned
        # auth row can be created after a local write failure.
        _create_private_key_file(path, private_key_hex)
        key_id = self._prove_and_register(
            private_key_hex,
            address,
            key_name=key_name,
            register_with_wallet=register_with_wallet,
            verify_ownership=verify_ownership,
        )
        result = EnsureKeyResult(
            address=address,
            private_key_hex=private_key_hex,
            key_id=key_id,
            newly_created=True,
        )

        self.logger.success(
            f"  ✅ key registered: address={result.address} key_id={result.key_id} "
            f"saved to {path}"
        )
        return result

    def _prove_and_register(
        self,
        private_key_hex: str,
        address: str,
        *,
        key_name: str,
        register_with_wallet: bool,
        verify_ownership: bool,
    ) -> Optional[str]:
        message, signature = sign_ownership_message(address, private_key_hex)
        if verify_ownership:
            verify = self.auth_service.verify_external_key_ownership(
                self.token,
                public_key=address,
                message=message,
                signature=signature,
            )
            if not verify.get("valid"):
                raise RuntimeError(
                    f"verify-ownership returned valid=false: {verify.get('message')}"
                )
        key_pair = self.auth_service.register_external_key(
            self.token,
            user_id=self.user_id,
            key_name=key_name,
            public_key=address,
            register_with_wallet=register_with_wallet,
        )
        key_id = key_pair.get("id")
        return str(key_id) if key_id else None

    def generate_and_register(
        self,
        *,
        key_name: str = "External key (Python CLI)",
        register_with_wallet: bool = False,
        verify_ownership: bool = True,
    ) -> EnsureKeyResult:
        """
        Generate a new key, optionally verify ownership, register.
        Does NOT persist to disk — use `ensure_external_key` for that.
        """
        private_key_hex, address = generate_ethereum_key()
        key_id = self._prove_and_register(
            private_key_hex,
            address,
            key_name=key_name,
            register_with_wallet=register_with_wallet,
            verify_ownership=verify_ownership,
        )
        return EnsureKeyResult(
            address=address,
            private_key_hex=private_key_hex,
            key_id=key_id,
            newly_created=True,
        )


# ----------------------------------------------------------------------
# Signer callback adapter for MessageSignatureListener.
# ----------------------------------------------------------------------

class FileBackedSigner:
    """
    Callable adapter that satisfies `MessageSignatureListener`'s
    `sign_callback` contract using a private key loaded from disk.

    Usage:
        signer = FileBackedSigner("./issuer_external_key.txt")
        with MessageSignatureListener(
            payments, user_id, token, sign_callback=signer
        ):
            ...run workflow...

    The backend's unsigned-transaction payload has a `message_hash`
    field (32-byte hex) that must be signed with personal_sign over
    the prefixed hash. That's what `sign_message_hash` does — same
    format the contract's ecrecover expects.
    """

    def __init__(
        self,
        key_file_path: Union[str, Path],
        *,
        expected_address: Optional[str] = None,
    ):
        self.path = Path(key_file_path)
        if not self.path.exists():
            raise FileNotFoundError(f"signer key file not found: {self.path}")
        self._private_key_hex = _read_private_key_file(self.path)
        # Derive + cache address once; surfaces key-format errors eagerly.
        self.address = address_from_private_key(self._private_key_hex)
        if (
            expected_address
            and self.address.lower() != str(expected_address).strip().lower()
        ):
            raise ValueError(
                "signer key file address does not match the JWT-bound signer"
            )

    def __call__(self, unsigned_tx: dict) -> str:
        """
        Sign the message_hash from `unsigned_tx`. Returns a 130-hex-char
        signature (no 0x prefix).

        The submit-signed-message endpoint wants it `0x`-prefixed, matching
        a browser wallet's `signMessage`; `PaymentsService.submit_signed_message`
        normalises at that boundary, so a `sign_callback` may return either
        shape.
        """
        if not isinstance(unsigned_tx, dict):
            raise ValueError(
                "unsigned_tx must be a dict (GET unsigned-transaction response)"
            )
        message_hash = verify_unsigned_transaction_digest(unsigned_tx)
        return sign_message_hash(self._private_key_hex, message_hash)

    def __repr__(self) -> str:  # pragma: no cover — debug aid
        return f"FileBackedSigner(path={self.path}, address={self.address})"
