import json
from collections import Counter
from pathlib import Path

import pytest

from dataset import load_dataset, parse_item, select

DATASET = Path(__file__).resolve().parent.parent / "dataset.jsonl"


def good(**over):
    base = {"id": "x1", "category": "tech", "kind": "single", "expected": "stale",
            "question": "q?", "answer": "a.", "ground_truth": "t", "basis": "durable"}  # fmt: skip
    return {**base, **over}


def test_shipped_dataset_is_valid_and_balanced():
    items = load_dataset(DATASET)
    assert 60 <= len(items) <= 100
    counts = Counter(i.expected for i in items)
    assert all(counts[label] >= 10 for label in ("fresh", "stale", "unverifiable"))
    kinds = Counter(i.kind for i in items)
    assert kinds["static"] >= 5 and kinds["unknown"] >= 5 and kinds["multi"] >= 5
    assert len({i.answer for i in items if i.kind == "single"}) > 40
    for item in items:
        assert item.verified_on == "2026-11-13"
        if item.basis == "verified" and item.source:
            assert item.source.startswith("https://")


@pytest.mark.parametrize(
    "bad,message",
    [
        ({"expected": "potentially_stale"}, "expected must be"),
        ({"kind": "weird"}, "kind must be"),
        ({"basis": "guess"}, "basis must be"),
        ({"question": " "}, "missing question"),
        ({"source": "ftp://x"}, "source must be"),
        ({"kind": "static", "expected": "stale"}, "static claims"),
        ({"kind": "unknown", "expected": "fresh"}, "unknown claims"),
    ],
)
def test_validation_rejects_bad_rows(bad, message):
    with pytest.raises(ValueError, match=message):
        parse_item(good(**bad))


def test_loader_rejects_duplicates_bad_json_and_empty(tmp_path):
    path = tmp_path / "d.jsonl"
    path.write_text(json.dumps(good()) + "\n" + json.dumps(good()) + "\n")
    with pytest.raises(ValueError, match="duplicate id"):
        load_dataset(path)
    path.write_text("{not json}\n")
    with pytest.raises(ValueError, match="invalid JSON"):
        load_dataset(path)
    path.write_text("\n\n")
    with pytest.raises(ValueError, match="empty"):
        load_dataset(path)


def test_select_filters_and_samples_evenly():
    items = load_dataset(DATASET)
    assert {i.expected for i in select(items, expected=["stale"])} == {"stale"}
    assert all(i.category == "tech" for i in select(items, categories=["tech"]))
    assert [i.id for i in select(items, ids=["c001", "c002"])] == ["c001", "c002"]
    sample = select(items, limit=10)
    assert len(sample) == 10 and len({i.expected for i in sample}) >= 2
    assert select(items, limit=1000) == items