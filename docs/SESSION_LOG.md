# Session log: building the OCBC 365 Card campaign targeting prototype

A record of one Claude Code session (6–7 Oct 2026): what was asked, what was built, the decisions taken and why,
the results, and the open caveats. For how to run the project, see [`HANDOFF.md`](../HANDOFF.md).

## Starting point
- **Repo:** `ocbc-campaigns`. It held cleaned OCBC product data (`data/products_clean/`, 10 deposit, loan and
  investment products from OCBC's public API, pulled 5 Oct 2026) and empty stubs for `src/data_gen.py`, `src/core.py`,
  `src/eval.py` and `app.py`.
- **Project rules** (`CLAUDE.md`):
  - Python 3.11; pandas, scikit-learn, Streamlit; minimal dependencies;
  - simple, explainable methods first, and every ranking must show WHY;
  - cite sources, and never present rates as current;
  - flag banking and regulatory assumptions;
  - dotenv for secrets;
  - run code after each change and show output;
  - don't run `streamlit run`.
- **Working style:** plan first with no code, then one step per prompt, each step committed once approved.

## Plan (approved after one revision)
The first plan was revised with the user's specifics:
- baseline conversion about 3%, with +6 points only for high-spend, high-engagement customers;
- `Pipeline` with `StandardScaler`, and the top drivers per customer;
- a 30% stratified holdout and a 3-way plotly comparison;
- `product_facts.md`, with subject and 2-sentence copy for the 3 largest segments;
- a plain-code `check_copy()`;
- the app layout.

Stress-testing the revised plan added:
- **A varying baseline.** With a flat 3% baseline, propensity and uplift would rank customers the same way and the
  demo would show nothing.
- **One shared scaler for the T and C models,** so their coefficients can be subtracted.
- **Stricter copy checks:** spelled-out numbers count as numbers, and naming a non-bonus category next to a rate fails.

Decisions taken during planning:
- **Product:** the OCBC 365 Credit Card. Credit cards aren't in the API data, so the card facts are pulled from public
  ocbc.com pages, after checking robots.txt.
- **Terms:** those effective 1 Nov 2026.
- **Reasons:** uplift drivers, (coef_T − coef_C) × scaled value, rather than treated-model drivers.
- **File name:** `src/offer_copywriter.py` instead of `src/copy.py`, which would shadow Python's built-in `copy` module.

## Step 0: product facts
- Downloaded the 365 page and T&C PDF, read the PDF with `pdftotext` (avoiding a `pypdf` dependency) and reused
  `to_text()` from `scripts/clean_products.py`.
- **Correction:** the T&C PDF showed the 1 Nov terms are a single tier (S$800 → S$160 cap). During planning a
  web-search snippet had been wrongly called mistaken; the two-tier figures on the page are the pre-November terms.
- 15 facts, each quote-checked against its source. A test with the old S$80 cap correctly failed.
- Topic labels contain no digits, so the copy check can treat the Fact column as the only source of allowed numbers.

## Step 1: synthetic customers
- First thresholds (S$1,500 and 12 logins) made only 7.6% of the test persuadable. Retuned to S$1,200 and 10 logins,
  which gives 16.6%.
- Observed: persuadables converted at 2.9% without the offer and 8.4% with it; everyone else at 3.1% vs 3.3%.
  Existing cardholders' baseline was 7.0% vs 1.5% for others, which makes them the "sure things".

## Step 2: models
- The first fit gave spend almost no weight and had noisy drivers.
- Tested on a 70/30 split:
  - stronger regularisation (C=0.01) raised the true-persuadable share of the top 20% only slightly, and spend stayed weak;
  - adding a `spend_x_app` interaction raised it from 54% to 64%;
  - a minimum-spend flag added nothing.
- Spend enters as log of total plus category shares. Vectorised the driver loop (43 s → 9 s) and fixed a sklearn
  feature-name warning.

## Step 3: evaluation
- At 20,000 customers the holdout had only 165 conversions, and the measured comparison was within noise (uplift
  16 ± 30). The user approved 100,000 customers.
- Result at 20%: uplift 171 ± 63, propensity 50 ± 81, random 51 ± 42 incremental conversions. Planted truth: 144 /
  56 / 45. Propensity AUC 0.772.

## Step 4: offer copy
- Claude (`claude-opus-5-5`, medium effort, JSON schema, `fallbacks: "default"`) sees only the segment name, its
  drivers and the facts table.
- All 3 segments passed on the first attempt. The online-shopper copy correctly offered only the 0.25% base rate on
  other spend. A deliberately bad draft failed 4 of 5 checks.
- **User decision:** keep age, income and residency drivers. Older and higher-income customers have more buying power.
  Noted: these traits drive propensity more than uplift, and residency shouldn't shape the copy itself.

## Step 5: app
- Verified headlessly with Streamlit `AppTest`. At 20% uplift it targets 15,231 customers: 606 expected vs
  571 ± 209 measured incremental conversions.

## Publishing
- Merged to `main` (fast-forward) and deleted the `campaign-prototype` branch.
- The GitHub repo is public; the user chose to push OCBC's raw files as they are.
- The first pushes failed with 403: the saved fine-grained token lacked Contents: write on the new repo. Fixed by
  replacing the Keychain credential.
- Then adopted from `ocbc-product-qa`:
  - README, HANDOFF and this log;
  - pinned `requirements.txt`;
  - a committed `data/eval/SUMMARY.md`;
  - the `OCBC_CAMPAIGN_MODEL` setting;
  - a Regenerate button that fails safely, tested with an invalid key: message shown, cached copy kept.

## Open caveats
See `HANDOFF.md` → Known shortcuts. The main ones:
- the evaluation is optimistic by construction;
- there are noisy drivers;
- the copy check doesn't verify that numbers are paired with the right claims;
- nothing has been reviewed by Compliance.
