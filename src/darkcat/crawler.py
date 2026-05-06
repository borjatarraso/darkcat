"""BFS crawler with per-protocol limits, politeness, topic scoring."""
from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from darkcat.blocklist import Blocklist
from darkcat.config import Config
from darkcat.encoded import extract_encoded_links
from darkcat.extractor import parse
from darkcat.fetcher import Fetcher, TransportError, TransportUnavailable
from darkcat.politeness import HostBackoff, TorRotator
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
    # Adaptive politeness — exponential backoff per host on consecutive errors.
    backoff_max_delay: float = 60.0
    # Reactive Tor circuit rotation — fire NEWNYM after this many consecutive
    # failures on the same .onion host. ``None`` disables rotation.
    newnym_after: Optional[int] = 3


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
        blocklist: Optional[Blocklist] = None,
        renderer=None,
    ):
        self.cfg = cfg
        self.storage = storage
        self.filter = topic_filter
        self.policy = policy
        self.blocklist = blocklist
        self.fetcher = Fetcher(cfg)
        # Optional darkcat.render.Renderer — when set, JS-renderable URLs go
        # through Chromium first. Plain transport remains the fallback when
        # rendering fails (timeout, missing deps, non-renderable proto).
        self.renderer = renderer
        self.stop_event = threading.Event()
        # Adaptive politeness state — created fresh per crawler instance.
        self.backoff = HostBackoff(
            base_delay=cfg.politeness_delay,
            max_delay=policy.backoff_max_delay,
        )
        self.rotator: Optional[TorRotator] = None
        if policy.newnym_after is not None:
            self.rotator = TorRotator(
                cfg, newnym_after=policy.newnym_after, enabled=True
            )

    def stop(self) -> None:
        self.stop_event.set()

    def close(self) -> None:
        """Tear down long-lived resources (Tor control connection)."""
        if self.rotator is not None:
            self.rotator.close()

    def crawl(self, seeds: Iterable[str], on_event: Optional[CrawlEvent] = None) -> CrawlStats:
        stats = CrawlStats()
        queue: deque[tuple[str, int]] = deque()
        seen: set[str] = set()
        host_counts: dict[str, int] = defaultdict(int)

        def emit(kind: str, **payload):
            if on_event:
                try:
                    on_event(kind, payload)
                except (KeyboardInterrupt, SystemExit):
                    # Propagate cooperative-cancellation signals — don't let
                    # the crawl swallow a Ctrl+C or interpreter shutdown.
                    raise
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

            if self.blocklist and not self.blocklist.is_empty:
                rule = self.blocklist.reason_for_url(url)
                if rule:
                    self.storage.record_block(url, rule)
                    stats.skipped += 1
                    emit("skip", url=url, reason=f"blocklist:{rule}")
                    continue

            log.info("[%s] depth=%d %s", proto.value, depth, url)
            # Adaptive politeness: if this host has been failing, sleep the
            # backoff before we hit it again.
            self.backoff.wait(host)
            result = None
            if self.renderer is not None:
                try:
                    from darkcat.render import is_renderable
                    if is_renderable(proto):
                        result = self.renderer.render(url)
                except Exception as e:
                    log.warning("render failed for %s — falling back: %s", url, e)
                    result = None
            fetch_error: Optional[Exception] = None
            try:
                if result is None:
                    result = self.fetcher.fetch(url)
            except TransportUnavailable as e:
                self.storage.record_error(url, proto.value, f"unavailable: {e}")
                stats.errors += 1
                emit("error", url=url, protocol=proto.value, error=str(e), reason="unavailable")
                fetch_error = e
            except TransportError as e:
                self.storage.record_error(url, proto.value, str(e))
                stats.errors += 1
                emit("error", url=url, protocol=proto.value, error=str(e), reason="fetch")
                fetch_error = e

            if fetch_error is not None or result is None:
                if fetch_error is None:
                    stats.errors += 1
                # Account the failure: bump backoff, maybe trigger NEWNYM.
                self.backoff.failure(host)
                if self.rotator is not None:
                    fired = self.rotator.on_failure(host)
                    if fired:
                        emit("newnym", host=host, protocol=proto.value)
                        # NEWNYM only takes effect for *new* circuits; reset
                        # this host's backoff so the next attempt isn't penalized.
                        self.backoff.success(host)
                continue

            # Fetch succeeded — clear the streak.
            self.backoff.success(host)
            if self.rotator is not None:
                self.rotator.on_success(host)

            page = parse(result.url, result.body, result.content_type)
            # Second-pass: rescue URLs hidden in JS strings, base64 blobs,
            # ROT13. Merge with the parser's hyperlink list (deduped).
            try:
                body_text = result.body.decode("utf-8", "replace") \
                    if isinstance(result.body, (bytes, bytearray)) else (result.body or "")
            except Exception:
                body_text = ""
            extra = extract_encoded_links(body_text)
            if extra:
                seen_links = set(page.links)
                for u in extra:
                    if u not in seen_links:
                        seen_links.add(u)
                        page.links.append(u)

            if self.blocklist and self.blocklist.hashes:
                ch = Blocklist.hash_text(page.text)
                rule = self.blocklist.reason_for_hash(ch)
                if rule:
                    self.storage.record_block(url, rule)
                    stats.skipped += 1
                    emit("skip", url=url, reason=f"blocklist:{rule}")
                    continue

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

            # Politeness pause between pages — interruptible so Stop takes
            # effect immediately instead of blocking on a multi-second sleep.
            # Event.wait() returns True the moment .set() is called.
            if self.cfg.politeness_delay > 0:
                if self.stop_event.wait(self.cfg.politeness_delay):
                    break

        return stats
