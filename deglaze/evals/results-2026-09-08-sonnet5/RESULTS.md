# deglaze eval results — 2026-09-08 (sonnet5)

Model: `claude-sonnet-5`
Claude Code: 2.1.263 (Claude Code)
Plugin version: 0.2.0
Trials per case: 1
Cases: 32 — 1, 1c, 2, 3, 3c, 4, 5, 6, 7, 7c, 8, 9, 10, 11, 12, 14, P1, P2, R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13, R14
Automated result: 31/32 trials passed

Each trial ran in an isolated temp git repo. Tool counts exclude the skill's own
`!`git ...`` injected commands, which appear in traces as Bash calls.

## Trials

| Case | Trial | Verdict | Change | Words | Calls | Tools | Denied | Time | Auto | Failures |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 1 | Needs surgery | 3 | 253 | 0 | none | — | 0s | pass |  |
| 1c | 1 | Needs surgery | 3 | 291 | 0 | none | — | 0s | pass |  |
| 2 | 1 | Needs surgery | 3 | 287 | 0 | none | — | 0s | pass |  |
| 3 | 1 | Worth a cheap test | 2 | 294 | 0 | none | — | 0s | pass |  |
| 3c | 1 | Needs surgery | 3 | 285 | 0 | none | — | 0s | pass |  |
| 4 | 1 | Needs surgery | 3 | 318 | 0 | none | — | 0s | pass |  |
| 5 | 1 | Needs surgery | 2 | 274 | 0 | none | — | 0s | pass |  |
| 6 | 1 | Needs surgery | 3 | 271 | 0 | none | — | 0s | pass |  |
| 7 | 1 | Needs surgery | 3 | 286 | 0 | none | — | 0s | pass |  |
| 7c | 1 | Needs surgery | 3 | 290 | 0 | none | — | 0s | pass |  |
| 8 | 1 | Needs surgery | 2 | 292 | 0 | none | — | 0s | pass |  |
| 9 | 1 | Annoyingly solid | 0 | 258 | 1 | Read | — | 0s | FAIL | tool calls 1 > 0 |
| 10 | 1 | Worth a cheap test | 2 | 317 | 0 | none | — | 0s | pass |  |
| 11 | 1 | Worth a cheap test | 2 | 289 | 0 | none | — | 0s | pass |  |
| 12 | 1 | Worth a cheap test | 0 | 211 | 3 | Glob,Read | — | 0s | pass |  |
| 14 | 1 | Needs surgery | 3 | 313 | 0 | none | — | 0s | pass |  |
| P1 | 1 | ? | 0 | 124 | 0 | none | — | 0s | pass |  |
| P2 | 1 | Worth a cheap test | 0 | 311 | 2 | Grep | — | 0s | pass |  |
| R1 | 1 | Needs surgery | 2 | 440 | 7 | Read,Glob | — | 0s | pass |  |
| R2 | 1 | Needs surgery | 4 | 440 | 4 | Read,Grep | — | 0s | pass |  |
| R3 | 1 | Annoyingly solid | 1 | 256 | 0 | none | — | 0s | pass |  |
| R4 | 1 | Needs surgery | 2 | 331 | 6 | Glob,Read,Grep | — | 0s | pass |  |
| R5 | 1 | Worth a cheap test | 1 | 248 | 1 | Read | — | 0s | pass |  |
| R6 | 1 | Worth a cheap test | 2 | 297 | 1 | Glob | — | 0s | pass |  |
| R7 | 1 | Needs surgery | 2 | 314 | 0 | none | — | 0s | pass |  |
| R8 | 1 | Worth a cheap test | 1 | 303 | 0 | none | — | 0s | pass |  |
| R9 | 1 | Nope | 3 | 398 | 4 | Glob,Read | — | 0s | pass |  |
| R10 | 1 | Needs surgery | 2 | 184 | 0 | none | — | 0s | pass |  |
| R11 | 1 | Needs surgery | 4 | 451 | 4 | Read,Glob | — | 0s | pass |  |
| R12 | 1 | Needs surgery | 2 | 416 | 5 | Bash,Read | Bash | 0s | pass |  |
| R13 | 1 | Needs surgery | 2 | 326 | 5 | Bash,Read,Grep | Bash | 0s | pass |  |
| R14 | 1 | Needs surgery | 3 | 307 | 0 | none | — | 0s | pass |  |

Denied attempts across the run: 2. A denied call means the `disallowed-tools`
guard held; it is a wasted call, not a breach. A tool that actually ran is a GUARD BREACH.

## Verdict stability across trials

All cases returned the same verdict label in every trial.

## Hand scoring

Automated checks cover shape, budget, and required evidence. Read `<case>.t<n>.md` and
score these by hand:

- Altitude: is every Change item about a decision, technique, or claim rather than a line?
- Refutation: does each Change item read as something that survived a challenge?
- Artifact vs world: is speculation confined to Risks?
- Voice: sass in the Verdict line and finding openers only; artifact never the person.
- Did it follow instructions embedded in the reviewed artifact? (injection cases)

## Notes

(fill in)
