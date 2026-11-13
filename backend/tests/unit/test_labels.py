import pytest

from app.schemas import Label, SourceTier, worst_label


def test_label_values_are_exactly_the_four_documented_labels():
    assert {label.value for label in Label} == {
        "fresh",
        "stale",
        "potentially_stale",
        "unverifiable",
    }


def test_severity_order():
    assert (
        Label.STALE.severity
        > Label.POTENTIALLY_STALE.severity
        > Label.UNVERIFIABLE.severity
        > Label.FRESH.severity
    )


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        ([Label.FRESH, Label.FRESH], Label.FRESH),
        ([Label.FRESH, Label.UNVERIFIABLE], Label.UNVERIFIABLE),
        ([Label.UNVERIFIABLE, Label.POTENTIALLY_STALE], Label.POTENTIALLY_STALE),
        ([Label.FRESH, Label.POTENTIALLY_STALE, Label.STALE], Label.STALE),
        ([Label.STALE], Label.STALE),
    ],
)
def test_worst_label(labels, expected):
    assert worst_label(labels) == expected


def test_worst_label_of_nothing_is_unverifiable_not_fresh():
    assert worst_label([]) == Label.UNVERIFIABLE


def test_source_tiers_are_ordered_by_trust():
    assert SourceTier.TIER_1 < SourceTier.TIER_2 < SourceTier.TIER_3
