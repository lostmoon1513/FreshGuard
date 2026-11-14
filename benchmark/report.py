"""Render a Markdown report from outcomes and the dataset."""

from __future__ import annotations

from typing import Any

from dataset import Item
from metrics import COLS, ROWS, is_harmful, summarize


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.0f}%"


def seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f}s"


def _cell(text: str, limit: int = 140) -> str:
    text = " ".join(str(text).split()).replace("|", "/")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_report(
    outcomes: list[dict[str, Any]],
    items: list[Item],
    meta: dict[str, Any] | None = None,
) -> str:
    s = summarize(outcomes)
    by_id = {i.id: i for i in items}
    meta = meta or {}
    lines = ["# FreshGuard benchmark report", ""]
    for key in ("run", "base_url", "dataset", "started", "finished"):
        if meta.get(key):
            lines.append(f"- {key}: {meta[key]}")
    lines += [
        (
            f"- claims run: {s['total']}; completed: {s['completed']}; "
            f"not completed (failed/error/timeout): {s['not_completed']}"
        ),
        "",
        "## Headline",
        "",
        f"- Exact accuracy: **{pct(s['exact_accuracy'])}**",
        (
            f"- Harmful errors: **{pct(s['harmful_error_rate'])}** "
            "(missed a stale answer, invented confidence on an unknowable claim, or false stale alarm)"
        ),
        (
            f"- Stale answers flagged (stale or potentially_stale): **{pct(s['stale']['flagged'])}** "
            f"(exactly `stale`: {pct(s['stale']['exactly_stale'])}; "
            f"**missed as fresh: {pct(s['stale']['missed_as_fresh'])}**)"
        ),
        (
            f"- Fresh answers: correct {pct(s['fresh']['correct'])}, cautious "
            f"{pct(s['fresh']['cautious'])}, false stale alarm {pct(s['fresh']['false_alarm'])}"
        ),
        (
            f"- Unknowable claims: correct {pct(s['unverifiable']['correct'])}, "
            f"invented `fresh` {pct(s['unverifiable']['invented_fresh'])}"
        ),
        f"- Latency: median {seconds(s['latency_median_s'])}, p90 {seconds(s['latency_p90_s'])}",
        "",
        "## Confusion matrix (rows: expected, columns: FreshGuard said)",
        "",
        "| expected \\ got | " + " | ".join(COLS) + " |",
        "|---|" + "---|" * len(COLS),
    ]
    for row in ROWS:
        lines.append(
            f"| **{row}** | "
            + " | ".join(str(s["matrix"][row][c]) for c in COLS)
            + " |"
        )

    lines += ["", "## By category", "", "| category | correct | n |", "|---|---|---|"]
    for key, v in s["by_category"].items():
        lines.append(f"| {key} | {v['correct']} | {v['n']} |")
    lines += ["", "## By kind", "", "| kind | correct | n |", "|---|---|---|"]
    for key, v in s["by_kind"].items():
        lines.append(f"| {key} | {v['correct']} | {v['n']} |")

    wrong = [
        o
        for o in outcomes
        if o.get("status") == "completed" and o["label"] != o["expected"]
    ]
    wrong.sort(key=lambda o: (not is_harmful(o["expected"], o["label"]), o["id"]))
    lines += ["", f"## Misses ({len(wrong)})", ""]
    if wrong:
        lines += [
            "| id | harmful | expected | got | answer | why | evidence |",
            "|---|---|---|---|---|---|---|",
        ]
    for o in wrong:
        item = by_id.get(o["id"])
        answer = item.answer if item else ""
        claim = (o.get("claims") or [{}])[0]
        urls = ", ".join(
            e["url"] for c in o.get("claims") or [] for e in c.get("evidence", [])[:2]
        )
        lines.append(
            f"| {o['id']} | {'YES' if is_harmful(o['expected'], o['label']) else ''} | "
            f"{o['expected']} | {o['label']} | {_cell(answer, 70)} | "
            f"{_cell(claim.get('reasoning', ''))} | {_cell(urls, 120)} |"
        )

    if s["not_completed_ids"]:
        lines += ["", "## Not completed", ""]
        for o in outcomes:
            if o["id"] in s["not_completed_ids"]:
                lines.append(
                    f"- {o['id']}: {o.get('status')} - {_cell(o.get('error') or '')}"
                )
    lines += [
        "",
        "## How to read this",
        "",
        (
            "- `potentially_stale` is never ground truth; it counts as 'flagged' for stale answers and as "
            "'cautious' for fresh ones."
        ),
        (
            "- Ground truth was checked on the date in `dataset.jsonl` (`verified_on`); "
            "`basis: durable` means the change cannot have reverted."
        ),
        "",
    ]
    return "\n".join(lines)