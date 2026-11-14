"""Load and validate the benchmark dataset (dataset.jsonl, one JSON object per line)."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

LABELS = ("fresh", "stale", "potentially_stale", "unverifiable")
EXPECTED_LABELS = (
    "fresh",
    "stale",
    "unverifiable",
)  # ground truth never says "potentially_stale"
KINDS = ("single", "static", "unknown", "multi")
BASES = ("verified", "durable")
REQUIRED = (
    "id",
    "category",
    "kind",
    "expected",
    "question",
    "answer",
    "ground_truth",
    "basis",
)


@dataclass(frozen=True)
class Item:
    id: str
    category: str
    kind: str
    expected: str
    question: str
    answer: str
    ground_truth: str
    basis: str  # "verified": checked against a dated source; "durable": cannot have reverted
    source: str | None = None
    claim_count: int = 1
    verified_on: str | None = None


def parse_item(data: dict, where: str = "item") -> Item:
    missing = [k for k in REQUIRED if not str(data.get(k, "")).strip()]
    if missing:
        raise ValueError(f"{where}: missing {', '.join(missing)}")
    if data["expected"] not in EXPECTED_LABELS:
        raise ValueError(
            f"{where}: expected must be one of {EXPECTED_LABELS}, got {data['expected']!r}"
        )
    if data["kind"] not in KINDS:
        raise ValueError(f"{where}: kind must be one of {KINDS}")
    if data["basis"] not in BASES:
        raise ValueError(f"{where}: basis must be one of {BASES}")
    source = data.get("source")
    if source is not None and not str(source).startswith(("http://", "https://")):
        raise ValueError(f"{where}: source must be an http(s) URL or null")
    if data["kind"] == "static" and data["expected"] != "fresh":
        raise ValueError(f"{where}: static claims are expected to be fresh")
    if data["kind"] == "unknown" and data["expected"] != "unverifiable":
        raise ValueError(f"{where}: unknown claims are expected to be unverifiable")
    return Item(
        id=str(data["id"]),
        category=str(data["category"]),
        kind=str(data["kind"]),
        expected=str(data["expected"]),
        question=str(data["question"]),
        answer=str(data["answer"]),
        ground_truth=str(data["ground_truth"]),
        basis=str(data["basis"]),
        source=source,
        claim_count=int(data.get("claim_count", 1)),
        verified_on=data.get("verified_on"),
    )


def load_dataset(path: Path | str) -> list[Item]:
    items: list[Item] = []
    seen: set[str] = set()
    for number, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        where = f"{Path(path).name}:{number}"
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{where}: invalid JSON ({exc.msg})") from None
        item = parse_item(data, where)
        if item.id in seen:
            raise ValueError(f"{where}: duplicate id {item.id}")
        seen.add(item.id)
        items.append(item)
    if not items:
        raise ValueError("dataset is empty")
    return items


def select(
    items: Iterable[Item],
    *,
    ids: Iterable[str] | None = None,
    categories: Iterable[str] | None = None,
    kinds: Iterable[str] | None = None,
    expected: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[Item]:
    """Filter, then (if `limit`) take an evenly spread sample so small runs stay representative."""
    chosen = list(items)
    if ids:
        wanted = set(ids)
        chosen = [i for i in chosen if i.id in wanted]
    if categories:
        chosen = [i for i in chosen if i.category in set(categories)]
    if kinds:
        chosen = [i for i in chosen if i.kind in set(kinds)]
    if expected:
        chosen = [i for i in chosen if i.expected in set(expected)]
    if limit is not None and 0 < limit < len(chosen):
        step = len(chosen) / limit
        chosen = [chosen[int(n * step)] for n in range(limit)]
    return chosen