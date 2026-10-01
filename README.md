# llm-style-audit: The Price of Style

> Does an LLM reward how you write, not what you say? A small audit of LLM decisions on social-benefit applications with identical facts but different writing style, emotion and language.

Synthetic utility-subsidy applications are decided by `openai/gpt-oss-120b` (Groq, temperature 0) under an explicit point policy given in the prompt. The reference decision is computed by code and never shown to the model, so a disagreement means a policy deviation. Every case is rendered in four styles from templates (no LLM): formal, sloppy and rude, emotional, and Russian. A checker confirms that style adds or removes no facts.

## Findings (short)

- **Strict policy:** 0 of 120 style comparisons changed a decision. Style has no price when the rules are explicit.
- **Policy with reviewer discretion:** all 9 style-driven changes went toward APPROVE, none the other way. The direction is consistent but not statistically significant (n is small; see the report).
- **Influence is undeclared:** the model almost never names style as a reason. It writes "serious hardship", often citing the applicant's own words.

Full numbers, method and limits: [`reports/REPORT.md`](reports/REPORT.md). Read the limits section before quoting anything.

## Three checks

1. **Accuracy by style** against the code-computed reference.
2. **Price of style:** shift in approval rate versus the formal baseline, with a repeated baseline run as the noise reference. Effects within noise are not claimed.
3. **Undeclared influence:** offline analysis of rationales. Did the decision change while the rationale stays silent about style?

## Repository

```
data/
  generate_cases.py    policy, 30 cases (5 clear approve, 5 clear reject, 20 borderline), seed 42
  render_styles.py     4 styles from templates + fact check (numbers and flags)
  cases.csv            generated cases
  cases_styled.csv     120 styled texts
validation/
  run_styles.py        model runner: resumable, stops on rate limit; --variant A|B
  analyze.py           the three checks; --variant A|B
reports/
  style_results*.csv   raw decisions and rationales
  analysis_output*.txt console output of the analysis
  flips_review_B.csv   flipped cases for manual reading
  REPORT.md            report
```

## Run

```
pip install pandas numpy groq
set GROQ_API_KEY=your_key          # PowerShell: $env:GROQ_API_KEY = "your_key"

python data/generate_cases.py
python data/render_styles.py
python validation/run_styles.py --limit 2     # smoke test
python validation/run_styles.py               # variant A: strict policy, 150 calls
python validation/run_styles.py --variant B   # variant B: with discretion, 100 calls
python validation/analyze.py
python validation/analyze.py --variant B
```

Total: 250 model calls. Do not commit your API key.

## Scope

A quick method demonstration, not a study. Synthetic data, one model, one run, small samples. Not evidence about any real benefits system.

## License

MIT, see [LICENSE](LICENSE).
