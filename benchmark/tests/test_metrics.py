from metrics import is_harmful, percentile, summarize


def o(
    id,
    expected,
    label,
    status="completed",
    latency=10.0,
    kind="single",
    category="tech",
):
    return {"id": id, "expected": expected, "label": label, "status": status,
            "latency_s": latency, "kind": kind, "category": category}  # fmt: skip


def test_harmful_definition():
    assert is_harmful("stale", "fresh")
    assert is_harmful("unverifiable", "fresh")
    assert is_harmful("fresh", "stale")
    assert not is_harmful("stale", "potentially_stale")
    assert not is_harmful("stale", "unverifiable")
    assert not is_harmful("fresh", "potentially_stale")
    assert not is_harmful("fresh", "fresh")


def test_summary_numbers():
    outcomes = [
        o("a", "stale", "stale"), o("b", "stale", "potentially_stale"), o("c", "stale", "fresh"),
        o("d", "stale", "unverifiable"),
        o("e", "fresh", "fresh"), o("f", "fresh", "potentially_stale"), o("g", "fresh", "stale"),
        o("h", "unverifiable", "unverifiable"), o("i", "unverifiable", "fresh"),
        o("j", "stale", None, status="timeout"),
    ]  # fmt: skip
    s = summarize(outcomes)
    assert s["total"] == 10 and s["completed"] == 9 and s["not_completed_ids"] == ["j"]
    assert s["exact_accuracy"] == 3 / 9
    assert s["harmful_error_rate"] == 3 / 9  # c, g, i
    assert s["stale"] == {"n": 4, "exactly_stale": 0.25, "flagged": 0.5,
                          "missed_as_fresh": 0.25, "missed_as_unverifiable": 0.25}  # fmt: skip
    assert s["fresh"]["correct"] == 1 / 3 and s["fresh"]["false_alarm"] == 1 / 3
    assert s["fresh"]["cautious"] == 1 / 3
    assert (
        s["unverifiable"]["correct"] == 0.5
        and s["unverifiable"]["invented_fresh"] == 0.5
    )
    assert s["matrix"]["stale"]["potentially_stale"] == 1


def test_empty_and_all_failed_do_not_divide_by_zero():
    s = summarize([])
    assert s["exact_accuracy"] is None and s["stale"]["flagged"] is None
    s = summarize([o("a", "stale", None, status="error")])
    assert s["completed"] == 0 and s["latency_median_s"] is None


def test_category_kind_and_latency():
    s = summarize([
        o("a", "fresh", "fresh", latency=5, category="leadership"),
        o("b", "fresh", "stale", latency=15, category="leadership"),
        o("c", "fresh", "fresh", latency=100, kind="static", category="static"),
    ])  # fmt: skip
    assert s["by_category"]["leadership"] == {"correct": 1, "n": 2}
    assert s["by_kind"]["static"] == {"correct": 1, "n": 1}
    assert s["latency_median_s"] == 15 and s["latency_p90_s"] == 100


def test_percentile_edges():
    assert percentile([], 90) is None
    assert percentile([7], 90) == 7
    assert percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9