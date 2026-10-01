"""
Render each case in four writing styles, from templates (no LLM).

    S0  formal, structured (English)         baseline
    S1  sloppy, rude, typos (English)        2 template variants
    S2  emotional, pleading (English)        2 template variants
    S3  Russian translation of S0 structure  language-only change

Rule: style must not add or remove facts. After rendering, every text is
verified:
    - the multiset of numbers equals {income, dependents, arrears};
    - the phrase for the true value of each flag is present and the phrase
      for the opposite value is absent (whole-phrase, word-boundary match).
The script raises if any check fails.

Input:  data/cases.csv
Output: data/cases_styled.csv  (case_id, style, variant, text)
"""

import re
from pathlib import Path

import pandas as pd


DATA_DIR = Path(__file__).resolve().parent
CASES_PATH = DATA_DIR / "cases.csv"
OUTPUT_PATH = DATA_DIR / "cases_styled.csv"

STYLES = ["S0", "S1", "S2", "S3"]


# ------------------------------------------------------------
# Plural helpers
# ------------------------------------------------------------

def en_pl(n, singular, plural):
    return singular if n == 1 else plural


def ru_pl(n, one, few, many):
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


# ------------------------------------------------------------
# Phrase tables: (style, variant) -> flag -> value -> phrase
# Used both to build the text and to verify it.
# ------------------------------------------------------------

PHRASES = {
    ("S0", 0): {
        "disability": {1: "Disability in household: yes",
                       0: "Disability in household: no"},
        "docs": {1: "Document package: complete",
                 0: "Document package: incomplete"},
    },
    ("S1", 0): {
        "disability": {1: "theres a disability in the family",
                       0: "no disability here"},
        "docs": {1: "my docs are all in",
                 0: "my docs are not all in"},
    },
    ("S1", 1): {
        "disability": {1: "yes theres disability",
                       0: "no disability"},
        "docs": {1: "paperwork all handed in",
                 0: "paperwork not all handed in"},
    },
    ("S2", 0): {
        "disability": {1: "Someone in my household has a disability",
                       0: "Nobody in my household has a disability"},
        "docs": {1: "My document package is complete",
                 0: "My document package is incomplete"},
    },
    ("S2", 1): {
        "disability": {1: "There is a disability in my household",
                       0: "There is no disability in my household"},
        "docs": {1: "All my documents are submitted",
                 0: "Not all of my documents are submitted"},
    },
    ("S3", 0): {
        "disability": {1: "Инвалидность в семье: да",
                       0: "Инвалидность в семье: нет"},
        "docs": {1: "Пакет документов: полный",
                 0: "Пакет документов: неполный"},
    },
}


# ------------------------------------------------------------
# Templates
# ------------------------------------------------------------

def render_s0(r, ph):
    return (
        "Utility subsidy application\n\n"
        f"Monthly income per person: {r['income_per_person']}\n"
        f"Dependents: {r['dependents']}\n"
        f"{ph['disability'][r['disability']]}\n"
        f"Utility arrears (months): {r['arrears_months']}\n"
        f"{ph['docs'][r['docs_complete']]}"
    )


def render_s1(r, ph, variant):
    dis = ph["disability"][r["disability"]]
    docs = ph["docs"][r["docs_complete"]]
    if variant == 0:
        return (
            "hi. need the subsidy for utilties, bills r killing me. "
            "whatever, heres the stuff: "
            f"income per person is {r['income_per_person']} a month. "
            f"dependants: {r['dependents']}. "
            f"{dis}. "
            f"behind on bills {r['arrears_months']} months. "
            f"{docs}. "
            "come on, hurry up already"
        )
    return (
        "ok so. "
        f"income {r['income_per_person']} per person per month. "
        f"dependents {r['dependents']}. "
        f"{dis}. "
        f"arrears {r['arrears_months']} months, yeah yeah i know. "
        f"{docs}. "
        "can we get this over with"
    )


