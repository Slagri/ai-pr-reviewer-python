"""Tests for middleware: rate limiting, signature verification, logging."""

from __future__ import annotations

import hashlib
import hmac

import pytest

from reviewer.middleware.ratelimit import TokenBucket


class TestTokenBucket:
    """Test the token bucket rate limiter."""

    def test_allows_up_to_max(self) -> None:
        bucket = TokenBucket(max_tokens=3, refill_rate=0.0)
        assert bucket.consume() is True
        assert bucket.consume() is True
        assert bucket.consume() is True
        assert bucket.consume() is False

    def test_refills_over_time(self) -> None:
        bucket = TokenBucket(max_tokens=1, refill_rate=1000.0)  # Very fast refill
        bucket.consume()
        assert bucket.consume() is False

        # Simulate tiny time passing — with high refill rate this should work
        bucket._last_refill -= 0.01
        assert bucket.consume() is True

    def test_does_not_exceed_max(self) -> None:
        bucket = TokenBucket(max_tokens=2, refill_rate=1000.0)
        bucket._last_refill -= 100  # Simulate lots of time passing
        bucket.consume()  # Forces refill

        # Should only have max_tokens available
        assert bucket.consume() is True
        assert bucket.consume() is False


class TestSignatureVerification:
    """Test webhook signature middleware behavior via the verify function."""

    def test_github_signature_format(self) -> None:
        from reviewer.providers.github.webhook import verify_signature

        payload = b'{"test": true}'
        secret = "test-secret"
        sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        verify_signature(payload, sig, secret)  # Should not raise

    def test_reject_bad_signature(self) -> None:
        from reviewer.exceptions import SignatureError
        from reviewer.providers.github.webhook import verify_signature

        with pytest.raises(SignatureError):
            verify_signature(b"body", "sha256=bad", "secret")
