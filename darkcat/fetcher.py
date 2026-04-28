from __future__ import annotations

from typing import Optional

from darkcat.config import Config
from darkcat.protocols import Protocol, classify, normalize
from darkcat.transports import (
    FetchResult,
    TransportError,
    TransportUnavailable,
    build_transports,
)


class Fetcher:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.transports = build_transports(cfg)

    def protocol_for(self, url: str) -> Protocol:
        return classify(normalize(url))

    def status(self) -> dict[Protocol, bool]:
        return {p: t.check() for p, t in self.transports.items()}

    def fetch(self, url: str) -> Optional[FetchResult]:
        url = normalize(url)
        proto = classify(url)
        transport = self.transports.get(proto)
        if transport is None:
            raise TransportError(f"No transport for protocol {proto}")
        return transport.fetch(url)


__all__ = ["Fetcher", "FetchResult", "TransportError", "TransportUnavailable"]
