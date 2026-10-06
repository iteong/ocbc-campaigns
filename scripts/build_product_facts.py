"""Build data/product_facts.md for the product being promoted: the OCBC 365 Credit Card.

Run from the project folder:  python scripts/build_product_facts.py [--refresh]
Reads:  data/ocbc_cards/ocbc_365_page.html             (public product page)
        data/ocbc_cards/ocbc_365_tncs_wef1nov26.pdf    (T&Cs effective 1 Nov 2026)
        data/products_clean/products.json              (one related 360 Account fact)
Writes: data/product_facts.md

The raw files are downloaded once and then left untouched; --refresh downloads
them again. Every fact is a verbatim snippet of a source. The script checks
each snippet still appears in its source text (after collapsing whitespace)
and stops if any does not, so wording and numbers can never be retyped.

Needs the `pdftotext` command (poppler) for the PDF. It is a system tool,
not a Python dependency.
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
from clean_products import to_text  # noqa: E402  reuse the HTML -> text cleaner

RAW_DIR = "data/ocbc_cards"
OUT_PATH = "data/product_facts.md"
PRODUCTS_JSON = "data/products_clean/products.json"
PULLED_ON = "2026-10-06"
PRODUCT = "OCBC 365 Credit Card"
EFFECTIVE_FROM = "1 November 2026"

SOURCES = {
    "page": ("ocbc_365_page.html",
             "https://www.ocbc.com/personal-banking/cards/365-cashback-credit-card"),
    "tncs": ("ocbc_365_tncs_wef1nov26.pdf",
             "https://www.ocbc.com/iwov-resources/sg/ocbc/personal/pdf/cards/"
             "tncs-governing-365-cc-cashback-programme-wef1nov26.pdf"),
}

# (id, topic, source key, verbatim snippet). Topics are my labels and contain
# no digits, so the copy check in step 4 can treat every number in the
# "Fact" column as an allowed number and nothing else.
# Not included on purpose:
#  - the welcome gift promotion (separate T&Cs, valid till 31 Dec 2026)
#  - MCC exclusions (laid out as a table in the PDF that doesn't extract as
#    clean sentences). The copy must still say "T&Cs apply".
FACTS = [
    ("F1", "Bonus cashback", "tncs",
     "Subject to the Minimum Spend Requirement being met: a) 6% cashback on "
     "“Dining”, “Groceries”, “Land Transport”, “Petrol”"),
    ("F2", "Minimum spend and cap", "tncs",
     "Minimum Spend Requirement Cashback Cap S$800 S$160"),
    ("F3", "Monthly cap", "tncs",
     "The maximum amount of Cashback that one account (the Principal and all "
     "Supplementary Cardmembers together) can earn in any calendar month under "
     "Clause 2A is S$160."),
    ("F4", "Watsons cashback", "tncs",
     "3% cashback on “Watsons” (valid till 31 March 2027)"),
    ("F5", "Base cashback", "tncs",
     "0.25% cashback on the following transactions: • All Card Transactions if "
     "the Minimum Spend Requirement is not met; and • All Card Transactions "
     "(excluding Card Transactions under the categories listed at Clause 2A) if "
     "the Minimum Spend Requirement is met."),
    ("F6", "Advertising platforms", "tncs",
     "1% cashback on “Advertising Platform” with full payment made"),
    ("F7", "Advertising platforms", "tncs",
     "0.5% cashback on “Advertising Platform” with payments made in instalments"),
    ("F8", "When cashback is credited", "tncs",
     "Cashback earned will be credited into the Principal Cardmember’s Card "
     "Account in the following month based on posted transactions."),
    ("F9", "Bank may change terms", "tncs",
     "We reserve the right to vary the percentage of the Cashback or revise the "
     "Minimum Spend Requirement without notice at any time or from time to time."),
    ("F10", "Annual fee", "page",
     "Principal card S$196.20 (including GST), waived for the first two years"),
    ("F11", "Annual fee waiver", "page",
     "Minimum spending required to have your Annual Service Fee automatically "
     "waived S$10,000 in one year, starting from the month in which your OCBC "
     "365 Credit Card was issued"),
    ("F12", "Eligibility", "page",
     "Singaporeans and Singapore PRs aged 21 to 55, with an annual income of at "
     "least S$30,000"),
    ("F13", "Eligibility", "page",
     "Singaporeans and Singapore PRs aged above 55, with an annual income of at "
     "least S$15,000"),
    ("F14", "Eligibility", "page",
     "Foreigners aged 21 and above, with an annual income of at least S$45,000"),
]

# Related fact from the existing clean product data (a cross-sell hook).
RELATED = ("F15", "Related account bonus", "360 Account",
           "0.3% per year - Spend at least S$500 on OCBC Credit Cards.")


def download(refresh=False):
    """Fetch each source into RAW_DIR unless already there (or refresh=True)."""
    os.makedirs(RAW_DIR, exist_ok=True)
    for fname, url in SOURCES.values():
        path = os.path.join(RAW_DIR, fname)
        if os.path.exists(path) and not refresh:
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(path, "wb") as f:
            f.write(resp.read())
        print(f"downloaded {url} -> {path}")


def squash(text):
    """Collapse all whitespace (incl. HTML-to-text line breaks) to single spaces."""
    text = re.sub(r"(?m)^\s*-\s+", " ", text)  # drop to_text's '- ' bullet markers
    return re.sub(r"\s+", " ", text).strip()


def source_texts():
    """Return {source key: whitespace-collapsed plain text} for page and PDF."""
    page_html = open(os.path.join(RAW_DIR, SOURCES["page"][0]), encoding="utf-8").read()
    pdf_path = os.path.join(RAW_DIR, SOURCES["tncs"][0])
    try:
        pdf_text = subprocess.run(["pdftotext", "-layout", pdf_path, "-"],
                                  capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("pdftotext not found: install poppler (brew install poppler)")
    return {"page": squash(to_text(page_html)), "tncs": squash(pdf_text)}


def related_fact():
    """Look up the 360 Account credit-card bonus line in products.json."""
    fid, topic, name, snippet = RELATED
    product = next(p for p in json.load(open(PRODUCTS_JSON, encoding="utf-8"))
                   if p["product_name"] == name)
    return fid, topic, product, snippet


def verify(texts, product):
    """Return [(fact id, ok)] after checking each snippet appears in its source."""
    results = [(fid, squash(snippet) in texts[src]) for fid, _, src, snippet in FACTS]
    results.append((RELATED[0], RELATED[3] in product["benefits"]))
    return results


def render(product):
    """Build the markdown: header, caveat, and a facts table with sources."""
    page_file, page_url = SOURCES["page"]
    tncs_file, tncs_url = SOURCES["tncs"]
    src_label = {"page": f"[product page]({page_url})", "tncs": f"[T&Cs PDF]({tncs_url})"}
    lines = [
        f"# Product facts: {PRODUCT}",
        "",
        f"- **Terms version:** cashback programme with effect from {EFFECTIVE_FROM}",
        f"- **Pulled on:** {PULLED_ON}",
        f"- **Sources:** `{RAW_DIR}/{tncs_file}` ({tncs_url}); "
        f"`{RAW_DIR}/{page_file}` ({page_url}); "
        f"`{PRODUCTS_JSON}` ({product['source_file']})",
        "- **Caveat:** public information, indicative and possibly outdated. "
        "Never present these figures as current without rechecking the source.",
        "",
        "Every row in the Fact column is copied word for word from its source "
        "(checked by `scripts/build_product_facts.py`). Offer copy may only use "
        "numbers that appear in that column.",
        "",
        "| ID | Topic | Fact (verbatim) | Source |",
        "|---|---|---|---|",
    ]
    for fid, topic, src, snippet in FACTS:
        lines.append(f"| {fid} | {topic} | {snippet} | {src_label[src]} |")
    fid, topic, _, snippet = RELATED
    lines.append(f"| {fid} | {topic} | {snippet} | 360 Account, "
                 f"`{product['source_file']}` |")
    return "\n".join(lines) + "\n"


def main():
    """Download if needed, verify every snippet, then write product_facts.md."""
    download(refresh="--refresh" in sys.argv)
    texts = source_texts()
    product = related_fact()[2]
    results = verify(texts, product)
    for fid, ok in results:
        print(f"  {fid:4} {'OK     ' if ok else 'MISSING'}")
    missing = [fid for fid, ok in results if not ok]
    if missing:
        sys.exit(f"Quote check failed for {missing}: source wording changed. Not writing.")
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(render(product))
    print(f"wrote {OUT_PATH} ({len(results)} facts, all verified verbatim)")


if __name__ == "__main__":
    main()
