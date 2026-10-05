"""Clean OCBC public product API data (Connect2OCBC) into one consistent table.

Run from the project folder:  python clean_products.py
Reads:  data/ocbc_products/*.json   (raw API responses, left untouched)
Writes: data/products_clean/products.json, products.csv, DATA_QUALITY.md

What it does: unifies the three JSON shapes into one schema, strips HTML into
plain text with '- ' bullets, and standardises currency spacing ("S$ 10,000" ->
"S$10,000"). What it deliberately does NOT do: fix typos, fill empty fields or
repair the time-deposit rate table. Those are reported, not hidden.
"""
import csv
import glob
import html
import json
import os
import re
from collections import Counter
from html.parser import HTMLParser

RAW_DIR = "data/ocbc_products"
OUT_DIR = "data/products_clean"
PULLED_ON = "2026-10-05"

FIELDS = [
    "product_name", "category", "sub_category", "source_file",
    "description", "eligibility", "initial_deposit", "minimum_balance",
    "fees_and_charges", "benefits", "interest_rates", "loan_amount",
    "overview", "how_it_works", "key_risks", "remarks", "how_to_apply",
    "website_link", "disclaimer", "pulled_on",
]


class _ToText(HTMLParser):
    """Turn the API's HTML fragments into plain text with nested '- ' bullets."""

    def __init__(self):
        super().__init__()
        self.lines, self.buf, self.depth = [], "", 0

    def _flush(self):
        text = re.sub(r"\s+", " ", self.buf).strip()
        if text:
            indent = "  " * max(self.depth - 1, 0)
            self.lines.append(f"{indent}- {text}" if self.depth else text)
        self.buf = ""

    def handle_starttag(self, tag, attrs):
        if tag in ("ul", "ol"):
            self._flush()
            self.depth += 1
        elif tag in ("li", "p", "div", "span", "br"):
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("ul", "ol"):
            self._flush()
            self.depth = max(self.depth - 1, 0)
        elif tag in ("li", "p", "div", "span"):
            self._flush()

    def handle_data(self, data):
        self.buf += data


def to_text(value):
    """Strip HTML, decode entities, tidy whitespace and currency spacing."""
    if not value:
        return ""
    parser = _ToText()
    parser.feed(html.unescape(str(value)))
    parser._flush()
    text = "\n".join(parser.lines)
    text = re.sub(r"\b(S|US)\$\s+(?=\d)", r"\1$", text)  # "S$ 10,000" -> "S$10,000"
    return text.strip()


def _row(**kw):
    row = {f: "" for f in FIELDS}
    row.update({k: to_text(v) if k not in ("source_file", "pulled_on") else v
                for k, v in kw.items()})
    return row


def parse_file(path):
    data = json.load(open(path, encoding="utf-8"))
    src = os.path.basename(path)
    disclaimer = data.get("Disclaimer") or data.get("disclaimer") or ""
    rows = []
    if "CASAAccountsList" in data:  # savings, current, deposit, foreign accounts
        for cat in data["CASAAccountsList"]:
            for sub in cat.get("subCategoryList", []):
                for p in sub.get("product", []):
                    rows.append(_row(
                        product_name=p.get("productName"), category=cat.get("categoryName"),
                        sub_category=sub.get("SubCategoryName"), source_file=src,
                        description=p.get("productDescription"), eligibility=p.get("eligibility"),
                        initial_deposit=p.get("initialDeposit"), minimum_balance=p.get("minimumBalance"),
                        fees_and_charges=p.get("feesAndCharges"), benefits=p.get("benefits"),
                        remarks=p.get("remarks"), how_to_apply=p.get("apply"),
                        website_link=p.get("websiteLink"), disclaimer=disclaimer, pulled_on=PULLED_ON))
    elif "homeLoanList" in data:
        for cat in data["homeLoanList"]:
            for sub in cat.get("subCategoryList", []):
                for p in sub.get("productList", []):
                    # the product's own description is empty; the useful text
                    # (e.g. "Financing of up to 80%") sits on the sub-category
                    desc = p.get("productDescription") or sub.get("description")
                    rows.append(_row(
                        product_name=p.get("productName"), category=cat.get("categoryName"),
                        sub_category=sub.get("subCategoryName"), source_file=src,
                        description=desc, eligibility=p.get("eligibility"),
                        loan_amount=p.get("loanAmount"), interest_rates=p.get("interestRates"),
                        fees_and_charges=p.get("feesAndCharges"), benefits=p.get("benefits"),
                        remarks=p.get("remarks"), website_link=p.get("webPageLink"),
                        disclaimer=disclaimer, pulled_on=PULLED_ON))
    elif "unitTrustsProductList" in data:
        for cat in data["unitTrustsProductList"]:
            for p in cat.get("productList", []):
                rows.append(_row(
                    product_name=p.get("productName"), category=cat.get("categoryName"),
                    sub_category=cat.get("categoryName"), source_file=src,
                    description=p.get("productDescription"), overview=p.get("overview"),
                    benefits=p.get("benefits"), how_it_works=p.get("howDoesItWork"),
                    key_risks=p.get("keyRisks"), how_to_apply=p.get("application"),
                    website_link=p.get("websiteLink"), disclaimer=disclaimer, pulled_on=PULLED_ON))
    else:
        print(f"SKIPPED (unknown shape): {src}")
    return rows


