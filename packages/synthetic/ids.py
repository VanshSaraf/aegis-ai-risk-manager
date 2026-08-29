import hashlib

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def synthetic_key(kind: str, seed: int, index: int) -> str:
    return f"syn_{kind}_{seed}_{index:06d}"


def deterministic_public_id(prefix: str, namespace: str) -> str:
    """Create a deterministic 26-character ULID-style payload for synthetic records."""
    number = int.from_bytes(hashlib.sha256(namespace.encode()).digest()[:16], "big")
    encoded = ""
    for _ in range(26):
        number, remainder = divmod(number, 32)
        encoded = CROCKFORD[remainder] + encoded
    return f"{prefix}_{encoded}"


def stable_ring_id(seed: int, scenario: str, ring_index: int) -> str:
    digest = hashlib.sha256(f"{seed}:{scenario}:{ring_index}".encode()).hexdigest()[:12]
    return f"ring_{digest}"
