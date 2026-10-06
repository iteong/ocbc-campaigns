"""Offer copy per targeted segment, written by Claude and checked in plain code.

Run from the project folder:  python src/offer_copywriter.py
Reads:  data/synthetic/customers.csv, data/product_facts.md
Writes: data/generated/offer_copy.json (cached so the app doesn't call the API on reload)

For the 3 largest segments in the top 20% by uplift, Claude gets ONLY:
  - the segment name and its most common uplift drivers (no names, ids or rows)
  - the verbatim facts table from data/product_facts.md
and returns an email subject line plus a 2-sentence body.

check_copy() then applies deterministic rules. If a draft fails, Claude gets
one retry with the failure reasons. The check decides; Claude never grades itself.

ASSUMPTION (compliance): these rules are a prototype stand-in. They are NOT a
review against MAS or ABS advertising guidelines (or any other regulation),
and real campaign copy still needs sign-off from Compliance.
"""
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

import anthropic
from dotenv import find_dotenv, load_dotenv

import core

FACTS_PATH = "data/product_facts.md"
OUT_PATH = "data/generated/offer_copy.json"
MODEL = "claude-opus-5-5"
BUDGET = 0.20
N_SEGMENTS = 3

BANNED_PHRASES = ["guaranteed", "guarantee", "risk-free", "risk free", "free money",
                  "unlimited", "no minimum spend", "no cap"]
TNC_PHRASES = ["t&cs apply", "terms and conditions apply"]
# Categories that earn a bonus rate on the 365 (product_facts.md F1, F4, F6/F7).
ALLOWED_CATEGORIES = ["dining", "groceries", "grocery", "land transport", "transport",
                      "petrol", "watsons", "advertising"]
# Categories a writer might be tempted to name that do NOT earn a bonus rate.
OFF_FACT_CATEGORIES = ["online", "e-commerce", "ecommerce", "travel", "utilities",
                       "streaming", "ev charging", "overseas", "entertainment", "fashion"]
NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
                "ten", "eleven", "twelve", "twenty", "thirty", "forty", "fifty",
                "hundred", "thousand", "percent", "half", "double", "triple"]

SYSTEM_PROMPT = """You write short marketing emails for a bank's credit card campaign.

Hard rules (a program checks every one of them):
- Use ONLY the facts in <product_facts>. Do not add any claim, benefit, rate, fee or date that is not stated there.
- Every number you write must appear in the Fact column exactly as written (for example "6%", "S$800", "S$160"). Write numbers as digits, never as words, unless the words appear in a fact word for word (for example "first two years").
- Only name cashback categories that the facts list. Never imply a bonus rate on online shopping or any other category not in the facts.
- If you mention a cashback rate on the bonus categories, also mention the S$800 minimum spend and the S$160 cap.
- Never use: guaranteed, risk-free, free money, unlimited, "no minimum spend".
- Do not refer to the reader's age, income, nationality or other personal details. Speak to their spending habits only.
- Subject line: at most 60 characters.
- Body: exactly 2 sentences, then the words "T&Cs apply." at the end.
- List the fact IDs (e.g. F1, F2) you relied on."""

SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "fact_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subject", "body", "fact_ids"],
    "additionalProperties": False,
}


# ---------- facts ----------

