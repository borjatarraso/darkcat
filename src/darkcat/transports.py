"""Transport implementations for each darknet / overlay / obscure protocol.

Five flavors of transport:

  HTTP-tunneled (over Tor SOCKS, I2P HTTP, IPFS gateway, FProxy, ZeroNet UI)
  Native socket  (Gemini TLS, Spartan, NEX, Gopher, Gophers, Finger, NNTP)
  System-routed  (Lokinet, GNUnet, Yggdrasil, cjdns, Namecoin, EmerCoin,
                  OpenNIC — relies on a TUN / DNS daemon on the host)
  Gateway        (ENS .eth → eth.limo, Handshake → hns.is, Hyper → hyper.fyi,
                  Unstoppable → unstoppabledomains.com)
  Stub           (DAT, SSB, Briar, Tox, Retroshare, Earthstar, Cabal,
                  Reticulum, bitchat, SimpleX SMP, Session, Berty, Jami,
                  Nostr, Veilid, Nym, Solana — known but require a daemon
                  we cannot speak to from here; fetch raises
                  TransportUnavailable with a helpful hint)
  Gateway        (… plus Arweave: ar://<txid> via arweave_gateway)
  Identifier     (magnet:, ed2k:, acct: — parses the URI and returns a
                  synthetic text/plain body)

Each transport exposes:
  check()  -> bool         daemon reachable / requirements met?
  fetch(url) -> FetchResult  or raises TransportError / TransportUnavailable.
"""
from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests

from darkcat.config import Config
from darkcat.protocols import Protocol


class TransportError(Exception):
    pass


class TransportUnavailable(TransportError):
    """Required local daemon / gateway / configuration not present."""


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    protocol: Protocol


def _tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _socket_request(
    host: str,
    port: int,
    request: bytes,
    *,
    timeout: float,
    max_bytes: int,
    tls_hostname: Optional[str] = None,
    terminator: Optional[bytes] = None,
) -> bytes:
    """Open TCP (optionally wrapped in TLS), send request, drain response.

    If ``terminator`` is provided, stops reading once data ends with it
    (useful for line-oriented protocols like Gopher / NNTP).
    """
    s: socket.socket = socket.create_connection((host, port), timeout=timeout)
    if tls_hostname is not None:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE  # TOFU / pinning is the Gemini norm
        s = ctx.wrap_socket(s, server_hostname=tls_hostname)
    try:
        s.sendall(request)
        data = b""
        while True:
            chunk = s.recv(16 * 1024)
            if not chunk:
                break
            data += chunk
            if len(data) >= max_bytes:
                break
            if terminator and data.endswith(terminator):
                break
        return data
    finally:
        try:
            s.close()
        except OSError:
            pass


# ---- HTTP-based transports --------------------------------------------------

class _HTTPBase:
    name: str = "base"
    protocol: Protocol = Protocol.UNKNOWN

    def __init__(self, cfg: Config, *, cookie_store=None):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers["User-Agent"] = cfg.user_agent
        self.session.headers["Accept"] = "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"
        # Share one CookieStore across all transports so authenticated
        # sessions seen by one fetch are visible to the next. The store is
        # owned by the Fetcher (or CLI), built from cfg.cookie_jar_path.
        self._cookie_store = cookie_store
        if cookie_store is not None:
            cookie_store.attach(self.session)

    def check(self) -> bool:
        return True

    def fetch(self, url: str) -> FetchResult:  # pragma: no cover
        raise NotImplementedError

    def _do_get(self, url: str, *, proxies: Optional[dict] = None) -> FetchResult:
        try:
            resp = self.session.get(
                url,
                proxies=proxies,
                timeout=self.cfg.request_timeout,
                stream=True,
                allow_redirects=True,
            )
        except requests.exceptions.RequestException as e:
            raise TransportError(f"{self.name} request failed: {e}") from e

        body = b""
        for chunk in resp.iter_content(chunk_size=16 * 1024):
            body += chunk
            if len(body) >= self.cfg.max_response_bytes:
                break
        resp.close()
        return FetchResult(
            url=url,
            final_url=resp.url,
            status=resp.status_code,
            content_type=resp.headers.get("Content-Type", ""),
            body=body,
            protocol=self.protocol,
        )


