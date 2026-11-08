"""Core probing logic for host-availability-tools.

The implementation deliberately uses only the standard library.  A TCP
connect is attempted for each host/port pair with a per-attempt timeout.
Because the caller may want to probe many hosts without waiting for the
slowest one to time out, the probes run in a thread pool and the overall
wall-clock cost is bounded by the slowest single probe rather than the
sum of all probes.

The three outcomes are:

* ``REACHABLE``   -- the TCP connect succeeded.
* ``UNREACHABLE`` -- the connect failed with a connection error (refused,
  reset, host unreachable, DNS failure, etc.).
* ``TIMEOUT``     -- the connect did not complete within the timeout.

DNS resolution is part of the connect attempt, so a name that cannot be
resolved is reported as ``UNREACHABLE`` rather than a separate state.
That keeps the result set closed and easy to reason about.
"""

from __future__ import annotations

import socket
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

REACHABLE = "reachable"
UNREACHABLE = "unreachable"
TIMEOUT = "timeout"

_VALID_STATUSES = frozenset({REACHABLE, UNREACHABLE, TIMEOUT})


@dataclass(frozen=True)
class HostResult:
    """Outcome of probing a single host/port pair.

    ``status`` is one of :data:`REACHABLE`, :data:`UNREACHABLE`, or
    :data:`TIMEOUT`.  ``detail`` carries a short human-readable reason
    (the exception class name for failures, an empty string on success).
    ``error`` is the original exception when one occurred, which is useful
    for logging without losing the classification.
    """

    host: str
    port: int
    status: str
    detail: str = ""
    error: BaseException | None = None

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"unknown status: {self.status!r}")
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise TypeError("port must be an int")
        if not 0 <= self.port <= 65535:
            raise ValueError(f"port out of range: {self.port!r}")

    @property
    def ok(self) -> bool:
        """True only when the host was reachable."""

        return self.status == REACHABLE


HostPort = Tuple[str, int]


def _normalise_targets(targets: Iterable[HostPort]) -> List[HostPort]:
    """Materialise and validate the input sequence.

    Accepting any iterable is convenient, but generators can only be
    consumed once; the thread pool needs to iterate the collection
    multiple times, so we snapshot it here.
    """

    normalised: List[HostPort] = []
    for item in targets:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise TypeError(f"target must be a (host, port) pair, got {item!r}")
        host, port = item
        if not isinstance(host, str) or not host:
            raise ValueError(f"host must be a non-empty string, got {host!r}")
        if not isinstance(port, int) or isinstance(port, bool):
            raise TypeError(f"port must be an int, got {port!r}")
        if not 0 <= port <= 65535:
            raise ValueError(f"port out of range: {port!r}")
        normalised.append((host, port))
    return normalised


def _probe_one(host: str, port: int, timeout: float) -> HostResult:
    """Attempt a single TCP connect and classify the outcome.

    ``socket.create_connection`` already distinguishes a timeout from
    other OSError subclasses, so the classification is a direct mapping
    of the exception type.  Everything that is not a timeout is treated
    as unreachable; that includes DNS failures, which surface as
    ``socket.gaierror`` (a subclass of ``OSError``).
    """

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return HostResult(host=host, port=port, status=REACHABLE)
    except socket.timeout as exc:
        return HostResult(
            host=host,
            port=port,
            status=TIMEOUT,
            detail=type(exc).__name__,
            error=exc,
        )
    except OSError as exc:
        return HostResult(
            host=host,
            port=port,
            status=UNREACHABLE,
            detail=type(exc).__name__,
            error=exc,
        )


def probe_hosts(
    targets: Iterable[HostPort],
    timeout: float = 0.5,
    max_workers: int | None = None,
) -> List[HostResult]:
    """Probe every (host, port) pair and return results in input order.

    ``timeout`` is the per-connect timeout in seconds.  Short values are
    the point of the library: a caller scanning a subnet wants a fast
    answer, not a correct-but-slow one.

    ``max_workers`` defaults to the number of targets (capped at a
    sensible minimum of 1) so that a small list does not pay for a large
    pool.  Passing an explicit value is useful when probing thousands of
    hosts and you want to bound resource usage.

    The returned list is always the same length as the input and in the
    same order, which makes it easy to zip against the original targets.
    """

    if timeout <= 0:
        raise ValueError("timeout must be positive")

    pairs = _normalise_targets(targets)
    if not pairs:
        return []

    if max_workers is None:
        workers = max(1, len(pairs))
    else:
        if max_workers < 1:
            raise ValueError("max_workers must be at least 1")
        workers = max_workers

    # A thread pool is the simplest way to get concurrent connects without
    # pulling in asyncio; each worker blocks on a syscall, so threads map
    # cleanly onto the work and the GIL is not a bottleneck.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(_probe_one, host, port, timeout) for host, port in pairs
        ]
        return [future.result() for future in futures]
