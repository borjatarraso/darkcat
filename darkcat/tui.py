"""Textual TUI for darkcat."""
from __future__ import annotations

from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
)

from darkcat.config import Config
from darkcat.crawler import Crawler, CrawlPolicy
from darkcat.fetcher import Fetcher
from darkcat.protocols import Protocol
from darkcat.seeds import SEEDS_BY_PROTOCOL, all_seeds
from darkcat.storage import Storage
from darkcat.topic_filter import TopicFilter


class StatusBar(Static):
    """One-line status of every transport's daemon reachability."""

    def __init__(self, fetcher: Fetcher, **kw) -> None:
        super().__init__("…", **kw)
        self.fetcher = fetcher

    def refresh_status(self) -> None:
        statuses = self.fetcher.status()
        chunks = []
        for proto, ok in statuses.items():
            mark = "[green]●[/green]" if ok else "[red]○[/red]"
            chunks.append(f"{mark} {proto.value}")
        self.update("  ".join(chunks))


class DarkcatApp(App):
    CSS = """
    Screen { layout: vertical; }
    #status { height: 1; padding: 0 1; background: $boost; }
    #form { height: auto; padding: 1; border: solid $primary; }
    #form Input { width: 1fr; }
    #form Select { width: 18; }
    #row1, #row2, #row3 { height: 3; margin-bottom: 1; }
    #content { height: 1fr; }
    #log { width: 1fr; border: solid $primary; }
    #results { width: 1fr; border: solid $primary; }
    .lbl { content-align: left middle; padding: 0 1; width: auto; }
    Button { margin: 0 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("ctrl+r", "refresh_status", "Refresh status"),
        Binding("ctrl+c", "cancel_crawl", "Stop crawl"),
        Binding("f5", "refresh_results", "Refresh results"),
    ]

    crawling: reactive[bool] = reactive(False)

    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self.cfg = cfg
        self.fetcher = Fetcher(cfg)
        self.storage = Storage(cfg.db_path)
        self._active_crawler: Optional[Crawler] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield StatusBar(self.fetcher, id="status")
        with Container(id="form"):
            with Horizontal(id="row1"):
                yield Label("Topics:", classes="lbl")
                yield Input(placeholder="whistleblower leak securedrop …", id="topics")
            with Horizontal(id="row2"):
                yield Label("Protocol:", classes="lbl")
                yield Select(
                    [(p, p) for p in (list(SEEDS_BY_PROTOCOL.keys()) + ["all"])],
                    value="tor",
                    id="protocol",
                    allow_blank=False,
                )
                yield Label("Max pages:", classes="lbl")
                yield Input(value="50", id="max_pages")
                yield Label("Max depth:", classes="lbl")
                yield Input(value="2", id="max_depth")
                yield Label("Threshold:", classes="lbl")
                yield Input(value="0", id="threshold")
            with Horizontal(id="row3"):
                yield Button("Crawl", variant="primary", id="crawl-btn")
                yield Button("Stop", variant="error", id="stop-btn", disabled=True)
                yield Input(placeholder="Search FTS5…", id="search")
                yield Button("Search", id="search-btn")
                yield Input(placeholder="Fetch URL…", id="fetch_url")
                yield Button("Fetch", id="fetch-btn")
        with Horizontal(id="content"):
            yield RichLog(highlight=True, markup=True, id="log", wrap=True)
            yield DataTable(id="results", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        self.title = "Darkcat"
        self.sub_title = "multi-protocol darknet crawler"
        table = self.query_one("#results", DataTable)
        table.add_columns("score", "proto", "title", "url")
        table.cursor_type = "row"
        self.query_one(StatusBar).refresh_status()
        self.refresh_results()
        self._log("[bold]darkcat TUI ready[/bold] — set topics, pick a protocol, hit Crawl.")
        self._log("Status legend: [green]●[/green] reachable, [red]○[/red] not reachable / not configured.")

    # --- actions -------------------------------------------------------------

    def action_refresh_status(self) -> None:
        self.query_one(StatusBar).refresh_status()

    def action_refresh_results(self) -> None:
        self.refresh_results()

    def action_cancel_crawl(self) -> None:
        if self._active_crawler:
            self._active_crawler.stop()
            self._log("[yellow]stop requested[/yellow]")

    # --- buttons -------------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "crawl-btn":
            self.start_crawl()
        elif bid == "stop-btn":
            self.action_cancel_crawl()
        elif bid == "search-btn":
            self.do_search()
        elif bid == "fetch-btn":
            self.do_fetch()

    def watch_crawling(self, value: bool) -> None:
        self.query_one("#crawl-btn", Button).disabled = value
        self.query_one("#stop-btn", Button).disabled = not value

    # --- crawl ---------------------------------------------------------------

    def start_crawl(self) -> None:
        topics = self.query_one("#topics", Input).value.split()
        protocol = self.query_one("#protocol", Select).value
        try:
            max_pages = int(self.query_one("#max_pages", Input).value or "50")
            max_depth = int(self.query_one("#max_depth", Input).value or "2")
            threshold = float(self.query_one("#threshold", Input).value or "0")
        except ValueError:
            self._log("[red]Invalid number in form[/red]")
            return
        seeds = all_seeds() if protocol == "all" else SEEDS_BY_PROTOCOL.get(protocol, [])
        if not seeds:
            self._log(f"[yellow]No built-in seeds for {protocol}[/yellow]")
            return
        self._log(f"[bold cyan]crawl starting[/bold cyan] proto={protocol} "
                  f"seeds={len(seeds)} max_pages={max_pages} max_depth={max_depth} "
                  f"topics={topics or '(none)'}")
        self.crawling = True
        self.run_worker(
            self._crawl_worker(seeds, topics, max_pages, max_depth, threshold),
            exclusive=True,
            thread=True,
        )

    def _crawl_worker(self, seeds, topics, max_pages, max_depth, threshold):
        tf = TopicFilter(topics)
        policy = CrawlPolicy(
            max_pages=max_pages,
            max_depth=max_depth,
            score_threshold=threshold,
        )
        crawler = Crawler(self.cfg, self.storage, tf, policy)
        self._active_crawler = crawler

        def on_event(kind: str, payload: dict) -> None:
            self.call_from_thread(self._handle_crawl_event, kind, payload)

        try:
            stats = crawler.crawl(seeds, on_event=on_event)
            self.call_from_thread(
                self._log,
                f"[bold green]done[/bold green] fetched={stats.fetched} "
                f"errors={stats.errors} skipped={stats.skipped}",
            )
        except Exception as e:
            self.call_from_thread(self._log, f"[red]crawl crashed: {e}[/red]")
        finally:
            self._active_crawler = None
            self.call_from_thread(self._set_crawling, False)
            self.call_from_thread(self.refresh_results)

    def _set_crawling(self, value: bool) -> None:
        self.crawling = value

    def _handle_crawl_event(self, kind: str, payload: dict) -> None:
        if kind == "fetch":
            self._log(
                f"[green][/green] [{payload['protocol']:<9}] "
                f"score={payload['score']:.2f} d={payload.get('depth', 0)} "
                f"{payload.get('title') or '(no title)'} — {payload['url']}"
            )
        elif kind == "error":
            self._log(
                f"[red]✗[/red] [{payload.get('protocol', '?')}] "
                f"{payload.get('reason', '')}: {payload.get('error', '')[:140]} — {payload['url']}"
            )
        elif kind == "skip":
            self._log(f"[dim]skip[/dim] {payload.get('reason', '')}: {payload['url']}")

    # --- search / fetch -------------------------------------------------------

    def do_search(self) -> None:
        q = self.query_one("#search", Input).value.strip()
        if not q:
            return
        rows = self.storage.search(q, limit=50)
        table = self.query_one("#results", DataTable)
        table.clear()
        for r in rows:
            table.add_row(
                f"{r['score']:.2f}",
                r["protocol"],
                (r["title"] or "")[:60],
                r["url"][:80],
            )
        self._log(f"search '{q}' → {len(rows)} result(s)")

    def do_fetch(self) -> None:
        url = self.query_one("#fetch_url", Input).value.strip()
        if not url:
            return
        self._log(f"fetching {url} …")
        self.run_worker(self._fetch_worker(url), thread=True)

    def _fetch_worker(self, url: str) -> None:
        try:
            result = self.fetcher.fetch(url)
        except Exception as e:
            self.call_from_thread(self._log, f"[red]fetch failed:[/red] {e}")
            return
        self.call_from_thread(
            self._log,
            f"status={result.status} bytes={len(result.body)} "
            f"ct={result.content_type} → {result.final_url}",
        )

    def refresh_results(self) -> None:
        table = self.query_one("#results", DataTable)
        table.clear()
        for r in self.storage.top(limit=200):
            table.add_row(
                f"{r['score']:.2f}",
                r["protocol"],
                (r["title"] or "")[:60],
                r["url"][:80],
            )

    def _log(self, msg: str) -> None:
        self.query_one("#log", RichLog).write(msg)


def run_tui(cfg: Config) -> int:
    DarkcatApp(cfg).run()
    return 0
