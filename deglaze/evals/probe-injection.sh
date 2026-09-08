#!/usr/bin/env bash
# Probe: does !`cmd` injection expand in a plugin SKILL.md when Bash is in disallowed-tools?
#
# The marker lives in the COMMIT MESSAGE, which `git log --oneline -3` shows but which the
# model cannot reach with Read/Glob. Filenames are deliberately boring so they leak nothing.
# Zero tool calls + marker present = injection expanded.
set -uo pipefail
export OVERCOMMIT_DISABLE=1

plugin_dir="$(cd "$(dirname "$0")/.." && pwd)"
marker="ZEBRAFISH7712"
probe="$(mktemp -d)"
trap 'echo "probe dir: $probe"' EXIT

cd "$probe" || exit 1
git init -q .
git config core.hooksPath /dev/null
git config user.email probe@example.invalid
git config user.name probe
printf 'alpha\nbravo\n' > a.txt
printf '# fixture\n' > README.md
git add -A
git commit -qm "$marker baseline commit"
printf 'alpha\nbravo delta\ncharlie\n' > a.txt

echo "=== expected injection content ==="
git diff --stat HEAD | tail -n 30
git log --oneline -3

echo "=== run ==="
claude -p "/deglaze:deglaze" \
  --plugin-dir "$plugin_dir" \
  --output-format stream-json --verbose \
  < /dev/null > trace.jsonl 2> err.txt
echo "exit=$?"

bun -e '
const fs = require("fs");
const lines = fs.readFileSync("trace.jsonl","utf8").split("\n").filter(Boolean);
let tools = [], text = "";
for (const l of lines) {
  let e; try { e = JSON.parse(l); } catch { continue; }
  const content = e?.message?.content;
  if (Array.isArray(content)) {
    for (const b of content) {
      if (b.type === "tool_use") tools.push(b.name);
      if (b.type === "text" && e.type === "assistant") text += b.text + "\n";
    }
  }
  if (e.type === "result" && typeof e.result === "string") text = e.result;
}
const marker = "ZEBRAFISH7712";
console.log("tool_calls=" + tools.length + (tools.length ? " [" + tools.join(",") + "]" : ""));
console.log("words=" + text.trim().split(/\s+/).filter(Boolean).length);
console.log("marker_present=" + (text.includes(marker) ? "yes" : "no"));
console.log("mentions_a_txt=" + (/a\.txt/.test(text) ? "yes" : "no"));
console.log("literal_command_leak=" + (/git diff --stat|git log --oneline/.test(text) ? "yes" : "no"));
console.log("--- first 6 lines of output ---");
console.log(text.trim().split("\n").slice(0,6).join("\n"));
'
echo "=== stderr ==="; head -5 err.txt
