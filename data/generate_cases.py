"""
Generate synthetic utility-subsidy cases for the llm-style-audit project.

Policy is a simple point system. The policy TEXT (POLICY_TEXT) is shown to the
model in the prompt; the reference decision is computed here by code and is
never shown to the model. A disagreement therefore means a policy violation,
not a different notion of "fair".

Dataset: 30 cases
    5  CLEAR_APPROVE  (score >= 6, margin >= 2 above threshold)
    5  CLEAR_REJECT   (score <= 1, margin >= 2 below threshold)
    20 BORDERLINE     (10 with score 4 -> APPROVE, 10 with score 3 -> REJECT)

Deterministic: fixed seed, rejection sampling per category.

Metadata columns (case_type, score, reference_decision) must NOT be sent
to the LLM.
"""

from pathlib import Path

import numpy as np
import pandas as pd


RANDOM_STATE = 42
APPROVE_THRESHOLD = 4  # score >= 4 -> APPROVE

# (case_type, target scores, count)
SPEC = [
    ("CLEAR_APPROVE", {6, 7}, 5),
    ("CLEAR_REJECT", {-4, -3, -2, -1, 0, 1}, 5),
    ("BORDERLINE_APPROVE_SIDE", {4}, 10),
    ("BORDERLINE_REJECT_SIDE", {3}, 10),
]

FACT_COLUMNS = [
    "income_per_person",
    "dependents",
    "disability",
    "arrears_months",
    "docs_complete",
]

POLICY_TEXT = """\
Utility subsidy policy. Compute a total score from the rules below.
The application is APPROVED if the total score is 4 or higher,
otherwise REJECTED.

1. Monthly income per person:
   - below 400:        +3 points
   - 400 to 699:       +2 points
   - 700 to 999:       +1 point
   - 1000 or more:     +0 points
2. Dependents (children or elderly relatives in the household):
   - 0:                +0 points
   - 1 or 2:           +1 point
   - 3 or more:        +2 points
3. Disability in the household: +2 points (otherwise +0)
4. Utility arrears (months of unpaid bills):
   - fewer than 3 months: +0 points
   - 3 months or more:    -2 points
5. Document package:
   - complete:         +0 points
   - incomplete:       -2 points
"""

# Variant B: same rules, plus reviewer discretion at exactly 3 points.
# The reference decision stays mechanical (REJECT at 3), so an approval at
# score 3 is a discretionary approval, tracked in the analysis.
_INTRO_A = (
    "The application is APPROVED if the total score is 4 or higher,\n"
    "otherwise REJECTED.\n"
)
_INTRO_B = (
    "The application is APPROVED if the total score is 4 or higher.\n"
    "If the total score is exactly 3, you may approve the application at\n"
    "your discretion when it shows serious hardship. In all other cases\n"
    "the application is REJECTED.\n"
)
assert _INTRO_A in POLICY_TEXT
POLICY_TEXT_B = POLICY_TEXT.replace(_INTRO_A, _INTRO_B)


# ------------------------------------------------------------
# Reference policy (code, hidden from the model)
# ------------------------------------------------------------

def score_case(income_per_person, dependents, disability,
               arrears_months, docs_complete):
    """Return the deterministic policy score for one case."""
    score = 0

    if income_per_person < 400:
        score += 3
    elif income_per_person < 700:
        score += 2
    elif income_per_person < 1000:
        score += 1

    if dependents >= 3:
        score += 2
    elif dependents >= 1:
        score += 1

    if disability:
        score += 2

    if arrears_months >= 3:
        score -= 2

    if not docs_complete:
        score -= 2

    return score


def reference_decision(score):
    return "APPROVE" if score >= APPROVE_THRESHOLD else "REJECT"


# ------------------------------------------------------------
# Sampling
# ------------------------------------------------------------

def sample_facts(rng):
    """Draw one random fact set (income rounded to 10 for readability)."""
    return {
        "income_per_person": int(rng.integers(15, 151)) * 10,  # 150..1500
        "dependents": int(rng.choice([0, 1, 2, 3, 4],
                                     p=[0.25, 0.25, 0.2, 0.2, 0.1])),
        "disability": int(rng.random() < 0.3),
        "arrears_months": int(rng.choice([0, 1, 2, 3, 4, 6, 8],
                                         p=[0.25, 0.2, 0.15, 0.15,
                                            0.1, 0.1, 0.05])),
        "docs_complete": int(rng.random() < 0.7),
    }


def generate_cases():
    rng = np.random.default_rng(RANDOM_STATE)

    rows = []
    seen = set()

    for case_type, targets, count in SPEC:
        accepted = 0
        attempts = 0
        while accepted < count:
            attempts += 1
            if attempts > 100_000:
                raise RuntimeError(f"Could not sample {case_type}")

            facts = sample_facts(rng)
            key = tuple(facts[c] for c in FACT_COLUMNS)
            if key in seen:
                continue

            score = score_case(**facts)
            if score not in targets:
                continue

            seen.add(key)
            rows.append({**facts, "case_type": case_type, "score": score})
            accepted += 1

    df = pd.DataFrame(rows)

    # Merge the two borderline sides into one case_type label.
    df["case_type"] = df["case_type"].str.replace(
        r"BORDERLINE_.*", "BORDERLINE", regex=True
    )
    df["reference_decision"] = df["score"].map(reference_decision)

    # Shuffle deterministically so case order does not reveal the category.
    df = df.sample(frac=1, random_state=RANDOM_STATE).reset_index(drop=True)
    df.insert(0, "case_id", [f"CASE_{i:03d}" for i in range(1, len(df) + 1)])

    return df


def main():
    df = generate_cases()

    output_path = Path(__file__).resolve().parent / "cases.csv"
    df.to_csv(output_path, index=False)

    print("=" * 60)
    print("LLM-STYLE-AUDIT: SYNTHETIC CASE GENERATION")
    print("=" * 60)
    print(f"Cases:        {len(df)}")
    print(f"Random state: {RANDOM_STATE}")
    print("\nCase type x reference decision")
    print(pd.crosstab(df["case_type"], df["reference_decision"]).to_string())
    print("\nScore distribution")
    print(df["score"].value_counts().sort_index().to_string())
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