class TorTransport(_HTTPBase):
    name = "tor"
    protocol = Protocol.TOR

    def check(self) -> bool:
        return _tcp_open(self.cfg.tor_socks_host, self.cfg.tor_socks_port)

    def fetch(self, url: str) -> FetchResult:
        if not self.check():
            raise TransportUnavailable(
                f"Tor SOCKS not reachable at {self.cfg.tor_socks_host}:{self.cfg.tor_socks_port}. "
                f"Start tor."
            )
        host = (urlparse(url).hostname or "")
        return self._do_get(url, proxies=self.cfg.tor_proxies_for(host))


class I2PTransport(_HTTPBase):
    name = "i2p"
    protocol = Protocol.I2P

    def check(self) -> bool:
        return _tcp_open(self.cfg.i2p_http_host, self.cfg.i2p_http_port)

    def fetch(self, url: str) -> FetchResult:
        if not self.check():
            raise TransportUnavailable(
                f"I2P HTTP proxy not reachable at {self.cfg.i2p_http_host}:{self.cfg.i2p_http_port}. "
                f"Start i2pd or the I2P router."
            )
        try:
            return self._do_get(url, proxies=self.cfg.i2p_proxies)
        except TransportError as e:
            # Address not in the local addressbook → try jump services.
            jumped = self._jump_resolve(url)
            if jumped and jumped != url:
                return self._do_get(jumped, proxies=self.cfg.i2p_proxies)
            raise

    def _jump_resolve(self, url: str) -> Optional[str]:
        """Look up url's host via configured jump services. Returns a rewritten
        URL with a `.b32.i2p` host, or None if nothing resolves."""
        from urllib.parse import urlparse, urlunparse
        import re as _re
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if not host or host.endswith(".b32.i2p"):
            return None
        b32_rx = _re.compile(r"\b([a-z2-7]{52,56}\.b32\.i2p)\b")
        for tmpl in self.cfg.i2p_jump_services:
            try:
                jump_url = tmpl.format(host=host)
            except Exception:
                continue
            try:
                r = self._do_get(jump_url, proxies=self.cfg.i2p_proxies)
            except TransportError:
                continue
            if not r or not r.body:
                continue
            body = r.body if isinstance(r.body, (bytes, bytearray)) else r.body.encode("utf-8")
            text = body.decode("utf-8", "replace")
            m = b32_rx.search(text)
            if not m:
                continue
            new_netloc = m.group(1)
            if parsed.port:
                new_netloc = f"{new_netloc}:{parsed.port}"
            return urlunparse(parsed._replace(netloc=new_netloc))
        return None


class IPFSTransport(_HTTPBase):
    name = "ipfs"
    protocol = Protocol.IPFS

    def _local_url(self, url: str) -> str:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme in ("ipfs", "ipns"):
            cid = parsed.netloc + parsed.path
            return f"http://{self.cfg.ipfs_gateway_host}:{self.cfg.ipfs_gateway_port}/{scheme}/{cid}"
        return url

    def _public_url(self, url: str) -> str:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        if scheme in ("ipfs", "ipns"):
            cid = parsed.netloc + parsed.path
            return f"{self.cfg.ipfs_public_gateway}/{scheme}/{cid}"
        return url

    def check(self) -> bool:
        return (
            _tcp_open(self.cfg.ipfs_gateway_host, self.cfg.ipfs_gateway_port)
            or self.cfg.use_public_ipfs_gateway
        )

    def fetch(self, url: str) -> FetchResult:
        if _tcp_open(self.cfg.ipfs_gateway_host, self.cfg.ipfs_gateway_port):
            return self._do_get(self._local_url(url))
        if self.cfg.use_public_ipfs_gateway:
            return self._do_get(self._public_url(url))
        raise TransportUnavailable(
            f"IPFS gateway not reachable at {self.cfg.ipfs_gateway_host}:{self.cfg.ipfs_gateway_port}. "
            f"Run `ipfs daemon`, or pass --public-ipfs."
        )


class FreenetTransport(_HTTPBase):
    name = "freenet"
    protocol = Protocol.FREENET

    def _to_fproxy(self, url: str) -> str:
        prefix = "freenet:" if url.lower().startswith("freenet:") else "hyphanet:"
        key = url[len(prefix):]
        return f"http://{self.cfg.freenet_fproxy_host}:{self.cfg.freenet_fproxy_port}/{key}"

    def check(self) -> bool:
        return _tcp_open(self.cfg.freenet_fproxy_host, self.cfg.freenet_fproxy_port)

    def fetch(self, url: str) -> FetchResult:
        if not self.check():
            raise TransportUnavailable(
                f"Hyphanet FProxy not reachable at "
                f"{self.cfg.freenet_fproxy_host}:{self.cfg.freenet_fproxy_port}."
            )
        return self._do_get(self._to_fproxy(url))


