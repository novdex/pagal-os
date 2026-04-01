"""Tests for PAGAL OS self-healing — retry, fallback, and graceful degradation."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.healing import with_fallback, with_retry


class TestRetry:
    """Test the with_retry function."""

    def test_retry_succeeds_on_second_attempt(self) -> None:
        """Should retry a failing function and succeed on a later attempt."""
        call_count = 0

        def flaky_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ConnectionError("Transient failure")
            return "success"

        result = with_retry(flaky_func, max_retries=3, delay=0.01)
        assert result == "success"
        assert call_count == 2

    def test_retry_fails_after_max(self) -> None:
        """Should raise the last exception after exhausting all retries."""
        def always_fails() -> None:
            raise RuntimeError("Permanent failure")

        with pytest.raises(RuntimeError, match="Permanent failure"):
            with_retry(always_fails, max_retries=2, delay=0.01)

    def test_retry_passes_args(self) -> None:
        """Should forward positional and keyword arguments."""
        call_count = 0

        def func_with_args(a: int, b: int, multiplier: int = 1) -> int:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("first fail")
            return (a + b) * multiplier

        result = with_retry(func_with_args, 3, 0.01, 1, 2, multiplier=10)
        assert result == 30

    def test_retry_succeeds_immediately(self) -> None:
        """Should return immediately on first success without retrying."""
        call_count = 0

        def works_first_time() -> str:
            nonlocal call_count
            call_count += 1
            return "immediate"

        result = with_retry(works_first_time, max_retries=3, delay=0.01)
        assert result == "immediate"
        assert call_count == 1


class TestFallback:
    """Test the with_fallback function."""

    def test_fallback_used_when_primary_fails(self) -> None:
        """Should use fallback function when primary raises."""
        def primary() -> str:
            raise RuntimeError("Primary crashed")

        def backup() -> str:
            return "fallback result"

        result = with_fallback(primary, backup)
        assert result == "fallback result"

    def test_fallback_primary_succeeds(self) -> None:
        """Should return primary result when it succeeds."""
        def primary() -> str:
            return "primary result"

        def backup() -> str:
            return "should not reach here"

        result = with_fallback(primary, backup)
        assert result == "primary result"

    def test_fallback_both_fail(self) -> None:
        """Should raise the fallback error when both functions fail."""
        def primary() -> None:
            raise RuntimeError("Primary fail")

        def backup() -> None:
            raise ValueError("Backup also fail")

        with pytest.raises(ValueError, match="Backup also fail"):
            with_fallback(primary, backup)

    def test_fallback_passes_args(self) -> None:
        """Should pass arguments to both primary and fallback."""
        def primary(x: int) -> int:
            raise RuntimeError("fail")

        def backup(x: int) -> int:
            return x * 2

        result = with_fallback(primary, backup, 5)
        assert result == 10
