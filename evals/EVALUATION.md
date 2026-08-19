# Evaluation

## Why this exists

An LLM coaching system has no ground truth. There is no "correct" coaching tip
to compare against. So the question isn't *"is the advice right?"* — it's
**"can the advice be wrong in a way that damages trust?"**

This harness answers that for one specific, previously-observed failure mode:
the model criticizing a metric that is actually a strength (or praising one
that is actually a gap) — the bug that motivated the contradiction check
("Seraphine's lack of early vision control..." on a 134-vs-72.5 vision score).

## Setup

- 20 fixed matches, sampled deterministically (every 45th match, rotating
  through all 10 participant slots) from `data/sample_matches.json` — the same
  900-match dataset the public demo runs on. Reproducible via
  `evals/select_matches.py`; picks committed in `evals/eval_matches.json`.
- Spans all 5 positions and a mix of wins/losses.
- Pipeline under test: `features/coaching/agents.run_strategic_agent` internals
  (the 3-card Main Diagnosis / Lane Phase / Threat Handling report).
- Model: `gemma2:2b` via local Ollama, `temperature=0.2, top_p=0.9`.
- Each match is drafted **once**; both validator configs are evaluated against
  that same draft, so the only thing differing between configs is the validator.

## Configs compared

- **baseline** — `judge_coaching_output` as it shipped before this work
  (frozen copy at `evals/run_eval.py:judge_coaching_output_legacy`): checked
  one direction only (criticizing an above-average metric), and only inside a
  loss where both above- and below-average metrics were present.
- **v2** — the current shipped `check_contradiction()`: both directions
  (criticizing a strength, praising a gap), unconditionally.

Both configs also run the finalize-step **safety net**: if text still fails
validation after the one allowed repair attempt, ship the deterministic
template instead of a known-bad draft.

## Results (n=20, gemma2:2b, 2026-08-19)

Compared **within a single run** (same drafts, so LLM sampling variance
cannot explain the difference):

| | baseline | v2 |
|---|---|---|
| Reflection pass rate (1st try) | 40% | 35% |
| Contradictions present after repair, *before* the safety net | 7/20 | 7/20 |
| **Contradictions in text actually shipped to the user** | **1/20** | **0/20** |
| Fell back to deterministic template | 12/20 | 13/20 |
| p50 repair latency | 14.4s | 15.1s |

### Finding 1 — the contradiction leak is closed

7 of 20 drafts still contained a real contradiction after the repair pass. The
safety net caught all 7 under v2: **0 contradictory reports reached the user.**
Baseline still leaked 1 — not because its safety net failed, but because its
narrower check never flagged that draft as bad in the first place, so the draft
"passed" and shipped as-is. That single case is the whole argument for the
bidirectional check: a safety net can only stop what the validator can see.

### Finding 2 — the real bottleneck is now formatting, not contradictions

The cost of the safety net is a **65% fallback rate** — two thirds of matches
ship the generic deterministic template instead of a specific LLM-written
report. Breaking down *why* v2 fell back on those 13 matches:

| Trigger | Count |
|---|---|
| Missing required labels (format failure) | 7 |
| Contradiction survived repair | 4 |
| Other format problems | 2 |

**Format failures, not contradictions, are the dominant cause.** `gemma2:2b`
frequently cannot hold the required `Main Diagnosis: / Lane Phase: /
Threat Handling:` structure with Evidence/Meaning/Action in each — so the
safety net fires on a formatting problem and the user loses a specific report
over something that has nothing to do with factual correctness.

That reframes the next step. The contradiction problem is handled. The open
problem is **report specificity**: a stronger model that can reliably hold the
output format would cut the fallback rate sharply, and the infrastructure for
that already exists (`utils/cloud_llm.py`, shipped for the AI Coach Report but
not wired into this legacy strategic path). This harness is set up to measure
exactly that — swap the backend behind `_llm()` and rerun.

### Finding 3 — passing every check does not mean the advice is usable

Format and contradiction checks answer *"does this look like coaching?"*. They
do not answer *"would a LoL player recognise this as advice about their game?"*
Inspecting the 7 reports that passed **every** existing check, against three
new content-quality checks (`check_content_quality` in `validators.py`):