class ZeroNetTransport(_HTTPBase):
    name = "zeronet"
    protocol = Protocol.ZERONET

    def _to_local(self, url: str) -> str:
        if url.lower().startswith("zero://"):
            return f"http://{self.cfg.zeronet_host}:{self.cfg.zeronet_port}/{url[len('zero://'):]}"
        return url

    def check(self) -> bool:
        return _tcp_open(self.cfg.zeronet_host, self.cfg.zeronet_port)

    def fetch(self, url: str) -> FetchResult:
        if not self.check():
            raise TransportUnavailable(
                f"ZeroNet not reachable at {self.cfg.zeronet_host}:{self.cfg.zeronet_port}."
            )
        return self._do_get(self._to_local(url))


# ---- System-routed -----------------------------------------------------------

class _DirectViaSystemRouting(_HTTPBase):
    """Daemon configures TUN routing or DNS at OS level — we just fetch."""
    daemon_hint: str = ""

    def check(self) -> bool:
        return True

    def fetch(self, url: str) -> FetchResult:
        try:
            return self._do_get(url)
        except TransportError as e:
            raise TransportUnavailable(
                f"{self.name} fetch failed. {self.daemon_hint} (orig: {e})"
            ) from e


class LokinetTransport(_DirectViaSystemRouting):
    name = "lokinet"
    protocol = Protocol.LOKINET
    daemon_hint = "Run lokinet and ensure DNS routes .loki to it."

    def check(self) -> bool:
        from darkcat.probe import lokinet_reachable
        return lokinet_reachable()


class GNUnetTransport(_DirectViaSystemRouting):
    name = "gnunet"
    protocol = Protocol.GNUNET
    daemon_hint = "Run gnunet-gns and configure the system resolver for .gnu/.zkey."


class YggdrasilTransport(_DirectViaSystemRouting):
    name = "yggdrasil"
    protocol = Protocol.YGGDRASIL
    daemon_hint = "Run yggdrasil; 200::/7 must be routed via its tun interface."

    def check(self) -> bool:
        from darkcat.probe import yggdrasil_reachable
        return yggdrasil_reachable()


class CjdnsTransport(_DirectViaSystemRouting):
    name = "cjdns"
    protocol = Protocol.CJDNS
    daemon_hint = "Run cjdroute; fc00::/8 must be routed via its tun interface."

    def check(self) -> bool:
        from darkcat.probe import cjdns_reachable
        return cjdns_reachable()


class NamecoinTransport(_DirectViaSystemRouting):
    name = "namecoin"
    protocol = Protocol.NAMECOIN
    daemon_hint = (
        "Configure ncdns or use an OpenNIC DNS server that mirrors .bit "
        "(e.g. add 185.121.177.177 to /etc/resolv.conf)."
    )


class EmerCoinTransport(_DirectViaSystemRouting):
    name = "emercoin"
    protocol = Protocol.EMERCOIN
    daemon_hint = (
        "Configure emcDNS, or use an OpenNIC DNS server that mirrors EmerCoin's NVS "
        "for .emc/.lib/.bazar/.coin."
    )


class OpenNICTransport(_DirectViaSystemRouting):
    name = "opennic"
    protocol = Protocol.OPENNIC
    daemon_hint = "Add an OpenNIC DNS server to /etc/resolv.conf (https://servers.opennic.org)."


# ---- Gateway-fallback --------------------------------------------------------

class _GatewayFallback(_HTTPBase):
    """Try direct fetch (for users with a local resolver); on failure rewrite
    the URL to ``<host>.<gateway_host>`` and retry."""
    gateway_host_value: str = ""

    @property
    def gateway_host(self) -> str:
        return self.gateway_host_value

    def _gateway_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return url
        netloc = host + "." + self.gateway_host
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return parsed._replace(scheme="https", netloc=netloc).geturl()

    def fetch(self, url: str) -> FetchResult:
        try:
            return self._do_get(url)
        except TransportError:
            return self._do_get(self._gateway_url(url))


class ENSTransport(_GatewayFallback):
    name = "ens"
    protocol = Protocol.ENS

    @property
    def gateway_host(self) -> str:
        return self.cfg.ens_gateway


