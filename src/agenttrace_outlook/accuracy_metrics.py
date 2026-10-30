"""Exact binomial limits and conservative independent-cluster sender metrics."""

from __future__ import annotations

import math
from typing import Any


def upper_bound(successes: int, trials: int, alpha: float = 0.05) -> float | None:
    """One-sided Clopper-Pearson upper limit by stable binomial-CDF inversion."""
    if (
        type(successes) is not int
        or type(trials) is not int
        or not 0 <= successes <= trials
        or not 0 < alpha < 1
    ):
        raise ValueError("invalid_binomial_counts")
    if trials == 0:
        return None
    if successes == trials:
        return 1.0
    if successes == 0:
        return -math.expm1(math.log(alpha) / trials)
    coefficients = [
        math.lgamma(trials + 1) - math.lgamma(k + 1) - math.lgamma(trials - k + 1)
        for k in range(successes + 1)
    ]
    low, high = 0.0, 1.0
    for _ in range(60):
        probability = (low + high) / 2
        log_p, log_q = math.log(probability), math.log1p(-probability)
        terms = [c + k * log_p + (trials - k) * log_q for k, c in enumerate(coefficients)]
        maximum = max(terms)
        log_cdf = maximum + math.log(math.fsum(math.exp(v - maximum) for v in terms))
        if log_cdf > math.log(alpha):
            low = probability
        else:
            high = probability
    return (low + high) / 2


def interval(successes: int, trials: int) -> list[float | None]:
    if trials == 0:
        return [None, None]
    upper = upper_bound(successes, trials, 0.025)
    complement = upper_bound(trials - successes, trials, 0.025)
    assert complement is not None
    return [1 - complement, upper]


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible = [r for r in rows if r["accuracy_eligible"]]
    clusters: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        clusters.setdefault(row["independence_cluster"], []).append(row)
    positives, negatives, tp, fp = 0, 0, 0, 0
    paired = 0
    for values in clusters.values():
        agent = [r for r in values if r["actor"] == "ai_agent"]
        other = [r for r in values if r["actor"] != "ai_agent"]
        paired += bool(agent and other)
        if agent:
            positives += 1
            tp += all(r["category"] == "AI Agent" for r in agent)
        if other:
            negatives += 1
            fp += any(r["category"] == "AI Agent" for r in other)
    calls = [r for r in eligible if r["category"] == "AI Agent"]
    message_tp = sum(r["actor"] == "ai_agent" for r in calls)
    n = len(eligible)
    return {
        "eligible_messages": n,
        "independent_positive_clusters": positives,
        "independent_negative_clusters": negatives,
        "paired_actor_clusters": paired,
        "cross_class_independence_claimed": False,
        "cluster_true_positives": tp,
        "cluster_false_positives": fp,
        "positive_misses_including_unknown_and_human_label": positives - tp,
        "recall": tp / positives if positives else None,
        "recall_exact_95_interval": interval(tp, positives),
        "false_positive_rate": fp / negatives if negatives else None,
        "false_positive_one_sided_95_upper": upper_bound(fp, negatives),
        "false_alerts_per_thousand": 1000 * fp / negatives if negatives else None,
        "message_precision": message_tp / len(calls) if calls else None,
        "unknown_messages": sum(r["category"] == "Unknown" for r in eligible),
        "unknown_fraction": sum(r["category"] == "Unknown" for r in eligible) / n if n else None,
        "human_label_nonhuman_messages": sum(
            r["category"] == "Human" and r["actor"] != "human" for r in eligible
        ),
        "human_label_is_controller_proof": False,
        "quarantined_or_pilot_messages": len(rows) - n,
        "quarantined_agent_labels": sum(
            not r["accuracy_eligible"] and r["actor"] == "ai_agent" for r in rows
        ),
    }