| Check | What it catches | Reports failing |
|---|---|---|
| Template leak | prompt scaffolding copied verbatim into the output | 3 |
| Role nonsense | advice the role would reject (telling a support to farm CS) | 1 |
| Generic | cites <2 facts that actually appear in this match's data | 2 |

**4 of 7 "passing" reports (57%) fail content quality.** Real examples:

> `Lane Phase: Evidence: CS@10, gold@10, deaths, CS/min, or say unclear from
> available data.`

— the model copied the prompt's instruction instead of answering it.

> `Action: Focus on consistent last hitting and farm efficiency.` (Karma, support)

— supports are not judged on CS; the app's own scorecard doesn't even track
CS for UTILITY. A real player rejects this instantly.

> `Action: Request additional data to analyze enemy champion compositions.`

— tells the *user* to go fetch data.

The genericness check is the load-bearing one: `count_match_anchors()` counts
only numbers that genuinely appear in this match's data (unlike `has_number()`,
which any hallucinated digit satisfies). A report scoring 0-1 anchors would
read identically for a completely different game.

**This reframes the whole eval.** Contradiction (Finding 1) was a real bug and
is fixed. Format (Finding 2) is a gate, not a goal. The actual product
question — *is this advice specific and correct enough for a ranked player to
act on?* — is what these checks start to measure, and by that measure the
current small-model output mostly is not.

## Model comparison: gemma2:2b (local) vs gpt-4o-mini (cloud)

Same 20 matches, same prompts, same validators — only the backend behind
`_llm()` differs. Content-quality figures for gemma2:2b were computed
retroactively over all 20 of its drafts so the columns are comparable.

| | gemma2:2b | gpt-4o-mini |
|---|---|---|
| Fallback to generic template (v2) | 65% | **20%** |
| Content-quality pass rate | 45% | **80%** |
| Template leak rate | 40% | **0%** |
| Generic (cites <2 match facts) | 35% | **15%** |
| Role-nonsense rate | 10% | **5%** |
| Avg match anchors per report | 1.85 | **2.55** |
| Contradictions shipped to user (v2) | 0% | **0%** |
| p50 draft latency | 20.1s | **3.2s** |

Every specificity measure improves, template leakage disappears entirely, and
it is ~6x faster. The formatting bottleneck identified in Finding 2 is
essentially resolved: fallback drops from 65% to 20%.

### Finding 4 — the better model contradicts the data *more often*, not less

The one metric that got **worse**: draft-level contradiction rate rose from
**20% (gemma2:2b) to 35% (gpt-4o-mini)**.

Within the cloud run, reports containing a contradiction average **3.00**
match anchors; those without average **2.31**. The more specific the report,
the more likely it contradicts the data.

The mechanism is straightforward once stated: a weak model writes vague filler
("Focus on maximizing impact in teamfights"), and vague text is *structurally
incapable* of contradicting the data because it makes no checkable directional
claim. A strong model writes specific, confident claims about named metrics —
and a specific claim can be specifically wrong.

**This inverts the usual assumption that a better model needs fewer
guardrails.** The contradiction validator became *more* load-bearing after the
upgrade, not less: it caught and blocked 7/20 contradictory drafts on
gpt-4o-mini output (vs 7/20 on gemma, but from a higher-specificity, more
plausible-sounding baseline where a slip does more damage to trust). Shipped
contradiction rate stayed at 0% only because the validator plus safety net
held.

Caveat on strength of claim: n=20 and the anchor gap (3.00 vs 2.31) is
suggestive, not statistically established. Sampling at `temperature=0.2` is
non-deterministic, so the 20%→35% cross-model comparison carries run-to-run
variance. The direction is consistent with the mechanism above, but a larger
n would be needed to state it as settled.

## Finding 5 — "the model lacks LoL knowledge" was the wrong diagnosis

The obvious explanation for generic reports is that the model doesn't know
enough about League. That predicts a knowledge fix (a curated guide corpus).
The data says otherwise.

Inspecting the 4 content-quality failures on the stripped demo dataset, 3 were
the same thing: the model writing `Lane Phase: Evidence: unclear from
available data`. It was not confused about laning — it was **correctly
reporting that the lane data wasn't in its input**. `data/sample_matches.json`
is privacy-stripped: no timeline, so no CS@10, no gold@10, no lane CS delta.

