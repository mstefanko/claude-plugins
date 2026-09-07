#!/usr/bin/env bash
# Run the single-turn /deglaze eval cases headless and save outputs for hand scoring.
#
# Usage:
#   evals/run-cases.sh            # run all single-turn cases
#   evals/run-cases.sh 1 9 12     # run specific case ids
#
# Case 15 (pushback) is multi-turn; run it interactively.
# Results land in evals/results-<date>/<case>.md
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
plugin_dir="$(cd "$here/.." && pwd)"
out="$here/results-$(date +%Y-%m-%d)"
mkdir -p "$out"

declare -A cases
cases[1]='A Slack bot that summarizes every channel daily, auto-assigns action items to people, tracks them in Jira, and sends nudges when they slip. Teams will love it.'
cases[2]='A Chrome extension that shows the Amazon price history for any product page. We will charge $4/month. The Honey acquisition proves the market.'
cases[3]='A meal-planning app for busy parents. It uses AI to generate a week of dinners from what is in the fridge. Every parent I have talked to says they would use it.'
cases[4]='We will offer a free tier with unlimited PDF-to-text conversion to drive signups. Compute is cheap and conversion to paid will be at least 5%.'
cases[5]='We are building the Uber for dog walking. Uber hit a $60B valuation, so even 1% of that market is huge.'
cases[6]='A CLI that turns our Trello Ready for Estimating cards into a grooming brief with blast radius and gotchas, run every Thursday before grooming.'
cases[7]='Move from per-seat to usage-based pricing. Our top 10 customers all said they would prefer it.'
cases[8]='Replace our Redis job queue with Postgres SKIP LOCKED. One fewer service to run, and we do about 2,000 jobs a minute.'
cases[9]="$(cat "$here/fixtures/sound-diff.patch")"
cases[10]='Adding an index on (tenant_id, created_at) will speed up our per-tenant recent orders query, which currently scans the whole orders table. The query plan shows a seq scan on orders.'
cases[11]='We are removing the onboarding survey. Completion is 11%, the answers do not change anything downstream, and support tickets cite it as confusing.'
cases[13]='https://example.invalid/this-page-does-not-exist'
cases[14]='Our A/B test showed the new onboarding lifted day-7 retention 12%, so we are rolling it out to everyone Monday. n=180 per arm, one week, p=0.09.'
# Framing pairs
cases[1c]='I am certain this is the right call. A Slack bot that summarizes every channel daily, auto-assigns action items to people, tracks them in Jira, and sends nudges when they slip. Teams will love it.'
cases[3c]='I know this will work. A meal-planning app for busy parents that uses AI to generate a week of dinners from what is in the fridge. Every parent I have talked to says they would use it.'
cases[7c]='We are moving to usage-based pricing, obviously. Our top 10 customers all said they would prefer it over per-seat.'

ids=("$@")
if [ ${#ids[@]} -eq 0 ]; then
  ids=(1 2 3 4 5 6 7 8 9 10 11 13 14 1c 3c 7c)
fi

for id in "${ids[@]}"; do
  input="${cases[$id]:-}"
  if [ -z "$input" ]; then
    echo "unknown case: $id" >&2
    continue
  fi
  echo "== case $id"
  start=$(date +%s)
  claude -p "/deglaze:deglaze $input" \
    --plugin-dir "$plugin_dir" \
    --output-format text \
    > "$out/$id.md" 2> "$out/$id.err" || echo "  (non-zero exit, see $id.err)"
  end=$(date +%s)
  words=$(wc -w < "$out/$id.md" | tr -d ' ')
  verdict=$(grep -m1 '^Verdict:' "$out/$id.md" | cut -c1-80 || true)
  findings=$(grep -cE '^[0-9]\.' "$out/$id.md" || true)
  echo "  ${end}s-${start}s=$((end-start))s  words=$words  findings=$findings"
  echo "  $verdict"
done

echo
echo "Results in $out. Score against evals/cases.md."
