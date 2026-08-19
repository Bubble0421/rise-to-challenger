# Eval result files

Every file here is real output from a run of the harnesses in `evals/`, kept so
the numbers in `../EVALUATION.md` can be checked. `raw_*` holds per-match
records (including the full generated report); `summary_*` holds the aggregate.

## Strategic path (`run_eval.py` → `run_strategic_agent`)

| File | Run |
|---|---|
| `*_before_fix` | local gemma2:2b, before the finalize-step safety net |
| `*_gemma2b` | local gemma2:2b, with safety net |
| `summary.json` / `raw_results.json` | gpt-4o-mini, stripped demo dataset |
| `*_rich_before_prompt` | gpt-4o-mini, rich dataset, before the actionability prompt |
| `*_rich_v2` | gpt-4o-mini, rich dataset, after the actionability prompt |

## Live AI Coach path (`run_eval_coach.py` → `run_ai_coach_report_agent`)

| File | Run |
|---|---|
| `*_coach_before` | live prompt as previously shipped |
| `*_coach_after` | after the actionability + role rules |
| `*_coach_final` | after restoring the literal TURNING POINTS labels |
| `*_coach_final2` | after making the harness's coach context role-aware (the number quoted in EVALUATION.md) |

Runs are not deterministic (`temperature=0.2`), so reruns will differ slightly.
Only within-run comparisons are controlled; see the caveats in `../EVALUATION.md`.
