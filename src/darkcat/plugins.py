"""Per-site extractor plugins.

Generic HTML scraping is fine for most onions, but some heavy sites — Dread
forum threads, paste-style breach mirrors, dark-market product listings —
hide their useful content (post bodies, pagination, mirror lists) behind
template-specific markup that the generic ``BeautifulSoup`` extractor either
loses or buries in chrome. Plugins let us hand-write a parser per host.

Contract:

    class MyPlugin(SitePlugin):
        name = "dread"

        def matches(self, url: str) -> bool:
            return urlparse(url).hostname.endswith("dread.onion")

        def parse(self, url, body, content_type) -> Optional[Page]:
            # return Page(...) to override, or None to defer to the next
            # plugin / generic extractor.

Loading order:

1. Built-ins shipped in :mod:`darkcat.plugins_builtin`.
2. Any ``*.py`` file under ``~/.darkcat/plugins/`` (each must define a
   module-level ``PLUGINS`` list of ``SitePlugin`` instances).
3. Anything registered programmatically via :func:`register`.

The first plugin whose ``matches()`` returns True and whose ``parse()`` returns
a non-``None`` ``Page`` wins. ``None`` falls through.

Failure-mode policy: a plugin raising during ``matches`` or ``parse`` is
logged and skipped — never breaks the crawl. Plugins are user code; they
mustn't be able to brick darkcat.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Iterable, Optional, Protocol as TypingProtocol

from darkcat.extractor import Page


log = logging.getLogger("darkcat.plugins")


class SitePlugin(TypingProtocol):
    """Plugin protocol — duck-typed, no inheritance required."""
    name: str

    def matches(self, url: str) -> bool: ...
    def parse(self, url: str, body: bytes, content_type: str) -> Optional[Page]: ...


_REGISTRY: list[SitePlugin] = []
_LOADED = False


def register(plugin: SitePlugin) -> None:
    """Add a plugin to the registry. Idempotent on plugin identity."""
    if plugin in _REGISTRY:
        return
    _REGISTRY.append(plugin)
    log.info("registered plugin %r", getattr(plugin, "name", type(plugin).__name__))


def registered() -> list[SitePlugin]:
    if not _LOADED:
        load_all()
    return list(_REGISTRY)


def reset() -> None:
    """Drop everything (mostly for tests)."""
    global _LOADED
    _REGISTRY.clear()
    _LOADED = False


def find(url: str) -> Optional[SitePlugin]:
    """Return the first non-catch-all plugin whose ``matches(url)`` is True.

    Catch-all plugins (those with ``is_catch_all = True``) are skipped here
    because they can't truly decide without seeing the body — listing them
    for every URL would just be noise. They still run during real parsing
    via :func:`parse_with_plugins`."""
    for p in registered():
        if getattr(p, "is_catch_all", False):
            continue
        try:
            if p.matches(url):
                return p
        except Exception:
            log.exception("plugin %r matches() raised", getattr(p, "name", "?"))
    return None


def parse_with_plugins(url: str, body: bytes, content_type: str) -> Optional[Page]:
    """Try every matching plugin in registration order; return the first
    non-``None`` Page or ``None`` if no plugin claims the URL."""
    for p in registered():
        try:
            if not p.matches(url):
                continue
        except Exception:
            log.exception("plugin %r matches() raised", getattr(p, "name", "?"))
            continue
        try:
            page = p.parse(url, body, content_type)
        except Exception:
            log.exception("plugin %r parse() raised on %s",
                          getattr(p, "name", "?"), url)
            continue
        if page is not None:
            return page
    return None


def load_all() -> None:
    """Populate the registry from built-ins and ``~/.darkcat/plugins/``."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True  # set first so re-entry from importer doesn't loop
    _load_builtins()
    _load_user_dir()


def _load_builtins() -> None:
    try:
        from darkcat import plugins_builtin
        for p in getattr(plugins_builtin, "PLUGINS", []):
            register(p)
    except Exception:
        log.exception("failed to load built-in plugins")


def _load_user_dir() -> None:
    user_dir = Path.home() / ".darkcat" / "plugins"
    if not user_dir.is_dir():
        return
    for path in sorted(user_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        _load_user_file(path)


def _load_user_file(path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        f"darkcat_user_plugin_{path.stem}", path,
    )
    if spec is None or spec.loader is None:
        log.warning("plugin %s: could not build import spec", path)
        return
    try:
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception:
        log.exception("plugin %s failed to import", path)
        return
    plugins: Iterable = getattr(mod, "PLUGINS", None) or []
    if not plugins:
        log.warning("plugin %s defines no PLUGINS list — skipping", path)
        return
    for p in plugins:
        try:
            register(p)
        except Exception:
            log.exception("could not register plugin from %s", path)


__all__ = [
    "SitePlugin", "register", "registered", "reset",
    "find", "parse_with_plugins", "load_all",
]