def load_facts(path=FACTS_PATH):
    """Parse the facts table into [{'id', 'topic', 'fact'}] (the verbatim Fact column)."""
    facts = []
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\|\s*(F\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|", line)
        if m:
            facts.append({"id": m.group(1), "topic": m.group(2), "fact": m.group(3)})
    return facts


def facts_table(facts):
    """Facts as plain lines for the prompt: 'F1 | topic | fact'."""
    return "\n".join(f"{f['id']} | {f['topic']} | {f['fact']}" for f in facts)


# ---------- the copy check (plain code, no model) ----------

_NUM = re.compile(r"(?<![\w.])(?:S?\$)?\d[\d,]*(?:\.\d+)?%?(?![\w])")


def _numbers(text):
    """Number tokens normalised so 'S$1,600', '$1600' and '1600' all read as '1600'.

    '6%' stays distinct from '6'. Numbers glued to letters (like '2A' in
    'Clause 2A') are not counted.
    """
    out = set()
    for tok in _NUM.findall(text):
        tok = tok.replace("S$", "").replace("$", "").replace(",", "")
        out.add(tok.rstrip(".") if not tok.endswith("%") else tok)
    return out


def _sentences(body):
    """Split into sentences on . ! ? followed by a space or the end (so 'S$196.20' stays whole)."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", body.strip()) if s.strip()]


def check_copy(subject, body, facts):
    """Run every rule on subject + body. Returns [(rule, passed, reason)].

    1. Every number in the copy appears in the facts. Spelled-out numbers
       count too: allowed only if that word is in the facts.
    2. Says "T&Cs apply" (or "Terms and conditions apply").
    3. No banned phrases.
    4. Any category named in a sentence with a rate or "cashback" must be a
       365 bonus category. Rule 1 alone would pass "6% cashback on online
       shopping", because 6% is a real figure.
    5. Format: subject <= 60 chars; body is 2 sentences plus "T&Cs apply.".
    """
    text = f"{subject}\n{body}"
    low = text.lower()
    fact_text = " ".join(f["fact"] for f in facts)
    fact_low = fact_text.lower()
    results = []

    unknown = sorted(_numbers(text) - _numbers(fact_text))
    words = sorted({w for w in NUMBER_WORDS if re.search(rf"\b{w}\b", low)
                    and not re.search(rf"\b{w}\b", fact_low)})
    ok = not unknown and not words
    results.append(("Numbers match product facts", ok,
                    "all numbers found in product_facts.md" if ok else
                    "not in facts: " + ", ".join(unknown + [f'"{w}"' for w in words])))

    ok = any(p in low for p in TNC_PHRASES)
    results.append(("Includes T&Cs apply", ok,
                    "found" if ok else 'missing "T&Cs apply" / "Terms and conditions apply"'))

    hits = [p for p in BANNED_PHRASES if re.search(rf"\b{re.escape(p)}\b", low)]
    results.append(("No banned phrases", not hits,
                    "none found" if not hits else "found: " + ", ".join(hits)))

    bad = []
    for s in _sentences(subject) + _sentences(body):
        sl = s.lower()
        if "%" in sl or "cashback" in sl:
            bad += [c for c in OFF_FACT_CATEGORIES if re.search(rf"\b{re.escape(c)}\b", sl)]
    results.append(("Only 365 bonus categories named", not bad,
                    "ok" if not bad else "rate/cashback claimed alongside: " + ", ".join(sorted(set(bad)))))

    core_body = re.sub(r"\s*(t&cs apply|terms and conditions apply)\.?\s*$", "", body.strip(),
                       flags=re.I)
    n_sent = len(_sentences(core_body))
    ok = len(subject) <= 60 and n_sent == 2
    results.append(("Format: subject <= 60 chars, 2-sentence body", ok,
                    f"subject {len(subject)} chars, body {n_sent} sentences"))
    return results


# ---------- segments ----------

def _driver_label(reason):
    """'High app engagement (15 logins/month)' -> 'High app engagement'."""
    return reason.split(" (")[0]


def target_segments(scored, budget=BUDGET, n=N_SEGMENTS):
    """The n largest segments in the top `budget` share by uplift, with their top drivers."""
    top = scored.nlargest(int(len(scored) * budget), "uplift")
    segments = []
    for name, size in top["segment"].value_counts().head(n).items():
        grp = top[top["segment"] == name]
        drivers = Counter(_driver_label(r) for col in ["driver_1", "driver_2"]
                          for r in grp[col] if r)
        segments.append({
            "segment": name, "size": int(size),
            "top_drivers": [{"driver": d, "share": round(c / size, 2)}
                            for d, c in drivers.most_common(3)],
        })
    return segments


# ---------- Claude ----------

def _client():
    """Anthropic client; the key comes from .env (never printed or hard-coded)."""
    load_dotenv(find_dotenv(usecwd=True))
    return anthropic.Anthropic()


def _segment_prompt(seg, facts, feedback=None):
    """User message: the segment, its drivers, and the facts. Nothing else."""
    drivers = "\n".join(f"- {d['driver']} ({d['share']:.0%} of this segment)"
                        for d in seg["top_drivers"])
    msg = (f"<product_facts>\nID | Topic | Fact (verbatim)\n{facts_table(facts)}\n</product_facts>\n\n"
           f"<segment>\nName: {seg['segment']}\n"
           f"Why the offer is likely to change their behaviour (top uplift drivers):\n{drivers}\n"
           f"</segment>\n\nWrite the email subject and body for this segment.")
    if feedback:
        msg += ("\n\nYour previous draft failed these checks. Fix them:\n"
                + "\n".join(f"- {rule}: {reason}" for rule, _, reason in feedback))
    return msg


def generate_copy(client, seg, facts, feedback=None):
    """One Claude call -> {'subject', 'body', 'fact_ids'}.

    Fallbacks are on ("default"): if a safety classifier declines, the API
    re-runs the request on Anthropic's recommended fallback model.
    """
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": SCHEMA}},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _segment_prompt(seg, facts, feedback)}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined for segment {seg['segment']!r}")
    text = next(b.text for b in response.content if b.type == "text")
    out = json.loads(text)
    out["model"] = response.model
    return out


def write_segment_copy(client, seg, facts, max_attempts=2):
    """Generate, check, and retry once with the failure reasons if any rule fails."""
    feedback = None
    for attempt in range(1, max_attempts + 1):
        draft = generate_copy(client, seg, facts, feedback)
        checks = check_copy(draft["subject"], draft["body"], facts)
        if all(ok for _, ok, _ in checks):
            break
        feedback = [c for c in checks if not c[1]]
    return {**seg, **draft, "attempts": attempt,
            "passed": all(ok for _, ok, _ in checks),
            "checks": [{"rule": r, "passed": ok, "reason": why} for r, ok, why in checks]}


def build_all(save=True):
    """Score customers, pick the segments, write and check copy for each; cache the result."""
    df = core.load_customers()
    models = core.fit_models(df)
    scored = core.score_customers(models, df[df["eligible"] == 1])
    facts = load_facts()
    client = _client()
    results = [write_segment_copy(client, seg, facts) for seg in target_segments(scored)]
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "facts_file": FACTS_PATH, "budget": BUDGET, "segments": results}
    if save:
        os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
    return payload


def load_cached(path=OUT_PATH):
    """Read the cached copy file, or None if it hasn't been generated yet."""
    if not os.path.exists(path):
        return None
    return json.load(open(path, encoding="utf-8"))


def _print_checks(checks):
    """Print one line per rule."""
    for c in checks:
        print(f"    {'PASS' if c['passed'] else 'FAIL'}  {c['rule']}: {c['reason']}")


def main():
    """Generate copy for the 3 largest targeted segments, print it with checks, plus a bad-copy test."""
    payload = build_all()
    for s in payload["segments"]:
        print(f"\n=== {s['segment']}  ({s['size']:,} customers in top 20% by uplift) ===")
        print("  drivers: " + "; ".join(f"{d['driver']} ({d['share']:.0%})" for d in s["top_drivers"]))
        print(f"  Subject: {s['subject']}")
        print(f"  Body:    {s['body']}")
        print(f"  Facts cited: {', '.join(s['fact_ids'])}   model: {s['model']}   attempts: {s['attempts']}")
        _print_checks(s["checks"])
    print(f"\ncached -> {OUT_PATH}")

    print("\n=== Deliberately bad copy (should fail) ===")
    bad_subject = "Guaranteed 10% cashback on online shopping!"
    bad_body = "Earn 10% cashback on everything you buy online for five years. Unlimited rewards."
    print(f"  Subject: {bad_subject}\n  Body:    {bad_body}")
    _print_checks([{"rule": r, "passed": ok, "reason": why}
                   for r, ok, why in check_copy(bad_subject, bad_body, load_facts())])


if __name__ == "__main__":
    main()
