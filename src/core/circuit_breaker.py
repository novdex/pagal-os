"""Circuit Breaker — prevents cascading failures in LLM and tool calls.

Tracks consecutive failures per service and trips the breaker when the
failure threshold is exceeded. While tripped, calls fail fast without
actually invoking the service, giving it time to recover.

States:
  CLOSED   → normal operation, failures counted
  OPEN     → breaker tripped, calls fail fast
  HALF_OPEN → after recovery_timeout, allow one probe call
"""

import logging
import threading
import time
from enum import Enum
from typing import Any

logger = logging.getLogger("pagal_os")


class _State(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Per-service circuit breaker with configurable thresholds.

    Args:
        name: Identifier for the service (e.g. "llm", "tool:search_web").
        failure_threshold: Consecutive failures before tripping.
        recovery_timeout: Seconds to wait before probing recovery.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout

        self._state = _State.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        """Return current breaker state as a string."""
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state.value

    def _maybe_transition_to_half_open(self) -> None:
        """Transition from OPEN → HALF_OPEN if recovery_timeout has elapsed."""
        if self._state == _State.OPEN:
            elapsed = time.time() - self._last_failure_time
            if elapsed >= self.recovery_timeout:
                self._state = _State.HALF_OPEN

    def allow_request(self) -> bool:
        """Check whether a request is allowed through the breaker.

        Returns True if the call should proceed, False if it should fail fast.
        """
        with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == _State.CLOSED:
                return True
            if self._state == _State.HALF_OPEN:
                return True  # Allow probe
            # OPEN — fail fast
            return False

    def record_success(self) -> None:
        """Record a successful call — resets the breaker to CLOSED."""
        with self._lock:
            self._failure_count = 0
            if self._state != _State.CLOSED:
                logger.info("Circuit breaker '%s' recovered → CLOSED", self.name)
            self._state = _State.CLOSED

    def record_failure(self) -> None:
        """Record a failed call — may trip the breaker."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == _State.HALF_OPEN:
                # Probe failed — re-open
                self._state = _State.OPEN
                logger.warning("Circuit breaker '%s' probe failed → OPEN", self.name)
            elif self._failure_count >= self.failure_threshold:
                self._state = _State.OPEN
                logger.warning(
                    "Circuit breaker '%s' tripped after %d failures → OPEN (recovery in %ds)",
                    self.name, self._failure_count, self.recovery_timeout,
                )


# ---------------------------------------------------------------------------
# Global breaker registry
# ---------------------------------------------------------------------------

_breakers: dict[str, CircuitBreaker] = {}
_registry_lock = threading.Lock()


def get_breaker(
    name: str,
    failure_threshold: int = 5,
    recovery_timeout: float = 60.0,
) -> CircuitBreaker:
    """Get or create a circuit breaker for the named service.

    Args:
        name: Service identifier (e.g. "llm", "tool:run_shell").
        failure_threshold: Consecutive failures to trip.
        recovery_timeout: Seconds before probing recovery.

    Returns:
        The CircuitBreaker instance.
    """
    with _registry_lock:
        if name not in _breakers:
            _breakers[name] = CircuitBreaker(name, failure_threshold, recovery_timeout)
        return _breakers[name]


def get_all_breaker_states() -> dict[str, dict[str, Any]]:
    """Snapshot of all circuit breaker states (for diagnostics)."""
    with _registry_lock:
        return {
            name: {
                "state": cb.state,
                "failure_count": cb._failure_count,
                "failure_threshold": cb.failure_threshold,
                "recovery_timeout": cb.recovery_timeout,
            }
            for name, cb in _breakers.items()
        }
