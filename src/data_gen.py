"""Synthetic customers and a simulated past randomised campaign for the OCBC 365 card.

ALL DATA HERE IS SYNTHETIC. No real customer data is used or implied.

Run from the project folder:  python src/data_gen.py
Writes: data/synthetic/customers.csv

The response pattern is planted on purpose so the evaluation has a known answer:
- Baseline conversion averages about 3%. It is higher for "sure things"
  (already hold an OCBC card, long tenure, open emails), who convert with or
  without the offer.
- The offer adds 6 points ONLY for persuadables: high card spend AND high app
  engagement. Everyone else gets 0 uplift.
"""
import os

import numpy as np
import pandas as pd
from faker import Faker

OUT_PATH = "data/synthetic/customers.csv"

BASELINE_RATE = 0.03        # ASSUMPTION: average take-up without an offer
OFFER_LIFT = 0.06           # ASSUMPTION: extra take-up for persuadables when offered
HIGH_SPEND = 1_200          # S$/month total card spend. ASSUMPTION, not an OCBC figure
HIGH_APP_LOGINS = 10        # logins/month. ASSUMPTION


def _sigmoid(x):
    """Logistic function."""
    return 1 / (1 + np.exp(-x))


def _demographics(rng, n):
    """Age, residency, income and tenure.

    ASSUMPTION: rough Singapore-like mix (70% citizens, 15% PRs, 15% foreigners).
    Not taken from census data.
    """
    age = rng.integers(18, 76, n)
    residency = rng.choice(["SC", "PR", "Foreigner"], n, p=[0.70, 0.15, 0.15])
    # income peaks in the 40s; lognormal around S$55k at peak
    age_effect = -((age - 45) / 25) ** 2
    income = np.exp(rng.normal(np.log(55_000) + 0.5 * age_effect, 0.55))
    income = np.round(income, -2)
    tenure = np.minimum(rng.gamma(2.0, 40, n), (age - 17) * 12).astype(int) + 1
    return pd.DataFrame({"age": age, "residency": residency,
                         "annual_income": income, "tenure_months": tenure})


def _holdings(rng, df):
    """Existing OCBC products. Longer tenure means more likely to hold them."""
    tenure_z = (df["tenure_months"] - df["tenure_months"].mean()) / df["tenure_months"].std()
    return pd.DataFrame({
        "holds_ocbc_card": rng.random(len(df)) < _sigmoid(-0.9 + 0.6 * tenure_z),
        "holds_360_account": rng.random(len(df)) < _sigmoid(-1.2 + 0.4 * tenure_z),
    }).astype(int)


def _spend(rng, df):
    """Monthly card spend (S$) by category, scaled by income.

    The categories follow the OCBC 365 bonus categories in data/product_facts.md
    (F1: Dining, Groceries, Land Transport, Petrol). Online shopping and other
    spend earn only the base rate (F5).
    ASSUMPTION: shares of income and car ownership (about 15%) are invented.
    """
    n = len(df)
    scale = df["annual_income"].to_numpy() / 12 * rng.lognormal(0, 0.5, n)
    has_car = rng.random(n) < 0.15
    spend = pd.DataFrame({
        "spend_dining": scale * rng.beta(2, 18, n),
        "spend_groceries": scale * rng.beta(2, 25, n),
        "spend_land_transport": scale * rng.beta(1.5, 60, n),
        "spend_petrol": np.where(has_car, scale * rng.beta(2, 40, n), 0.0),
        "spend_online": scale * rng.beta(1.5, 25, n),
        "spend_other": scale * rng.beta(2, 20, n),
    }).round(0)
    spend["spend_total"] = spend.sum(axis=1)
    return spend


def _engagement(rng, df):
    """App logins per month and email open rate (0-1).

    App use is higher for younger customers; email opens rise with tenure.
    """
    young = (df["age"] < 40).to_numpy()
    logins = rng.poisson(np.where(young, 11, 6))
    tenure_z = ((df["tenure_months"] - df["tenure_months"].mean())
                / df["tenure_months"].std()).to_numpy()
    email = rng.beta(2 + np.clip(tenure_z, -1, 2), 6)
    return pd.DataFrame({"app_logins_month": logins, "email_open_rate": email.round(3)})


