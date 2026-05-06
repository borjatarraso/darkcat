"""SQLite storage for crawl results."""
from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS pages (
    url           TEXT PRIMARY KEY,
    final_url     TEXT,
    protocol      TEXT,
    status        INTEGER,
    title         TEXT,
    text          TEXT,
    score         REAL DEFAULT 0,
    topic_hits    TEXT,
    fetched_at    REAL,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_pages_protocol ON pages(protocol);
CREATE INDEX IF NOT EXISTS idx_pages_score ON pages(score DESC);

CREATE TABLE IF NOT EXISTS links (
    src           TEXT,
    dst           TEXT,
    PRIMARY KEY (src, dst)
);
CREATE INDEX IF NOT EXISTS idx_links_dst ON links(dst);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    url, title, text, content='pages', content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, url, title, text)
    VALUES (new.rowid, new.url, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS pages_au AFTER UPDATE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, url, title, text)
    VALUES('delete', old.rowid, old.url, old.title, old.text);
    INSERT INTO pages_fts(rowid, url, title, text)
    VALUES (new.rowid, new.url, new.title, new.text);
END;
CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, url, title, text)
    VALUES('delete', old.rowid, old.url, old.title, old.text);
END;

CREATE TABLE IF NOT EXISTS findings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    protocol    TEXT NOT NULL,
    category    TEXT NOT NULL,
    sample      TEXT NOT NULL,
    digest      TEXT NOT NULL,
    target      TEXT,
    confidence  REAL DEFAULT 0,
    line_no     INTEGER,
    found_at    REAL,
    UNIQUE(url, category, digest)
);
CREATE INDEX IF NOT EXISTS idx_findings_category ON findings(category);
CREATE INDEX IF NOT EXISTS idx_findings_target   ON findings(target);
CREATE INDEX IF NOT EXISTS idx_findings_url      ON findings(url);

CREATE TABLE IF NOT EXISTS watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target      TEXT,
    category    TEXT,
    sample      TEXT,
    is_regex    INTEGER DEFAULT 0,
    sink        TEXT NOT NULL,
    note        TEXT,
    created_at  REAL,
    UNIQUE(target, category, sample, sink)
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    watch_id    INTEGER NOT NULL,
    url         TEXT NOT NULL,
    digest      TEXT NOT NULL,
    sink_status TEXT,
    fired_at    REAL,
    UNIQUE(watch_id, url, digest)
);
CREATE INDEX IF NOT EXISTS idx_alerts_fired ON alerts(fired_at DESC);

CREATE TABLE IF NOT EXISTS page_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    url          TEXT NOT NULL,
    protocol     TEXT,
    content_hash TEXT NOT NULL,
    title        TEXT,
    text         TEXT,
    score        REAL,
    captured_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_page_history_url     ON page_history(url, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_history_hash    ON page_history(content_hash);
CREATE INDEX IF NOT EXISTS idx_page_history_capture ON page_history(captured_at DESC);

CREATE TABLE IF NOT EXISTS blocklist_audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL,
    rule        TEXT NOT NULL,
    blocked_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_blocklist_audit_time ON blocklist_audit(blocked_at DESC);

CREATE TABLE IF NOT EXISTS pgp_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT,
    user_ids    TEXT,
    block       TEXT NOT NULL,
    source_url  TEXT,
    found_at    REAL,
    UNIQUE(fingerprint, source_url)
);
CREATE INDEX IF NOT EXISTS idx_pgp_fpr ON pgp_keys(fingerprint);

CREATE TABLE IF NOT EXISTS page_simhash (
    url         TEXT PRIMARY KEY,
    simhash     INTEGER NOT NULL,
    -- 4 × 16-bit bands of the simhash, used as LSH index for near-duplicate
    -- search. Any two fingerprints with Hamming distance ≤ 3 must agree in
    -- at least one band, giving us O(N) candidate filtering instead of O(N²).
    band0       INTEGER NOT NULL,
    band1       INTEGER NOT NULL,
    band2       INTEGER NOT NULL,
    band3       INTEGER NOT NULL,
    computed_at REAL
);
CREATE INDEX IF NOT EXISTS idx_simhash_band0 ON page_simhash(band0);
CREATE INDEX IF NOT EXISTS idx_simhash_band1 ON page_simhash(band1);
CREATE INDEX IF NOT EXISTS idx_simhash_band2 ON page_simhash(band2);
CREATE INDEX IF NOT EXISTS idx_simhash_band3 ON page_simhash(band3);

