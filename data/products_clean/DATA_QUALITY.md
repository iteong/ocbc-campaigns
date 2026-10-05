# Data-quality report — OCBC public product API data
Pulled 2026-10-05 from Connect2OCBC. Every file says the data is *indicative and subject to change*. Customer data is never included.

**Products:** 10

## Products
| Product | Category | Source file | Empty fields |
|---|---|---|---|
| 360 Account | Current Account | ocbc_current_accounts_sg_response_1791199625431.json | 5 |
| FRANK Account | Current Account | ocbc_current_accounts_sg_response_1791199625431.json | 6 |
| Time Deposit (Fixed Deposit) | Deposit Accounts | ocbc_deposit_accounts_response_1791199738343.json | 8 |
| USD Current Account | Foreign currency | ocbc_foreign_accounts_response_1791200445017.json | 6 |
| Global Savings Account | Foreign currency | ocbc_foreign_accounts_response_1791200445017.json | 8 |
| Home Loan (New Purchase) | Home Loans | ocbc_home_loan_response_1791200316701.json | 9 |
| Home Loan (Refinancing) | Home Loans | ocbc_home_loan_response_1791200316701.json | 10 |
| Bonus+ Savings Account | Savings Account | ocbc_savings_accounts_sg_response_1791198246180.json | 6 |
| Monthly Savings Account | Savings Account | ocbc_savings_accounts_sg_response_1791198246180.json | 7 |
| Unit Trusts | Unit Trusts | ocbc_unit_trusts_response_1791199834643.json | 8 |

## Time Deposit rate tiers — checked for missing and repeated tenors
- $5,000 - S$20,000: OK
- >$20,000 - S$50,000: OK
- >$50,000 - S$99,999: OK
- $100,000 - S$249,999: OK
- $250,000 - S$499,999: missing 3 - 5 mths; repeated 6 mth
- $500,000 - S$999,999: missing 7 - 8 mths; repeated 36 mth

## Known issues to mention (not auto-detected)
- Tier labels are inconsistent (`$5,000`, `>$20,000`, `S$99,999`).
- Typos kept as-is: "0,35%", "wirthdrawals", "investors? money", "accountor", "tosave", "balancefor", "resindential".
- Stale content: links tagged `Nov16`; unit trust returns "as of March 2016"; home loan rates reference SIBOR (since retired in Singapore).
- Unit trusts: `key_risks` is empty while `overview` advertises back-tested returns.
- Not available for SG via the API: credit cards, fixed-deposit rates, card promotions.
