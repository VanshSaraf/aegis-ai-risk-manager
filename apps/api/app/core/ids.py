from typing import Final

from ulid import ULID

PUBLIC_ID_PREFIXES: Final[frozenset[str]] = frozenset(
    {"txn", "cus", "dev", "card", "ip", "addr", "mer", "clu", "dec", "aud", "inv", "run"}
)


def generate_public_id(prefix: str) -> str:
    """Generate a sortable, opaque public identifier with a controlled prefix."""
    if prefix not in PUBLIC_ID_PREFIXES:
        raise ValueError(f"Unsupported public ID prefix: {prefix}")
    return f"{prefix}_{ULID()}"
