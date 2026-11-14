"""Run the FreshGuard benchmark against a RUNNING server, through the Python SDK.

    cd benchmark
    python run_benchmark.py --limit 10                  # small, representative first run
    python run_benchmark.py                             # all claims (slow: see README)
    python run_benchmark.py --resume results/run-...    # continue an interrupted run

Start the backend first (from backend/):  uvicorn app.main:app --port 8000
Results go to results/run-<time>/: results.jsonl (one line per claim, written as it finishes)
and report.md (rewritten at the end, or on Ctrl-C).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dataset import Item, load_dataset, select
from report import render_report

HERE = Path(__file__).resolve().parent
OUTAGE_LIMIT = 4  # consecutive provider-unavailable failures before the run stops


def claim_summary(verification: Any) -> list[dict[str, Any]]:
    """Compact, JSON-friendly view of a result: claim labels plus the non-neutral evidence."""
    out = []
    for claim in verification.claims:
        out.append(
            {
                "text": claim.text,
                "label": claim.label,
                "volatility": claim.volatility,
                "reasoning": claim.reasoning,
                "evidence": [
                    {
                        "stance": e.stance,
                        "url": e.url,
                        "tier": e.tier,
                        "quoted_span": e.quoted_span,
                        "published_at": e.published_at.isoformat()
                        if e.published_at
                        else None,
                    }
                    for e in claim.evidence
                    if e.stance != "neutral"
                ],
            }
        )
    return out


def run_item(
    client: Any, item: Item, timeout: float, errors: tuple[type[BaseException], ...]
) -> dict:
    """Verify one item. Never raises: failures become an outcome with a status and error."""
    base = {
        "id": item.id,
        "expected": item.expected,
        "kind": item.kind,
        "category": item.category,
    }
    started = time.monotonic()
    try:
        job = client.submit(
            item.question, item.answer, metadata={"benchmark_id": item.id}
        )
        result = client.wait(job.id, timeout=timeout)
    except errors as exc:
        name = type(exc).__name__
        status = "timeout" if name == "VerificationTimeout" else "error"
        return {**base, "status": status, "label": None, "confidence": None,
                "latency_s": round(time.monotonic() - started, 1), "error": f"{name}: {exc}",
                "claims": []}  # fmt: skip
    return {
        **base,
        "status": result.status,
        "label": result.label,
        "confidence": result.confidence,
        "latency_s": round(time.monotonic() - started, 1),
        "error": result.error,
        "verification_id": result.id,
        "claims": claim_summary(result),
    }


def read_results(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def latest_per_id(rows: list[dict]) -> list[dict]:
    """A resumed run may re-run an id; the last line for an id wins."""
    last: dict[str, dict] = {}
    for row in rows:
        last[row["id"]] = row
    return list(last.values())


def write_report(run_dir: Path, items: list[Item], meta: dict) -> None:
    outcomes = latest_per_id(read_results(run_dir / "results.jsonl"))
    (run_dir / "report.md").write_text(
        render_report(outcomes, items, meta), encoding="utf-8"
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    p.add_argument(
        "--base-url", default=os.getenv("FRESHGUARD_URL", "http://localhost:8000")
    )
    p.add_argument("--api-key", default=os.getenv("FRESHGUARD_API_KEY", ""))
    p.add_argument("--dataset", default=str(HERE / "dataset.jsonl"))
    p.add_argument("--limit", type=int, help="evenly spread sample of this many claims")
    p.add_argument("--ids", nargs="*", help="only these claim ids, e.g. c001 c002")
    p.add_argument(
        "--category", nargs="*", help="leadership government sports tech static ..."
    )
    p.add_argument(
        "--kind", nargs="*", choices=["single", "static", "unknown", "multi"]
    )
    p.add_argument("--expected", nargs="*", choices=["fresh", "stale", "unverifiable"])
    p.add_argument(
        "--concurrency", type=int, default=2, help="parallel verifications (default 2)"
    )
    p.add_argument(
        "--timeout", type=float, default=150, help="seconds to wait per claim"
    )
    p.add_argument("--resume", help="an existing results/run-... folder to continue")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    from freshguard import FreshGuard, FreshGuardError  # needs: pip install -e ../sdk

    items = load_dataset(args.dataset)
    chosen = select(items, ids=args.ids, categories=args.category, kinds=args.kind,
                    expected=args.expected, limit=args.limit)  # fmt: skip
    if not chosen:
        print("No claims match those filters.")
        return 1

    run_dir = (
        Path(args.resume)
        if args.resume
        else HERE / "results" / f"run-{datetime.now(UTC):%Y%m%d-%H%M%S}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"
    done_ids = {
        r["id"] for r in read_results(results_path) if r.get("status") == "completed"
    }
    todo = [i for i in chosen if i.id not in done_ids]
    print(f"{len(chosen)} claims selected, {len(done_ids & {i.id for i in chosen})} already done, "
          f"{len(todo)} to run (concurrency {args.concurrency}). Output: {run_dir}")  # fmt: skip

    client = FreshGuard(args.base_url, args.api_key or None, timeout=30.0)
    if not client.health():
        print(
            f"Server not reachable at {args.base_url}. Start it: uvicorn app.main:app --port 8000"
        )
        return 1

    meta = {"run": run_dir.name, "base_url": args.base_url, "dataset": Path(args.dataset).name,
            "started": datetime.now(UTC).isoformat(timespec="seconds")}  # fmt: skip
    lock = threading.Lock()
    finished = 0
    outage_streak = 0
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
            futures = {
                pool.submit(run_item, client, i, args.timeout, (FreshGuardError,)): i
                for i in todo
            }
            for future in as_completed(futures):
                outcome = future.result()
                with lock:
                    with results_path.open("a", encoding="utf-8") as handle:
                        handle.write(json.dumps(outcome, ensure_ascii=False) + "\n")
                    finished += 1
                    ok = "OK " if outcome["label"] == outcome["expected"] else "-- "
                    unavailable = outcome["status"] == "failed" and "unavailable" in (
                        outcome.get("error") or ""
                    )
                    outage_streak = outage_streak + 1 if unavailable else 0
                    print(f"[{finished}/{len(todo)}] {ok}{outcome['id']} expected={outcome['expected']} "
                          f"got={outcome['label'] or outcome['status']} ({outcome['latency_s']}s)")  # fmt: skip
                    if outage_streak >= OUTAGE_LIMIT:
                        print(
                            f"\n{OUTAGE_LIMIT} providers-unavailable failures in a row: the free-tier "
                            "quota is probably used up. Stopping. Wait for the quota to reset, then "
                            f"resume with --resume {run_dir}"
                        )
                        for pending in futures:
                            pending.cancel()
                        break
    except KeyboardInterrupt:
        print(
            "\nInterrupted: writing a report from what finished. Resume with --resume "
            + str(run_dir)
        )
    finally:
        meta["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
        write_report(run_dir, items, meta)
        client.close()
    print(f"\nReport: {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())