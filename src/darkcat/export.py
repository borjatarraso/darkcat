"""Export darkcat findings to interchange formats.

Formats:
    jsonl   newline-delimited JSON (one object per finding)
    stix    STIX 2.1 bundle of Indicator objects
    misp    MISP event JSON with Attribute list

These are minimal-but-valid serializations; downstream platforms (TIPs, SOC
playbooks, MISP servers, OpenCTI) will accept them. We store SHA-256
digests of leaked secrets, so the IOC pattern is hash-based by default —
sharing a feed never leaks the underlying credential.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Iterable, Iterator


def _iso(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def _stix_id(prefix: str) -> str:
    return f"{prefix}--{uuid.uuid4()}"


def _label_for(category: str) -> list[str]:
    if category == "email_password":
        return ["compromised-credentials"]
    if category in (
        "aws_access_key", "aws_secret_key", "github_token", "slack_token",
        "stripe_key", "google_api_key", "discord_token", "jwt",
        "private_key", "pgp_block", "seed_phrase",
    ):
        return ["compromised-key"]
    if category == "credit_card":
        return ["fraud"]
    if category in ("sql_dump", "breach_marker"):
        return ["data-leak"]
    return ["malicious-activity"]


def to_jsonl(rows: Iterable) -> Iterator[str]:
    for r in rows:
        d = dict(r)
        if d.get("found_at"):
            d["found_at_iso"] = _iso(d["found_at"])
        yield json.dumps(d, ensure_ascii=False)


def to_stix(rows: Iterable) -> str:
    now = _iso(time.time())
    objs: list[dict] = []
    for r in rows:
        ts = _iso(r["found_at"]) if r["found_at"] else now
        digest = r["digest"]
        objs.append({
            "type": "indicator",
            "spec_version": "2.1",
            "id": _stix_id("indicator"),
            "created": ts,
            "modified": ts,
            "valid_from": ts,
            "name": f"darkcat:{r['category']}",
            "description": (
                f"target={r['target'] or '-'} "
                f"url={r['url']} sample={r['sample']}"
            ),
            "pattern": f"[file:hashes.'SHA-256' = '{digest}']",
            "pattern_type": "stix",
            "labels": _label_for(r["category"]),
            "confidence": int((r["confidence"] or 0) * 100),
        })
    bundle = {
        "type": "bundle",
        "id": _stix_id("bundle"),
        "objects": objs,
    }
    return json.dumps(bundle, ensure_ascii=False, indent=2)


def to_misp(rows: Iterable) -> str:
    attrs: list[dict] = []
    for r in rows:
        bits = [r["category"]]
        if r["target"]:
            bits.append(f"target={r['target']}")
        bits.append(f"url={r['url']}")
        comment = " | ".join(bits)
        attrs.append({
            "type": "sha256",
            "category": "Other",
            "value": r["digest"],
            "comment": comment,
            "to_ids": True,
        })
        if r["category"] == "email_password" and r["target"]:
            attrs.append({
                "type": "domain",
                "category": "Network activity",
                "value": r["target"],
                "comment": f"darkcat:{r['category']}",
                "to_ids": False,
            })
    event = {
        "Event": {
            "info": f"Darkcat findings export {datetime.now(timezone.utc).date()}",
            "Attribute": attrs,
        }
    }
    return json.dumps(event, ensure_ascii=False, indent=2)
