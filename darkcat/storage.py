"""SQLite storage for crawl results."""
from __future__ import annotations

import sqlite3
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
"""


class Storage:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def already_seen(self, url: str) -> bool:
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

    def search(self, query: str, limit: int = 20) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """SELECT p.url, p.title, p.protocol, p.score,
                      snippet(pages_fts, 2, '[', ']', '...', 12) AS snippet
               FROM pages_fts
               JOIN pages p ON p.rowid = pages_fts.rowid
               WHERE pages_fts MATCH ?
               ORDER BY p.score DESC
               LIMIT ?""",
            (query, limit),
        )
        return cur.fetchall()

    def top(self, limit: int = 20, protocol: Optional[str] = None) -> list[sqlite3.Row]:
        if protocol:
            cur = self.conn.execute(
                "SELECT url, title, protocol, score FROM pages WHERE protocol = ? ORDER BY score DESC LIMIT ?",
                (protocol, limit),
            )
        else:
            cur = self.conn.execute(
                "SELECT url, title, protocol, score FROM pages ORDER BY score DESC LIMIT ?",
                (limit,),
            )
        return cur.fetchall()

    def stats(self) -> dict:
        cur = self.conn.execute(
            "SELECT protocol, COUNT(*) AS n FROM pages GROUP BY protocol"
        )
        per_proto = {row["protocol"]: row["n"] for row in cur}
        cur = self.conn.execute("SELECT COUNT(*) AS n FROM pages")
        total = cur.fetchone()["n"]
        cur = self.conn.execute("SELECT COUNT(*) AS n FROM links")
        links = cur.fetchone()["n"]
        return {"total_pages": total, "links": links, "by_protocol": per_proto}