def quality_report(rows):
    content = [f for f in FIELDS if f not in ("product_name", "category", "sub_category",
                                             "source_file", "disclaimer", "pulled_on")]
    out = ["# Data-quality report — OCBC public product API data",
           f"Pulled {PULLED_ON} from Connect2OCBC. Every file says the data is "
           "*indicative and subject to change*. Customer data is never included.",
           "", f"**Products:** {len(rows)}", ""]
    out += ["## Products", "| Product | Category | Source file | Empty fields |", "|---|---|---|---|"]
    for r in rows:
        empty = [f for f in content if not r[f]]
        out.append(f"| {r['product_name']} | {r['category']} | {r['source_file']} | {len(empty)} |")

    out += ["", "## Time Deposit rate tiers — checked for missing and repeated tenors"]
    expected = ["1 - 2 mths", "3 - 5 mths", "6 mth", "7 - 8 mths", "9 - 11 mths",
                "12 - 15 mths", "18 mth", "24 mth", "36 mth"]
    td = next((r for r in rows if r["product_name"].startswith("Time Deposit")), None)
    if td:
        tier, seen = None, []
        def close():
            if tier:
                missing = [t for t in expected if t not in seen]
                repeated = [t for t, n in Counter(seen).items() if n > 1]
                problems = ([f"missing {', '.join(missing)}"] if missing else []) + \
                           ([f"repeated {', '.join(repeated)}"] if repeated else [])
                out.append(f"- {tier}: " + ("; ".join(problems) if problems else "OK"))
        for line in td["benefits"].splitlines():
            m = re.match(r"\s*- (>?\$?S?\$?[\d,]+ - S\$[\d,]+):?$", line)
            if m:
                close(); tier, seen = m.group(1), []
            else:
                t = re.match(r"\s*- ([\d -]+ mths?):", line)
                if t and tier:
                    seen.append(t.group(1).strip())
        close()

    out += ["", "## Known issues to mention (not auto-detected)",
            "- Tier labels are inconsistent (`$5,000`, `>$20,000`, `S$99,999`).",
            "- Typos kept as-is: \"0,35%\", \"wirthdrawals\", \"investors? money\", "
            "\"accountor\", \"tosave\", \"balancefor\", \"resindential\".",
            "- Stale content: links tagged `Nov16`; unit trust returns \"as of March 2016\"; "
            "home loan rates reference SIBOR (since retired in Singapore).",
            "- Unit trusts: `key_risks` is empty while `overview` advertises back-tested returns.",
            "- Not available for SG via the API: credit cards, fixed-deposit rates, card promotions."]
    return "\n".join(out) + "\n"


def main():
    rows = []
    for path in sorted(glob.glob(os.path.join(RAW_DIR, "*.json"))):
        rows += parse_file(path)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "products.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, ensure_ascii=False)
    with open(os.path.join(OUT_DIR, "products.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    report = quality_report(rows)
    with open(os.path.join(OUT_DIR, "DATA_QUALITY.md"), "w", encoding="utf-8") as f:
        f.write(report)
    print(f"{len(rows)} products -> {OUT_DIR}/")
    print(report)


if __name__ == "__main__":
    main()
