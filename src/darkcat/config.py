import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    # Tor SOCKS5
    tor_socks_host: str = "127.0.0.1"
    tor_socks_port: int = 9050
    # Tor control port (for NEWNYM, GETCONF, SETCONF Bridge ...)
    tor_control_port: int = 9051
    tor_control_password: Optional[str] = None
    tor_control_cookie_path: Optional[str] = None
    # Per-host SOCKS auth → distinct circuit per onion host. Tor's
    # IsolateSOCKSAuth flag (default on) treats different (user,pass) pairs
    # as separate circuit-isolation keys.
    tor_stream_isolation: bool = True

    # I2P HTTP proxy
    i2p_http_host: str = "127.0.0.1"
    i2p_http_port: int = 4444
    # Jump-service URLs tried in order when an I2P fetch fails because the
    # host isn't in the local addressbook. {host} = original hostname.
    i2p_jump_services: list = field(default_factory=lambda: [
        "http://notbob.i2p/cgi-bin/jump.cgi?q={host}",
        "http://stats.i2p/cgi-bin/jump.cgi?q={host}",
    ])

    # IPFS gateway
    ipfs_gateway_host: str = "127.0.0.1"
    ipfs_gateway_port: int = 8080
    ipfs_public_gateway: str = "https://ipfs.io"
    use_public_ipfs_gateway: bool = False

    # Hyphanet / Freenet FProxy
    freenet_fproxy_host: str = "127.0.0.1"
    freenet_fproxy_port: int = 8888

    # ZeroNet UI
    zeronet_host: str = "127.0.0.1"
    zeronet_port: int = 43110

    # ENS / Handshake gateways (used as fallback when no local resolver)
    ens_gateway: str = "eth.limo"
    handshake_gateway: str = "hns.is"
    hyper_gateway: str = "hyper.fyi"
    # Local hyperdrive HTTP gateway (Beaker / hypercored) — tried first if reachable.
    hyper_local_gateway: str = "127.0.0.1:4501"

    # Arweave permaweb gateway. ar://<txid> → <base>/<txid>.
    arweave_gateway: str = "https://arweave.net"

    # Networking defaults
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; rv:115.0) Gecko/20100101 Firefox/115.0"
    )
    request_timeout: float = 45.0
    politeness_delay: float = 1.5
    max_response_bytes: int = 4 * 1024 * 1024

    db_path: Path = field(default_factory=lambda: Path.home() / ".darkcat" / "crawl.db")

    # Persistent cookie jar (Netscape format). When set, every HTTP-based
    # transport and the headless renderer attach this jar so authenticated
    # sessions survive across runs. ``None`` disables persistence (per-run
    # cookies still work, just aren't saved).
    cookie_jar_path: Optional[Path] = None

    @property
    def tor_proxies(self) -> dict:
        url = f"socks5h://{self.tor_socks_host}:{self.tor_socks_port}"
        return {"http": url, "https": url}

    def tor_proxies_for(self, host: str) -> dict:
        """Return Tor SOCKS proxies, optionally with per-host stream isolation.

        Tor uses the (username, password) pair on the SOCKS handshake as a
        circuit-isolation key (when IsolateSOCKSAuth is enabled, which is the
        default). Same host → same circuit; different host → new circuit.
        Reduces correlation across the page graph at no perf cost.
        """
        if not self.tor_stream_isolation or not host:
            return self.tor_proxies
        iso = hashlib.sha256(host.encode("utf-8", "replace")).hexdigest()[:16]
        url = (
            f"socks5h://iso:{iso}@{self.tor_socks_host}:{self.tor_socks_port}"
        )
        return {"http": url, "https": url}

    @property
    def i2p_proxies(self) -> dict:
        url = f"http://{self.i2p_http_host}:{self.i2p_http_port}"
        return {"http": url, "https": url}
