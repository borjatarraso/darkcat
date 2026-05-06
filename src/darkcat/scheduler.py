"""Scheduled re-crawl runner.

Provides the glue between persisted schedules (``schedules`` table) and the
:class:`darkcat.crawler.Crawler`. The CLI subcommand ``darkcat schedule``
manages rows; ``darkcat schedule run-due`` (and the daemon-mode loop) calls
:func:`run_due` to fire any schedule whose ``next_run_at`` is in the past.

Each schedule is a tuple of (seeds, topics, policy-knobs, interval). On a
successful run we record the stats JSON and bump ``next_run_at = now +
interval``; on error we still reschedule, with the error stored in
``last_status`` so ``schedule list`` shows it.

Design notes:

* The runner is single-process; concurrent runs are handled by the
  ``last_run_at`` window inside SQLite plus the busy-timeout. Two darkcat
  processes started simultaneously will sometimes double-fire a schedule —
  acceptable for re-crawls (writes are idempotent on URL).
* ``policy_json`` stores only the fields a user actually overrode at
  ``schedule add`` time. Defaults come from :class:`CrawlPolicy`.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict
from typing import Callable, Iterable, Optional

from darkcat.config import Config
from darkcat.crawler import Crawler, CrawlPolicy, CrawlStats
from darkcat.storage import Storage
from darkcat.topic_filter import TopicFilter


log = logging.getLogger("darkcat.scheduler")


# Knobs we let users override per-schedule. Anything not listed gets the
# CrawlPolicy default at run time.
POLICY_KEYS = (
    "max_pages", "max_depth", "follow_clearnet", "follow_cross_protocol",
    "score_threshold", "per_host_limit", "backoff_max_delay", "newnym_after",
)


def encode_policy(policy: CrawlPolicy) -> str:
    """Serialize the policy fields we persist. We round-trip through asdict
    rather than __dict__ so dataclass defaults stay in sync if a field is
    added later."""
    raw = asdict(policy)
    return json.dumps({k: raw.get(k) for k in POLICY_KEYS}, ensure_ascii=False)


def decode_policy(blob: Optional[str]) -> CrawlPolicy:
    if not blob:
        return CrawlPolicy()
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return CrawlPolicy()
    kw = {k: v for k, v in data.items() if k in POLICY_KEYS and v is not None}
    return CrawlPolicy(**kw)


def run_schedule(
    cfg: Config,
    storage: Storage,
    name: str,
    *,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> Optional[CrawlStats]:
    """Run a single schedule by name. Returns the CrawlStats on success."""
    row = storage.get_schedule(name)
    if row is None:
        log.warning("schedule %r not found", name)
        return None

    try:
        seeds = json.loads(row["seeds_json"])
    except json.JSONDecodeError:
        seeds = []
    if not seeds:
        storage.mark_schedule_run(name, status="error: empty seeds")
        return None

    topics = json.loads(row["topics_json"]) if row["topics_json"] else []
    policy = decode_policy(row["policy_json"])
    tf = TopicFilter(topics)
    crawler = Crawler(cfg, storage, tf, policy)
    started = time.time()
    try:
        stats = crawler.crawl(seeds, on_event=on_event)
        storage.mark_schedule_run(
            name,
            status="ok",
            stats_json=json.dumps({
                "fetched": stats.fetched,
                "errors": stats.errors,
                "skipped": stats.skipped,
                "by_protocol": dict(stats.by_protocol),
                "elapsed": round(time.time() - started, 2),
            }, ensure_ascii=False),
        )
        return stats
    except Exception as e:
        log.exception("schedule %r failed", name)
        storage.mark_schedule_run(name, status=f"error: {e!s}"[:500])
        return None
    finally:
        try:
            crawler.fetcher.save_cookies()
        except Exception:
            pass
        try:
            crawler.close()
        except Exception:
            pass


def run_due(
    cfg: Config,
    storage: Storage,
    *,
    on_event: Optional[Callable[[str, dict], None]] = None,
    on_schedule_start: Optional[Callable[[str], None]] = None,
    on_schedule_end: Optional[Callable[[str, Optional[CrawlStats]], None]] = None,
) -> int:
    """Run every schedule whose ``next_run_at`` has passed. Returns count."""
    due = storage.due_schedules()
    n = 0
    for row in due:
        name = row["name"]
        if on_schedule_start:
            try:
                on_schedule_start(name)
            except Exception:
                log.exception("on_schedule_start failed")
        stats = run_schedule(cfg, storage, name, on_event=on_event)
        if on_schedule_end:
            try:
                on_schedule_end(name, stats)
            except Exception:
                log.exception("on_schedule_end failed")
        n += 1
    return n


def loop_forever(
    cfg: Config,
    storage: Storage,
    *,
    tick_seconds: float = 30.0,
    stop_event=None,
    on_event: Optional[Callable[[str, dict], None]] = None,
    on_schedule_start: Optional[Callable[[str], None]] = None,
    on_schedule_end: Optional[Callable[[str, Optional[CrawlStats]], None]] = None,
    on_idle: Optional[Callable[[], None]] = None,
) -> None:
    """Run the scheduler as a daemon: poll every ``tick_seconds`` and fire
    anything due. Stops cleanly when ``stop_event`` (a ``threading.Event``) is
    set or on Ctrl-C."""
    log.info("scheduler loop starting (tick=%ss)", tick_seconds)
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break
            try:
                run_due(
                    cfg, storage,
                    on_event=on_event,
                    on_schedule_start=on_schedule_start,
                    on_schedule_end=on_schedule_end,
                )
            except Exception:
                log.exception("scheduler tick failed")
            if on_idle:
                try:
                    on_idle()
                except Exception:
                    pass
            # Use Event.wait() if we have one — that returns True the moment
            # stop is signalled, so SIGINT/SIGTERM stop the loop instantly
            # instead of waiting up to `tick_seconds` for the next slice.
            if stop_event is not None:
                if stop_event.wait(tick_seconds):
                    break
            else:
                time.sleep(tick_seconds)
    except KeyboardInterrupt:
        log.info("scheduler loop interrupted by user")


__all__ = [
    "POLICY_KEYS", "encode_policy", "decode_policy",
    "run_schedule", "run_due", "loop_forever",
]
