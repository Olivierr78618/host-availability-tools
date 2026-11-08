# host-availability-tools

Probe a list of host/port pairs with short TCP connect timeouts and get back a
reachable / unreachable / timeout classification for each one.

```python
from host_availability_tools import probe_hosts, REACHABLE

results = probe_hosts([("db.internal", 5432), ("cache.internal", 6379)], timeout=0.25)
for result in results:
    if result.status == REACHABLE:
        print(result.host, result.port, "is up")
    else:
        print(result.host, result.port, "is", result.status, result.detail)
```

## Why this exists

Most availability checks either wait for the OS default connect timeout
(which can be minutes) or require a third-party library.  This package does
neither: it uses `socket.create_connection` with an explicit timeout and
runs the probes concurrently in a thread pool, so a scan of many hosts costs
roughly as long as the slowest single probe rather than the sum of all of
them.  The trade-off is that a probe is a plain TCP connect — it tells you
the port accepted a connection, not that the service behind it is healthy.
That is deliberate: a connect is cheap, dependency-free, and good enough for
the "is this thing listening" question.

## API

`probe_hosts(targets, timeout=0.5, max_workers=None) -> list[HostResult]`

`targets` is any iterable of `(host, port)` pairs.  The return value is a
list of `HostResult` in the same order as the input.  `timeout` is the
per-connect timeout in seconds and must be positive.  `max_workers` defaults
to the number of targets; pass a smaller value to bound concurrency.

`HostResult` is a frozen dataclass with fields `host`, `port`, `status`,
`detail`, and `error`, plus an `ok` property that is true only for
`REACHABLE`.  The `status` is one of the module constants `REACHABLE`,
`UNREACHABLE`, or `TIMEOUT`.  `detail` is the exception class name for
failures and an empty string on success.

## The awkward edge

DNS resolution happens inside the connect attempt, so a hostname that does
not resolve is reported as `UNREACHABLE`, not as a separate error state.
If you need to distinguish "could not resolve" from "connection refused",
inspect `HostResult.error` — a resolution failure surfaces as
`socket.gaierror`.