class HandshakeTransport(_GatewayFallback):
    name = "handshake"
    protocol = Protocol.HANDSHAKE

    @property
    def gateway_host(self) -> str:
        return self.cfg.handshake_gateway


class HyperTransport(_GatewayFallback):
    name = "hyper"
    protocol = Protocol.HYPER

    @property
    def gateway_host(self) -> str:
        return self.cfg.hyper_gateway

    def _local_url(self, url: str) -> str:
        """Map hyper://<key>/path → http://<local-gw>/<key>/path."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        key = parsed.hostname or ""
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        return f"http://{self.cfg.hyper_local_gateway}/{key}{path}"

    def fetch(self, url: str) -> FetchResult:
        # Prefer a local Beaker / hypercored gateway if it's listening.
        local = (self.cfg.hyper_local_gateway or "").strip()
        if local and ":" in local:
            host, port_s = local.rsplit(":", 1)
            try:
                port = int(port_s)
            except ValueError:
                port = 0
            if port and _tcp_open(host, port):
                try:
                    return self._do_get(self._local_url(url))
                except TransportError:
                    pass  # fall through to public gateway
        return self._do_get(self._gateway_url(url))


class UnstoppableDomainsTransport(_DirectViaSystemRouting):
    """Unstoppable resolves via custom DNS or browser extensions; no widely-usable HTTP gateway."""
    name = "unstoppable"
    protocol = Protocol.UNSTOPPABLE
    daemon_hint = (
        "Install Unstoppable Domains' DNS resolver, or use Cloudflare's "
        "https://1.1.1.1#crypto resolver."
    )


class ClearnetViaTorTransport(_HTTPBase):
    name = "clearnet"
    protocol = Protocol.CLEARNET

    def check(self) -> bool:
        return _tcp_open(self.cfg.tor_socks_host, self.cfg.tor_socks_port)

    def fetch(self, url: str) -> FetchResult:
        if self.check():
            host = (urlparse(url).hostname or "")
            return self._do_get(url, proxies=self.cfg.tor_proxies_for(host))
        return self._do_get(url)


# ---- Native socket transports -----------------------------------------------

class _SocketTransport:
    """Base for protocols that speak their own line-oriented wire format."""
    name = "base"
    protocol = Protocol.UNKNOWN
    default_port = 0
    use_tls = False
    response_terminator: Optional[bytes] = None

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def check(self) -> bool:
        return True

    def _build_request(self, url: str, parsed) -> bytes:  # pragma: no cover
        raise NotImplementedError

    def _parse_response(self, url: str, data: bytes) -> tuple[int, str, bytes]:
        return 200, "text/plain", data

    def fetch(self, url: str) -> FetchResult:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or self.default_port
        if not host:
            raise TransportError(f"{self.name}: missing host in {url}")
        try:
            data = _socket_request(
                host,
                port,
                self._build_request(url, parsed),
                timeout=self.cfg.request_timeout,
                max_bytes=self.cfg.max_response_bytes,
                tls_hostname=host if self.use_tls else None,
                terminator=self.response_terminator,
            )
        except (socket.timeout, OSError, ssl.SSLError) as e:
            raise TransportError(f"{self.name} fetch failed: {e}") from e
        status, ct, body = self._parse_response(url, data)
        return FetchResult(
            url=url, final_url=url, status=status, content_type=ct, body=body,
            protocol=self.protocol,
        )


class GeminiTransport(_SocketTransport):
    name = "gemini"
    protocol = Protocol.GEMINI
    default_port = 1965
    use_tls = True

    def _build_request(self, url: str, parsed) -> bytes:
        return f"{url}\r\n".encode("utf-8")

    def _parse_response(self, url, data):
        header, _, body = data.partition(b"\r\n")
        try:
            parts = header.decode("utf-8", errors="replace").split(" ", 1)
            status = int(parts[0]) if parts and parts[0].isdigit() else 0
            meta = parts[1] if len(parts) > 1 else ""
        except Exception:
            status, meta = 0, ""
        ct = meta if status == 20 else "text/gemini"
        return status, ct, body


class SpartanTransport(_SocketTransport):
    """Spartan: like Gemini but unencrypted; request includes content-length."""
    name = "spartan"
    protocol = Protocol.SPARTAN
    default_port = 300

    def _build_request(self, url: str, parsed) -> bytes:
        host = parsed.hostname or ""
        path = parsed.path or "/"
        return f"{host} {path} 0\r\n".encode("utf-8")

    def _parse_response(self, url, data):
        header, _, body = data.partition(b"\r\n")
        try:
            parts = header.decode("utf-8", errors="replace").split(" ", 1)
            status = int(parts[0]) if parts and parts[0].isdigit() else 0
            meta = parts[1] if len(parts) > 1 else ""
        except Exception:
            status, meta = 0, ""
        ct = meta if status == 2 else "text/gemini"
        return status, ct, body


class NEXTransport(_SocketTransport):
    """NEX: send `<path>\\r\\n`, receive raw body, no headers, no TLS."""
    name = "nex"
    protocol = Protocol.NEX
    default_port = 1900

    def _build_request(self, url: str, parsed) -> bytes:
        path = parsed.path or "/"
        return (path + "\r\n").encode("utf-8")

    def _parse_response(self, url, data):
        return 200, "text/nex", data


class GopherTransport(_SocketTransport):
    name = "gopher"
    protocol = Protocol.GOPHER
    default_port = 70

    def _build_request(self, url: str, parsed) -> bytes:
        path = parsed.path or "/"
        if len(path) >= 2 and path[0] == "/" and path[1] in "0123456789+gIMhT":
            selector = path[2:]
        else:
            selector = path.lstrip("/")
        return (selector + "\r\n").encode("latin-1", errors="replace")

    def _type_char(self, parsed) -> str:
        path = parsed.path or "/"
        if len(path) >= 2 and path[0] == "/" and path[1] in "0123456789+gIMhT":
            return path[1]
        return "1"

    def _parse_response(self, url, data):
        parsed = urlparse(url)
        ct = "text/plain" if self._type_char(parsed) == "0" else "application/gopher-menu"
        return 200, ct, data


class GophersTransport(GopherTransport):
    """Gopher over TLS."""
    name = "gophers"
    protocol = Protocol.GOPHERS
    use_tls = True


class FingerTransport(_SocketTransport):
    name = "finger"
    protocol = Protocol.FINGER
    default_port = 79

    def _build_request(self, url: str, parsed) -> bytes:
        user = parsed.username or ""
        return (user + "\r\n").encode("utf-8")

    def _parse_response(self, url, data):
        return 200, "text/plain", data


class NNTPTransport(_SocketTransport):
    """Minimal NNTP client: list groups, group overview, or single-article fetch."""
    name = "nntp"
    protocol = Protocol.NNTP
    default_port = 119
    response_terminator = b"\r\n.\r\n"

    def fetch(self, url: str) -> FetchResult:
        parsed = urlparse(url)
        host = parsed.hostname or ""
        port = parsed.port or self.default_port
        parts = [p for p in (parsed.path or "").split("/") if p]
        group = parts[0] if parts else ""
        article = parts[1] if len(parts) > 1 else ""
        try:
            sock = socket.create_connection((host, port), timeout=self.cfg.request_timeout)
        except (socket.timeout, OSError) as e:
            raise TransportError(f"nntp fetch failed: {e}") from e
        try:
            banner = sock.recv(4096)
            commands: list[bytes] = []
            if group:
                commands.append(f"GROUP {group}\r\n".encode())
                commands.append(
                    f"ARTICLE {article}\r\n".encode() if article else b"OVER 1-30\r\n"
                )
            else:
                commands.append(b"LIST ACTIVE\r\n")
            commands.append(b"QUIT\r\n")
            for cmd in commands:
                sock.sendall(cmd)
            data = banner
            while True:
                chunk = sock.recv(16 * 1024)
                if not chunk:
                    break
                data += chunk
                if b"\r\n.\r\n" in data or len(data) >= self.cfg.max_response_bytes:
                    break
        finally:
            try:
                sock.close()
            except OSError:
                pass
        return FetchResult(
            url=url, final_url=url, status=200, content_type="text/plain",
            body=data, protocol=Protocol.NNTP,
        )


# ---- WebFinger over HTTPS ---------------------------------------------------

class WebFingerTransport(_HTTPBase):
    """acct:user@host -> https://host/.well-known/webfinger?resource=acct:user@host"""
    name = "webfinger"
    protocol = Protocol.WEBFINGER

    def fetch(self, url: str) -> FetchResult:
        if not url.startswith("acct:"):
            raise TransportError("webfinger: not an acct: URI")
        addr = url[len("acct:"):]
        if "@" not in addr:
            raise TransportError("webfinger: acct: requires user@host")
        _, host = addr.rsplit("@", 1)
        target = f"https://{host}/.well-known/webfinger?resource={url}"
        return self._do_get(target)


