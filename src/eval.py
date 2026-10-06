"""Compare propensity, uplift and random targeting on a held-out 30% of the past test.

Run from the project folder:  python src/eval.py
Writes: data/generated/eval.html (the comparison chart, to open in a browser)

Incremental conversions for a targeted group are measured the way a campaign
team would, from the randomised test:
  (conversion rate of treated - conversion rate of control, within the group)
  x group size
That estimates how many extra conversions offering the card to everyone in
the group would have caused. The planted `true_uplift` sum (known only because
the data is synthetic) is shown alongside as a sanity check.
"""
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

import core

CHART_PATH = "data/generated/eval.html"
HOLDOUT = 0.30
RANDOM_DRAWS = 200
COLORS = {"measured": "#2a78d6", "planted": "#eb6834"}  # dataviz categorical slots 1, 2


def split_holdout(df, test_size=HOLDOUT, seed=42):
    """Split test customers 70/30, stratified on treated x converted.

    Stratifying on both keeps each arm and its ~3% conversion rate in the same
    proportions in train and holdout, which matters with so few conversions.
    """
    test = df[df["in_test"] == 1]
    strata = test["treated"] * 2 + test["converted"]
    return train_test_split(test, test_size=test_size, random_state=seed, stratify=strata)


def evaluate(df=None):
    """Fit on the 70% and score the 30%. Returns (models, scored holdout, AUC)."""
    df = core.load_customers() if df is None else df
    train, holdout = split_holdout(df)
    models = core.fit_models(train)
    scored = core.score_customers(models, holdout)
    auc = roc_auc_score(scored["converted"], scored["propensity"])
    return models, scored, auc


def incremental(group):
    """Measured incremental conversions in a group, with its 95% margin of error."""
    t, c = group[group["treated"] == 1], group[group["treated"] == 0]
    rt, rc = t["converted"].mean(), c["converted"].mean()
    se = np.sqrt(rt * (1 - rt) / len(t) + rc * (1 - rc) / len(c))
    n = len(group)
    return {"n": n, "n_treated": len(t), "n_control": len(c),
            "conv_treated": rt, "conv_control": rc,
            "incremental": (rt - rc) * n, "margin_95": 1.96 * se * n,
            "planted_incremental": group["true_uplift"].sum(),
            "persuadable_share": group["persuadable"].mean()}


def compare_strategies(scored, budget=0.20, seed=0):
    """Table of incremental conversions when targeting the top `budget` share.

    Propensity and uplift take the top-ranked customers. Random is averaged
    over RANDOM_DRAWS seeded draws so it isn't one lucky or unlucky sample.
    """
    k = int(len(scored) * budget)
    rows = {
        "Propensity": incremental(scored.nlargest(k, "propensity")),
        "Uplift": incremental(scored.nlargest(k, "uplift")),
    }
    rng = np.random.default_rng(seed)
    draws = [incremental(scored.iloc[rng.choice(len(scored), k, replace=False)])
             for _ in range(RANDOM_DRAWS)]
    rows["Random"] = pd.DataFrame(draws).mean().to_dict()
    rows["Random"]["margin_95"] = 1.96 * pd.DataFrame(draws)["incremental"].std()
    table = pd.DataFrame(rows).T
    table.index.name = "strategy"
    return table


def strategy_chart(table, budget=0.20):
    """Plotly grouped bar: measured incremental conversions (with 95% error bars) vs planted."""
    fig = go.Figure()
    fig.add_bar(name="Measured on holdout (treated − control)", x=table.index,
                y=table["incremental"],
                error_y=dict(type="data", array=table["margin_95"], thickness=1.5, width=6),
                marker_color=COLORS["measured"],
                hovertemplate="%{x}<br>Measured: %{y:.1f} ± %{error_y.array:.1f}<extra></extra>")
    fig.add_bar(name="Planted truth (synthetic data only)", x=table.index,
                y=table["planted_incremental"], marker_color=COLORS["planted"],
                hovertemplate="%{x}<br>Planted: %{y:.1f}<extra></extra>")
    fig.update_traces(marker_line_width=0)
    fig.update_layout(
        title=f"Incremental conversions from targeting the top {budget:.0%} of the holdout",
        barmode="group", bargap=0.35, bargroupgap=0.08,
        yaxis_title="Incremental conversions", xaxis_title=None,
        legend=dict(orientation="h", yanchor="bottom", y=1.0, x=0),
        margin=dict(t=90, l=60, r=20, b=40), hoverlabel=dict(namelength=-1),
    )
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.2)", zeroline=True,
                     zerolinecolor="rgba(128,128,128,0.5)")
    return fig


def main():
    """Print AUC and the strategy table, and save the chart as HTML."""
    _, scored, auc = evaluate()
    print(f"Holdout: {len(scored):,} customers "
          f"({scored['treated'].sum():,} treated / {(1 - scored['treated']).sum():,} control), "
          f"{scored['converted'].sum()} conversions")
    print(f"Propensity model AUC on holdout: {auc:.3f}\n")

    table = compare_strategies(scored)
    show = table.copy()
    for c in ["n", "n_treated", "n_control"]:
        show[c] = show[c].round(0).astype(int)
    for c in ["conv_treated", "conv_control", "persuadable_share"]:
        show[c] = show[c].map("{:.1%}".format)
    for c in ["incremental", "margin_95", "planted_incremental"]:
        show[c] = show[c].map("{:.1f}".format)
    print("Top 20% of holdout by each strategy:")
    print(show.to_string(), "\n")

    up, pr = table.loc["Uplift", "incremental"], table.loc["Propensity", "incremental"]
    print(f"Uplift targeting: {up:.0f} incremental conversions vs {pr:.0f} for propensity "
          f"and {table.loc['Random', 'incremental']:.0f} for random, from the same "
          f"{int(table.loc['Uplift', 'n']):,} customers contacted.")

    os.makedirs(os.path.dirname(CHART_PATH), exist_ok=True)
    strategy_chart(table).write_html(CHART_PATH, include_plotlyjs="cdn")
    print(f"chart -> {CHART_PATH}")


if __name__ == "__main__":
    main()
