"""Numerical and denominator regressions; generated counts are never measured accuracy."""

import math

import pytest

from agenttrace_outlook.accuracy_metrics import interval, metrics, upper_bound


def row(actor: str, category: str, cluster: str, eligible: bool = True) -> dict:
    return {
        "actor": actor,
        "category": category,
        "independence_cluster": cluster,
        "accuracy_eligible": eligible,
    }


def test_exact_zero_error_g1_boundary_and_empty_sample() -> None:
    assert upper_bound(0, 0) is None
    assert upper_bound(0, 3000) == pytest.approx(1 - math.pow(0.05, 1 / 3000))
    assert upper_bound(0, 3000) < 0.001 < upper_bound(0, 2994)
    assert interval(0, 0) == [None, None]


def test_exact_binomial_reference_and_symmetry() -> None:
    assert upper_bound(1, 10) == pytest.approx(0.3941633024, abs=1e-9)
    assert interval(5, 10) == pytest.approx([0.1870860284, 0.8129139716], abs=1e-9)
    assert upper_bound(10, 10) == 1


@pytest.mark.parametrize("k,n", [(True, 1), (-1, 1), (2, 1), (1, -1)])
def test_invalid_counts_cannot_create_a_bound(k, n) -> None:
    with pytest.raises(ValueError):
        upper_bound(k, n)


def test_unknown_and_human_label_agents_are_recall_misses() -> None:
    result = metrics(
        [
            row("ai_agent", "AI Agent", "a"),
            row("ai_agent", "Unknown", "b"),
            row("ai_agent", "Human", "c"),
        ]
    )
    assert result["recall"] == pytest.approx(1 / 3)
    assert result["positive_misses_including_unknown_and_human_label"] == 2
    assert result["human_label_nonhuman_messages"] == 1
    assert result["human_label_is_controller_proof"] is False


def test_ordinary_automation_and_unknown_negatives_remain_in_g1() -> None:
    result = metrics(
        [
            row("human", "Human", "a"),
            row("non_ai_automation", "AI Agent", "b"),
            row("non_ai_automation", "Unknown", "c"),
        ]
    )
    assert result["independent_negative_clusters"] == 3 and result["cluster_false_positives"] == 1
    assert result["false_alerts_per_thousand"] == pytest.approx(1000 / 3)


def test_duplicates_collapse_and_crossed_actor_templates_keep_both_denominators() -> None:
    result = metrics(
        [row("ai_agent", "AI Agent", "same")] * 100
        + [
            row("ai_agent", "Unknown", "same"),
            row("human", "Human", "same"),
            row("non_ai_automation", "AI Agent", "same"),
        ]
    )
    assert result["independent_positive_clusters"] == result["independent_negative_clusters"] == 1
    assert result["cluster_true_positives"] == 0 and result["cluster_false_positives"] == 1
    assert result["paired_actor_clusters"] == 1


def test_authored_or_unresolved_cases_never_inflate_independent_counts() -> None:
    result = metrics([row("ai_agent", "AI Agent", "fixture", False)])
    assert result["independent_positive_clusters"] == 0 and result["recall"] is None


def test_powered_generated_count_math_is_not_a_dataset_qualification() -> None:
    rows = [row("human", "Human", str(i)) for i in range(3000)]
    rows += [
        row("ai_agent", "AI Agent" if i < 990 else "Unknown", "positive" + str(i))
        for i in range(1000)
    ]
    result = metrics(rows)
    assert result["false_positive_one_sided_95_upper"] < 0.001
    assert result["recall"] == 0.99
    assert "release_accuracy_qualified" not in result  # Counts alone cannot authorize release.