-- Persistent crawl schedules. The seeds / topics / policy are stored as JSON
-- so the runner can reconstitute a CrawlPolicy without a schema migration
-- every time a knob is added. ``next_run_at`` is the canonical due-time;
-- ``interval_sec`` is kept so re-scheduling after a successful run is trivial.
CREATE TABLE IF NOT EXISTS schedules (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL UNIQUE,
    seeds_json    TEXT NOT NULL,
    topics_json   TEXT,
    policy_json   TEXT,
    interval_sec  INTEGER NOT NULL,
    enabled       INTEGER DEFAULT 1,
    last_run_at   REAL,
    next_run_at   REAL,
    last_status   TEXT,
    last_stats    TEXT,
    created_at    REAL
);
CREATE INDEX IF NOT EXISTS idx_schedules_due ON schedules(enabled, next_run_at);

-- Liveness probes: periodic GETs against known URLs to track uptime, latency,
-- and content drift. ``content_hash`` is sha256 of the response body so we can
-- tell "still alive but page changed" from "still alive same content".
-- ``error`` carries the transport / HTTP-error string when probe failed.
CREATE TABLE IF NOT EXISTS liveness_probes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    url           TEXT NOT NULL,
    protocol      TEXT,
    probed_at     REAL NOT NULL,
    ok            INTEGER NOT NULL,
    status        INTEGER,
    latency_ms    INTEGER,
    bytes         INTEGER,
    content_hash  TEXT,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS idx_liveness_url  ON liveness_probes(url, probed_at DESC);
