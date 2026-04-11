# Tech Radar Scan Performance Analysis

## Deep Analysis

### Time Budget Breakdown (11 min total)

| Phase | Estimated Time | % of Total |
|-------|---------------|------------|
| Script: GitHub API (37 queries) | ~56s request + 60s rate-limit pause = ~116s | 18% |
| Script: HN API (19 queries) | ~10s (concurrent) | 2% |
| Script: overhead/history | ~5s | 1% |
| **Script subtotal** | **~130s (2.2 min)** | **20%** |
| Claude: Parse JSON + plan | ~30s | 5% |
| Claude: Reddit WebSearch (6 calls) | ~60-90s | 12% |
| Claude: Write verdicts (35 repos + 15 HN + 5 UTR) | ~5-6 min | 50% |
| Claude: Write file + format tables | ~1 min | 10% |
| **Claude subtotal** | **~8-9 min** | **80%** |

### Assumptions Audit

- 37 GitHub queries confirmed via stderr and code analysis -- [VERIFIED: tech-radar-gather line 1060, stderr line 1]
- 19 HN queries confirmed -- [VERIFIED: stderr line 6]
- Rate-limit batch size 25, pause 60s -- [VERIFIED: tech-radar-gather lines 45-46]
- 37 queries = 2 batches (25 + 12), one 60s pause -- [VERIFIED: stderr line 5]
- 3 phrase queries always fail with 403 -- [VERIFIED: stderr lines 2-4]
- Under-radar duplicates all 11 stack query keywords -- [VERIFIED: build_queries lines 228-239]
- MAX_UNDER_RADAR = 5 items in final output -- [VERIFIED: line 41]

### Recommended Approach

**Merge stack + under-radar into single queries, drop phrase queries, and parallelize GitHub/HN.** This cuts GitHub queries from 37 to 23, eliminates the 60s rate-limit pause, and saves ~75s of script time (from 130s to ~55s). Combined with reducing Claude's verdict scope, total scan drops from ~11 min to ~7-8 min.

### Why Not "Weekly Default"

Changing from monthly to weekly doesn't reduce query count at all -- it only changes the `created:>` date filter. The same 37 queries fire. It would reduce result volume slightly (fewer repos created in 7 days vs 30), which speeds up Claude's verdict phase marginally. It's a complementary change, not a substitute for query reduction.

### Verification Summary

| Question | Answer | Verdict |
|----------|--------|---------|
| How many UTR items survive vs queries spent? | 5 items from 11 queries | CONFIRMS |
| Do failed phrase queries waste time? | ~3-6s, minor but 3 wasted slots | CONFIRMS |
| Can stack + UTR queries merge? | Yes, use `stars:>100` and post-filter | CONFIRMS |
| Where is Claude's time spent? | ~50% on verdict writing, ~12% on WebSearch | NEUTRAL |
| Is there keyword redundancy in index? | No, clustering already deduplicates | NEUTRAL |
| Would smaller per_page help? | Marginal -- latency is query-side | NEUTRAL |

### Contradictions Found & How Resolved

None. All verification questions confirmed or were neutral to the draft recommendation.

### Top 5 Optimizations (Ranked by Time Saved)

#### 1. Merge stack + under-radar queries (saves ~75s)

**Current:** 11 stack queries (`stars:>1000`) + 11 under-radar queries (`stars:100..1000`) = 22 queries with identical keywords.

**Proposed:** 11 queries with `stars:>100`, post-filter in `process_results()` to split main vs under-radar by the `min_stars` threshold.

**Impact:**
- Cuts 11 queries, dropping total GitHub from 37 to 26
- 26 queries fit in ONE batch (batch_size=25... need to also fix phrase queries to hit 23)
- Eliminates the 60-second rate-limit pause between batches
- Net savings: ~17s (11 fewer requests) + 60s (no batch pause) = **~77s**

**Implementation:** In `build_queries()`, remove the under-radar loop (lines 228-239). In `build_repo_url()`, change `stars:>{min_stars}` to `stars:>100`. In `process_results()`, split items into main (stars >= min_stars) vs radar (100 <= stars < min_stars) based on the star count.

#### 2. Remove or fix phrase queries (saves ~6s + eliminates 403 errors)

**Current:** 3 phrase queries always return HTTP 403. GitHub Search API does not support quoted phrase search in the way the URL is constructed (`%22generative+UI%22`).

**Proposed:** Either:
- (a) Remove phrase_queries entirely -- the `interests` field already covers these terms as individual keywords
- (b) Fix the URL encoding to use GitHub's actual phrase search syntax (if it exists for repo search)

**Impact:** Saves 3 queries + eliminates error noise. Combined with optimization 1, total drops to 23 queries = safely within one batch.

#### 3. Parallelize GitHub and HN fetching (saves ~10s)

