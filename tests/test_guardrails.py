"""Guardrail tests: consent, the value of uplift targeting, and the copy check.

Run from the project folder:  pytest tests/ -v
"""
import pytest

import core
import eval as evaluation
import offer_copywriter as copywriter


def test_no_target_list_includes_customers_without_marketing_opt_in(customers, scored_all):
    """(1) PDPA guardrail: nobody without marketing_opt_in appears in any target list."""
    assert (customers["marketing_opt_in"] == 0).sum() > 0, "test needs some opted-out customers"

    # Every strategy and budget the app offers, starting from an unfiltered score table.
    for strategy in ["uplift", "propensity", "random"]:
        for budget in [0.05, 0.20, 0.50]:
            targets = core.select_targets(scored_all, strategy, budget)
            assert len(targets) > 0
            assert (targets["marketing_opt_in"] == 1).all(), f"{strategy} @ {budget:.0%}"

    # The past test (what the models train and are evaluated on) and the holdout.
    assert (customers.loc[customers["in_test"] == 1, "marketing_opt_in"] == 1).all()
    _, holdout, _ = evaluation.evaluate(customers)
    assert (holdout["marketing_opt_in"] == 1).all()

    # The segments the offer copy is written for come from the same target list.
    allowed = set(core.select_targets(scored_all, "uplift", copywriter.BUDGET)["segment"])
    assert {s["segment"] for s in copywriter.target_segments(scored_all)} <= allowed


def test_uplift_beats_random_at_20_percent_budget(customers):
    """(2) Uplift targeting yields more measured incremental conversions than random at 20%."""
    _, holdout, _ = evaluation.evaluate(customers)
    table = evaluation.compare_strategies(holdout, budget=0.20)
    uplift, rand = table.loc["Uplift", "incremental"], table.loc["Random", "incremental"]
    assert uplift > rand, f"uplift {uplift:.0f} vs random {rand:.0f}"


@pytest.mark.parametrize("subject, body", [
    ("Guaranteed 6% cashback on Dining",
     "Earn 6% cashback on Dining when you meet the S$800 Minimum Spend Requirement, capped at "
     "S$160 per calendar month. The annual fee is waived for the first two years. T&Cs apply."),
    ("Earn 6% cashback on Dining",
     "Cashback is GUARANTEED: earn 6% on Dining when you meet the S$800 Minimum Spend "
     "Requirement, capped at S$160 per calendar month. T&Cs apply."),
])
def test_check_copy_rejects_guaranteed(subject, body):
    """(3) check_copy() rejects copy containing 'guaranteed', in the subject or body, any case."""
    results = {rule: (ok, why) for rule, ok, why in
               copywriter.check_copy(subject, body, copywriter.load_facts())}
    ok, why = results["No banned phrases"]
    assert not ok and "guaranteed" in why
