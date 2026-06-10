# SPDX-License-Identifier: BSD-3-Clause
# Copyright (c) 2026 Borja Tarraso
"""Tests for the curated examples catalog (``darkcat.help_examples``).

Guards the data integrity contract every frontend depends on: every
``Example`` must carry the four canonical frontend steps (CLI / REPL /
TUI / GUI), ids are unique and slug-shaped, ``find`` / ``search`` /
``categories`` behave, and the Rich renderers emit the expected colour
tags. Without these, a typo in the catalog ships a broken cheatsheet
across all four UIs at once."""
from __future__ import annotations

import re

import pytest

from darkcat import help_examples as he


_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_FRONTENDS = ("cli", "repl", "tui", "gui")


# ---- data integrity --------------------------------------------------


def test_catalog_is_non_empty():
    assert he.EXAMPLES, "EXAMPLES catalog must not be empty"


def test_every_example_id_is_unique_and_slug_shaped():
    seen: set[str] = set()
    for ex in he.EXAMPLES:
        assert _SLUG_RE.match(ex.id), f"non-slug id: {ex.id!r}"
        assert ex.id not in seen, f"duplicate example id: {ex.id}"
        seen.add(ex.id)


def test_every_example_has_one_step_per_frontend():
    """Each entry must cover all four frontends — otherwise the
    cheatsheet ships an asymmetric story where one UI has no path."""
    for ex in he.EXAMPLES:
        frontends = [s.frontend for s in ex.steps]
        for fe in _FRONTENDS:
            assert fe in frontends, (
                f"example {ex.id!r} is missing a step for {fe!r}; "
                f"saw {frontends}"
            )


def test_every_example_has_non_empty_command():
    for ex in he.EXAMPLES:
        for step in ex.steps:
            assert step.command.strip(), (
                f"empty command for {ex.id}/{step.frontend}"
            )


def test_every_example_has_title_description_category():
    for ex in he.EXAMPLES:
        assert ex.title.strip(), f"{ex.id} has empty title"
        assert ex.description.strip(), f"{ex.id} has empty description"
        assert ex.category.strip(), f"{ex.id} has empty category"


def test_frontend_styles_cover_every_known_frontend():
    for fe in _FRONTENDS:
        assert fe in he.FRONTEND_STYLES, f"missing FRONTEND_STYLES['{fe}']"
        label, colour = he.FRONTEND_STYLES[fe]
        assert label, f"empty label for {fe}"
        assert colour.startswith("#"), f"non-hex colour for {fe}: {colour!r}"


# ---- helpers ---------------------------------------------------------


def test_categories_are_stable_and_unique():
    cats = he.categories()
    assert cats, "categories() must return at least one category"
    assert len(cats) == len(set(cats)), f"duplicate category: {cats}"


def test_by_category_returns_only_matching_entries():
    for cat in he.categories():
        entries = he.by_category(cat)
        assert entries, f"category {cat!r} reported but has no entries"
        for ex in entries:
            assert ex.category == cat


def test_find_known_id_returns_example():
    sample = he.EXAMPLES[0]
    found = he.find(sample.id)
    assert found is sample


def test_find_unknown_id_returns_none():
    assert he.find("does-not-exist-xyzzy") is None


def test_search_empty_returns_full_catalog():
    assert he.search("") == list(he.EXAMPLES)
    assert he.search("   ") == list(he.EXAMPLES)


def test_search_matches_id_title_tag_and_description():
    sample = he.EXAMPLES[0]
    # id match
    assert sample in he.search(sample.id)
    # title-word match
    first_word = sample.title.split()[0]
    assert sample in he.search(first_word)
    # tag match (if any)
    if sample.tags:
        assert sample in he.search(sample.tags[0])


def test_search_is_case_insensitive():
    sample = he.EXAMPLES[0]
    upper = sample.title.split()[0].upper()
    lower = upper.lower()
    assert he.search(upper) == he.search(lower)


def test_search_unknown_returns_empty():
    assert he.search("this-query-matches-nothing-xyzzy") == []


# ---- rendering -------------------------------------------------------


def test_render_one_contains_title_and_every_command():
    ex = he.EXAMPLES[0]
    out = he.render_one(ex)
    assert ex.title in out
    for step in ex.steps:
        assert step.command in out


def test_render_one_uses_frontend_colour_tags():
    ex = he.EXAMPLES[0]
    out = he.render_one(ex)
    # Each frontend's hex colour from FRONTEND_STYLES must appear in
    # the markup — that's the contract the TUI/GUI/CLI all rely on.
    for fe in _FRONTENDS:
        _label, colour = he.FRONTEND_STYLES[fe]
        assert colour in out, (
            f"render_one missing {fe} colour {colour}; got: {out[:200]}"
        )


def test_render_index_lists_every_category_and_id():
    out = he.render_index()
    for cat in he.categories():
        assert cat in out, f"render_index missing category {cat!r}"
    for ex in he.EXAMPLES:
        assert ex.id in out, f"render_index missing example {ex.id!r}"
