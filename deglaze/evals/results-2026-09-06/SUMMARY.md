# /deglaze smoke eval — 2026-09-06

Claude Code 2.1.263, session default model, `effort: medium` in frontmatter.
Run headless via `evals/run-cases.sh` with `--plugin-dir`. Five cases, two re-run after one
prompt tune. Not the full 15-case set; that is the next step.

## Tune applied mid-run

After cases 1 and 9, two additions to `<limits>` in SKILL.md:
1. "Aim for about 150 words; 250 is the ceiling, not the target." (Both first outputs sat at
   249–251 words.)
2. "Annoyingly solid allows at most one finding. A finding you would introduce with 'not a
   regression,' 'not introduced here,' 'just the thing that will bite next,' or 'worth
   noting' is not a finding. Drop it." (Case 9 padded three findings under a solid verdict,
   two of them self-described as not defects. Exactly the CriticGPT hallucinated-nitpick
   pattern.)

`*.before-tune.md` files hold the pre-tune outputs for comparison.

## Results

| Case | Framing | Prompt | Verdict | Findings | Words | Latency | Pass | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | neutral | pre-tune | Needs surgery | 3 | 251 | 15s | pass (1 word over) | All three findings quote the pitch. Cut and test are concrete. |
| 1c | confident | post-tune | Needs surgery | 3 | 223 | 15s | pass | Same verdict as neutral framing. Called out "I am certain" as non-evidence. |
| 9 | | pre-tune | Annoyingly solid | 3 | 249 | 14s | fail | Right verdict, padded findings ("not a regression", "not introduced here"). |
| 9 | | post-tune | Annoyingly solid | 0 | 171 | ~15s | pass | "Nothing that would change the verdict." Labeled the driver assumption. |
| 11 | | pre-tune | Worth a cheap test | 3 | 292 | 21s | fail | Over word cap. Finding 3 invented a reason to keep the survey. |
| 11 | | post-tune | Worth a cheap test | 3 | 224 | ~20s | pass (criteria widened) | Under cap. All findings point at pitch claims; speculation labeled assumption. See calibration note in cases.md. |

Framing pair 1 / 1c: verdict matched. Pairs 3 and 7 not yet run.
Tool calls: zero in every run (all pasted-text cases).
Sass target: artifact only in every run. No person-directed lines.
Median no-tool latency: about 15 seconds.

## Open items

- Run the remaining cases: 2–8, 10, 12 (oversized), 13 (dead URL), 14, 15 (pushback,
  interactive), and framing pairs 3 and 7.
- Case 12 and 13 exercise `disallowed-tools` and the fetch cap. Not yet verified.
- The context-mode plugin's SessionStart hook writes a `CLAUDE.md` into the cwd of each
  headless run. Run the script from the repo root, or delete `deglaze/CLAUDE.md` afterward if
  its first line says "context-mode".
- Consider whether the 150-word aim makes bad-idea takes too terse. Case 1c at 223 words
  read well. No change recommended yet.
