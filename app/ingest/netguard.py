"""Network-level protection for outbound fetches.

The URL allowlist in app.ingest.urls decides whether a name may be fetched.
This module decides whether the address that name resolves to may be
connected to. Both gates are needed, because a hostname on the allowlist can
still resolve to a private address, either through a misconfiguration or
because someone controls a DNS record.

What is rejected, and why each one matters:

* Loopback (127.0.0.0/8, ::1). Reaches services bound to localhost, including
  the application's own admin interface and Adminer.
* Private ranges (10/8, 172.16/12, 192.168/16, fc00::/7). Reaches other hosts
  inside the deployment network.
* Link-local (169.254/16, fe80::/10). Includes the cloud instance metadata
  address, which on an unhardened instance returns credentials.
* Carrier-grade NAT (100.64/10). Includes Alibaba Cloud's metadata address.
* Reserved, multicast, broadcast and unspecified addresses.

DNS rebinding is handled by resolving once, validating every address the name
returns, and then connecting to a validated address rather than to the name.
Without that, a name can pass validation and resolve to something else
microseconds later when the connection is actually opened.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass

# Addresses that return cloud credentials when fetched from inside an
# instance. They fall inside ranges rejected below, and are named explicitly
# so a blocked attempt reports the specific cause in the audit log.
CLOUD_METADATA_ADDRESSES = frozenset(
    {
        "169.254.169.254",   # AWS, Azure, GCP, DigitalOcean, Oracle
        "169.254.170.2",     # AWS ECS task metadata
        "100.100.100.200",   # Alibaba Cloud
        "192.0.0.192",       # Oracle Cloud legacy
        "fd00:ec2::254",     # AWS IMDS over IPv6
    }
)


@dataclass(frozen=True)
class AddressDecision:
    """Whether an address may be connected to."""

    allowed: bool
    reason: str = ""
    # The validated addresses, in resolution order. The caller connects to one
    # of these rather than re-resolving the hostname.
    addresses: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.allowed


def classify_address(raw: str) -> str:
    """Return the reason an address is refused, or an empty string if allowed.

    Written as a sequence of explicit checks rather than one boolean, so that
    a blocked attempt records which rule stopped it.
    """
    try:
        address = ipaddress.ip_address(raw)
    except ValueError:
        return "unparseable_address"

    if raw in CLOUD_METADATA_ADDRESSES:
        return "cloud_metadata_address"

    # An IPv4-mapped IPv6 address such as ::ffff:127.0.0.1 reaches the IPv4
    # address it wraps, so unwrap it first and classify what it really is.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return classify_address(str(address.ipv4_mapped))

    # Specific causes are checked before the general ones. ipaddress treats
    # 0.0.0.0 and 255.255.255.255 as private, so a generic is_private check
    # placed first would report both as "private_address" and lose the more
    # useful reason in the audit log.
    if address.is_unspecified:
        return "unspecified_address"
    if address.is_loopback:
        return "loopback_address"
    if address.is_link_local:
        return "link_local_address"
    if address.is_multicast:
        return "multicast_address"

    if isinstance(address, ipaddress.IPv4Address):
        if address == ipaddress.IPv4Address("255.255.255.255"):
            return "broadcast_address"
        # Carrier-grade NAT. Not covered by is_private, and it contains
        # Alibaba Cloud's metadata service.
        if address in ipaddress.ip_network("100.64.0.0/10"):
            return "carrier_grade_nat_address"
        if address in ipaddress.ip_network("0.0.0.0/8"):
            return "this_network_address"
        # The 6to4 relay range can be used to reach an internal IPv4 address.
        if address in ipaddress.ip_network("192.88.99.0/24"):
            return "6to4_relay_address"

    if isinstance(address, ipaddress.IPv6Address) and address.is_site_local:
        return "site_local_address"

    # The broad catch-alls come last, so they only apply to addresses no
    # specific rule named.
    if address.is_private:
        return "private_address"
    if address.is_reserved:
        return "reserved_address"

    return ""


def resolve_and_validate(
    hostname: str,
    port: int = 443,
    *,
    resolver=socket.getaddrinfo,  # type: ignore[no-untyped-def]
) -> AddressDecision:
    """Resolve ``hostname`` and confirm every address it returns is public.

    Every address is checked, not just the first. A name that returns one
    public and one private address must be refused: which one gets used is
    outside our control, and accepting the name would make the outcome depend
    on resolver ordering.

    ``resolver`` is injectable so tests can supply resolutions without
    depending on real DNS.
    """
    # An IP literal is validated directly. Passing it to a resolver would work,
    # but this makes the intent explicit and avoids a needless lookup.
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        reason = classify_address(hostname)
        if reason:
            return AddressDecision(False, reason)
        return AddressDecision(True, "", (hostname,))

    try:
        infos = resolver(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return AddressDecision(False, "dns_resolution_failed")
    except OSError:
        return AddressDecision(False, "dns_error")

    if not infos:
        return AddressDecision(False, "dns_returned_no_addresses")

    addresses: list[str] = []
    for info in infos:
        sockaddr = info[4]
        raw = str(sockaddr[0])
        reason = classify_address(raw)
        if reason:
            # One bad address refuses the whole name. Accepting the rest would
            # leave the outcome up to resolver ordering.
            return AddressDecision(False, reason)
        if raw not in addresses:
            addresses.append(raw)

    return AddressDecision(True, "", tuple(addresses))
