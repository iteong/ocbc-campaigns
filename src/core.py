"""Propensity model, two-model uplift estimate, per-customer drivers and segments.

Run from the project folder:  python src/core.py
Reads data/synthetic/customers.csv (create it with python src/data_gen.py).

How uplift is computed (two-model approach):
  uplift(x) = P(convert | x, offered)     from model T, fit on treated customers
            - P(convert | x, not offered) from model C, fit on control customers
It estimates the extra chance of conversion that the offer itself causes.
Positive means persuadable. About 0 means they convert (or don't) regardless.
This only works because the past campaign was randomised: treated and
control customers are alike apart from the offer.

Every score is explainable. All three models are logistic regressions on the
same standardised features, so each feature's pull on a score is just
coefficient x scaled value.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

DATA_PATH = "data/synthetic/customers.csv"
BONUS_CATEGORIES = ["dining", "groceries", "land_transport", "petrol"]  # product_facts.md F1

# Model inputs. Spend enters as size (log of total) plus where it goes (shares),
# so coefficients don't fight over a sum of correlated category amounts.
# Name, id, residency text and the planted columns are never inputs.
FEATURES = [
    "age", "log_income", "tenure_months", "is_foreigner",
    "holds_ocbc_card", "holds_360_account",
    "log_spend_total", "share_dining", "share_groceries",
    "share_land_transport", "share_petrol", "share_online",
    "app_logins_month", "email_open_rate", "spend_x_app",
]

# Plain-English names for drivers: (label when high, label when low, raw column, format)
LABELS = {
    "age": ("Older", "Younger", "age", "{:.0f} yrs"),
    "log_income": ("Higher income", "Lower income", "annual_income", "S${:,.0f}/yr"),
    "tenure_months": ("Long-standing customer", "Newer customer", "tenure_months", "{:.0f} months"),
    "is_foreigner": ("Foreigner", "Singaporean/PR", None, None),
    "holds_ocbc_card": ("Already holds an OCBC card", "No OCBC card yet", None, None),
    "holds_360_account": ("Has a 360 Account", "No 360 Account", None, None),
    "log_spend_total": ("High card spend", "Low card spend", "spend_total", "S${:,.0f}/month"),
    "share_dining": ("Dines out a lot", "Little dining spend", "share_dining", "{:.0%} of spend"),
    "share_groceries": ("Grocery-heavy spend", "Little grocery spend", "share_groceries", "{:.0%} of spend"),
    "share_land_transport": ("Heavy transport spend", "Little transport spend",
                             "share_land_transport", "{:.0%} of spend"),
    "share_petrol": ("Spends on petrol", "No petrol spend", "share_petrol", "{:.0%} of spend"),
    "share_online": ("Shops online a lot", "Little online spend", "share_online", "{:.0%} of spend"),
    "app_logins_month": ("High app engagement", "Low app engagement",
                         "app_logins_month", "{:.0f} logins/month"),
    "email_open_rate": ("Opens most emails", "Rarely opens emails", "email_open_rate", "{:.0%} opened"),
    "spend_x_app": ("High spend AND high app use", "Not both high spend and app use", None, None),
}


@dataclass
class Models:
    """The three fitted models plus the scaler shared by the uplift pair."""
    propensity: Pipeline   # P(convert), all test customers, no treatment flag
    treated: Pipeline      # model T: P(convert | offered)
    control: Pipeline      # model C: P(convert | not offered)


def load_customers(path=DATA_PATH):
    """Read the synthetic customer file."""
    return pd.read_csv(path)


def build_features(df):
    """Return df with the derived model inputs added (logs, spend shares, flags)."""
    out = df.copy()
    total = out["spend_total"].clip(lower=1)
    out["log_income"] = np.log(out["annual_income"].clip(lower=1))
    out["log_spend_total"] = np.log1p(out["spend_total"])
    for cat in BONUS_CATEGORIES + ["online"]:
        out[f"share_{cat}"] = out[f"spend_{cat}"] / total
    out["is_foreigner"] = (out["residency"] == "Foreigner").astype(int)
    # Interaction: card spend (S$ thousands/month) x app logins. Lets a linear
    # model say "big spenders who also use the app" respond more to the offer
    # than either trait alone would suggest.
    out["spend_x_app"] = out["spend_total"] / 1000 * out["app_logins_month"]
    return out


def _new_lr():
    """Same settings for every model so their coefficients are comparable.

    C=0.01 is strong L2 regularisation. Uplift is a difference of two models,
    so noise in either shows up as fake drivers. Shrinking the coefficients cut
    that noise and ranked persuadables better on a held-out split
    (C=1: 54% of the top 20% were true persuadables; C=0.01 with spend_x_app: 64%).
    """
    return LogisticRegression(C=0.01, max_iter=2000)


def _scaler():
    """StandardScaler that keeps column names, so the models see named features."""
    return StandardScaler().set_output(transform="pandas")


def fit_models(train):
    """Fit propensity and two-model uplift on test customers in `train`.

    The uplift pair shares ONE scaler fit on all training customers. Separate
    Pipelines would each fit their own scaler on their own half, putting the
    coefficients on different scales so they could not be subtracted to
    explain uplift.
    """
    train = build_features(train[train["in_test"] == 1])
    X, y, t = train[FEATURES], train["converted"], train["treated"] == 1

    propensity = Pipeline([("scale", _scaler()), ("lr", _new_lr())]).fit(X, y)

    scaler = _scaler().fit(X)
    Xs = scaler.transform(X)
    lr_t = _new_lr().fit(Xs[t], y[t])
    lr_c = _new_lr().fit(Xs[~t], y[~t])
    # Pipelines built from already-fitted steps: predict without refitting
    treated = Pipeline([("scale", scaler), ("lr", lr_t)])
    control = Pipeline([("scale", scaler), ("lr", lr_c)])
    return Models(propensity, treated, control)


def coefficients(models):
    """Coefficient table (log-odds per 1 std dev) for all models, plus T - C."""
    coef = lambda p: p.named_steps["lr"].coef_[0]
    table = pd.DataFrame({
        "propensity": coef(models.propensity),
        "treated_T": coef(models.treated),
        "control_C": coef(models.control),
    }, index=FEATURES)
    table["uplift_T_minus_C"] = table["treated_T"] - table["control_C"]
    return table.round(3)


def driver_contributions(models, df):
    """Per-customer, per-feature pull on uplift: (coef_T - coef_C) x scaled value.

    Exact in log-odds: the sum over features is logit(P_T) - logit(P_C) minus
    the intercept gap. It is only an approximation of each feature's share of
    the probability difference (uplift), which is fine for ranking reasons.
    """
    xs = _scaled(models, df)
    diff = (models.treated.named_steps["lr"].coef_[0]
            - models.control.named_steps["lr"].coef_[0])
    return xs * diff


def _scaled(models, df):
    """Customers' features on the shared uplift scale (std devs from the mean)."""
    return models.treated.named_steps["scale"].transform(build_features(df)[FEATURES])