# ---- Stub transports (acknowledged but daemon-only) -------------------------

class _StubTransport:
    name = "stub"
    protocol = Protocol.UNKNOWN
    daemon_hint = ""

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def check(self) -> bool:
        return False

    def fetch(self, url: str) -> FetchResult:
        raise TransportUnavailable(
            f"{self.name}:// is not crawlable from a generic HTTP client. {self.daemon_hint}"
        )


class DatTransport(_StubTransport):
    name = "dat"
    protocol = Protocol.DAT
    daemon_hint = "DAT (Beaker) is deprecated; use hyper:// (Hypercore) instead."


class SSBTransport(_StubTransport):
    name = "ssb"
    protocol = Protocol.SSB
    daemon_hint = "Run an SSB pub (Patchwork, ssb-server) and use its local API; ssb:// URIs are not HTTP-fetchable."


class BriarTransport(_StubTransport):
    name = "briar"
    protocol = Protocol.BRIAR
    daemon_hint = "Briar is a mobile mesh messenger; no desktop crawl client exists."


class ToxTransport(_StubTransport):
    name = "tox"
    protocol = Protocol.TOX
    daemon_hint = "Tox is a real-time messaging protocol; use a Tox client (qTox, uTox)."


class RetroshareTransport(_StubTransport):
    name = "retroshare"
    protocol = Protocol.RETROSHARE
    daemon_hint = "Retroshare uses an F2F overlay; run the Retroshare client and open links from there."