Test: rerun with lane-phase facts restored from the full local dataset's
`challenges` block (`laneMinionsFirst10Minutes`, `maxCsAdvantageOnLaneOpponent`,
`laningPhaseGoldExpAdvantage`, `turretPlatesTaken`, `soloKills`) — same model,
same prompt, same validators, only the input data is richer.

| | stripped (n=20) | rich (n=19) |
|---|---|---|
| Generic (cites <2 match facts) | 15% | **5.3%** |
| Avg match anchors per report | 2.55 | **3.42** |
| Content-quality pass rate | 80% | **84.2%** |
| Draft contradiction rate | 35% | 26.3% |
| Fallback to template (v2) | 20% | 15.8% |
| Contradictions shipped (v2) | 0% | 0% |

Genericness drops ~3x and the model cites ~1 more real match fact per report.
**Nothing about the model's LoL knowledge changed — only what it was told
about the game.** The bottleneck was data plumbing, not domain knowledge, so a
guide/knowledge corpus would not have fixed any of these three failures.

Where a knowledge corpus *would* still help is narrower and worth stating
honestly: patch-specific meta (a model's pretraining goes stale), and
champion-specific tactical detail — which this project already covers with
`champion_rules.json` + `build_knowledge_context`, and with the behavioral
narrative corpus (what Challenger players actually did), which is genuinely
not in any model's pretraining.

**Caveat — this comparison is confounded.** The rich run draws different
matches (from the full local dataset) than the stripped run, so "richer data"
and "different matches" vary together; it is not a controlled A/B. The anchors
result (2.55 → 3.42) is the most direct signal, since more facts in the input
mechanically enable more facts in the output, and it agrees with the mechanism
above. A clean test would restrict both runs to the same match IDs.

### The one failure richer data did not fix

Role-appropriateness got slightly worse (5% → 10.5%, 2 cases): both were
supports (Anivia, Nami) told to work on farming. gpt-4o-mini certainly knows
supports aren't graded on CS — this is a prompting failure, not a knowledge
gap. The fix is to put role responsibility in the prompt as a hard constraint,
reusing the per-position metric definitions that already exist in
`services/execution_service.py`. That is the highest-value remaining item.

## Finding 6 — grounded in real data still isn't the same as usable

The checks so far verify the report is *true*: it cites real facts, doesn't
contradict them, isn't generic. None of them ask whether the player can **do**
anything with it. Extracting all 57 `Action:` lines from the rich run:

| | before | after |
|---|---|---|
| Actions a player could execute (trigger **and** target) | **2%** | **93%** |
| Actions opening with "Focus on / Work on / Prioritize" | 56% | **0%** |
| Actions naming a trigger (when it fires) | 46% | **100%** |
| Actions naming a measurable target | 2% | **93%** |
| **Reports with zero usable actions** | **95%** | **0%** |

Before: 95% of reports contained no advice a player could act on. Every report
was factually correct and told the player things like *"Focus on positioning
to avoid unnecessary deaths"* — which they already knew, phrased as coaching.

The fix was a prompt change, not a model or data change: every `Action:` must
carry a **TRIGGER** (when it fires) and a **TARGET** (a number to check
afterwards), with the vague openers explicitly banned and worked examples
given. The same change added per-position role constraints (a support is never
graded on CS), which took role-nonsense from 10.5% to 0%.

Real output, before and after:

> before: *"Focus on positioning to avoid unnecessary deaths."*
> after: *"Recall by minute 10 with 1300g to target first item by 12:00."*
> after: *"Before each dragon spawn, set vision in the enemy jungle — place at least 2 control wards."*

Side effects, all in the same direction: content-quality pass rate 84% → 100%,
generic rate 5.3% → 0%, average match anchors 3.42 → 4.79, draft contradiction
rate 26.3% → 15.8%, fallback rate 15.8% → 10.5%, shipped contradictions
still 0%.

### A measurement bug worth recording

The first version of the actionability check reported **31.6%**, not 93%. Its
target-detection regex required a number immediately followed by a unit, so it
scored all of these as having no target:

> "Recall by minute 10 with **1300g**…" (gold unit missing from the pattern)
> "reduce deaths to **4 or fewer**" (phrasing not covered)
> "place **2 control wards**" (word between number and noun)

An under-matching validator silently under-reports quality, which is the more
dangerous direction of error: it would have sent us optimising a problem that
was already 3x better than measured. The patterns are now deliberately broad,
with regression tests pinning each real phrasing
(`test_target_detection_handles_real_phrasings`).

## Finding 7 — same treatment applied to the live path

Findings 1-6 were measured on `run_strategic_agent`, which no page calls. The
report users actually see comes from `run_ai_coach_report_agent`. A second
harness (`evals/run_eval_coach.py`) measures that path directly, with the
action-bearing section being PRACTICE ASSIGNMENT.

| | before | after |
|---|---|---|
| Reflection pass rate | 5.3% | **94.7%** |
| Practice assignment a player can execute | 52.6% | **100%** |
| — names a trigger (when it fires) | 57.9% | **100%** |
| — names a measurable target | 94.7% | **100%** |
| Template leak (`[Unknown Timestamp]` etc.) | 100% | **0%** |
| Role-nonsense rate | 10.5% | **0%** |
| Avg match anchors per report | 6.05 | **7.42** |

Real practice assignment, after:

> *"Before each dragon spawn, place a control ward in the enemy raptor camp —
> target 2 per game."*

### Two bugs this surfaced that were not in the prompt

**1. A validator/prompt contract that broke silently.** Rewriting the TURNING
POINTS template dropped the literal labels `What happened:` / `Why it
mattered:` / `Replay checklist:` — which `judge_ai_coach_output` greps for.
Output quality was fine; the pass rate collapsed because the validator and the
prompt had drifted apart. Restoring the literal labels took the pass rate from
36.8% to ~100%. Worth noting as a class of bug: **when a validator matches on
keywords, the prompt owns those keywords, and changing one without the other
fails loudly in the metric but invisibly in the text.**

**2. Garbage in, garbage out — the model faithfully repeats a bad
deterministic diagnosis.** One report told an Anivia *support* their primary
failure was CS/min and they should work on last-hitting. The prompt's role
rules were correct; the *input* was wrong — this harness's `build_coach_context`
ranked below-benchmark metrics without regard to position, so it handed the
model "CS/min" as a support's primary failure and the model dutifully coached
it. The live app does not have this bug (`POSITION_METRICS["UTILITY"]` in
`services/execution_service.py` grades vision / KP / survival / roam, never
CS), so this was an eval-fidelity defect, not a product defect. Making the
harness role-aware took role-nonsense to 0%.

The general lesson holds for the product though: **no prompt rule can save a
report whose deterministic input is already wrong.** The role guard has to live
in the gap-selection layer, not only in the prompt.

### A metric that does not apply cleanly

`turning_actionable_rate` scores TURNING POINTS with the same trigger+target
test used for drills, and lands at 8-45% depending on run. That is arguably
measuring the wrong thing: a turning point is a *replay check* ("verify whether
the wave was crashed before you rotated"), not a drill with a numeric target.
It is reported for transparency but should not be read as a quality regression.

## Honest caveats on these numbers

- **Cross-run comparison is not valid here.** An earlier run of this harness
  (pre-safety-net, `evals/results/*_before_fix.json`) saw a 30% draft-level
  contradiction rate vs 20% here. Sampling is not deterministic at
  `temperature=0.2`, so drafts differ between runs. Only the within-run
  baseline-vs-v2 comparison above is a controlled measurement.
- **n=20, single small local model.** Enough to show the mechanism works and
  to identify the next bottleneck; not enough for a confident percentage claim
  about a production model.
- **No human ratings.** This measures internal consistency (does the text
  contradict the data it was given), not whether the advice helps a player
  climb. That needs real usage data this project does not have yet.
- **Sample dataset is privacy-stripped** (no timeline, items, or runes), so
  this evaluates text-only reasoning over box-score stats — a narrower slice
  than the live Player Review AI Coach Report, which also has timeline + RAG
  context and a different prompt and validator.
- **One repair attempt**, matching the app's own `MAX_REPAIRS = 1`.
