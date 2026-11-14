"""Benchmark metrics. Pure functions: outcomes in, numbers out. No I/O, no network.

An outcome is a dict (one line of results.jsonl) with at least:
  id, expected, kind, category, status ("completed" | "failed" | "error" | "timeout"),
  label (None unless completed), latency_s.

Terms (E = what a perfect checker would say, G = what FreshGuard said):
  harmful error   E=stale & G=fresh   (missed a stale answer: the dangerous one)
                  E=unverifiable & G=fresh   (invented confidence)
                  E=fresh & G=stale   (false alarm)
  cautious        G=potentially_stale or unverifiable when E=fresh: unhelpful, not harmful
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from typing import Any

ROWS = ("fresh", "stale", "unverifiable")  # expected
COLS = ("fresh", "stale", "potentially_stale", "unverifiable")  # actual


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def is_harmful(expected: str, got: str) -> bool:
    return (
        (expected == "stale" and got == "fresh")
        or (expected == "unverifiable" and got == "fresh")
        or (expected == "fresh" and got == "stale")
    )


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def summarize(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    done = [o for o in outcomes if o.get("status") == "completed" and o.get("label")]
    not_done = [o for o in outcomes if o not in done]

    matrix: dict[str, Counter] = {row: Counter() for row in ROWS}
    for o in done:
        matrix[o["expected"]][o["label"]] += 1

    def count(expected: str, *labels: str) -> int:
        return sum(matrix[expected][label] for label in labels)

    n_fresh, n_stale, n_unk = (sum(matrix[r].values()) for r in ROWS)
    exact = sum(1 for o in done if o["label"] == o["expected"])
    harmful = sum(1 for o in done if is_harmful(o["expected"], o["label"]))

    by_category: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    by_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for o in done:
        hit = int(o["label"] == o["expected"])
        for table, key in (
            (by_category, o.get("category", "?")),
            (by_kind, o.get("kind", "?")),
        ):
            table[key][0] += hit
            table[key][1] += 1

    latencies = [float(o["latency_s"]) for o in done if o.get("latency_s") is not None]
    return {
        "total": len(outcomes),
        "completed": len(done),
        "not_completed": len(not_done),
        "not_completed_ids": [o["id"] for o in not_done],
        "exact_accuracy": rate(exact, len(done)),
        "harmful_error_rate": rate(harmful, len(done)),
        "matrix": {row: {col: matrix[row][col] for col in COLS} for row in ROWS},
        "stale": {
            "n": n_stale,
            "exactly_stale": rate(count("stale", "stale"), n_stale),
            "flagged": rate(count("stale", "stale", "potentially_stale"), n_stale),
            "missed_as_fresh": rate(count("stale", "fresh"), n_stale),
            "missed_as_unverifiable": rate(count("stale", "unverifiable"), n_stale),
        },
        "fresh": {
            "n": n_fresh,
            "correct": rate(count("fresh", "fresh"), n_fresh),
            "cautious": rate(
                count("fresh", "potentially_stale", "unverifiable"), n_fresh
            ),
            "false_alarm": rate(count("fresh", "stale"), n_fresh),
        },
        "unverifiable": {
            "n": n_unk,
            "correct": rate(count("unverifiable", "unverifiable"), n_unk),
            "invented_fresh": rate(count("unverifiable", "fresh"), n_unk),
            "false_alarm": rate(
                count("unverifiable", "stale", "potentially_stale"), n_unk
            ),
        },
        "by_category": {
            k: {"correct": v[0], "n": v[1]} for k, v in sorted(by_category.items())
        },
        "by_kind": {
            k: {"correct": v[0], "n": v[1]} for k, v in sorted(by_kind.items())
        },
        "latency_median_s": statistics.median(latencies) if latencies else None,
        "latency_p90_s": percentile(latencies, 90),
    }