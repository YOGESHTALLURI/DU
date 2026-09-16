import contextlib
import itertools
from typing import Iterable, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

# PostgreSQL advisory lock uses signed 64‑bit integers. We accept any number of keys,
# sort them deterministically, and acquire a transaction‑level advisory lock for each.

def _sorted_int_keys(keys: Iterable[int]) -> Tuple[int, ...]:
    """Return a tuple of keys sorted in ascending order.

    PostgreSQL advisory lock acquisition order must be consistent across concurrent
    callers to avoid dead‑locks. By sorting the keys we guarantee a total ordering.
    """
    return tuple(sorted(int(k) for k in keys))

@contextlib.contextmanager
def acquire_identity_operation_lock(db: Session, *keys: int):
    """Acquire one or more transaction‑level advisory locks.

    The function yields control after acquiring all locks. The locks are held for the
    duration of the surrounding transaction (i.e. they are released automatically when
    the transaction ends or is rolled back).

    Parameters
    ----------
    db: Session
        An active SQLAlchemy session/transaction.
    *keys: int
        One or more integer lock identifiers. They are sorted before acquisition to
        guarantee a deterministic order and thus avoid dead‑locks.
    """
    sorted_keys = _sorted_int_keys(keys)
    # Use the underlying DB‑API connection to execute raw SQL. ``connection`` is a
    # ``sqlalchemy.engine.Connection`` object.
    connection = db.connection()
    try:
        for key in sorted_keys:
            # ``pg_advisory_xact_lock`` obtains a lock that is automatically released
            # at the end of the current transaction.
            connection.execute(text(f"SELECT pg_advisory_xact_lock({key});"))
        yield
    finally:
        # No explicit release is required for transaction‑level locks.
        pass

def generate_lock_keys(exc) -> Tuple[int, ...]:
    """Generate deterministic lock keys for a given ``IdentityException``.

    The lock key composition mirrors the logic described in the implementation plan:
    * If the exception contains a SSN hash, we use a signed 63‑bit integer derived from
      the first 8 bytes of the hash (interpreted as big‑endian).
    * Otherwise we fall back to the source identifier hash prefixed with ``SRC:``.
    * The result is always a tuple to allow future expansion (e.g., including
      ``source_system``).
    """
    # ``exc`` is expected to be an ORM instance of ``IdentityException``.
    if getattr(exc, "ssn_hash", None):
        # Take the first 8 bytes of the hex string, convert to int, then to signed 63‑bit.
        raw = int(exc.ssn_hash[:16], 16)
        # Ensure it fits into signed 63‑bit range.
        signed = raw if raw < (1 << 63) else raw - (1 << 64)
        return (signed,)
    else:
        # Use a deterministic hash of the source identifier.
        # ``hash()`` is not stable across processes, so we use a stable SHA‑256.
        import hashlib
        src = f"SRC:{exc.source_identifier_hash}".encode("utf-8")
        digest = hashlib.sha256(src).digest()[:8]
        raw = int.from_bytes(digest, "big", signed=False)
        signed = raw if raw < (1 << 63) else raw - (1 << 64)
        return (signed,)
