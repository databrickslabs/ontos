"""
Multihash encoding and hashing for data product manifests.

Implements multihash (https://github.com/multiformats/multihash) with
multibase base16 encoding for content digests.

Reference:
  - Multihash specification
  - Multibase specification (base16)
  - Decision 2: Hash function and encoding in
    docs/decisions/manifest-canonicalization-hashing-signing.md
"""

import hashlib
from typing import Literal, Tuple


# Multihash codes for supported algorithms
MULTIHASH_SHA2_256 = 0x12
MULTIHASH_SHA3_256 = 0x16
HASH_LENGTH_SHA256 = 0x20  # 32 bytes

# Multibase prefix for base16 (lowercase hex)
MULTIBASE_BASE16_PREFIX = "f"

# Supported hash algorithms
HashAlgorithm = Literal["sha2-256", "sha3-256"]


class MultihashError(ValueError):
    """Raised when multihash encoding/decoding fails."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def hash_bytes(
    data: bytes,
    algorithm: HashAlgorithm = "sha2-256",
) -> bytes:
    """
    Hash data using the specified algorithm and return raw digest.

    Args:
        data: Bytes to hash.
        algorithm: Hash algorithm ("sha2-256" or "sha3-256").

    Returns:
        Raw digest bytes.

    Raises:
        MultihashError: If algorithm is unsupported.
    """
    if algorithm == "sha2-256":
        return hashlib.sha256(data).digest()
    elif algorithm == "sha3-256":
        return hashlib.sha3_256(data).digest()
    else:
        raise MultihashError(
            "unsupported_hash_alg",
            f"Algorithm {algorithm} is not supported",
        )


def encode_multihash(
    data: bytes,
    algorithm: HashAlgorithm = "sha2-256",
) -> str:
    """
    Hash data and encode as multihash with multibase base16.

    The format is: multibase prefix + multihash code (2 hex) + digest length
    (2 hex) + digest (hex encoded).

    For sha2-256: f1220 + 64 hex characters (total: 69 chars)
    For sha3-256: f1620 + 64 hex characters (total: 69 chars)

    Args:
        data: Bytes to hash.
        algorithm: Hash algorithm ("sha2-256" or "sha3-256").

    Returns:
        Encoded multihash string (multibase base16).

    Raises:
        MultihashError: If algorithm is unsupported.
    """
    digest = hash_bytes(data, algorithm)

    # Determine multihash code
    if algorithm == "sha2-256":
        code = MULTIHASH_SHA2_256
    elif algorithm == "sha3-256":
        code = MULTIHASH_SHA3_256
    else:
        raise MultihashError(
            "unsupported_hash_alg",
            f"Algorithm {algorithm} is not supported",
        )

    # Build multihash: code (1 byte) + length (1 byte) + digest
    multihash_bytes = bytes([code, len(digest)]) + digest

    # Encode as multibase base16 (lowercase hex)
    hex_part = multihash_bytes.hex()
    return MULTIBASE_BASE16_PREFIX + hex_part


def decode_multihash(encoded: str) -> Tuple[str, bytes]:
    """
    Decode a multibase base16 multihash string.

    Args:
        encoded: Encoded multihash string (must start with 'f').

    Returns:
        Tuple of (algorithm_name, digest_bytes).

    Raises:
        MultihashError: If encoding is invalid.
    """
    if not encoded.startswith(MULTIBASE_BASE16_PREFIX):
        raise MultihashError(
            "invalid_multibase_prefix",
            f"Expected multibase prefix 'f', got '{encoded[0]}'",
        )

    # Remove prefix and decode hex
    try:
        hex_part = encoded[1:]
        multihash_bytes = bytes.fromhex(hex_part)
    except ValueError as e:
        raise MultihashError(
            "invalid_hex_encoding",
            f"Failed to decode hex: {e}",
        )

    if len(multihash_bytes) < 2:
        raise MultihashError(
            "invalid_multihash_format",
            "Multihash must be at least 2 bytes (code + length)",
        )

    code = multihash_bytes[0]
    length = multihash_bytes[1]
    digest = multihash_bytes[2:]

    if len(digest) != length:
        raise MultihashError(
            "length_mismatch",
            f"Expected {length} bytes, got {len(digest)}",
        )

    # Map code to algorithm name
    if code == MULTIHASH_SHA2_256:
        algorithm = "sha2-256"
    elif code == MULTIHASH_SHA3_256:
        algorithm = "sha3-256"
    else:
        raise MultihashError(
            "unsupported_hash_alg",
            f"Unsupported multihash code: 0x{code:02x}",
        )

    return algorithm, digest


def verify_multihash(
    data: bytes,
    encoded: str,
) -> bool:
    """
    Verify that data matches the digest in an encoded multihash.

    Args:
        data: Bytes to verify.
        encoded: Encoded multihash string to verify against.

    Returns:
        True if the digest matches, False otherwise.

    Raises:
        MultihashError: If the encoding is invalid.
    """
    algorithm, expected_digest = decode_multihash(encoded)
    computed_digest = hash_bytes(data, algorithm)
    return computed_digest == expected_digest
