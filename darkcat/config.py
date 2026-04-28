from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # Tor SOCKS5
    tor_socks_host: str = "127.0.0.1"
    tor_socks_port: int = 9050

    # I2P HTTP proxy
    i2p_http_host: str = "127.0.0.1"
    i2p_http_port: int = 4444

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

    # Networking defaults
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; rv:115.0) Gecko/20100101 Firefox/115.0"
    )
    request_timeout: float = 45.0
    politeness_delay: float = 1.5
    max_response_bytes: int = 4 * 1024 * 1024

    db_path: Path = field(default_factory=lambda: Path.home() / ".darkcat" / "crawl.db")

    @property
    def tor_proxies(self) -> dict:
        url = f"socks5h://{self.tor_socks_host}:{self.tor_socks_port}"
        return {"http": url, "https": url}

    @property
    def i2p_proxies(self) -> dict:
        url = f"http://{self.i2p_http_host}:{self.i2p_http_port}"
        return {"http": url, "https": url}
