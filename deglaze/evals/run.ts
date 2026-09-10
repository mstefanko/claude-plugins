#!/usr/bin/env bun
/**
 * deglaze smoke check: two cases, about two minutes. Run after editing SKILL.md.
 *
 *   bun evals/run.ts                    # both cases, claude-sonnet-5
 *   bun evals/run.ts --only altitude    # one case
 *   bun evals/run.ts --model claude-opus-5
 *
 * Each case runs headless in a temp git repo and is scored from the stream-json trace, the
 * only place tool calls, refused tools, and the --md Write are visible. The skill's own
 * !`.../scripts/context.sh` line is ignored if it shows up as a Bash call. Read-only Bash calls
 * are tolerated and counted as shell=N; a mutating one is a guard breach. Output lands in
 * results-<date>/ (gitignored); read <id>.md by hand for the verdict, altitude, and voice.
 * Verdict labels move run to run on the same prompt, so they are parsed but never asserted.
 */

import { mkdtempSync, rmSync, cpSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname, resolve } from "node:path";

const HERE = dirname(new URL(import.meta.url).pathname);
const PLUGIN_DIR = resolve(HERE, "..");
const INJECTED_BASH = [/\/skills\/deglaze\/scripts\/context\.sh$/];
const SECTIONS = ["Verdict", "Trying to do", "Keep", "Change", "Prove me wrong", "Confidence"];
const VERDICTS = ["Nope", "Needs surgery", "Worth a cheap test", "Annoyingly solid"];
const FORBIDDEN_TOOLS = ["Bash", "Agent", "Task", "Edit", "NotebookEdit", "EnterPlanMode",
  "EnterWorktree", "Workflow", "Skill", "AskUserQuestion", "WebSearch"];
