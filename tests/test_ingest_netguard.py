"""SSRF protection at the address level.

The crawler follows links found in pages the Canton of Zug publishes, and an
administrator can add a source URL. Neither input is trusted, so the address a
hostname resolves to is validated before a connection is opened.
"""

from __future__ import annotations

import socket

import pytest

from app.ingest.netguard import classify_address, resolve_and_validate


def fake_resolver(addresses: list[str]):  # type: ignore[no-untyped-def]
    """Build a getaddrinfo stand-in returning fixed addresses."""

    def resolver(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        out = []
        for address in addresses:
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            out.append((family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port)))
        return out

    return resolver


class TestClassifyAddress:
    @pytest.mark.parametrize(
        ("address", "reason"),
        [
            ("127.0.0.1", "loopback_address"),
            ("127.1.2.3", "loopback_address"),
            ("::1", "loopback_address"),
            ("10.0.0.5", "private_address"),
            ("172.16.4.9", "private_address"),
            ("192.168.1.1", "private_address"),
            ("fc00::1", "private_address"),
            ("169.254.1.1", "link_local_address"),
            ("fe80::1", "link_local_address"),
            ("224.0.0.1", "multicast_address"),
            ("0.0.0.0", "unspecified_address"),
            ("100.64.0.1", "carrier_grade_nat_address"),
            ("255.255.255.255", "broadcast_address"),
            ("192.88.99.1", "6to4_relay_address"),
        ],
    )
    def test_non_public_addresses_are_refused(self, address: str, reason: str) -> None:
        assert classify_address(address) == reason

    @pytest.mark.parametrize(
        "address",
        ["169.254.169.254", "169.254.170.2", "100.100.100.200", "192.0.0.192"],
    )
    def test_cloud_metadata_addresses_are_named_specifically(self, address: str) -> None:
        """They fall inside rejected ranges anyway, but the cause is worth logging."""
        assert classify_address(address) == "cloud_metadata_address"

    def test_ipv4_mapped_ipv6_is_unwrapped(self) -> None:
        """::ffff:127.0.0.1 reaches 127.0.0.1 and must not pass as IPv6.

        The wrapped address is classified as what it actually is, so the
        metadata address reports as metadata rather than as merely link-local.
        """
        assert classify_address("::ffff:127.0.0.1") == "loopback_address"
        assert classify_address("::ffff:10.0.0.1") == "private_address"
        assert classify_address("::ffff:169.254.169.254") == "cloud_metadata_address"
        assert classify_address("::ffff:8.8.8.8") == ""

    def test_public_addresses_are_allowed(self) -> None:
        for address in ("195.65.100.10", "8.8.8.8", "2001:4860:4860::8888"):
            assert classify_address(address) == "", address

    def test_garbage_is_refused(self) -> None:
        assert classify_address("not-an-address") == "unparseable_address"


class TestResolveAndValidate:
    def test_a_public_resolution_is_allowed(self) -> None:
        decision = resolve_and_validate("www.zug.ch", resolver=fake_resolver(["195.65.100.10"]))
        assert decision.allowed
        assert decision.addresses == ("195.65.100.10",)

    def test_a_name_resolving_to_loopback_is_refused(self) -> None:
        """A hostname on the allowlist can still point at 127.0.0.1."""
        decision = resolve_and_validate("www.zug.ch", resolver=fake_resolver(["127.0.0.1"]))
        assert not decision.allowed
        assert decision.reason == "loopback_address"

    def test_one_bad_address_refuses_the_whole_name(self) -> None:
        """Otherwise the outcome depends on resolver ordering."""
        decision = resolve_and_validate(
            "www.zug.ch", resolver=fake_resolver(["195.65.100.10", "10.0.0.1"])
        )
        assert not decision.allowed
        assert decision.reason == "private_address"

    def test_metadata_address_is_refused(self) -> None:
        decision = resolve_and_validate("meta.test", resolver=fake_resolver(["169.254.169.254"]))
        assert decision.reason == "cloud_metadata_address"

    def test_resolution_failure_is_reported_not_raised(self) -> None:
        def failing(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise socket.gaierror("nope")

        decision = resolve_and_validate("nowhere.invalid", resolver=failing)
        assert not decision.allowed
        assert decision.reason == "dns_resolution_failed"

    def test_empty_resolution_is_refused(self) -> None:
        decision = resolve_and_validate("nowhere.invalid", resolver=fake_resolver([]))
        assert decision.reason == "dns_returned_no_addresses"

    def test_ip_literals_are_validated_without_a_lookup(self) -> None:
        called = {"n": 0}

        def counting(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
            called["n"] += 1
            return []

        assert not resolve_and_validate("127.0.0.1", resolver=counting).allowed
        assert resolve_and_validate("195.65.100.10", resolver=counting).allowed
        assert called["n"] == 0, "an IP literal needs no DNS lookup"

    def test_addresses_are_returned_for_pinning(self) -> None:
        """The caller connects to these, not to the name, which closes rebinding."""
        decision = resolve_and_validate(
            "www.zug.ch", resolver=fake_resolver(["195.65.100.10", "195.65.100.11"])
        )
        assert decision.addresses == ("195.65.100.10", "195.65.100.11")
