# FreshGuard benchmark (M7)

81 labeled claims (fresh / stale / unverifiable) checked against the live web on 2026-11-13.
It measures the real system through the SDK, so the backend must be running.

## Run

```powershell
# terminal 1 (backend/)
uvicorn app.main:app --port 8000

# terminal 2 (benchmark/)
pip install -e ../sdk
python run_benchmark.py --limit 10            # small, representative first run
python run_benchmark.py                       # all 81 (about 1+ hour on free-tier models)
python run_benchmark.py --resume results\run-YYYYMMDD-HHMMSS
python run_benchmark.py --category leadership --expected stale
```

Options: `--base-url`, `--api-key` (or env `FRESHGUARD_API_KEY`), `--concurrency` (default 2; keep low on free tiers),
`--timeout` (150s per claim), `--ids`, `--category`, `--kind single|static|unknown|multi`, `--expected`.

Output in `results/run-<time>/`: `results.jsonl` (one line per claim, written as it finishes) and `report.md`
(also written on Ctrl-C; resume with `--resume`). Only `completed` items are skipped on resume.

## Dataset
`dataset.jsonl`, one JSON object per line: id, category, kind, expected, question, answer, ground_truth, source, basis, claim_count, verified_on.
`basis: verified` = checked against a dated source; `durable` = the change cannot have reverted. `potentially_stale` is never ground truth.
Spot-check some entries yourself before quoting numbers publicly.

## Metrics
Exact accuracy; harmful errors (stale->fresh, unverifiable->fresh, fresh->stale); stale flagged rate; confusion matrix; per category/kind; median/p90 latency.

## Tests
`PYTHONPATH=../sdk python -m pytest tests` (runner tests skip if the SDK is not installed).