def is_eligible(df):
    """Card eligibility from data/product_facts.md F12-F14 (age, income, residency).

    ASSUMPTION: simplified. Real approval also involves credit-bureau checks,
    income documents and MAS credit card rules, none of which are modelled.
    Customers under 21 are not eligible.
    """
    local = df["residency"].isin(["SC", "PR"])
    inc, age = df["annual_income"], df["age"]
    return ((local & age.between(21, 55) & (inc >= 30_000))
            | (local & (age > 55) & (inc >= 15_000))
            | (~local & (age >= 21) & (inc >= 45_000)))


def generate_customers(n=20_000, seed=42):
    """Return a DataFrame of n synthetic customers with ids, names and features.

    `name` comes from Faker and is for display only. It is never a model feature
    and is never sent to Claude.
    """
    rng = np.random.default_rng(seed)
    df = _demographics(rng, n)
    df = pd.concat([df, _holdings(rng, df), _spend(rng, df), _engagement(rng, df)], axis=1)
    fake = Faker("en_GB")
    fake.seed_instance(seed)
    df.insert(0, "name", [fake.name() for _ in range(n)])
    df.insert(0, "customer_id", [f"C{i:05d}" for i in range(1, n + 1)])
    df["eligible"] = is_eligible(df).astype(int)
    return df


def _baseline_prob(df):
    """P(convert | no offer). Sure-thing traits raise it; mean set to BASELINE_RATE."""
    z = lambda c: (df[c] - df[c].mean()) / df[c].std()
    score = (1.2 * df["holds_ocbc_card"] + 0.6 * z("email_open_rate")
             + 0.4 * z("tenure_months")).to_numpy()
    lo, hi = -10.0, 0.0                     # bisection on the intercept
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _sigmoid(mid + score).mean() < BASELINE_RATE else (lo, mid)
    return _sigmoid(lo + score)


def simulate_campaign(df, seed=7):
    """Add a past 50/50 randomised test among eligible customers.

    Adds columns:
      in_test      1 if the customer was in the test (eligible only)
      treated      1 if they got the offer (random, 50/50 within the test)
      persuadable  planted ground truth: high spend AND high app engagement
      true_uplift  planted effect of the offer. Used for sanity checks only,
                   never as a model feature.
      converted    1 if they applied and were approved within 30 days
    """
    rng = np.random.default_rng(seed)
    df = df.copy()
    df["in_test"] = df["eligible"]
    df["treated"] = ((rng.random(len(df)) < 0.5) & (df["in_test"] == 1)).astype(int)
    df["persuadable"] = ((df["spend_total"] >= HIGH_SPEND)
                         & (df["app_logins_month"] >= HIGH_APP_LOGINS)).astype(int)
    df["true_uplift"] = OFFER_LIFT * df["persuadable"]
    p = _baseline_prob(df) + df["treated"] * df["true_uplift"]
    df["converted"] = ((rng.random(len(df)) < p) & (df["in_test"] == 1)).astype(int)
    return df


def main():
    """Generate, simulate, save, and print a sanity summary."""
    df = simulate_campaign(generate_customers())
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    df.to_csv(OUT_PATH, index=False)
    test = df[df["in_test"] == 1]
    print(f"wrote {OUT_PATH}: {df.shape[0]:,} rows x {df.shape[1]} cols")
    print(f"eligible / in test: {len(test):,} ({len(test) / len(df):.0%})")
    print(f"treated / control: {test['treated'].sum():,} / {(1 - test['treated']).sum():,}")
    print(f"persuadable share of test: {test['persuadable'].mean():.1%}\n")
    print(df.head(5).to_string(max_colwidth=18), "\n")
    rates = (test.groupby(["persuadable", "treated"])["converted"]
             .agg(["size", "mean"]).rename(columns={"size": "n", "mean": "conv_rate"}))
    print("Conversion by group x arm (expect ~3%/3% outside, ~9% vs ~3% inside):")
    print(rates.assign(conv_rate=rates["conv_rate"].map("{:.1%}".format)))
    print(f"\nOverall control conversion: {test.loc[test.treated == 0, 'converted'].mean():.1%}")
    print("Baseline by holds_ocbc_card (control only):")
    print(test[test.treated == 0].groupby("holds_ocbc_card")["converted"].mean()
          .map("{:.1%}".format).to_string())


if __name__ == "__main__":
    main()
