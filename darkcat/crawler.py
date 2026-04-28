"""BFS crawler with per-protocol limits, politeness, topic scoring."""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from darkcat.config import Config
from darkcat.extractor import parse
from darkcat.fetcher import Fetcher, TransportError, TransportUnavailable
from darkcat.protocols import Protocol, classify, normalize
from darkcat.storage import Storage
from darkcat.topic_filter import TopicFilter


log = logging.getLogger("darkcat.crawler")


@dataclass
class CrawlPolicy:
    max_pages: int = 100
    max_depth: int = 2
    follow_clearnet: bool = False
    follow_cross_protocol: bool = True
    score_threshold: float = 0.0
    per_host_limit: int = 25


@dataclass
class CrawlStats:
    fetched: int = 0
    errors: int = 0
    skipped: int = 0
    by_protocol: dict[str, int] = field(default_factory=lambda: defaultdict(int))


# event types: "fetch" | "error" | "skip"
CrawlEvent = Callable[[str, dict], None]


class Crawler:
    def __init__(
        self,
        cfg: Config,
        storage: Storage,
        topic_filter: TopicFilter,
        policy: CrawlPolicy,
    ):
        self.cfg = cfg
        self.storage = storage
        self.filter = topic_filter
        self.policy = policy
        self.fetcher = Fetcher(cfg)
        self.stop_event = threading.Event()

    def stop(self) -> None:
        self.stop_event.set()

    def crawl(self, seeds: Iterable[str], on_event: Optional[CrawlEvent] = None) -> CrawlStats:
        stats = CrawlStats()
        queue: deque[tuple[str, int]] = deque()
        seen: set[str] = set()
        host_counts: dict[str, int] = defaultdict(int)

        def emit(kind: str, **payload):
            if on_event:
                try:
                    on_event(kind, payload)
                except Exception:  # never let a UI bug break the crawl
                    log.exception("on_event callback failed")

        for s in seeds:
            url = normalize(s)
            if url in seen:
                continue
            seen.add(url)
            queue.append((url, 0))

        while queue and stats.fetched < self.policy.max_pages:
            if self.stop_event.is_set():
                break
            url, depth = queue.popleft()
            proto = classify(url)

            if proto == Protocol.CLEARNET and not self.policy.follow_clearnet and depth > 0:
                stats.skipped += 1
                emit("skip", url=url, reason="clearnet")
                continue

            host = (urlparse(url).hostname or "").lower()
            if host_counts[host] >= self.policy.per_host_limit:
                stats.skipped += 1
                emit("skip", url=url, reason="per_host_limit")
                continue
            host_counts[host] += 1

            log.info("[%s] depth=%d %s", proto.value, depth, url)
            try:
                result = self.fetcher.fetch(url)
            except TransportUnavailable as e:
                self.storage.record_error(url, proto.value, f"unavailable: {e}")
                stats.errors += 1
                emit("error", url=url, protocol=proto.value, error=str(e), reason="unavailable")
                continue
            except TransportError as e:
                self.storage.record_error(url, proto.value, str(e))
                stats.errors += 1
                emit("error", url=url, protocol=proto.value, error=str(e), reason="fetch")
                continue

            if result is None:
                stats.errors += 1
                continue

            page = parse(result.url, result.body, result.content_type)
            match = self.filter.score(page.title, page.text)

            self.storage.record_page(
                url=url,
                final_url=result.final_url,
                protocol=proto.value,
                status=result.status,
                title=page.title,
                text=page.text,
                score=match.score,
                topic_hits=json.dumps(match.hits, ensure_ascii=False),
            )
            stats.fetched += 1
            stats.by_protocol[proto.value] += 1
            emit("fetch", url=url, protocol=proto.value, title=page.title,
                 score=match.score, status=result.status, depth=depth)

            self.storage.record_links(url, page.links)

            if depth >= self.policy.max_depth:
                continue
            if not self.filter.empty and match.score < self.policy.score_threshold:
                continue

            for link in page.links:
                if link in seen:
                    continue
                link_proto = classify(link)
                if link_proto == Protocol.UNKNOWN:
                    continue
                if not self.policy.follow_cross_protocol and link_proto != proto:
                    continue
                if link_proto == Protocol.CLEARNET and not self.policy.follow_clearnet:
                    continue
                seen.add(link)
                queue.append((link, depth + 1))

            time.sleep(self.cfg.politeness_delay)

        return stats
