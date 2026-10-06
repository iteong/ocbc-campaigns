# Handoff: OCBC 365 Card campaign targeting (prototype)

The prototype ranks customers for a cashback credit card offer by **uplift** (the extra chance of converting caused
by the offer), explains each ranking, and writes per-segment offer copy with Claude. Plain-code checks then test the
copy against cited product facts.

## Run it
Python 3.11. Run `source ~/Source/ocbc-env/.venv/bin/activate`, then put `ANTHROPIC_API_KEY` in `.env`. Run everything
from the repo root, in this order:
1. `python src/data_gen.py`: 100,000 synthetic customers plus a past randomised test → `data/synthetic/customers.csv`.
2. `python src/core.py`: fit and inspect the models (coefficients, uplift by planted group, top customers).
3. `python src/eval.py`: holdout comparison → `data/eval/SUMMARY.md` (committed) and `data/generated/eval.html`.
4. `python src/offer_copywriter.py`: copy for the 3 largest targeted segments (3–6 Claude calls) →
   `data/generated/offer_copy.json`.
5. `streamlit run app.py`.

To rebuild the product facts, run `python scripts/build_product_facts.py [--refresh]`. It needs `pdftotext` (brew
install poppler) and stops if any fact no longer matches its source word for word.

## Files
| File | What it does |
|---|---|
| `scripts/build_product_facts.py` | Downloads the 365 page and T&C PDF to `data/ocbc_cards/`, then writes `data/product_facts.md` (15 facts, each quote-checked). |
| `src/data_gen.py` | Customers (Faker names for display only), `is_eligible()` from facts F12–F14, `simulate_campaign()` with planted persuadables. |
| `src/core.py` | `fit_models()` (propensity Pipeline, and T and C models sharing one scaler), `score_customers()`, `top_drivers()`, `assign_segment()`. |
| `src/eval.py` | `split_holdout()`, `evaluate()`, `compare_strategies()`, `strategy_chart()`, `write_summary()`. |
| `src/offer_copywriter.py` | `target_segments()`, `generate_copy()` (Claude, JSON schema, fallbacks), `check_copy()`, cache helpers. |
| `app.py` | Streamlit UI. Targeting uses models fit on the whole past test; the chart and measured tile use the holdout. Regenerate errors show a message, never a stack trace. |

## Data sources and what should replace them
- **Customers and the past campaign are synthetic.** In production, replace them with a real **randomised** past
  campaign: a random holdout that wasn't offered. Uplift can't be estimated without one, and observational data
  confounds who got offers with who converts.
- **Product facts** come from OCBC's public 365 page and the cashback T&Cs effective 1 Nov 2026, pulled 6 Oct 2026.
  The page still showed the pre-November two-tier terms, so the PDF (single tier: S$800 → S$160 cap) was used.
  Replace with the bank's approved product disclosures (T&Cs, product highlights sheet, fee schedule), with effective
  dates and named owners.
- Left out of the facts on purpose: the welcome gift promotion (separate T&Cs, ends 31 Dec 2026) and the MCC
  exclusion table (doesn't extract cleanly).

## Key assumptions
- Response rates, persuadable thresholds (S$1,200/month spend, 10 app logins/month), the income mix and car ownership
  are all invented. Each is labelled `ASSUMPTION` in the code.
- Eligibility is simplified to the age, income and residency rules on the product page. There are no credit-bureau,
  income-document or MAS credit card checks.
- `check_copy()` is a prototype stand-in, **not** a review against MAS or ABS advertising guidelines. Real copy needs
  Compliance sign-off.
- Age, income and residency are kept as model features and as drivers sent to Claude, by decision. The prompt forbids
  the copy from mentioning them.

## Known shortcuts
- **The evaluation is optimistic.** We planted the response pattern, then chose `spend_x_app` and C=0.01 knowing it,
  testing them on a split of the same data.
- **Noisy drivers.** Two-model uplift subtracts two noisy models, so small spurious drivers appear (e.g. "Has a 360
  Account"). Some existing cardholders also get negative uplift, though the true effect is 0.
- **Diluted uplift.** Strong regularisation ranks well but shrinks predicted uplift towards zero.
- **Gaps in the copy check.**
  - It confirms each number exists in the facts, not that it's paired with the right claim ("S$160 minimum spend"
    would pass).
  - The category rule only scans sentences with a rate or "cashback".
- **Copy is fixed at one selection.** It is generated for the top 20% by uplift and doesn't change with the app's
  budget or strategy.
- **Testing.** There are no unit tests; checks were run by hand and with Streamlit's `AppTest`.

## To productionise
1. **Data:** a real randomised past campaign (or a fresh test cell), a feature store with point-in-time features, and
   checks that block bad loads.
2. **Modelling:** compare the two-model approach with single-model uplift (treatment interactions), X-learner or uplift
   trees on Qini/AUUC. Use a held-out time period, and calibrate predicted uplift before quoting conversion forecasts.
3. **Targeting rules:** exclude customers without marketing consent or registered on the Do Not Call registry (PDPA).
   Add contact-frequency caps, and set a policy on existing cardholders.
4. **Copy governance:** Compliance-approved templates or claims library, pairing-aware fact checks, human approval
   before send, and an audit log of prompt, facts version and output.
5. **Measurement:** keep a random control in every campaign, monitor realised uplift against predicted, and retrain on
   each new campaign.
