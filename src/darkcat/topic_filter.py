"""Topic-keyword scoring.

Given a list of topic terms, score a page by:
  - Term frequency in title (weighted 5x) and body
  - Bonus for any whole-phrase match
  - Normalize by log of body length so long pages don't dominate
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


@dataclass
class TopicMatch:
    score: float
    hits: dict[str, int]


class TopicFilter:
    def __init__(self, topics: Iterable[str]):
        self.topics = [t.strip().lower() for t in topics if t and t.strip()]

    @property
    def empty(self) -> bool:
        return not self.topics

    def score(self, title: str, text: str) -> TopicMatch:
        if self.empty:
            return TopicMatch(score=0.0, hits={})
        title_l = (title or "").lower()
        text_l = (text or "").lower()
        body_tokens = _TOKEN_RE.findall(text_l)
        title_tokens = _TOKEN_RE.findall(title_l)
        body_count = len(body_tokens)
        norm = math.log(body_count + 10)

        hits: dict[str, int] = {}
        total = 0.0
        for topic in self.topics:
            n = 0
            if " " in topic:
                # phrase match
                n += text_l.count(topic) + 5 * title_l.count(topic)
            else:
                n += body_tokens.count(topic)
                n += 5 * title_tokens.count(topic)
            if n:
                hits[topic] = n
                total += n
        return TopicMatch(score=total / norm, hits=hits)

    def passes(self, title: str, text: str, threshold: float) -> bool:
        if self.empty:
            return True
        return self.score(title, text).score >= threshold
