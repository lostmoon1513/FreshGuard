import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from dataset import Item, load_dataset
from report import render_report

pytest.importorskip("freshguard")

import run_benchmark as rb


def item(id="c1", expected="stale"):
    return Item(id=id, category="tech", kind="single", expected=expected, question="Q?",
                answer="Python 3.14 is the latest.", ground_truth="t", basis="durable")  # fmt: skip


def outcome(id, expected, label, status="completed", **extra):
    base = {"id": id, "expected": expected, "label": label, "status": status, "kind": "single",
            "category": "tech", "latency_s": 12.0, "confidence": 0.4, "error": None, "claims": []}  # fmt: skip
    return {**base, **extra}


def test_report_lists_harmful_misses_first_and_escapes_pipes():
    items = [item("c1", "stale"), item("c2", "fresh")]
    claims = [{"reasoning": "a | b", "evidence": [{"url": "https://x.org/a"}]}]
    outcomes = [
        outcome("c2", "fresh", "potentially_stale"),
        outcome("c1", "stale", "fresh", claims=claims),
        outcome(
            "c3", "stale", None, status="timeout", error="VerificationTimeout: slow"
        ),
    ]
    text = render_report(outcomes, items, {"run": "run-1"})
    assert "# FreshGuard benchmark report" in text and "run: run-1" in text
    assert text.index("| c1 | YES |") < text.index("| c2 |")
    assert "a / b" in text and "https://x.org/a" in text
    assert "c3: timeout" in text and "Confusion matrix" in text


def test_report_handles_no_misses():
    text = render_report([outcome("c1", "stale", "stale")], [item()])
    assert "Misses (0)" in text and "100%" in text


class FakeClient:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def submit(self, q, a, metadata=None):
        self.calls.append((q, a, metadata))
        return SimpleNamespace(id="v1")

    def wait(self, vid, timeout):
        if self.error:
            raise self.error
        return self.result


def verification(label="stale"):
    ev = SimpleNamespace(stance="contradicts", url="https://x.org", tier=2,
                         quoted_span="a quote", published_at=datetime(2026, 1, 1, tzinfo=UTC))  # fmt: skip
    neutral = SimpleNamespace(
        stance="neutral",
        url="https://n.org",
        tier=3,
        quoted_span=None,
        published_at=None,
    )
    claim = SimpleNamespace(
        text="c",
        label=label,
        volatility="slow",
        reasoning="why",
        evidence=[ev, neutral],
    )
    return SimpleNamespace(
        id="v1",
        status="completed",
        label=label,
        confidence=0.7,
        error=None,
        claims=[claim],
    )


def test_run_item_success_summarises_non_neutral_evidence():
    client = FakeClient(verification())
    out = rb.run_item(client, item(), 30, (RuntimeError,))
    assert (
        out["status"] == "completed"
        and out["label"] == "stale"
        and out["confidence"] == 0.7
    )
    assert client.calls[0][2] == {"benchmark_id": "c1"}
    ev = out["claims"][0]["evidence"]
    assert (
        len(ev) == 1
        and ev[0]["url"] == "https://x.org"
        and ev[0]["published_at"].startswith("2026")
    )
    json.dumps(out)  # must be serialisable


def test_run_item_never_raises():
    class VerificationTimeout(RuntimeError):
        pass

    out = rb.run_item(
        FakeClient(error=VerificationTimeout("slow")), item(), 30, (RuntimeError,)
    )
    assert (
        out["status"] == "timeout" and out["label"] is None and "slow" in out["error"]
    )
    out = rb.run_item(
        FakeClient(error=RuntimeError("boom")), item(), 30, (RuntimeError,)
    )
    assert out["status"] == "error"


def test_resume_helpers(tmp_path):
    path = tmp_path / "results.jsonl"
    rows = [
        outcome("c1", "stale", None, status="error"),
        outcome("c1", "stale", "stale"),
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    read = rb.read_results(path)
    assert len(read) == 2 and rb.read_results(tmp_path / "missing.jsonl") == []
    latest = rb.latest_per_id(read)
    assert len(latest) == 1 and latest[0]["label"] == "stale"


def test_write_report_end_to_end(tmp_path):
    items = load_dataset(rb.HERE / "dataset.jsonl")[:2]
    rows = [outcome(items[0].id, items[0].expected, items[0].expected)]
    (tmp_path / "results.jsonl").write_text(json.dumps(rows[0]) + "\n")
    rb.write_report(tmp_path, items, {"run": "r"})
    assert "Exact accuracy" in (tmp_path / "report.md").read_text()


def test_argument_parsing_defaults():
    args = rb.parse_args(["--limit", "5", "--kind", "static"])
    assert args.limit == 5 and args.kind == ["static"] and args.concurrency == 2


def test_runner_stops_at_first_auth_error(tmp_path, monkeypatch, capsys):
    import freshguard

    class Denied:
        def __init__(self, *a, **k):
            pass

        def health(self):
            return True

        def submit(self, *a, **k):
            raise freshguard.AuthError("Missing or invalid API key.")

        def close(self):
            pass

    monkeypatch.setattr(freshguard, "FreshGuard", Denied)
    code = rb.main(["--limit", "6", "--concurrency", "1", "--resume", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0 and "rejected the API key" in out
    assert (
        len(rb.read_results(tmp_path / "results.jsonl")) <= 2
    )  # stopped early, not all 6