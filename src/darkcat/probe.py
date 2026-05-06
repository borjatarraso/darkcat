"""Active probes for system-routed transports.

Yggdrasil (200::/7) and cjdns (fc00::/8) are reachable iff a local
interface holds an address in their respective IPv6 subnet. Lokinet
exposes a TUN named `lokitun*`. Probes are best-effort and Linux-first;
on systems without `/proc/net/if_inet6` or `/sys/class/net` we fall back
to "trust the user" (return True) to preserve the prior behavior.
"""
from __future__ import annotations

import ipaddress
import os
from typing import Iterator


YGG_NET = ipaddress.ip_network("200::/7")
CJDNS_NET = ipaddress.ip_network("fc00::/8")


def _iter_local_ipv6() -> Iterator[ipaddress.IPv6Address]:
    """Yield IPv6 addresses from /proc/net/if_inet6 (Linux)."""
    try:
        fh = open("/proc/net/if_inet6", encoding="ascii")
    except OSError:
        return
    with fh:
        for raw in fh:
            hex_addr = (raw.split() or [""])[0]
            if len(hex_addr) != 32:
                continue
            colon = ":".join(hex_addr[i:i + 4] for i in range(0, 32, 4))
            try:
                yield ipaddress.IPv6Address(colon)
            except ipaddress.AddressValueError:
                continue


def _has_proc_inet6() -> bool:
    return os.path.exists("/proc/net/if_inet6")


def has_ipv6_in(net: ipaddress.IPv6Network) -> bool:
    if not _has_proc_inet6():
        return True   # can't probe → preserve prior "trust the user" default
    return any(addr in net for addr in _iter_local_ipv6())


def yggdrasil_reachable() -> bool:
    return has_ipv6_in(YGG_NET)


def cjdns_reachable() -> bool:
    return has_ipv6_in(CJDNS_NET)


def has_iface_starting_with(prefix: str) -> bool:
    try:
        names = os.listdir("/sys/class/net")
    except OSError:
        return True   # can't probe → preserve prior default
    return any(n.startswith(prefix) for n in names)


def lokinet_reachable() -> bool:
    if not os.path.isdir("/sys/class/net"):
        return True
    return (
        has_iface_starting_with("lokitun")
        or has_iface_starting_with("lokinet")
    )