// Bash is not in disallowed-tools (the ban broke back-to-back invocations), so the model
// occasionally runs harmless read-only commands. Those are tolerated; a mutating one is a breach.
const READ_ONLY_BASH = /^(true|false|echo|printf|pwd|ls|cat|head|tail|wc|stat|file|test|\[|find|grep|rg|sort|uniq|cut|tr|awk|sed -n|which|date|git (-C \S+ )?(status|log|diff|show|grep|rev-parse|branch|ls-files|blame|describe))(\s|$)/;
function isReadOnlyBash(cmd: string): boolean {
  const stripped = cmd.replace(/2>\/dev\/null|2>&1/g, "");
  if (/>/.test(stripped)) return false; // any remaining redirection writes somewhere
  return stripped.split(/\|\||&&|;|\|/).every((seg) => READ_ONLY_BASH.test(seg.trim()));
}

type Case = {
  id: string;
  input: string;
  fixture?: string;
  expect: {
    verdict?: string[]; maxWords?: number; maxChangeItems?: number; minChangeItems?: number;
    maxToolCalls?: number; minToolCalls?: number; mustRead?: string[]; mustMention?: string[];
    forbiddenPhrases?: string[]; mustWrite?: boolean; notes?: string;
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

/** Temp repo per case with one baseline commit. CASE.md is for humans and is removed. */
function makeWorkspace(c: Case): string {
  const dir = mkdtempSync(join(tmpdir(), `deglaze-${c.id}-`));
  if (c.fixture) cpSync(join(HERE, "fixtures", c.fixture), dir, { recursive: true });
  else writeFileSync(join(dir, "README.md"), "# scratch\n");
  rmSync(join(dir, "CASE.md"), { force: true });
  sh(["git", "init", "-q", "."], dir);
  sh(["git", "config", "core.hooksPath", "/dev/null"], dir);
  sh(["git", "config", "user.email", "eval@example.invalid"], dir);
  sh(["git", "config", "user.name", "deglaze-eval"], dir);
  sh(["git", "add", "-A"], dir);
  sh(["git", "commit", "-qm", "baseline"], dir);
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
      // Join all assistant text: with --md the review precedes the Write and "Saved:" follows it.
      if (e.type === "assistant" && b.type === "text") text += (text ? "\n" : "") + b.text;
    }
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
  const budgeted = calls.filter((t) => t.name !== "Write").length;

  if (!text.trim()) f.push("empty output");
  for (const s of SECTIONS) if (!new RegExp(`^${s}:`, "m").test(text)) f.push(`missing section: ${s}`);
  if (!verdict) f.push("no parseable verdict");
  else if (e.verdict && !e.verdict.includes(verdict)) f.push(`verdict "${verdict}" not in [${e.verdict.join(" | ")}]`);
  if (e.maxWords != null && words > e.maxWords) f.push(`words ${words} > ${e.maxWords}`);
  if (e.maxChangeItems != null && items > e.maxChangeItems) f.push(`change items ${items} > ${e.maxChangeItems}`);
  if (e.minChangeItems != null && items < e.minChangeItems) f.push(`change items ${items} < ${e.minChangeItems}`);
  if (e.maxToolCalls != null && budgeted > e.maxToolCalls) f.push(`tool calls ${budgeted} > ${e.maxToolCalls}`);
  if (e.minToolCalls != null && budgeted < e.minToolCalls) f.push(`tool calls ${budgeted} < ${e.minToolCalls}`);
  const bashCmd = (t: ToolCall) => (typeof t.input?.command === "string" ? t.input.command.trim() : "");
  const shell = calls.filter((t) => t.name === "Bash" && !t.denied);
  const breached = calls
    .filter((t) => FORBIDDEN_TOOLS.includes(t.name) && !t.denied && !(t.name === "Bash" && isReadOnlyBash(bashCmd(t))))
    .map((t) => (t.name === "Bash" ? `Bash(${bashCmd(t).slice(0, 60)})` : t.name));
  if (breached.length) f.push(`GUARD BREACH, forbidden tool ran: ${[...new Set(breached)].join(",")}`);
  const read = calls.filter((t) => t.name === "Read").map((t) => String(t.input?.file_path ?? ""));
  for (const w of e.mustRead ?? []) if (!read.some((p) => p.endsWith(w))) f.push(`did not read: ${w}`);
  for (const w of e.mustMention ?? []) if (!lower.includes(w.toLowerCase())) f.push(`missing mention: "${w}"`);
  for (const w of e.forbiddenPhrases ?? []) if (lower.includes(w.toLowerCase())) f.push(`forbidden phrase: "${w}"`);

  // Write is allowed only for the --md report: one file, under .deglaze/, with the header lines.
  const writes = calls.filter((t) => t.name === "Write" && !t.denied);
  if (!e.mustWrite && writes.length) f.push(`wrote a file without --md: ${writes.map((t) => t.input?.file_path).join(",")}`);
  if (e.mustWrite) {
    if (writes.length !== 1) f.push(`expected exactly one Write, got ${writes.length}`);
    for (const w of writes) {
      if (!/\/\.deglaze\/\d{4}-\d{2}-\d{2}-[a-z0-9-]+\.md$/.test(String(w.input?.file_path))) f.push(`report path off-pattern: ${w.input?.file_path}`);
      const body = String(w.input?.content ?? "");
      for (const h of ["# deglaze", "Target:", "Commit:", "Verdict:"]) if (!body.includes(h)) f.push(`report missing "${h}"`);
    }
    if (!/^Saved: /m.test(text)) f.push("missing Saved: line");
  }
  return { verdict, words, items, calls: budgeted, shell: shell.length, failures: f };
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
  console.log(`${r.failures.length ? "FAIL" : "PASS"} verdict="${r.verdict ?? "?"}" words=${r.words} change=${r.items} calls=${r.calls} shell=${r.shell}` +
    (r.failures.length ? `\n     ${r.failures.join("\n     ")}` : ""));
}
console.log(`\n${passed}/${cases.length} passed. Outputs in ${outDir}`);
process.exit(passed === cases.length ? 0 : 1);
