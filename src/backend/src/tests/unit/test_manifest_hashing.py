"""
Tests for manifest hashing and multihash encoding/decoding.

Covers:
- SHA2-256 and SHA3-256 hashing
- Multihash encoding/decoding
- Multibase base16 format
- Round-trip consistency
- Error handling for invalid formats
"""

import pytest
from src.common.manifest_hashing import (
    hash_bytes,
    encode_multihash,
    decode_multihash,
    verify_multihash,
    MultihashError,
    MULTIHASH_SHA2_256,
    MULTIHASH_SHA3_256,
    HASH_LENGTH_SHA256,
    MULTIBASE_BASE16_PREFIX,
)


class TestHashBytes:
    """Test raw hash computation."""

    def test_sha2_256_deterministic(self):
        """SHA2-256 hashing is deterministic."""
        data = b"test data"
        result1 = hash_bytes(data, "sha2-256")
        result2 = hash_bytes(data, "sha2-256")
        assert result1 == result2

    def test_sha2_256_length(self):
        """SHA2-256 produces 32-byte digests."""
        result = hash_bytes(b"test", "sha2-256")
        assert len(result) == 32

    def test_sha3_256_deterministic(self):
        """SHA3-256 hashing is deterministic."""
        data = b"test data"
        result1 = hash_bytes(data, "sha3-256")
        result2 = hash_bytes(data, "sha3-256")
        assert result1 == result2

    def test_sha3_256_length(self):
        """SHA3-256 produces 32-byte digests."""
        result = hash_bytes(b"test", "sha3-256")
        assert len(result) == 32

    def test_different_algorithms_different_digest(self):
        """SHA2 and SHA3 produce different digests for same data."""
        data = b"test"
        sha2_result = hash_bytes(data, "sha2-256")
        sha3_result = hash_bytes(data, "sha3-256")
        assert sha2_result != sha3_result

    def test_empty_input(self):
        """Empty input can be hashed."""
        result = hash_bytes(b"", "sha2-256")
        assert len(result) == 32

    def test_large_input(self):
        """Large input can be hashed."""
        large_data = b"x" * 1000000
        result = hash_bytes(large_data, "sha2-256")
        assert len(result) == 32

    def test_unsupported_algorithm(self):
        """Unsupported algorithm raises MultihashError."""
        with pytest.raises(MultihashError) as exc:
            hash_bytes(b"test", "sha1-160")  # type: ignore
        assert exc.value.code == "unsupported_hash_alg"


class TestEncode:
    """Test multihash encoding."""

    def test_sha2_256_format(self):
        """SHA2-256 multihash has correct format: f1220 + 64 hex."""
        data = b"test"
        result = encode_multihash(data, "sha2-256")

        # Should start with f (multibase base16)
        assert result.startswith(MULTIBASE_BASE16_PREFIX)

        # Should be 69 characters total (f + 2 code hex + 2 length hex + 64 digest hex)
        assert len(result) == 69

        # Should only contain hex characters after the prefix
        hex_part = result[1:]
        assert all(c in "0123456789abcdef" for c in hex_part)

    def test_sha3_256_format(self):
        """SHA3-256 multihash has correct format: f1620 + 64 hex."""
        data = b"test"
        result = encode_multihash(data, "sha3-256")

        assert result.startswith(MULTIBASE_BASE16_PREFIX)
        assert len(result) == 69  # Same length (same hash algorithm)

    def test_encoding_deterministic(self):
        """Encoding is deterministic."""
        data = b"test"
        result1 = encode_multihash(data, "sha2-256")
        result2 = encode_multihash(data, "sha2-256")
        assert result1 == result2

    def test_different_data_different_encoding(self):
        """Different data produces different encodings."""
        result1 = encode_multihash(b"test1", "sha2-256")
        result2 = encode_multihash(b"test2", "sha2-256")
        assert result1 != result2

    def test_empty_data(self):
        """Empty data can be encoded."""
        result = encode_multihash(b"", "sha2-256")
        assert result.startswith(MULTIBASE_BASE16_PREFIX)
        assert len(result) == 69

    def test_unsupported_algorithm_raises(self):
        """Unsupported algorithm raises MultihashError."""
        with pytest.raises(MultihashError) as exc:
            encode_multihash(b"test", "sha1-160")  # type: ignore
        assert exc.value.code == "unsupported_hash_alg"


class TestDecode:
    """Test multihash decoding."""

    def test_decode_sha2_256(self):
        """Decoding SHA2-256 multihash returns correct algorithm and digest."""
        data = b"test"
        encoded = encode_multihash(data, "sha2-256")

        algorithm, digest = decode_multihash(encoded)

        assert algorithm == "sha2-256"
        assert len(digest) == 32
        # Verify it matches the original hash
        assert digest == hash_bytes(data, "sha2-256")

    def test_decode_sha3_256(self):
        """Decoding SHA3-256 multihash returns correct algorithm and digest."""
        data = b"test"
        encoded = encode_multihash(data, "sha3-256")

        algorithm, digest = decode_multihash(encoded)

        assert algorithm == "sha3-256"
        assert len(digest) == 32
        assert digest == hash_bytes(data, "sha3-256")

    def test_decode_invalid_prefix(self):
        """Invalid multibase prefix raises MultihashError."""
        with pytest.raises(MultihashError) as exc:
            decode_multihash("x" + "1220" + "00" * 32)
        assert exc.value.code == "invalid_multibase_prefix"

    def test_decode_invalid_hex(self):
        """Invalid hex encoding raises MultihashError."""
        with pytest.raises(MultihashError) as exc:
            decode_multihash("fXXXX")
        assert exc.value.code == "invalid_hex_encoding"

    def test_decode_too_short(self):
        """Multihash too short raises MultihashError."""
        with pytest.raises(MultihashError) as exc:
            decode_multihash("f12")  # Only code, no length
        assert exc.value.code == "invalid_multihash_format"

    def test_decode_length_mismatch(self):
        """Length mismatch raises MultihashError."""
        # f1220 means: code 0x12, length 0x20 (32 bytes)
        # But provide only 16 bytes of digest
        with pytest.raises(MultihashError) as exc:
            decode_multihash("f1220" + "00" * 16)
        assert exc.value.code == "length_mismatch"

    def test_decode_unsupported_code(self):
        """Unsupported multihash code raises MultihashError."""
        # Use code 0x99 which is not SHA2-256 or SHA3-256
        with pytest.raises(MultihashError) as exc:
            decode_multihash("f9920" + "00" * 32)
        assert exc.value.code == "unsupported_hash_alg"


