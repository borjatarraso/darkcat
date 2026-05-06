"""Heuristic content categorization for crawled pages.

Maps a page's title / url / snippet / topic-hits to one or more category
labels (hack, drugs, legal, hacktivism, …) using keyword/regex maps. This
is a *coarse* surface-feature classifier — good enough to give the user a
glance-able sense of what each result *covers* in addition to the numeric
relevance score.

Categories are intentionally darknet-flavoured: the keyword inventories
are drawn from common topic clusters seen on Tor/I2P indexes, hidden
wikis, and cryptomarkets. Multiple labels per page are normal — order
returned is descending by hit count.
"""
from __future__ import annotations

import re

# Category → list of regex fragments. Each fragment is an alternation
# branch joined with ``|`` and wrapped in a single ``\b(?:…)`` boundary
# at compile time, so all matching is whole-word and case-insensitive.
_CATEGORIES: dict[str, list[str]] = {
    "hack": [
        r"hack", r"exploit", r"cve", r"rce", r"0day", r"zero[- ]?day",
        r"malware", r"ransomware", r"phish\w*", r"rootkit", r"shellcode",
        r"infosec", r"vuln\w*", r"botnet", r"c2\b", r"stealer", r"backdoor",
        r"keylog\w*", r"reverse[- ]engineer\w*",
    ],
    "drugs": [
        r"drug\w*", r"cannabis", r"weed\b", r"marijuana", r"cocaine",
        r"heroin", r"lsd", r"mdma", r"meth\b", r"methamphetamine",
        r"ketamine", r"opioid\w*", r"psychedel\w*", r"narcot\w*",
        r"dispensary", r"fentanyl", r"benzo\w*", r"shroom\w*",
    ],
    "legal": [
        r"legal", r"lawyer", r"attorney", r"court", r"constitut\w*",
        r"statute", r"jurisdiction", r"due[- ]process", r"compliance",
        r"gdpr", r"\beula\b", r"copyright", r"dmca",
    ],
    "hacktivism": [
        r"hacktivis\w*", r"anonymou[sz]", r"lulzsec", r"activist",
        r"protest", r"dissident", r"whistleblow\w*", r"transparen\w*",
        r"occupy", r"chaos[- ]computer", r"freedom[- ]fighter",
    ],
    "crypto": [
        r"bitcoin", r"btc\b", r"monero", r"xmr\b", r"ethereum", r"eth\b",
        r"wallet", r"crypto\w*", r"blockchain", r"ledger", r"tumbler",
        r"mixer", r"privacy[- ]coin", r"satoshi", r"hodl",
    ],
    "markets": [
        r"market\w*", r"vendor", r"listing", r"escrow", r"marketplace",
        r"shop", r"buyer", r"seller", r"for[- ]sale", r"checkout",
    ],
    "forums": [
        r"forum\w*", r"thread\w*", r"imageboard", r"chan\b", r"bbs\b",
        r"discussion", r"subforum", r"sticky", r"reply",
    ],
    "news": [
        r"news", r"press[- ]release", r"journalist", r"article",
        r"headline", r"investigat\w*", r"expos[eé]", r"breaking[- ]news",
        r"bulletin",
    ],
    "privacy": [
        r"privacy", r"anonym\w*", r"encrypt\w*", r"pgp", r"gpg",
        r"tor\b", r"i2p\b", r"\bvpn\b", r"tails", r"qubes", r"signal[- ]?app",
        r"securedrop", r"opsec",
    ],
    "leaks": [
        r"leak\w*", r"dox\w*", r"dumped", r"exfiltrat\w*", r"breach\w*",
        r"disclosure", r"wikileaks", r"cryptome", r"snowden", r"\bpaste\b",
    ],
    "weapons": [
        r"weapon\w*", r"firearm\w*", r"pistol", r"rifle\w*", r"ammo\b",
        r"ammunition", r"explosive\w*", r"\bC4\b", r"silencer", r"suppressor",
    ],
    "fraud": [
        r"fraud\w*", r"scam\w*", r"carding", r"cvv\b", r"fullz", r"skimmer",
        r"counterfeit", r"phish[- ]?kit", r"money[- ]launder\w*",
    ],
    "csam": [
        # Detected so we can *down-rank* / quarantine, never to seek.
        r"\bcp\b", r"loli", r"shota", r"jailbait",
    ],
}

_COMPILED: dict[str, re.Pattern] = {
    cat: re.compile(r"\b(?:" + "|".join(pats) + r")", re.IGNORECASE)
    for cat, pats in _CATEGORIES.items()
}


def categorize(*texts: str | None, max_labels: int = 3) -> list[tuple[str, int]]:
    """Return ``[(label, hits), …]`` ranked by hit count (descending)."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return []
    scores: list[tuple[str, int]] = []
    for cat, rx in _COMPILED.items():
        n = len(rx.findall(blob))
        if n:
            scores.append((cat, n))
    scores.sort(key=lambda x: (x[1], x[0]), reverse=True)
    return scores[:max_labels]


def categorize_str(*texts: str | None, max_labels: int = 3) -> str:
    """Comma-separated category labels for display in a single cell."""
    cats = categorize(*texts, max_labels=max_labels)
    return ",".join(c for c, _ in cats) if cats else "—"


# Public, read-only view of the keyword categories — used by the help
# tooltip in the GUI / TUI so users can see what "category" means.
CATEGORY_NAMES: tuple[str, ...] = tuple(_CATEGORIES.keys())


SCORE_HELP = (
    "score = topic-keyword frequency, normalised by page length\n"
    "\n"
    "  • each topic word counts +1 in the body and +5 in the title\n"
    "  • exact phrases also score +5 in the title\n"
    "  • the total is divided by log(body_words + 10) so long pages\n"
    "    don't dominate short, on-topic ones\n"
    "\n"
    "rough scale:\n"
    "  0.00          no topic match (or no topics set)\n"
    "  0.30 – 1.00   weak / off-topic page\n"
    "  1.00 – 5.00   on-topic\n"
    "  5.00+         strongly on-topic\n"
    "\n"
    "category is a separate, heuristic keyword classifier:\n"
    f"  {', '.join(CATEGORY_NAMES)}"
)
