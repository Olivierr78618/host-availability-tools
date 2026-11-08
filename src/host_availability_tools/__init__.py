"""Host availability probing with short connect timeouts.

This package exposes a single synchronous probe function and the
classification result type it returns.  The design goal is to keep the
surface area small: one call, one result object, three states.
"""

from .core import (
    HostResult,
    REACHABLE,
    UNREACHABLE,
    TIMEOUT,
    probe_hosts,
)

__all__ = [
    "HostResult",
    "REACHABLE",
    "UNREACHABLE",
    "TIMEOUT",
    "probe_hosts",
]