class TestRoundTrip:
    """Test encoding and decoding round-trip."""

    def test_encode_decode_sha2(self):
        """SHA2-256 encode/decode round-trip."""
        data = b"test payload for hashing"
        encoded = encode_multihash(data, "sha2-256")
        algorithm, digest = decode_multihash(encoded)

        assert algorithm == "sha2-256"
        assert digest == hash_bytes(data, "sha2-256")

    def test_encode_decode_sha3(self):
        """SHA3-256 encode/decode round-trip."""
        data = b"test payload for hashing"
        encoded = encode_multihash(data, "sha3-256")
        algorithm, digest = decode_multihash(encoded)

        assert algorithm == "sha3-256"
        assert digest == hash_bytes(data, "sha3-256")

    def test_multiple_round_trips(self):
        """Multiple round-trips preserve data."""
        data = b"test"
        encoded1 = encode_multihash(data, "sha2-256")

        for _ in range(3):
            alg, digest = decode_multihash(encoded1)
            # Re-encode using the same algorithm
            encoded_again = encode_multihash(data, alg)
            assert encoded_again == encoded1


class TestVerify:
    """Test multihash verification."""

    def test_verify_matching_data(self):
        """Verification succeeds when data matches."""
        data = b"test"
        encoded = encode_multihash(data, "sha2-256")
        assert verify_multihash(data, encoded) is True

    def test_verify_mismatched_data(self):
        """Verification fails when data differs."""
        data1 = b"test1"
        data2 = b"test2"
        encoded = encode_multihash(data1, "sha2-256")
        assert verify_multihash(data2, encoded) is False

    def test_verify_with_different_algorithm(self):
        """Verification works regardless of algorithm."""
        data = b"test"

        for alg in ["sha2-256", "sha3-256"]:
            encoded = encode_multihash(data, alg)
            assert verify_multihash(data, encoded) is True

    def test_verify_empty_data(self):
        """Verification works with empty data."""
        encoded = encode_multihash(b"", "sha2-256")
        assert verify_multihash(b"", encoded) is True
        assert verify_multihash(b"x", encoded) is False

    def test_verify_tampered_digest(self):
        """Verification fails when digest is tampered."""
        data = b"test"
        encoded = encode_multihash(data, "sha2-256")

        # Tamper with one character
        tampered = encoded[:-1] + ("0" if encoded[-1] != "0" else "1")
        assert verify_multihash(data, tampered) is False


class TestGoldenVectors:
    """Test against known good values."""

    def test_empty_sha2_256(self):
        """Known SHA2-256 hash of empty data."""
        # SHA2-256("") = e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
        empty_hash = hash_bytes(b"", "sha2-256")
        expected_hex = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert empty_hash.hex() == expected_hex

    def test_abc_sha2_256(self):
        """Known SHA2-256 hash of 'abc'."""
        # SHA2-256("abc") = ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad
        abc_hash = hash_bytes(b"abc", "sha2-256")
        expected_hex = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        assert abc_hash.hex() == expected_hex

    def test_empty_sha3_256(self):
        """Known SHA3-256 hash of empty data."""
        # SHA3-256("") = a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a
        empty_hash = hash_bytes(b"", "sha3-256")
        expected_hex = "a7ffc6f8bf1ed76651c14756a061d662f580ff4de43b49fa82d80a4b80f8434a"
        assert empty_hash.hex() == expected_hex


class TestConsistency:
    """Test that encodings are consistent across calls."""

    def test_same_data_always_same_encoding(self):
        """Same data always produces same encoding."""
        data = b"manifest content"
        encodings = [encode_multihash(data, "sha2-256") for _ in range(5)]
        assert len(set(encodings)) == 1

    def test_large_batch_consistency(self):
        """Large batch of data produces consistent encodings."""
        test_cases = [
            b"test",
            b"",
            b"x" * 1000,
            b"\x00\x01\x02\x03",
        ]
        for data in test_cases:
            encoded1 = encode_multihash(data, "sha2-256")
            encoded2 = encode_multihash(data, "sha2-256")
            assert encoded1 == encoded2

    def test_determinism_across_formats(self):
        """Hashing same data via different encodings is consistent."""
        data = b"test"
        encoded_sha2 = encode_multihash(data, "sha2-256")

        # Decode and re-encode
        alg, digest = decode_multihash(encoded_sha2)
        re_encoded = encode_multihash(data, alg)

        assert encoded_sha2 == re_encoded