class EarthstarTransport(_StubTransport):
    name = "earthstar"
    protocol = Protocol.EARTHSTAR
    daemon_hint = "Earthstar shares are accessed via JS clients; no native HTTP crawl."


class CabalTransport(_StubTransport):
    name = "cabal"
    protocol = Protocol.CABAL
    daemon_hint = "Cabal is a P2P chat protocol; install the cabal client."


class ReticulumTransport(_StubTransport):
    name = "reticulum"
    protocol = Protocol.RETICULUM
    daemon_hint = "Reticulum/LXMF needs the rnsd daemon and an LXMF-aware app (Sideband, Nomad)."


class BitchatTransport(_StubTransport):
    name = "bitchat"
    protocol = Protocol.BITCHAT
    daemon_hint = (
        "bitchat is a Bluetooth-LE proximity mesh chat — no internet, no servers. "
        "Install the bitchat app (iOS/Android/macOS) on a device with BLE; "
        "peers and channels are reachable only within ~30m radio range."
    )


class SimpleXTransport(_StubTransport):
    """SimpleX SMP (Simple Messaging Protocol) — the only chat protocol with
    no user identifiers. Connections are queue-based and can't be enumerated
    from outside, so this is a stub that documents the requirement.
    """
    name = "simplex"
    protocol = Protocol.SIMPLEX
    daemon_hint = (
        "SimpleX SMP queues are pairwise and unaddressable from outside. "
        "Install the SimpleX Chat client (mobile or desktop) and open the "
        "invite link there; smp:// / simplex:// URIs cannot be HTTP-fetched."
    )


class SessionTransport(_StubTransport):
    name = "session"
    protocol = Protocol.SESSION
    daemon_hint = (
        "Session is anonymous messaging routed through the Oxen / Lokinet "
        "service-node network. Install the Session client (mobile or desktop) "
        "and open the session://<id> URI from there."
    )


class BertyTransport(_StubTransport):
    name = "berty"
    protocol = Protocol.BERTY
    daemon_hint = (
        "Berty is offline-first P2P chat over BLE / Wi-Fi-Direct / Tor. "
        "Install the Berty client to open berty://#/... invitation URIs."
    )


class JamiTransport(_StubTransport):
    name = "jami"
    protocol = Protocol.JAMI
    daemon_hint = (
        "Jami (formerly Ring) is distributed SIP/chat with no central server. "
        "Install the Jami client; jami: / ring: URIs reference accounts and "
        "cannot be HTTP-fetched."
    )


class NostrTransport(_StubTransport):
    """nostr: URIs (NIP-21) carry bech32-encoded event/profile/relay refs.
    Fetching them properly means subscribing to relays over WebSocket; we
    document the requirement and leave wire-level support to a future
    transport once relay selection becomes a config concern.
    """
    name = "nostr"
    protocol = Protocol.NOSTR
    daemon_hint = (
        "Nostr events live on relays; resolving nostr:nevent1.../npub1.../... "
        "requires a WebSocket subscription to one or more wss:// relays "
        "(use a Nostr client like Damus, Coracle, Iris, snort, or nostrclient.py)."
    )