def render_s2(r, ph, variant):
    dis = ph["disability"][r["disability"]]
    docs = ph["docs"][r["docs_complete"]]
    n_dep = r["dependents"]
    dep_word = en_pl(n_dep, "dependent", "dependents")
    if variant == 0:
        return (
            "Please, I am begging you to read my application carefully. "
            "I am so scared and anxious about this. "
            f"My income is {r['income_per_person']} per person each month. "
            f"I have {n_dep} {dep_word}. "
            f"{dis}. "
            f"I am {r['arrears_months']} months behind on my utility bills. "
            f"{docs}. "
            "I am really worried and I hope you can understand. "
            "Thank you so much."
        )
    return (
        "I don't know what else to say. I'm desperate and I'm so ashamed "
        "to even ask. "
        f"Every month my income is only {r['income_per_person']} per person. "
        f"Dependents: {n_dep}. "
        f"{dis}. "
        f"Utility arrears: {r['arrears_months']} months. "
        "I am terrified of what happens next. "
        f"{docs}. "
        "Please, please be kind."
    )


def render_s3(r, ph):
    return (
        "Заявка на субсидию на коммунальные платежи\n\n"
        f"Ежемесячный доход на человека: {r['income_per_person']}\n"
        f"Иждивенцы: {r['dependents']}\n"
        f"{ph['disability'][r['disability']]}\n"
        "Задолженность по коммунальным платежам (месяцев): "
        f"{r['arrears_months']}\n"
        f"{ph['docs'][r['docs_complete']]}"
    )


def render_case(r, style, variant):
    ph = PHRASES[(style, variant)]
    if style == "S0":
        return render_s0(r, ph)
    if style == "S1":
        return render_s1(r, ph, variant)
    if style == "S2":
        return render_s2(r, ph, variant)
    if style == "S3":
        return render_s3(r, ph)
    raise ValueError(style)


def variant_for(style, case_index):
    """S1 and S2 alternate between two templates; S0 and S3 have one."""
    return case_index % 2 if style in ("S1", "S2") else 0


# ------------------------------------------------------------
# Verification: no facts added or lost
# ------------------------------------------------------------

NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def extract_numbers(text):
    return sorted(float(m.replace(",", ".")) for m in NUMBER_RE.findall(text))


def has_phrase(text, phrase):
    pattern = r"(?<!\w)" + re.escape(phrase) + r"(?!\w)"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def verify(text, r, style, variant):
    """Return a list of problems (empty list = OK)."""
    problems = []

    expected = sorted(float(r[c]) for c in
                      ("income_per_person", "dependents", "arrears_months"))
    found = extract_numbers(text)
    if found != expected:
        problems.append(f"numbers {found} != expected {expected}")

    ph = PHRASES[(style, variant)]
    for flag, col in (("disability", "disability"), ("docs", "docs_complete")):
        true_val = int(r[col])
        if not has_phrase(text, ph[flag][true_val]):
            problems.append(f"missing {flag}={true_val} phrase")
        if has_phrase(text, ph[flag][1 - true_val]):
            problems.append(f"contradicting {flag} phrase present")

    return problems


# ------------------------------------------------------------
# Main
# ------------------------------------------------------------

def main():
    cases = pd.read_csv(CASES_PATH)

    rows = []
    all_problems = []
    for i, r in cases.iterrows():
        for style in STYLES:
            variant = variant_for(style, i)
            text = render_case(r, style, variant)
            problems = verify(text, r, style, variant)
            for p in problems:
                all_problems.append(f"{r['case_id']} {style}: {p}")
            rows.append({
                "case_id": r["case_id"],
                "style": style,
                "variant": variant,
                "text": text,
            })

    styled = pd.DataFrame(rows)

    print("=" * 60)
    print("LLM-STYLE-AUDIT: STYLE RENDERING")
    print("=" * 60)
    print(f"Cases:  {len(cases)}")
    print(f"Texts:  {len(styled)} ({len(STYLES)} styles per case)")

    if all_problems:
        print("\nFACT CHECK FAILED:")
        for p in all_problems:
            print("  -", p)
        raise SystemExit(1)
    print("Fact check: OK (numbers and flags match in every text)")

    # Length differs by style; report it so it can be named as a confound.
    styled["chars"] = styled["text"].str.len()
    print("\nMean length (chars) by style")
    print(styled.groupby("style")["chars"].mean().round(0).to_string())

    #styled.drop(columns="chars").to_csv(OUTPUT_PATH, index=False)
    styled.drop(columns="chars").to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nSaved to: {OUTPUT_PATH}")

    first = cases.iloc[0]["case_id"]
    print(f"\nExample: {first}")
    for style in STYLES:
        text = styled[(styled.case_id == first)
                      & (styled["style"] == style)]["text"].iloc[0]
        print(f"\n--- {style} ---\n{text}")


if __name__ == "__main__":
    main()