def _reason(feature, scaled_value, row):
    """Plain-English reason, e.g. 'High app engagement (14 logins/month)'."""
    high, low, col, fmt = LABELS[feature]
    text = high if scaled_value > 0 else low
    return f"{text} ({fmt.format(row[col])})" if col else text


def top_drivers(models, df, k=3):
    """Return the k features that raise each customer's uplift most, as text.

    Only positive pulls count. If a customer has fewer than k, the rest are "".
    """
    contrib = driver_contributions(models, df)
    scaled, feats = _scaled(models, df), build_features(df)
    order = np.argsort(-contrib.to_numpy(), axis=1)[:, :k]
    out = {}
    for j in range(k):
        cols = [FEATURES[i] for i in order[:, j]]
        out[f"driver_{j + 1}"] = [
            _reason(f, scaled.at[idx, f], feats.loc[idx]) if contrib.at[idx, f] > 0 else ""
            for idx, f in zip(df.index, cols)]
    return pd.DataFrame(out, index=df.index)


def assign_segment(row):
    """Rule-based copy segment from where the customer's card spend goes.

    Rule: if online spend beats every 6% bonus category, "Frequent online
    shopper". Otherwise the largest 6% category (product_facts.md F1) names
    the segment.
    """
    bonus = {c: row[f"spend_{c}"] for c in BONUS_CATEGORIES}
    top = max(bonus, key=bonus.get)
    if row["spend_online"] > bonus[top]:
        return "Frequent online shopper"
    return {
        "dining": "High spender who dines out",
        "groceries": "Grocery-heavy household",
        "land_transport": "Daily commuter",
        "petrol": "Driver who pays for petrol",
    }[top]


def score_customers(models, df, k=3):
    """Return df plus propensity, p_treated, p_control, uplift, drivers and segment."""
    X = build_features(df)[FEATURES]
    out = df.copy()
    out["propensity"] = models.propensity.predict_proba(X)[:, 1]
    out["p_treated"] = models.treated.predict_proba(X)[:, 1]
    out["p_control"] = models.control.predict_proba(X)[:, 1]
    out["uplift"] = out["p_treated"] - out["p_control"]
    out = out.join(top_drivers(models, df, k))
    out["segment"] = df.apply(assign_segment, axis=1)
    return out


def main():
    """Fit on all test customers (the 70/30 split lives in eval.py) and print samples."""
    df = load_customers()
    models = fit_models(df)
    print("Coefficients (log-odds per 1 std dev; positive = raises the score):")
    print(coefficients(models).sort_values("uplift_T_minus_C", ascending=False).to_string(), "\n")

    scored = score_customers(models, df[df["eligible"] == 1])
    print("Predicted uplift by planted group (sanity check; the model never saw this):")
    print(scored.groupby("persuadable")["uplift"].describe()[["mean", "25%", "50%", "75%"]]
          .map("{:+.3f}".format).to_string(), "\n")

    cols = ["customer_id", "name", "segment", "propensity", "uplift", "driver_1", "driver_2"]
    top = scored.sort_values("uplift", ascending=False)
    fmt = {"propensity": "{:.1%}".format, "uplift": "{:+.1%}".format}
    print("Top 5 by uplift:")
    print(top[cols].head(5).to_string(index=False, formatters=fmt), "\n")
    print("Top 5 by propensity (note who these are):")
    print(scored.sort_values("propensity", ascending=False)[cols + ["holds_ocbc_card"]]
          .head(5).to_string(index=False, formatters=fmt), "\n")
    print("Segments among the top 20% by uplift:")
    print(top.head(len(top) // 5)["segment"].value_counts().to_string())


if __name__ == "__main__":
    main()
