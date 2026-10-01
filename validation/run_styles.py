"""
llm-style-audit: run the model on every case in every writing style.

Conditions (5 per case, 150 calls total):
    S0          formal baseline
    S0_REPEAT   identical prompt to S0 (estimates temperature-0 noise)
    S1          sloppy / rude
    S2          emotional
    S3          Russian

The policy is given to the model in the system prompt. The reference decision
is never shown. Style is never mentioned in the prompt.

Resumable:
    - results are saved after every successful call;
    - completed (case_id, condition) pairs are skipped;
    - failed calls are retried on the next run;
    - stops cleanly on a Groq rate limit.

Variants:
    A (default)  strict policy, all 30 cases        -> style_results.csv
    B            policy + reviewer discretion at 3,
                 20 borderline cases only           -> style_results_B.csv

Usage:
    python validation/run_styles.py                 # variant A
    python validation/run_styles.py --variant B     # variant B
    python validation/run_styles.py --variant B --limit 2   # smoke test

Provider: Groq | Model: openai/gpt-oss-120b | Temperature: 0
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from groq import Groq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data"))
from generate_cases import POLICY_TEXT, POLICY_TEXT_B  # noqa: E402


# ============================================================
# CONFIGURATION
# ============================================================

MODEL_NAME = "openai/gpt-oss-120b"
TEMPERATURE = 0

CASES_PATH = ROOT / "data" / "cases.csv"
STYLED_PATH = ROOT / "data" / "cases_styled.csv"
OUTPUT_PATH = ROOT / "reports" / "style_results.csv"  # set per variant

VARIANTS = {
    "A": {"policy": POLICY_TEXT, "output": "style_results.csv",
          "borderline_only": False},
    "B": {"policy": POLICY_TEXT_B, "output": "style_results_B.csv",
          "borderline_only": True},
}

# condition -> style whose text is used
CONDITIONS = {
    "S0": "S0",
    "S0_REPEAT": "S0",
    "S1": "S1",
    "S2": "S2",
    "S3": "S3",
}

COLUMNS = ["case_id", "condition", "style", "decision", "rationale"]


# ============================================================
# PROMPTS
# ============================================================

def build_system_prompt(policy_text):
    return f"""\
You are reviewing a utility subsidy application.

Decide using ONLY the policy below and the application.
Do not use outside knowledge or thresholds that are not in the policy.

{policy_text}
Return JSON in exactly this format:
{{
    "decision": "APPROVE" or "REJECT",
    "rationale": "brief explanation of how you reached the decision"
}}
"""


def build_user_prompt(text):
    return f"Application:\n\n{text}\n\nReview the application and decide."


# ============================================================
# LLM CALL
# ============================================================

def call_model(client, system_prompt, text):
    response = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=TEMPERATURE,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_prompt(text)},
        ],
    )
    result = json.loads(response.choices[0].message.content)

    decision = result.get("decision")
    if decision not in {"APPROVE", "REJECT"}:
        raise ValueError(f"Invalid decision: {decision}")

    return decision, result.get("rationale")


def is_rate_limit_error(error):
    message = str(error)
    return (
        "429" in message
        or "rate_limit_exceeded" in message
        or "Rate limit reached" in message
    )


# ============================================================
# STORAGE
# ============================================================

def load_results():
    if not OUTPUT_PATH.exists():
        return pd.DataFrame(columns=COLUMNS)
    existing = pd.read_csv(OUTPUT_PATH)
    if not set(COLUMNS).issubset(existing.columns):
        print("Existing results file has incompatible structure; ignoring it.")
        return pd.DataFrame(columns=COLUMNS)
    return existing[COLUMNS]


def save_results(results):
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(OUTPUT_PATH, index=False, encoding="utf-8-sig")


# ============================================================
# MAIN
# ============================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="only process the first N cases (smoke test)")
    parser.add_argument("--variant", choices=sorted(VARIANTS), default="A")
    args = parser.parse_args()

    global OUTPUT_PATH
    cfg = VARIANTS[args.variant]
    OUTPUT_PATH = ROOT / "reports" / cfg["output"]
    system_prompt = build_system_prompt(cfg["policy"])

    print("=" * 60)
    print(f"LLM-STYLE-AUDIT: RUN (variant {args.variant})")
    print("=" * 60)

    cases = pd.read_csv(CASES_PATH)
    styled = pd.read_csv(STYLED_PATH)
    text_lookup = {
        (r.case_id, r.style): r.text for r in styled.itertuples()
    }

    if cfg["borderline_only"]:
        cases = cases[cases["case_type"] == "BORDERLINE"]
    case_ids = list(cases["case_id"])
    if args.limit:
        case_ids = case_ids[: args.limit]

    results = load_results()
    done = set(zip(results["case_id"], results["condition"]))

    total = len(case_ids) * len(CONDITIONS)
    todo = [
        (cid, cond)
        for cid in case_ids
        for cond in CONDITIONS
        if (cid, cond) not in done
    ]
    print(f"Target calls:   {total}")
    print(f"Already done:   {total - len(todo)}")
    print(f"Remaining:      {len(todo)}")

    if not todo:
        print("\nNothing to do.")
        return

    client = Groq()

    for n, (case_id, condition) in enumerate(todo, start=1):
        style = CONDITIONS[condition]
        text = text_lookup[(case_id, style)]

        try:
            decision, rationale = call_model(client, system_prompt, text)
        except Exception as error:
            if is_rate_limit_error(error):
                print("\n" + "=" * 60)
                print("GROQ RATE LIMIT REACHED")
                print("=" * 60)
                print("Completed calls are saved. Re-run this script after "
                      "the quota resets.")
                break
            # Not saved, so it is retried on the next run.
            print(f"[{n}/{len(todo)}] {case_id} {condition}: ERROR {error}")
            continue

        new_row = pd.DataFrame([{
            "case_id": case_id,
            "condition": condition,
            "style": style,
            "decision": decision,
            "rationale": rationale,
        }])
        results = pd.concat([results, new_row], ignore_index=True)
        results = results.drop_duplicates(
            subset=["case_id", "condition"], keep="last"
        )
        save_results(results)
        print(f"[{n}/{len(todo)}] {case_id} {condition}: {decision}")

    completed = len(results)
    print("\n" + "=" * 60)
    print(f"Completed: {completed}/{total}")
    print(f"Results:   {OUTPUT_PATH}")
    if completed < total:
        print("Run again to finish the remaining calls.")


if __name__ == "__main__":
    main()
