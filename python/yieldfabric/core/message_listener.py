"""
Background message-signature listener.

Manual-signature workflows (loan_management/issue_workflow.py,
payment_workflow.py) need a thread that continuously polls
`/api/users/{user_id}/messages/awaiting-signature`, grabs each new
unsigned transaction, and submits the locally-produced signature
back. The listener runs alongside the main command sequence so
signatures are cleared as mutations produce them.

This framework provides the *polling + dispatch* half of that pattern.
The *signing* half is deliberately a caller-supplied callback: the
framework does not carry private keys or know which curve / message
format the backend expects for a given mutation type. Callers plug in
their own signing function:

    def my_signer(unsigned_tx: dict) -> str:
        # unsigned_tx is whatever the backend returned on
        # GET /api/users/.../messages/.../unsigned-transaction
        message_hash = unsigned_tx["message_hash"]
        signature_bytes = sign_with_my_key(message_hash, my_private_key)
        return "0x" + signature_bytes.hex()

    listener = MessageSignatureListener(
        payments_service, user_id, jwt_token, sign_callback=my_signer
    )
    listener.start()
    try:
        ...run workflow commands...
    finally:
        listener.stop()

The listener swallows per-message signing errors (logging them) rather
than failing the whole loop — a poisoned message shouldn't derail
other pending signatures.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional, Set, Union

from ..services import PaymentsService
from ..utils.logger import get_logger


SignerCallback = Callable[[dict], str]
"""A callable that turns an unsigned-transaction dict into a hex-string signature."""
TokenLike = Union[str, Callable[[], Optional[str]]]


class MessageSignatureListener:
    """
    Thread-based background listener that signs and submits manual-
    signature messages as they become available.

    Lifecycle:
        listener.start()          — launches daemon thread
        # (do work that produces messages needing signatures)
        listener.stop()           — signals stop, joins within ~1 interval
        listener.signed_count     — messages signed successfully
        listener.errored_count    — messages that errored

    Idempotency: a message id is signed at most once per listener
    lifetime (tracked in an in-memory set). Restarting the listener
    resets the set.
    """

    def __init__(
        self,
        payments_service: PaymentsService,
        user_id: str,
        token: TokenLike,
        *,
        sign_callback: SignerCallback,
        interval: float = 3.0,
        unsigned_tx_timeout: float = 30.0,
        debug: bool = False,
    ):
        if interval <= 0:
            raise ValueError("interval must be > 0")
        self._payments = payments_service
        self._user_id = user_id
        self._token = token
        self._sign_callback = sign_callback
        self._interval = interval
        self._unsigned_tx_timeout = unsigned_tx_timeout

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._seen: Set[str] = set()
        self._lock = threading.Lock()

        self.signed_count = 0
        self.errored_count = 0

        self.logger = get_logger(debug=debug)

    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the background thread. No-op if already running."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name=f"MessageSignatureListener[{self._user_id[:8]}...]",
                daemon=True,
            )
            self._thread.start()
            self.logger.info(
                f"  🎧 signature listener started for user {self._user_id[:8]}..."
            )

    def stop(self, timeout: Optional[float] = None) -> None:
        """Signal the listener to stop and join the thread."""
        self._stop_event.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread.is_alive():
            # If caller didn't specify a timeout, give the thread one
            # poll interval plus a grace margin to drain its in-flight
            # work — enough to finish signing the last message it
            # picked up, but not indefinite.
            join_timeout = timeout if timeout is not None else self._interval + 2.0
            thread.join(timeout=join_timeout)
        self.logger.info(
            f"  🛑 signature listener stopped (signed={self.signed_count} "
            f"errored={self.errored_count})"
        )

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main loop — polls for new awaiting-signature messages."""
        while not self._stop_event.is_set():
            try:
                messages = self._payments.get_messages_awaiting_signature(
                    self._user_id, self._token_value()
                )
            except Exception as e:
                self.logger.error(
                    f"  ❌ listener failed to fetch awaiting-signature list: {e}"
                )
                messages = []

            for m in messages:
                if self._stop_event.is_set():
                    break
                message_id = (
                    m.get("id")
                    or m.get("message_id")
                    or (m.get("message") or {}).get("id")
                )
                if not message_id or message_id in self._seen:
                    continue
                self._seen.add(message_id)
                self._process_one(message_id)

            # Wait either the full interval or until stop() is called,
            # whichever comes first — responsive shutdown without
            # polling faster than configured.
            self._stop_event.wait(self._interval)

    def _process_one(self, message_id: str) -> None:
        """Poll for the unsigned tx, sign, and submit."""
        try:
            poll = self._payments.poll_unsigned_transaction_ready(
                self._user_id,
                message_id,
                self._token,
                interval=1.0,
                timeout=self._unsigned_tx_timeout,
            )
        except TimeoutError as e:
            self.logger.error(f"  ❌ signature listener: {e}")
            self.errored_count += 1
            return
        except Exception as e:
            self.logger.error(f"  ❌ signature listener probe failed: {e}")
            self.errored_count += 1
            return

        unsigned_tx = poll.observation
        unsigned_transaction_id = unsigned_tx.get("unsigned_transaction_id")
        if not isinstance(unsigned_transaction_id, str) or not unsigned_transaction_id.strip():
            self.logger.error(
                f"  ❌ unsigned transaction for {message_id[:8]}... has no "
                "unsigned_transaction_id"
            )
            self.errored_count += 1
            return

        try:
            signature_hex = self._sign_callback(unsigned_tx)
        except Exception as e:
            self.logger.error(
                f"  ❌ signer callback raised for message {message_id[:8]}...: {e}"
            )
            self.errored_count += 1
            return

        if not signature_hex or not isinstance(signature_hex, str):
            self.logger.error(
                f"  ❌ signer callback returned invalid signature for {message_id[:8]}..."
            )
            self.errored_count += 1
            return

        try:
            result = self._payments.submit_signed_message(
                self._user_id,
                message_id,
                signature_hex,
                unsigned_transaction_id,
                self._token_value(),
            )
        except Exception as e:
            self.logger.error(
                f"  ❌ submit_signed_message failed for {message_id[:8]}...: {e}"
            )
            self.errored_count += 1
            return

        if (result or {}).get("status") == "error":
            self.logger.error(
                f"  ❌ submit_signed_message error for {message_id[:8]}...: "
                f"{result.get('message')}"
            )
            self.errored_count += 1
        else:
            self.signed_count += 1
            self.logger.success(
                f"  ✍️  signed and submitted message {message_id[:8]}..."
            )

    def _token_value(self) -> Optional[str]:
        return self._token() if callable(self._token) else self._token
