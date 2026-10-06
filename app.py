"""Campaign targeting prototype for the OCBC 365 Credit Card launch.

All customer data is SYNTHETIC. Product facts are public, indicative and possibly
outdated (see data/product_facts.md).

Prerequisites (run once from the project folder):
  python src/data_gen.py          # synthetic customers
  python src/offer_copywriter.py  # offer copy cache (or use the Regenerate button)
"""
import re
import sys
from pathlib import Path

import numpy as np
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent / "src"))
import core  # noqa: E402
import eval as evaluation  # noqa: E402
import offer_copywriter as copywriter  # noqa: E402

STRATEGIES = {"Uplift": "uplift", "Propensity": "propensity", "Random": None}

st.set_page_config(page_title="365 Card Campaign Targeting", page_icon="💳", layout="wide")


# ---------- cached data and models ----------

@st.cache_resource(show_spinner="Fitting models on the past campaign…")
def deployment_scores():
    """Models fit on the whole past test, scoring every eligible customer (for targeting)."""
    df = core.load_customers()
    models = core.fit_models(df)
    return core.score_customers(models, df[df["eligible"] == 1])


@st.cache_resource(show_spinner="Evaluating on the 30% holdout…")
def holdout_scores():
    """Models fit on 70%, scoring the 30% holdout (for the honest comparison)."""
    _, scored, auc = evaluation.evaluate()
    return scored, auc


@st.cache_data
def strategy_table(budget):
    """Propensity vs uplift vs random on the holdout at this budget."""
    scored, _ = holdout_scores()
    return evaluation.compare_strategies(scored, budget)


def pick_targets(scored, strategy, budget, seed=0):
    """Top `budget` share by the chosen score (or a seeded random sample)."""
    k = int(len(scored) * budget)
    col = STRATEGIES[strategy]
    if col is None:
        idx = np.random.default_rng(seed).choice(len(scored), k, replace=False)
        return scored.iloc[idx]
    return scored.nlargest(k, col)


def facts_pulled_on():
    """'Pulled on' date from the product facts header, for the caveat line."""
    m = re.search(r"\*\*Pulled on:\*\*\s*(\S+)", Path(copywriter.FACTS_PATH).read_text())
    return m.group(1) if m else "unknown date"


# ---------- sidebar ----------

with st.sidebar:
    st.header("Targeting")
    budget = st.slider("Budget: share of eligible customers to contact", 0.05, 0.50, 0.20, 0.05,
                       format="%.2f")
    strategy = st.radio("Rank customers by", list(STRATEGIES), index=0,
                        help="Uplift = extra chance of converting caused by the offer. "
                             "Propensity = chance of converting at all.")
    st.divider()
    st.caption("All customers are **synthetic**. Product facts come from public OCBC "
               f"sources pulled on {facts_pulled_on()}; they are indicative and may be outdated.")

# ---------- headline ----------

st.title("OCBC 365 Credit Card: who to target, and what to say")

scored = deployment_scores()
targets = pick_targets(scored, strategy, budget)
table = strategy_table(budget)
row = table.loc[strategy]
per_contact = row["incremental"] / row["n"]
margin_per_contact = row["margin_95"] / row["n"]

c1, c2, c3 = st.columns(3)
c1.metric("Customers targeted", f"{len(targets):,}",
          help=f"Top {budget:.0%} of {len(scored):,} eligible customers, ranked by {strategy.lower()}.")
c2.metric("Expected incremental conversions", f"{targets['uplift'].sum():,.0f}",
          help="Sum of predicted uplift (P_offered − P_not offered) over targeted customers. "
               "A model estimate; compare it with the holdout-measured figure next to it.")
c3.metric("Holdout-measured incremental (scaled)",
          f"{per_contact * len(targets):,.0f} ± {margin_per_contact * len(targets):,.0f}",
          help="Treated − control conversion rate in the same strategy's top group on the 30% "
               "holdout, scaled to the number targeted here. ± is the 95% margin of error.")

# ---------- evaluation chart ----------

st.subheader("Does the targeting method matter?")
holdout, auc = holdout_scores()
st.plotly_chart(evaluation.strategy_chart(table, budget), width="stretch")
st.caption(f"Holdout of {len(holdout):,} past-test customers. "
           f"Propensity model AUC {auc:.3f}: it predicts who converts well, but many of "
           "those customers convert without the offer. Planted truth is only known because "
           "the data is synthetic.")

# ---------- targeted customers ----------

st.subheader(f"Targeted customers ({strategy.lower()} ranking)")
st.caption("Reasons are uplift drivers: the features that most widen the gap between "
           "'offered' and 'not offered' for that customer. Small drivers can be model noise.")
show = targets[["customer_id", "name", "segment", "propensity", "uplift",
                "driver_1", "driver_2", "driver_3"]]
st.dataframe(
    show, hide_index=True, width="stretch", height=380,
    column_config={
        "customer_id": "ID", "name": "Name", "segment": "Segment",
        "propensity": st.column_config.NumberColumn("Propensity", format="percent"),
        "uplift": st.column_config.NumberColumn("Uplift", format="percent"),
        "driver_1": "Reason 1", "driver_2": "Reason 2", "driver_3": "Reason 3",
    },
)

# ---------- offer copy ----------

st.subheader("Offer copy for the largest uplift segments")
cached = copywriter.load_cached()
left, right = st.columns([3, 1])
with right:
    if st.button("Regenerate copy", help="Calls Claude for each segment (about a minute)."):
        with st.spinner("Writing and checking copy…"):
            cached = copywriter.build_all()
if cached is None:
    left.info("No copy generated yet. Click **Regenerate copy** or run "
              "`python src/offer_copywriter.py`.")
else:
    left.caption(f"Generated {cached['generated_at']} for the top {cached['budget']:.0%} "
                 "by uplift. Claude saw only the segment name, its drivers and "
                 "data/product_facts.md. Checks are plain code; they are a prototype "
                 "stand-in, not a compliance review.")
    facts = {f["id"]: f for f in copywriter.load_facts()}
    in_view = targets["segment"].value_counts()
    for seg in cached["segments"]:
        status = "✅ all checks pass" if seg["passed"] else "❌ check failed"
        label = f"{seg['segment']} · {seg['size']:,} customers · {status}"
        with st.expander(label, expanded=False):
            st.markdown(f"**Subject:** {seg['subject']}")
            st.markdown(f"**Body:** {seg['body']}")
            st.caption("Top drivers: " + "; ".join(
                f"{d['driver']} ({d['share']:.0%})" for d in seg["top_drivers"])
                + f" · in current selection: {in_view.get(seg['segment'], 0):,}"
                + f" · model {seg['model']}, attempts {seg['attempts']}")
            st.markdown("**Compliance checks**")
            for chk in seg["checks"]:
                st.markdown(f"{'✅' if chk['passed'] else '❌'} **{chk['rule']}**: {chk['reason']}")
            st.markdown("**Facts cited**")
            for fid in seg["fact_ids"]:
                f = facts.get(fid)
                st.markdown(f"- `{fid}` {f['fact']}" if f else f"- `{fid}` (not in facts file)")
            st.caption(f"Product facts pulled {facts_pulled_on()}; indicative and possibly "
                       "outdated. Recheck the OCBC source before any real use.")