class VeilidTransport(_StubTransport):
    name = "veilid"
    protocol = Protocol.VEILID
    daemon_hint = (
        "Veilid is the cDc anonymous P2P framework — nodes exchange data via a "
        "DHT with no addressable hosts. Install veilid-server and a Veilid app "
        "(VeilidChat) to resolve veilid:// / vld0: URIs."
    )


class NymTransport(_StubTransport):
    name = "nym"
    protocol = Protocol.NYM
    daemon_hint = (
        "Nym is a Sphinx-based mixnet (Loopix). Run nym-socks5-client locally "
        "and route HTTP through it (similar to Tor's SOCKS5); nym:// URIs are "
        "not directly fetchable without that proxy."
    )


class SolanaTransport(_StubTransport):
    name = "solana"
    protocol = Protocol.SOLANA
    daemon_hint = "*.sol resolution requires Solana Name Service (SNS) via a SNS-aware client or RPC."


# ---- Arweave permaweb (gateway transport) -----------------------------------

class ArweaveTransport(_HTTPBase):
    """ar://<txid>[/path] → <arweave_gateway>/<txid>[/path].

    Arweave transactions are immutable and content-addressable; the public
    gateway returns the stored payload directly. This is a real fetcher
    (not a stub) because the gateway model works the same way the IPFS
    public gateway does.
    """
    name = "arweave"
    protocol = Protocol.ARWEAVE

    def _to_gateway_url(self, url: str) -> str:
        parsed = urlparse(url)
        # ar://<txid>/path — netloc holds the txid.
        txid = parsed.netloc or parsed.path.lstrip("/")
        rest = ""
        if parsed.netloc and parsed.path:
            rest = parsed.path
        if parsed.query:
            rest = f"{rest}?{parsed.query}"
        base = (self.cfg.arweave_gateway or "").rstrip("/")
        return f"{base}/{txid}{rest}"

    def fetch(self, url: str) -> FetchResult:
        if not url.lower().startswith("ar:"):
            return self._do_get(url)
        return self._do_get(self._to_gateway_url(url))


# ---- Identifier-only URIs ---------------------------------------------------

class MagnetTransport:
    """magnet:?xt=urn:btih:HASH&dn=NAME&tr=TRACKER..."""
    name = "magnet"
    protocol = Protocol.MAGNET

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def check(self) -> bool:
        return True

    def fetch(self, url: str) -> FetchResult:
        if not url.lower().startswith("magnet:?"):
            raise TransportError("magnet: malformed (expected magnet:?...)")
        params = parse_qs(url[len("magnet:?"):])
        lines: list[str] = []
        for xt in params.get("xt", []):
            lines.append(f"info-hash:   {xt}")
        for dn in params.get("dn", []):
            lines.append(f"display:     {dn}")
        for tr in params.get("tr", []):
            lines.append(f"tracker:     {tr}")
        for xs in params.get("xs", []):
            lines.append(f"web-seed:    {xs}")
        for xl in params.get("xl", []):
            lines.append(f"length:      {xl}")
        for so in params.get("so", []):
            lines.append(f"select-only: {so}")
        body = ("\n".join(lines) or "(empty magnet)").encode("utf-8")
        return FetchResult(
            url=url, final_url=url, status=200, content_type="text/plain",
            body=body, protocol=Protocol.MAGNET,
        )


class ED2KTransport:
    """ed2k://|file|name|size|hash|/  or  ed2k://|server|host|port|/"""
    name = "ed2k"
    protocol = Protocol.ED2K

    def __init__(self, cfg: Config):
        self.cfg = cfg

    def check(self) -> bool:
        return True

    def fetch(self, url: str) -> FetchResult:
        if not url.lower().startswith("ed2k://"):
            raise TransportError("ed2k: malformed (expected ed2k://|...|)")
        parts = url[len("ed2k://"):].strip("|").split("|")
        labels = ["kind", "field1", "field2", "field3", "field4", "field5", "field6"]
        if parts and parts[0] == "file":
            labels = ["kind", "name", "size", "hash", "extra1", "extra2"]
        elif parts and parts[0] == "server":
            labels = ["kind", "host", "port"]
        out = []
        for i, p in enumerate(parts):
            label = labels[i] if i < len(labels) else f"part{i}"
            out.append(f"{label}: {p}")
        body = "\n".join(out).encode("utf-8")
        return FetchResult(
            url=url, final_url=url, status=200, content_type="text/plain",
            body=body, protocol=Protocol.ED2K,
        )


