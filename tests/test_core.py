"""Tests for host_availability_tools.core.

These tests avoid real network access.  They exercise the classification
logic by monkey-patching ``socket.create_connection`` with a fake that
raises the exact exception types the implementation handles.  That keeps
the suite deterministic and runnable in a sandbox with no network.
"""

import socket
import unittest
from unittest import mock

from host_availability_tools import (
    HostResult,
    REACHABLE,
    UNREACHABLE,
    TIMEOUT,
    probe_hosts,
)


class FakeSocket:
    """Minimal context manager standing in for a connected socket."""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class ProbeHostsTests(unittest.TestCase):
    def test_reachable_when_connect_succeeds(self):
        with mock.patch(
            "host_availability_tools.core.socket.create_connection",
            return_value=FakeSocket(),
        ):
            results = probe_hosts([("host-a", 80)])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, REACHABLE)
        self.assertTrue(results[0].ok)
        self.assertEqual(results[0].host, "host-a")
        self.assertEqual(results[0].port, 80)

    def test_unreachable_on_connection_refused(self):
        with mock.patch(
            "host_availability_tools.core.socket.create_connection",
            side_effect=ConnectionRefusedError("refused"),
        ):
            results = probe_hosts([("host-b", 22)])
        self.assertEqual(results[0].status, UNREACHABLE)
        self.assertFalse(results[0].ok)
        self.assertEqual(results[0].detail, "ConnectionRefusedError")

    def test_unreachable_on_dns_failure(self):
        # gaierror is an OSError subclass and should be classified as
        # unreachable, not timeout.
        with mock.patch(
            "host_availability_tools.core.socket.create_connection",
            side_effect=socket.gaierror("name not known"),
        ):
            results = probe_hosts([("no-such-host.invalid", 443)])
        self.assertEqual(results[0].status, UNREACHABLE)
        self.assertEqual(results[0].detail, "gaierror")

    def test_timeout_classified_separately(self):
        with mock.patch(
            "host_availability_tools.core.socket.create_connection",
            side_effect=socket.timeout("timed out"),
        ):
            results = probe_hosts([("host-c", 8080)], timeout=0.01)
        self.assertEqual(results[0].status, TIMEOUT)
        self.assertEqual(results[0].detail, "TimeoutError")

    def test_results_preserve_input_order(self):
        def fake(addr, timeout=None):
            host, _port = addr
            if host == "first":
                return FakeSocket()
            if host == "second":
                raise ConnectionRefusedError("nope")
            raise socket.timeout("slow")

        with mock.patch(
            "host_availability_tools.core.socket.create_connection",
            side_effect=fake,
        ):
            results = probe_hosts(
                [("first", 1), ("second", 2), ("third", 3)],
                max_workers=3,
            )
        self.assertEqual([r.host for r in results], ["first", "second", "third"])
        self.assertEqual([r.status for r in results], [REACHABLE, UNREACHABLE, TIMEOUT])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(probe_hosts([]), [])

    def test_accepts_generator_once(self):
        def gen():
            yield ("host-d", 53)

        with mock.patch(
            "host_availability_tools.core.socket.create_connection",
            return_value=FakeSocket(),
        ):
            results = probe_hosts(gen())
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, REACHABLE)

    def test_rejects_bad_target_shapes(self):
        with self.assertRaises(TypeError):
            probe_hosts(["host-e"])
        with self.assertRaises(TypeError):
            probe_hosts([("host-e", "80")])
        with self.assertRaises(ValueError):
            probe_hosts([("", 80)])
        with self.assertRaises(ValueError):
            probe_hosts([("host-e", 70000)])

    def test_rejects_non_positive_timeout(self):
        with self.assertRaises(ValueError):
            probe_hosts([("host-f", 80)], timeout=0)
        with self.assertRaises(ValueError):
            probe_hosts([("host-f", 80)], timeout=-1)

    def test_rejects_bad_max_workers(self):
        with self.assertRaises(ValueError):
            probe_hosts([("host-g", 80)], max_workers=0)

    def test_host_result_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            HostResult(host="h", port=80, status="maybe")

    def test_host_result_ok_property(self):
        self.assertTrue(HostResult("h", 1, REACHABLE).ok)
        self.assertFalse(HostResult("h", 1, UNREACHABLE).ok)
        self.assertFalse(HostResult("h", 1, TIMEOUT).ok)


if __name__ == "__main__":
    unittest.main()