CREATE INDEX IF NOT EXISTS idx_liveness_time ON liveness_probes(probed_at DESC);
"""


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False + an explicit RLock lets the GUI/TUI run
        # crawler workers in background threads without throwing
        # `SQLite objects created in a thread can only be used in that same
        # thread`. WAL mode + a generous busy timeout makes concurrent reads
        # cheap and writes wait gracefully instead of erroring.
        self.conn = sqlite3.connect(
            self.path, check_same_thread=False, timeout=30, isolation_level=None,
        )
        self.conn.row_factory = sqlite3.Row
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA busy_timeout=30000")
            self.conn.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.DatabaseError:
            pass
        self._lock = threading.RLock()
        with self._lock:
            self.conn.executescript(SCHEMA)

    def close(self) -> None:
        with self._lock:
            try:
                self.conn.close()
            except sqlite3.Error:
                pass

    def __enter__(self) -> "Storage":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        # isolation_level=None puts us in autocommit mode, so we manage
        # BEGIN/COMMIT explicitly. The RLock keeps writes serialised across
        # threads; SQLite's own busy-timeout handles cross-process waits.
        with self._lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except Exception:
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    @staticmethod
    def _sanitize_fts5(query: str, *, mode: str = "broad") -> str:
        """Turn arbitrary user input into a safe FTS5 MATCH expression.

        FTS5's MATCH grammar treats ``-``, ``:``, ``(``, ``"``, ``*`` and many
        other characters as syntax. We strip the noisy chars per token and
        either:

          * ``mode="broad"`` (default) — OR of prefix matches: ``tok1* OR tok2*``.
            Maximises recall: any token's prefix anywhere in url/title/text
            counts as a hit. Designed so a one-word query returns many results.
          * ``mode="strict"`` — AND of quoted phrases (the original behavior),
            useful when the caller explicitly wants every word present.
        """
        import re as _re
        tokens: list[str] = []
        for raw in query.split():
            cleaned = _re.sub(r'[^\w\-]+', ' ', raw, flags=_re.UNICODE).strip()
            cleaned = cleaned.replace('-', ' ').strip()
            for piece in cleaned.split():
                if len(piece) >= 2:
                    tokens.append(piece)
        if not tokens:
            return ""
        if mode == "strict":
            return " ".join(f'"{t}"' for t in tokens)
        return " OR ".join(f'{t}*' for t in tokens)

    def already_seen(self, url: str) -> bool:
        with self._lock:
            cur = self.conn.execute("SELECT 1 FROM pages WHERE url = ?", (url,))
            return cur.fetchone() is not None

    def record_page(
        self,
        *,
        url: str,
        final_url: str,
        protocol: str,
        status: int,
        title: str,
        text: str,
        score: float,
        topic_hits: str,
        error: Optional[str] = None,
    ) -> None:
        with self.transaction() as c:
            c.execute(
                """INSERT INTO pages
                (url, final_url, protocol, status, title, text, score, topic_hits, fetched_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    final_url = excluded.final_url,
                    protocol  = excluded.protocol,
                    status    = excluded.status,
                    title     = excluded.title,
                    text      = excluded.text,
                    score     = excluded.score,
                    topic_hits = excluded.topic_hits,
                    fetched_at = excluded.fetched_at,
                    error     = excluded.error
                """,
                (url, final_url, protocol, status, title, text[:200_000], score, topic_hits, time.time(), error),
            )
        self._snapshot_history(url, protocol, title, text, score)

    def _snapshot_history(
        self, url: str, protocol: str, title: str, text: str, score: float,
    ) -> None:
        if not text:
            return
        h = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
        with self._lock:
            last = self.conn.execute(
                "SELECT content_hash FROM page_history WHERE url = ? "
                "ORDER BY captured_at DESC LIMIT 1",
                (url,),
            ).fetchone()
        if last and last["content_hash"] == h:
            return
        with self.transaction() as c:
            c.execute(
                """INSERT INTO page_history
                   (url, protocol, content_hash, title, text, score, captured_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (url, protocol, h, title, text[:200_000], score, time.time()),
            )
        self._record_simhash(url, text)

    @staticmethod
    def compute_simhash(text: str, *, shingle_k: int = 3) -> int:
        """64-bit SimHash of normalized text. Returns 0 for empty / very short
        inputs (won't cluster). Word-shingles of length ``shingle_k`` are
        hashed with blake2b; final bits are the sign of the per-bit sum."""
        if not text:
            return 0
        norm = " ".join(text.lower().split())
        if len(norm) < 32:
            return 0
        words = norm.split()
        if len(words) < shingle_k:
            shingles = [norm]
        else:
            shingles = [
                " ".join(words[i:i + shingle_k])
                for i in range(len(words) - shingle_k + 1)
            ]
        bits = [0] * 64
        for s in shingles:
            h = int.from_bytes(
                hashlib.blake2b(s.encode("utf-8", "replace"), digest_size=8).digest(),
                "big",
            )
            for i in range(64):
                bits[i] += 1 if (h >> i) & 1 else -1
        out = 0
        for i in range(64):
            if bits[i] > 0:
                out |= (1 << i)
        return out

    @staticmethod
    def _bands(sh: int) -> tuple[int, int, int, int]:
        return (
            sh & 0xFFFF,
            (sh >> 16) & 0xFFFF,
            (sh >> 32) & 0xFFFF,
            (sh >> 48) & 0xFFFF,
        )

    @staticmethod
    def _to_signed64(u: int) -> int:
        # SQLite INTEGER is signed 64-bit; the simhash is unsigned. Convert
        # at the boundary so we don't OverflowError on values with bit 63 set.
        return u - (1 << 64) if u >= (1 << 63) else u

    @staticmethod
    def _to_unsigned64(s: int) -> int:
        return s + (1 << 64) if s < 0 else s

    def _record_simhash(self, url: str, text: str) -> None:
        sh = self.compute_simhash(text)
        if sh == 0:
            return
        b0, b1, b2, b3 = self._bands(sh)
        with self.transaction() as c:
            c.execute(
                """INSERT INTO page_simhash(url, simhash, band0, band1, band2, band3, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(url) DO UPDATE SET
                       simhash = excluded.simhash,
                       band0 = excluded.band0, band1 = excluded.band1,
                       band2 = excluded.band2, band3 = excluded.band3,
                       computed_at = excluded.computed_at""",
                (url, self._to_signed64(sh), b0, b1, b2, b3, time.time()),
            )

    def record_error(self, url: str, protocol: str, error: str) -> None:
        self.record_page(
            url=url, final_url=url, protocol=protocol, status=0,
            title="", text="", score=0.0, topic_hits="", error=error,
        )

    def record_links(self, src: str, dsts: list[str]) -> None:
        if not dsts:
            return
        with self.transaction() as c:
            c.executemany(
                "INSERT OR IGNORE INTO links(src, dst) VALUES (?, ?)",
                [(src, d) for d in dsts],
            )

    def search(self, query: str, limit: int = 50, *, strict: bool = False) -> list[sqlite3.Row]:
        """Multi-strategy search optimised for recall.

        Combines three passes, deduplicated by URL and sorted by score:

          1. FTS5 prefix-OR match (``tok1* OR tok2*``). Catches stems and
             tokens we may not have stored verbatim. With ``strict=True`` this
             becomes an AND of quoted phrases instead.
          2. FTS5 phrase match (``"tok1" "tok2"``) — bumps exact-phrase hits.
          3. LIKE substring across url, title, text, topic_hits — picks up
             matches that the FTS tokenizer missed (e.g. embedded in a longer
             word, hyphenated identifiers, onion addresses).

        The overshoot factor (4×) lets each pass surface candidates that may
        rank lower than a near-miss in another pass.
        """
        q = (query or "").strip()
        if not q:
            return []

        results: dict[str, sqlite3.Row] = {}
        fanout = max(limit * 4, 200)

        def merge(rows: Iterator[sqlite3.Row]) -> None:
            for r in rows:
                url = r["url"]
                if url and url not in results:
                    results[url] = r

        broad = self._sanitize_fts5(q, mode="strict" if strict else "broad")
        if broad:
            sql = (
                "SELECT p.url, p.title, p.protocol, p.score, p.topic_hits, "
                "snippet(pages_fts, 2, '[', ']', '...', 16) AS snippet "
                "FROM pages_fts JOIN pages p ON p.rowid = pages_fts.rowid "
                "WHERE pages_fts MATCH ? ORDER BY p.score DESC LIMIT ?"
            )
            try:
                with self._lock:
                    merge(iter(self.conn.execute(sql, (broad, fanout)).fetchall()))
            except sqlite3.OperationalError:
                pass

        if not strict:
            phrase = self._sanitize_fts5(q, mode="strict")
            if phrase and phrase != broad:
                try:
                    with self._lock:
                        merge(iter(self.conn.execute(
                            "SELECT p.url, p.title, p.protocol, p.score, p.topic_hits, "
                            "snippet(pages_fts, 2, '[', ']', '...', 16) AS snippet "
                            "FROM pages_fts JOIN pages p ON p.rowid = pages_fts.rowid "
                            "WHERE pages_fts MATCH ? ORDER BY p.score DESC LIMIT ?",
                            (phrase, fanout),
                        ).fetchall()))
                except sqlite3.OperationalError:
                    pass

        # LIKE substring pass: catches hits the FTS tokenizer misses (middle
        # of words, weird punctuation, hyphenated identifiers, onion suffixes).
        # In strict mode only the full query string is matched; in broad mode
        # each token is also matched individually for maximum recall.
        like_terms: list[str] = [q]
        if not strict:
            like_terms.extend(t for t in q.split() if t and t != q)
        seen_terms: set[str] = set()
        for term in like_terms:
            if not term or term in seen_terms:
                continue
            seen_terms.add(term)
            like = f"%{term}%"
            with self._lock:
                merge(iter(self.conn.execute(
                    "SELECT url, title, protocol, score, topic_hits, "
                    "substr(coalesce(text,''), 1, 220) AS snippet "
                    "FROM pages "
                    "WHERE title LIKE ?1 OR url LIKE ?1 OR text LIKE ?1 OR topic_hits LIKE ?1 "
                    "ORDER BY score DESC LIMIT ?2",
                    (like, fanout),
                ).fetchall()))

        ranked = sorted(
            results.values(),
            key=lambda r: (r["score"] or 0.0, r["url"] or ""),
            reverse=True,
        )
        return ranked[:limit]

    def top(self, limit: int = 20, protocol: Optional[str] = None) -> list[sqlite3.Row]:
        cols = (
            "SELECT url, title, protocol, score, topic_hits, "
            "substr(coalesce(text,''), 1, 220) AS snippet FROM pages "
        )
        with self._lock:
            if protocol:
                return self.conn.execute(
                    cols + "WHERE protocol = ? ORDER BY score DESC LIMIT ?",
                    (protocol, limit),
                ).fetchall()
            return self.conn.execute(
                cols + "ORDER BY score DESC LIMIT ?",
                (limit,),
            ).fetchall()

    def iter_pages_for_scan(
        self,
        protocol: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Iterator[sqlite3.Row]:
        sql = "SELECT url, protocol, text FROM pages WHERE text IS NOT NULL AND text != ''"
        params: list = []
        if protocol:
            sql += " AND protocol = ?"
            params.append(protocol)
        sql += " ORDER BY fetched_at DESC"
        if limit:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        for row in rows:
            yield row

    def record_findings(self, url: str, protocol: str, findings: list) -> list:
        """Insert findings, deduping by (url, digest). Return only the
        Finding objects that were newly inserted (so callers can fire
        watchlist alerts only on first sighting)."""
        if not findings:
            return []
        digests = [f.digest for f in findings]
        placeholders = ",".join("?" * len(digests))
        with self._lock:
            cur = self.conn.execute(
                f"SELECT digest FROM findings WHERE url = ? "
                f"AND digest IN ({placeholders})",
                [url] + digests,
            )
            existing = {row["digest"] for row in cur}
        new = [f for f in findings if f.digest not in existing]
        if new:
            rows = [
                (url, protocol, f.category, f.sample, f.digest, f.target,
                 f.confidence, f.line_no, time.time())
                for f in new
            ]
            with self.transaction() as c:
                c.executemany(
                    """INSERT OR IGNORE INTO findings
                       (url, protocol, category, sample, digest, target,
                        confidence, line_no, found_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
        return new

    def findings_query(
        self,
        category: Optional[str] = None,
        target: Optional[str] = None,
        protocol: Optional[str] = None,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM findings WHERE 1=1"
        params: list = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        if protocol:
            sql += " AND protocol = ?"
            params.append(protocol)
        if target:
            sql += " AND target LIKE ?"
            params.append(f"%{target.lower()}%")
        sql += " ORDER BY found_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    # ---- page history (diff / change watch) ------------------------------

    def page_history_for(self, url: str, limit: int = 20) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                """SELECT id, content_hash, title, score, captured_at,
                          length(text) AS bytes
                   FROM page_history WHERE url = ?
                   ORDER BY captured_at DESC LIMIT ?""",
                (url, limit),
            ).fetchall()

    def page_history_get(self, history_id: int) -> Optional[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM page_history WHERE id = ?", (history_id,),
            ).fetchone()

    def page_changes_since(
        self,
        since_ts: float,
        protocol: Optional[str] = None,
        limit: int = 200,
    ) -> list[sqlite3.Row]:
        params: list = []
        sql = (
            "SELECT url, protocol, MAX(captured_at) AS latest_at, COUNT(*) AS n "
            "FROM page_history "
        )
        if protocol:
            sql += "WHERE protocol = ? "
            params.append(protocol)
        sql += "GROUP BY url HAVING n >= 2 AND latest_at >= ? "
        params.append(since_ts)
        sql += "ORDER BY latest_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    # ---- PGP key harvest -------------------------------------------------

    def record_pgp_key(
        self, *,
        fingerprint: str,
        user_ids: str,
        block: str,
        source_url: str,
    ) -> bool:
        with self.transaction() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO pgp_keys
                   (fingerprint, user_ids, block, source_url, found_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (fingerprint, user_ids, block, source_url, time.time()),
            )
        return (cur.rowcount or 0) > 0

    def pgp_keys_query(
        self, fingerprint: Optional[str] = None, limit: int = 50,
    ) -> list[sqlite3.Row]:
        with self._lock:
            if fingerprint:
                return self.conn.execute(
                    "SELECT * FROM pgp_keys WHERE fingerprint LIKE ? "
                    "ORDER BY found_at DESC LIMIT ?",
                    (f"%{fingerprint.upper()}%", limit),
                ).fetchall()
            return self.conn.execute(
                "SELECT * FROM pgp_keys ORDER BY found_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    # ---- blocklist audit -------------------------------------------------

    def record_block(self, url: str, rule: str) -> None:
        with self.transaction() as c:
            c.execute(
                "INSERT INTO blocklist_audit(url, rule, blocked_at) "
                "VALUES (?, ?, ?)",
                (url, rule, time.time()),
            )

    def blocklist_audit(self, limit: int = 100) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM blocklist_audit "
                "ORDER BY blocked_at DESC LIMIT ?",
                (limit,),
            ).fetchall()

    # ---- mirror / clone clustering ---------------------------------------

    def page_clusters(
        self, min_size: int = 2, limit: int = 100,
    ) -> list[sqlite3.Row]:
        """Group URLs by identical latest text content. Returns rows of
        (content_hash, n, urls) where `urls` is a newline-separated list."""
        with self._lock:
            return self.conn.execute(
                """WITH latest AS (
                       SELECT url, MAX(captured_at) AS ts
                       FROM page_history GROUP BY url
                   )
                   SELECT ph.content_hash,
                          COUNT(*) AS n,
                          group_concat(ph.url, char(10)) AS urls
                   FROM latest l
                   JOIN page_history ph
                     ON ph.url = l.url AND ph.captured_at = l.ts
                   GROUP BY ph.content_hash
                   HAVING n >= ?
                   ORDER BY n DESC
                   LIMIT ?""",
                (min_size, limit),
            ).fetchall()

    # ---- mirror / near-duplicate detection (SimHash) ----------------------

    def simhash_backfill(self, limit: Optional[int] = None) -> int:
        """Compute SimHashes for every page that doesn't have one yet.
        Returns the number of fingerprints written. Safe to re-run."""
        sql = (
            "SELECT p.url, p.text FROM pages p "
            "LEFT JOIN page_simhash s ON s.url = p.url "
            "WHERE s.url IS NULL AND p.text IS NOT NULL AND p.text != ''"
        )
        params: tuple = ()
        if limit:
            sql += " LIMIT ?"
            params = (limit,)
        with self._lock:
            rows = self.conn.execute(sql, params).fetchall()
        n = 0
        for r in rows:
            self._record_simhash(r["url"], r["text"] or "")
            n += 1
        return n

    def mirror_clusters(
        self, *, distance: int = 3, min_size: int = 2, limit: int = 50,
    ) -> list[dict]:
        """Cluster pages whose SimHashes lie within ``distance`` Hamming bits.

        Uses LSH banding (4 × 16-bit bands) to filter candidate pairs in
        SQL — any pair within distance ≤ 3 must agree in at least one band
        (pigeonhole). Then verify each candidate's full Hamming distance and
        union-find the survivors into clusters.
        """
        if distance < 0:
            distance = 0
        with self._lock:
            rows = self.conn.execute(
                "SELECT url, simhash, band0, band1, band2, band3 FROM page_simhash"
            ).fetchall()
        if len(rows) < 2:
            return []

        url_to_idx = {r["url"]: i for i, r in enumerate(rows)}
        # Unsign the simhash column once so XOR + bit_count work cleanly.
        sh_arr = [self._to_unsigned64(r["simhash"]) for r in rows]
        parent = list(range(len(rows)))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        # Build per-band buckets in memory: O(N) instead of O(N²) cross-joins.
        for band_idx in range(4):
            buckets: dict[int, list[int]] = {}
            key = f"band{band_idx}"
            for i, r in enumerate(rows):
                buckets.setdefault(r[key], []).append(i)
            for indices in buckets.values():
                if len(indices) < 2:
                    continue
                for i in range(len(indices)):
                    a = indices[i]
                    sa = sh_arr[a]
                    for j in range(i + 1, len(indices)):
                        b = indices[j]
                        if (sa ^ sh_arr[b]).bit_count() <= distance:
                            union(a, b)

        clusters: dict[int, list[int]] = {}
        for i in range(len(rows)):
            r = find(i)
            clusters.setdefault(r, []).append(i)

        out = []
        for members in clusters.values():
            if len(members) < min_size:
                continue
            urls = [rows[i]["url"] for i in members]
            # Cluster's representative simhash = first member's; max pairwise
            # distance gives a quick spread metric.
            sh0 = sh_arr[members[0]]
            spread = max(
                (sh0 ^ sh_arr[m]).bit_count() for m in members
            )
            out.append({
                "size": len(members),
                "max_distance": spread,
                "simhash": sh0,
                "urls": urls,
            })
        out.sort(key=lambda c: (-c["size"], c["max_distance"]))
        return out[:limit]

    def near_duplicates_of(
        self, url: str, *, distance: int = 3, limit: int = 50,
    ) -> list[dict]:
        """Return pages with SimHash within ``distance`` of ``url``'s
        fingerprint. Useful for "find mirrors of THIS onion" queries."""
        with self._lock:
            row = self.conn.execute(
                "SELECT simhash, band0, band1, band2, band3 FROM page_simhash WHERE url = ?",
                (url,),
            ).fetchone()
        if row is None:
            return []
        sh = self._to_unsigned64(row["simhash"])
        candidates: dict[str, int] = {}
        with self._lock:
            for band_idx, key in enumerate(("band0", "band1", "band2", "band3")):
                cur = self.conn.execute(
                    f"SELECT url, simhash FROM page_simhash WHERE {key} = ? AND url != ?",
                    (row[key], url),
                )
                for r in cur:
                    candidates[r["url"]] = self._to_unsigned64(r["simhash"])
        out = []
        for u, other_sh in candidates.items():
            d = (sh ^ other_sh).bit_count()
            if d <= distance:
                out.append({"url": u, "distance": d})
        out.sort(key=lambda x: x["distance"])
        return out[:limit]

    # ---- watchlist / alerts -----------------------------------------------

    def watchlist_add(
        self,
        *,
        target: Optional[str],
        category: Optional[str],
        sample: Optional[str],
        is_regex: bool,
        sink: str,
        note: Optional[str],
    ) -> int:
        with self.transaction() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO watchlist
                   (target, category, sample, is_regex, sink, note, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (target, category, sample, 1 if is_regex else 0,
                 sink, note, time.time()),
            )
            if cur.lastrowid:
                return cur.lastrowid
            row = c.execute(
                """SELECT id FROM watchlist WHERE
                   ifnull(target,'')=ifnull(?,'') AND
                   ifnull(category,'')=ifnull(?,'') AND
                   ifnull(sample,'')=ifnull(?,'') AND sink=?""",
                (target, category, sample, sink),
            ).fetchone()
            return row["id"] if row else -1

    def watchlist_query(self) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM watchlist ORDER BY id"
            ).fetchall()

    def watchlist_remove(self, watch_id: int) -> bool:
        with self.transaction() as c:
            cur = c.execute("DELETE FROM watchlist WHERE id = ?", (watch_id,))
        return (cur.rowcount or 0) > 0

    def watchlist_get(self, watch_id: int) -> Optional[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM watchlist WHERE id = ?", (watch_id,)
            ).fetchone()

    def record_alert(
        self, watch_id: int, url: str, digest: str, sink_status: str,
    ) -> bool:
        with self.transaction() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO alerts
                   (watch_id, url, digest, sink_status, fired_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (watch_id, url, digest, sink_status, time.time()),
            )
        return (cur.rowcount or 0) > 0

    def alerts_query(self, limit: int = 50) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                """SELECT a.*, w.target AS w_target, w.category AS w_category,
                          w.sample AS w_sample, w.note AS w_note, w.sink AS w_sink
                   FROM alerts a LEFT JOIN watchlist w ON w.id = a.watch_id
                   ORDER BY a.fired_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()

    def findings_export(
        self,
        category: Optional[str] = None,
        target: Optional[str] = None,
        protocol: Optional[str] = None,
        since_ts: Optional[float] = None,
        limit: Optional[int] = None,
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM findings WHERE 1=1"
        params: list = []
        if category:
            sql += " AND category = ?"; params.append(category)
        if protocol:
            sql += " AND protocol = ?"; params.append(protocol)
        if target:
            sql += " AND target LIKE ?"; params.append(f"%{target.lower()}%")
        if since_ts is not None:
            sql += " AND found_at >= ?"; params.append(since_ts)
        sql += " ORDER BY found_at DESC"
        if limit:
            sql += " LIMIT ?"; params.append(limit)
        with self._lock:
            return self.conn.execute(sql, params).fetchall()

    def findings_stats(self) -> dict:
        with self._lock:
            cur = self.conn.execute(
                "SELECT category, COUNT(*) AS n FROM findings GROUP BY category"
            )
            per_cat = {row["category"]: row["n"] for row in cur}
            total = self.conn.execute(
                "SELECT COUNT(*) AS n FROM findings"
            ).fetchone()["n"]
        return {"total": total, "by_category": per_cat}

    def stats(self) -> dict:
        with self._lock:
            cur = self.conn.execute(
                "SELECT protocol, COUNT(*) AS n FROM pages GROUP BY protocol"
            )
            per_proto = {row["protocol"]: row["n"] for row in cur}
            total = self.conn.execute(
                "SELECT COUNT(*) AS n FROM pages"
            ).fetchone()["n"]
            links = self.conn.execute(
                "SELECT COUNT(*) AS n FROM links"
            ).fetchone()["n"]
        return {"total_pages": total, "links": links, "by_protocol": per_proto}

    # ---- schedules ------------------------------------------------------

    def add_schedule(
        self,
        *,
        name: str,
        seeds_json: str,
        topics_json: str,
        policy_json: str,
        interval_sec: int,
        enabled: bool = True,
        first_run_in: float = 0.0,
    ) -> int:
        """Insert a new schedule. ``first_run_in`` is seconds until next_run_at
        from now (0 = run immediately on next runner pass)."""
        now = time.time()
        with self.transaction() as c:
            cur = c.execute(
                """INSERT INTO schedules
                   (name, seeds_json, topics_json, policy_json, interval_sec,
                    enabled, next_run_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, seeds_json, topics_json, policy_json, int(interval_sec),
                 1 if enabled else 0, now + first_run_in, now),
            )
            return cur.lastrowid or 0

    def remove_schedule(self, name: str) -> int:
        with self.transaction() as c:
            cur = c.execute("DELETE FROM schedules WHERE name = ?", (name,))
            return cur.rowcount

    def set_schedule_enabled(self, name: str, enabled: bool) -> int:
        with self.transaction() as c:
            cur = c.execute(
                "UPDATE schedules SET enabled = ? WHERE name = ?",
                (1 if enabled else 0, name),
            )
            return cur.rowcount

    def list_schedules(self) -> list[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM schedules ORDER BY name"
            ).fetchall()

    def get_schedule(self, name: str) -> Optional[sqlite3.Row]:
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM schedules WHERE name = ?", (name,)
            ).fetchone()

    def due_schedules(self, now: Optional[float] = None) -> list[sqlite3.Row]:
        ts = now if now is not None else time.time()
        with self._lock:
            return self.conn.execute(
                "SELECT * FROM schedules WHERE enabled = 1 AND next_run_at <= ? "
                "ORDER BY next_run_at",
                (ts,),
            ).fetchall()

    def mark_schedule_run(
        self,
        name: str,
        *,
        status: str,
        stats_json: Optional[str] = None,
        ran_at: Optional[float] = None,
    ) -> None:
        """Update last_run/last_status and reschedule next_run = now + interval."""
        ts = ran_at if ran_at is not None else time.time()
        with self.transaction() as c:
            row = c.execute(
                "SELECT interval_sec FROM schedules WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return
            interval = int(row["interval_sec"])
            c.execute(
                """UPDATE schedules
                   SET last_run_at = ?, last_status = ?, last_stats = ?,
                       next_run_at = ?
                   WHERE name = ?""",
                (ts, status, stats_json, ts + interval, name),
            )
