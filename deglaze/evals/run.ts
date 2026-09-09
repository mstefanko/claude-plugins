#!/usr/bin/env bun
/**
 * deglaze smoke evals: five cases, one property each. See cases.json `notes`.
 *
 *   bun evals/run.ts                     # all cases, claude-sonnet-5
 *   bun evals/run.ts --only altitude     # one case
 *   bun evals/run.ts --model claude-opus-5
 *
 * Each case runs headless in a temp git repo and is scored from the stream-json trace, which
 * is the only place tool calls, files read, and refused tools are visible. The skill's own
 * !`git ...` context lines appear in the trace as Bash calls and are excluded from the budget.
 * Output goes to results-<date>/ (gitignored). Hand-read <id>.md for altitude and voice.
 */

import { mkdtempSync, rmSync, cpSync, existsSync, readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";

const HERE = dirname(new URL(import.meta.url).pathname);
const PLUGIN_DIR = resolve(HERE, "..");
const INJECTED_BASH = [/^git diff --stat HEAD/, /^git log --oneline -3/];
const SECTIONS = ["Verdict", "Trying to do", "Keep", "Change", "Prove me wrong", "Confidence"];
const VERDICTS = ["Nope", "Needs surgery", "Worth a cheap test", "Annoyingly solid"];
const FORBIDDEN_TOOLS = ["Bash", "Agent", "Task", "Edit", "Write", "NotebookEdit", "EnterPlanMode",
  "EnterWorktree", "Workflow", "Skill", "AskUserQuestion", "WebSearch"];

type Case = {
  id: string;
  input: string;
  fixture?: string;
  expect: {
    verdict?: string[];
    maxWords?: number;
    maxChangeItems?: number;
    minChangeItems?: number;
    maxToolCalls?: number;
    minToolCalls?: number;
    mustRead?: string[];
    mustMention?: string[];
    forbiddenPhrases?: string[];
    notes?: string;
  };
};
type ToolCall = { name: string; input: any; denied: boolean };

const flag = (f: string) => { const i = process.argv.indexOf(f); return i === -1 ? undefined : process.argv[i + 1]; };
const MODEL = flag("--model") ?? "claude-sonnet-5";
const ONLY = flag("--only")?.split(",");

function sh(cmd: string[], cwd: string) {
  const p = Bun.spawnSync(cmd, { cwd, env: { ...process.env, OVERCOMMIT_DISABLE: "1" }, stdout: "pipe", stderr: "pipe" });
  if (p.exitCode !== 0) throw new Error(`${cmd.join(" ")} failed\n${p.stderr.toString()}`);
}

/** Temp repo per case. CASE.md is for humans and is removed; `_dirty/` is copied in after
 *  the baseline commit so the skill's injected `git diff --stat` sees uncommitted work. */
function makeWorkspace(c: Case): string {
  const dir = mkdtempSync(join(tmpdir(), `deglaze-${c.id}-`));
  if (c.fixture) cpSync(join(HERE, "fixtures", c.fixture), dir, { recursive: true });
  else writeFileSync(join(dir, "README.md"), "# scratch\n");
  rmSync(join(dir, "CASE.md"), { force: true });
  const dirty = join(dir, "_dirty");
  sh(["git", "init", "-q", "."], dir);
  sh(["git", "config", "core.hooksPath", "/dev/null"], dir);
  sh(["git", "config", "user.email", "eval@example.invalid"], dir);
  sh(["git", "config", "user.name", "deglaze-eval"], dir);
  if (existsSync(dirty)) writeFileSync(join(dir, ".git", "info", "exclude"), "_dirty/\n");
  sh(["git", "add", "-A"], dir);
  sh(["git", "commit", "-qm", "baseline"], dir);
  if (existsSync(dirty)) {
    for (const e of readdirSync(dirty)) cpSync(join(dirty, e), join(dir, e), { recursive: true });
    rmSync(dirty, { recursive: true, force: true });
  }
  return dir;
}

function parseTrace(jsonl: string) {
  const calls: (ToolCall & { id: string })[] = [];
  const denied = new Set<string>();
  let text = "";
  for (const line of jsonl.split("\n")) {
    let e: any;
    try { e = JSON.parse(line); } catch { continue; }
    for (const b of e?.message?.content ?? []) {
      if (b.type === "tool_use") {
        const cmd = typeof b.input?.command === "string" ? b.input.command.trim() : "";
        if (b.name === "Bash" && INJECTED_BASH.some((re) => re.test(cmd))) continue;
        calls.push({ name: b.name, input: b.input, denied: false, id: b.id });
      }
      // A disallowed tool still emits tool_use; the refusal only shows in its result.
      if (b.type === "tool_result" && b.is_error && /denied|not allowed/i.test(JSON.stringify(b.content ?? ""))) denied.add(b.tool_use_id);
    }
    if (e.type === "result" && typeof e.result === "string") text = e.result;
  }
  for (const c of calls) c.denied = denied.has(c.id);
  return { calls, text };
}

function countChangeItems(text: string): number {
  const lines = text.split("\n");
  const start = lines.findIndex((l) => /^Change:/.test(l));
  let n = 0;
  for (const l of start === -1 ? [] : lines.slice(start + 1)) {
    if (/^(Risks|Prove me wrong|Confidence):/.test(l)) break;
    if (/^\s*\d+\.\s+\S/.test(l)) n++;
  }
  return n;
}

function score(c: Case, text: string, calls: ToolCall[]) {
  const e = c.expect;
  const f: string[] = [];
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  const items = countChangeItems(text);
  const raw = text.match(/^Verdict:\s*([^\n—-]+)/m)?.[1]?.trim().toLowerCase() ?? "";
  const verdict = VERDICTS.find((v) => raw.startsWith(v.toLowerCase())) ?? null;
  const lower = text.toLowerCase();

  if (!text.trim()) f.push("empty output");
  for (const s of SECTIONS) if (!new RegExp(`^${s}:`, "m").test(text)) f.push(`missing section: ${s}`);
  if (!verdict) f.push("no parseable verdict");
  else if (e.verdict && !e.verdict.includes(verdict)) f.push(`verdict "${verdict}" not in [${e.verdict.join(" | ")}]`);
  if (e.maxWords != null && words > e.maxWords) f.push(`words ${words} > ${e.maxWords}`);
  if (e.maxChangeItems != null && items > e.maxChangeItems) f.push(`change items ${items} > ${e.maxChangeItems}`);
  if (e.minChangeItems != null && items < e.minChangeItems) f.push(`change items ${items} < ${e.minChangeItems}`);
  if (e.maxToolCalls != null && calls.length > e.maxToolCalls) f.push(`tool calls ${calls.length} > ${e.maxToolCalls}`);
  if (e.minToolCalls != null && calls.length < e.minToolCalls) f.push(`tool calls ${calls.length} < ${e.minToolCalls}`);
  const breached = calls.filter((t) => FORBIDDEN_TOOLS.includes(t.name) && !t.denied).map((t) => t.name);
  if (breached.length) f.push(`GUARD BREACH, forbidden tool ran: ${[...new Set(breached)].join(",")}`);
  const read = calls.filter((t) => t.name === "Read").map((t) => String(t.input?.file_path ?? ""));
  for (const w of e.mustRead ?? []) if (!read.some((p) => p.endsWith(w))) f.push(`did not read: ${w}`);
  for (const w of e.mustMention ?? []) if (!lower.includes(w.toLowerCase())) f.push(`missing mention: "${w}"`);
  for (const w of e.forbiddenPhrases ?? []) if (lower.includes(w.toLowerCase())) f.push(`forbidden phrase: "${w}"`);
  return { verdict, words, items, failures: f };
}

const all = JSON.parse(readFileSync(join(HERE, "cases.json"), "utf8")) as Case[];
const cases = ONLY ? all.filter((c) => ONLY.includes(c.id)) : all;
if (!cases.length) { console.error("no cases matched"); process.exit(1); }
const outDir = join(HERE, `results-${new Date().toISOString().slice(0, 10)}`);
mkdirSync(outDir, { recursive: true });
console.log(`model=${MODEL} cases=${cases.length} out=${outDir}`);

let passed = 0;
for (const c of cases) {
  process.stdout.write(`== ${c.id} ... `);
  const ws = makeWorkspace(c);
  const p = Bun.spawnSync(
    ["claude", "-p", `/deglaze:deglaze ${c.input}`, "--plugin-dir", PLUGIN_DIR, "--model", MODEL, "--output-format", "stream-json", "--verbose"],
    { cwd: ws, env: { ...process.env, OVERCOMMIT_DISABLE: "1" }, stdin: "ignore", stdout: "pipe", stderr: "pipe" },
  );
  rmSync(ws, { recursive: true, force: true });
  const jsonl = p.stdout.toString();
  writeFileSync(join(outDir, `${c.id}.jsonl`), jsonl);
  const { calls, text } = parseTrace(jsonl);
  writeFileSync(join(outDir, `${c.id}.md`), text);
  const r = score(c, text, calls);
  if (p.exitCode !== 0) r.failures.unshift(`claude exited ${p.exitCode}: ${p.stderr.toString().slice(0, 200)}`);
  if (!r.failures.length) passed++;
  console.log(`${r.failures.length ? "FAIL" : "PASS"} verdict="${r.verdict ?? "?"}" words=${r.words} change=${r.items} calls=${calls.length}` +
    (r.failures.length ? `\n     ${r.failures.join("\n     ")}` : ""));
}
console.log(`\n${passed}/${cases.length} passed. Outputs in ${outDir}`);
process.exit(passed === cases.length ? 0 : 1);