# ---- Registry ----------------------------------------------------------------

def build_transports(cfg: Config, *, cookie_store=None) -> dict[Protocol, object]:
    cs = cookie_store
    if cs is None and getattr(cfg, "cookie_jar_path", None) is not None:
        # Auto-load when the user configured a jar but didn't pass one.
        try:
            from darkcat.auth import CookieStore
            cs = CookieStore(cfg.cookie_jar_path)
        except Exception:
            cs = None
    return {
        # HTTP-tunneled — share one CookieStore so a login on one transport
        # is visible to the rest (and persists across runs).
        Protocol.TOR: TorTransport(cfg, cookie_store=cs),
        Protocol.I2P: I2PTransport(cfg, cookie_store=cs),
        Protocol.IPFS: IPFSTransport(cfg, cookie_store=cs),
        Protocol.IPNS: IPFSTransport(cfg, cookie_store=cs),
        Protocol.FREENET: FreenetTransport(cfg, cookie_store=cs),
        Protocol.ZERONET: ZeroNetTransport(cfg, cookie_store=cs),
        # System-routed
        Protocol.LOKINET: LokinetTransport(cfg, cookie_store=cs),
        Protocol.GNUNET: GNUnetTransport(cfg, cookie_store=cs),
        Protocol.YGGDRASIL: YggdrasilTransport(cfg, cookie_store=cs),
        Protocol.CJDNS: CjdnsTransport(cfg, cookie_store=cs),
        Protocol.NAMECOIN: NamecoinTransport(cfg, cookie_store=cs),
        Protocol.EMERCOIN: EmerCoinTransport(cfg, cookie_store=cs),
        Protocol.OPENNIC: OpenNICTransport(cfg, cookie_store=cs),
        # Gateway fallback
        Protocol.ENS: ENSTransport(cfg, cookie_store=cs),
        Protocol.HANDSHAKE: HandshakeTransport(cfg, cookie_store=cs),
        Protocol.HYPER: HyperTransport(cfg, cookie_store=cs),
        Protocol.UNSTOPPABLE: UnstoppableDomainsTransport(cfg, cookie_store=cs),
        # Native socket
        Protocol.GEMINI: GeminiTransport(cfg),
        Protocol.SPARTAN: SpartanTransport(cfg),
        Protocol.NEX: NEXTransport(cfg),
        Protocol.GOPHER: GopherTransport(cfg),
        Protocol.GOPHERS: GophersTransport(cfg),
        Protocol.FINGER: FingerTransport(cfg),
        Protocol.NNTP: NNTPTransport(cfg),
        # Discovery / well-known
        Protocol.WEBFINGER: WebFingerTransport(cfg, cookie_store=cs),
        # Stubs (raise TransportUnavailable with hint)
        Protocol.DAT: DatTransport(cfg),
        Protocol.SSB: SSBTransport(cfg),
        Protocol.BRIAR: BriarTransport(cfg),
        Protocol.TOX: ToxTransport(cfg),
        Protocol.RETROSHARE: RetroshareTransport(cfg),
        Protocol.EARTHSTAR: EarthstarTransport(cfg),
        Protocol.CABAL: CabalTransport(cfg),
        Protocol.RETICULUM: ReticulumTransport(cfg),
        Protocol.BITCHAT: BitchatTransport(cfg),
        Protocol.SIMPLEX: SimpleXTransport(cfg),
        Protocol.SESSION: SessionTransport(cfg),
        Protocol.BERTY: BertyTransport(cfg),
        Protocol.JAMI: JamiTransport(cfg),
        Protocol.NOSTR: NostrTransport(cfg),
        Protocol.VEILID: VeilidTransport(cfg),
        Protocol.NYM: NymTransport(cfg),
        Protocol.SOLANA: SolanaTransport(cfg),
        # Gateway HTTP (real fetcher, not stub)
        Protocol.ARWEAVE: ArweaveTransport(cfg, cookie_store=cs),
        # Identifier-only
        Protocol.MAGNET: MagnetTransport(cfg),
        Protocol.ED2K: ED2KTransport(cfg),
        # Fallback
        Protocol.CLEARNET: ClearnetViaTorTransport(cfg, cookie_store=cs),
    }