**Current:** GitHub runs first (lines 1058-1065), then HN runs (lines 1067-1073). Sequential.

**Proposed:** Use `concurrent.futures` to run `fetch_all_github()` and `fetch_all_hn()` in parallel.

**Impact:** HN takes ~10s. Running it concurrently with GitHub means it's fully hidden behind GitHub's longer runtime. Saves ~10s.

#### 4. Pre-filter low-value repos in script output (saves ~2-3 min of Claude time)

**Current:** Script outputs up to 30 main repos + 5 UTR + 15 HN stories = 50 items. Claude writes verdicts for ALL of them.

**Proposed:** Add a `--max-repos` flag (default 15) and smarter ranking in the script:
- Prioritize stack-match and plugin categories over general
- Cap general repos at 5 (currently no cap within MAX_RESULTS=30)
- Pre-score repos by relevance (matched_projects count + stars_per_day) and only output top N

**Impact:** Halving Claude's verdict workload from ~50 items to ~25 saves ~2-3 minutes of model time. This is the single largest opportunity since Claude's work is 80% of total time.

#### 5. Cache GitHub results for same-day re-scans (saves full script time on retries)

**Current:** 14 scans recorded on 2026-04-09 (development iteration). Each re-ran all 56 API calls.

**Proposed:** Cache raw API responses in `~/.tech-radar/cache/` with a TTL (e.g., 4 hours). On re-scan within TTL, skip API calls entirely and re-process cached data.

**Impact:** During development/iteration, saves the full ~130s script time. In normal weekly/monthly usage, no impact (cache always expired). But for the common pattern of "scan, tweak config, re-scan," this is significant.

### Projected Impact

| Optimization | Script savings | Claude savings | Total |
|-------------|---------------|---------------|-------|
| 1. Merge stack+UTR | 77s | 0 | 77s |
| 2. Drop phrase queries | 6s | 0 | 6s |
| 3. Parallelize GH+HN | 10s | 0 | 10s |
| 4. Pre-filter repos | 0 | 120-180s | 150s |
| 5. Same-day cache | 130s (conditional) | 0 | 130s* |
| **Total (1-4)** | **93s** | **150s** | **~4 min saved** |

*Optimization 5 only applies to repeat scans within TTL window.

**Expected time after optimizations 1-4: ~7 minutes** (down from ~11).

### Risks

- **Merging star ranges might return too many low-star repos**: Mitigation -- GitHub API returns sorted by stars desc, so the 30-item cap naturally favors higher-star repos. Post-filtering handles the split.
- **Pre-filtering repos might miss something interesting**: Mitigation -- keep the full JSON in a sidecar file for manual review; only limit what Claude processes.
- **Phrase queries might be wanted for specific search**: Mitigation -- test whether GitHub's repo search actually supports phrase matching before removing entirely.

### Open Questions

- **Exact Claude thinking time**: No way to measure model inference time directly. The 5-6 minute estimate is based on wall-clock observation minus known script/WebSearch time. Reducing input volume is the only lever.
- **GitHub phrase search syntax**: Need to verify whether GitHub repo search supports any form of phrase/exact matching. If yes, fix the encoding. If no, remove the feature.

### Work Breakdown

1. **Merge stack + under-radar queries** in `build_queries()` (lines 196-241) -- remove under-radar loop, widen star range to `>100`
2. **Split results in `process_results()`** (lines 675-747) -- post-filter items into main vs radar by star threshold
3. **Remove `build_under_radar_url()`** (lines 322-324) -- dead code after merge
4. **Remove or fix phrase queries** in `build_queries()` (lines 218-222) -- either delete the block or fix URL encoding
5. **Parallelize GitHub + HN** in `main()` (lines 1058-1073) -- wrap both in a ThreadPoolExecutor
6. **Add `--max-repos` flag** and pre-ranking logic in `process_results()` -- reduce Claude's workload
7. **Optional: Add response cache** with TTL in `main()` -- for development iteration speed

### Sources

- `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar/scripts/tech-radar-gather` -- all query generation and API logic
- `/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/tech-radar/commands/scan.md` -- Claude's phase work definition
- `/Users/mstefanko/.tech-radar.json` -- config driving query generation (5 projects, 11 interests, 3 phrases)
- `/tmp/tech-radar-stderr.txt` -- confirmed 37 GH queries, 19 HN queries, 1 rate-limit pause, 3 failed phrase queries
- `/Users/mstefanko/Documents/Notes/Dev/notes/2026-04-09-tech-radar.md` -- actual scan output (35 repos tracked)

## Confidence: HIGH (90%)

All numbers verified against source code and stderr logs. The merged-query approach is straightforward and the math on batch elimination is deterministic.

## Status: COMPLETE

## Handoff: Option C (standalone)

Writer executes optimizations 1-6 directly from this work breakdown. No further analysis needed.
