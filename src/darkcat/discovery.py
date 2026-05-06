"""Form-based discovery — query darknet search engines for seed URLs.

Each engine has a URL template with a `{q}` placeholder. We fetch the
result page through the normal Fetcher (so onion-only engines transparently
go through Tor), parse the result links via the standard extractor, unwrap
any redirector wrappers, and dedupe. Output is a list of (url, engine)
pairs that can be piped into a crawl.
"""
from __future__ import annotations

import urllib.parse
from dataclasses import dataclass
from typing import Callable, Iterable, Optional

from darkcat.extractor import parse as parse_page
from darkcat.fetcher import Fetcher


@dataclass(frozen=True)
class Engine:
    name: str
    url_template: str       # use {q} for the URL-encoded query
    only_onion: bool = False
    note: str = ""


ENGINES: list[Engine] = [
    Engine("ahmia",
           "https://ahmia.fi/search/?q={q}",
           note="clearnet meta-search of ahmia"),
    Engine("ahmia-onion",
           "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/?q={q}",
           only_onion=True, note="ahmia via Tor"),
    Engine("haystak",
           "http://haystak5njsmn2hqkewecpaxetahtwhsbsa64jom2k22z5afxhnpxfid.onion/?q={q}",
           only_onion=True, note="onion-only search engine"),
    Engine("onionland",
           "https://onionlandsearchengine.com/search?q={q}",
           note="clearnet portal"),
    Engine("torch",
           "http://torchdeedp3i2jigzjdmfpn5ttjhthh5wbmda2rr3jvqjg5p77c54dqd.onion/search?query={q}",
           only_onion=True, note="long-running Tor search engine"),
    Engine("phobos",
           "http://phobosxilamwcg75xt22id7aywkzol6q6rfl2flipcqoc4e4ahima5id.onion/search?query={q}",
           only_onion=True),
    Engine("submarine",
           "http://no6m4wzdexe3auiupv2zwif7rm6qwxcyhslkcnzisxgeiw6pvjsgafad.onion/search?q={q}",
           only_onion=True, note="submarine search"),
]


# Common query parameter names used by darknet engines for redirect URLs.
_REDIRECT_PARAMS = (
    "redirect_url", "url", "u", "q", "to", "redirect", "out", "go", "target",
)
_INTERESTING_TLDS = (".onion", ".i2p", ".loki", ".eth", ".bit", ".gnu", ".zkey")
_INTERESTING_SCHEMES = (
    "gemini", "gopher", "gophers", "ipfs", "ipns", "freenet", "hyper",
    "spartan", "nex", "zero",
)


def _unwrap_redirect(url: str) -> str:
    """If `url` looks like an engine redirector, peel off and return the target."""
    try:
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)
    except Exception:
        return url
    for k in _REDIRECT_PARAMS:
        vals = qs.get(k)
        if not vals:
            continue
        cand = urllib.parse.unquote(vals[0])
        if cand.startswith(("http://", "https://")) or any(
            cand.startswith(s + "://") for s in _INTERESTING_SCHEMES
        ):
            return cand
    return url


def _is_interesting(url: str) -> bool:
    try:
        p = urllib.parse.urlparse(url)
    except Exception:
        return False
    if p.scheme.lower() in _INTERESTING_SCHEMES:
        return True
    host = (p.hostname or "").lower()
    if not host:
        return False
    return any(host.endswith(tld) for tld in _INTERESTING_TLDS)


def discover(
    fetcher: Fetcher,
    query: str,
    engines: Optional[Iterable[str]] = None,
    *,
    max_per_engine: int = 50,
    only_interesting: bool = True,
    on_event: Optional[Callable[[str, dict], None]] = None,
) -> list[tuple[str, str]]:
    """Run `query` against the selected engines. Return [(url, engine_name)]."""
    if engines:
        names = {n.lower() for n in engines}
        selected = [e for e in ENGINES if e.name.lower() in names]
    else:
        selected = list(ENGINES)
    seen: dict[str, str] = {}
    out: list[tuple[str, str]] = []
    q = urllib.parse.quote_plus(query)

    def emit(kind: str, **kw) -> None:
        if on_event:
            try:
                on_event(kind, kw)
            except Exception:
                pass

    for eng in selected:
        url = eng.url_template.format(q=q)
        emit("query", engine=eng.name, url=url)
        try:
            r = fetcher.fetch(url)
        except Exception as e:
            emit("error", engine=eng.name, url=url, error=str(e))
            continue
        if not r or not r.body:
            emit("error", engine=eng.name, url=url, error="empty response")
            continue
        page = parse_page(r.final_url, r.body, r.content_type)
        n = 0
        for link in page.links:
            target = _unwrap_redirect(link)
            if only_interesting and not _is_interesting(target):
                continue
            if target in seen:
                continue
            seen[target] = eng.name
            out.append((target, eng.name))
            n += 1
            if n >= max_per_engine:
                break
        emit("done", engine=eng.name, found=n)
    return out
