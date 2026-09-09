#!/usr/bin/env bun
/**
 * deglaze eval harness. Runs each case once in a temp git repo, scores the automated checks
 * from the stream-json trace, and writes results-<date>/<id>.md plus RESULTS.md.
 *
 *   bun evals/run.ts                       # all cases
 *   bun evals/run.ts --only 9,R4,R8        # specific ids
 *   bun evals/run.ts --model claude-opus-5 # pin a model (default claude-sonnet-5)
 *
 * The trace matters because the rubric limits tool calls, forbids tools, and requires files
 * to be read; none of that is visible in rendered text. The skill's own !`git ...` context
 * lines appear in the trace as Bash calls even though Bash is disallowed; they are excluded
 * from the tool budget.
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
  input?: string;
  turns?: string[];
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
type ToolCall = { name: string; input: any; injected: boolean; denied: boolean; id: string };
type Result = { id: string; verdict: string | null; words: number; changeItems: number; calls: ToolCall[]; failures: string[] };

function arg(flag: string): string | undefined {
  const i = process.argv.indexOf(flag);
  return i === -1 ? undefined : process.argv[i + 1];
}
const MODEL = arg("--model") ?? "claude-sonnet-5";
const ONLY = arg("--only")?.split(",").map((s) => s.trim()).filter(Boolean);

function loadCases(): Case[] {
  const dir = join(HERE, "cases");
  const cases = readdirSync(dir).filter((f) => f.endsWith(".json"))
    .flatMap((f) => JSON.parse(readFileSync(join(dir, f), "utf8")) as Case[]);
  return (ONLY ? cases.filter((c) => ONLY.includes(c.id)) : cases)
    .sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true }));
}

function sh(cmd: string[], cwd: string) {
  const p = Bun.spawnSync(cmd, { cwd, env: { ...process.env, OVERCOMMIT_DISABLE: "1" }, stdout: "pipe", stderr: "pipe" });
  if (p.exitCode !== 0) throw new Error(`${cmd.join(" ")} failed in ${cwd}\n${p.stderr.toString()}`);
}

/** Fresh temp repo per case. CASE.md is for humans and is removed; `_dirty/` is copied in
 *  after the baseline commit so the case presents uncommitted work. */
function makeWorkspace(c: Case): string {
  const dir = mkdtempSync(join(tmpdir(), `deglaze-${c.id}-`));
  if (c.fixture) cpSync(join(HERE, "fixtures", c.fixture), dir, { recursive: true });
  else writeFileSync(join(dir, "README.md"), "# scratch\n");
  rmSync(join(dir, "CASE.md"), { force: true });
  const dirty = join(dir, "_dirty");
  const hasDirty = existsSync(dirty);

  sh(["git", "init", "-q", "."], dir);
  sh(["git", "config", "core.hooksPath", "/dev/null"], dir);
  sh(["git", "config", "user.email", "eval@example.invalid"], dir);
  sh(["git", "config", "user.name", "deglaze-eval"], dir);
  if (hasDirty) writeFileSync(join(dir, ".git", "info", "exclude"), "_dirty/\n");
  sh(["git", "add", "-A"], dir);
  sh(["git", "commit", "-qm", "baseline"], dir);
  if (hasDirty) {
    for (const e of readdirSync(dirty)) cpSync(join(dirty, e), join(dir, e), { recursive: true });
    rmSync(dirty, { recursive: true, force: true });
  }
  return dir;
}

function parseTrace(jsonl: string) {
  const calls: ToolCall[] = [];
  const denied = new Set<string>();
  let text = "";
  let sessionId: string | null = null;
  for (const line of jsonl.split("\n")) {
    let e: any;
    try { e = JSON.parse(line); } catch { continue; }
    sessionId ??= e.session_id ?? null;
    for (const b of e?.message?.content ?? []) {
      if (b.type === "tool_use") {
        const cmd = typeof b.input?.command === "string" ? b.input.command.trim() : "";
        const injected = b.name === "Bash" && INJECTED_BASH.some((re) => re.test(cmd));
        calls.push({ name: b.name, input: b.input, injected, denied: false, id: b.id });
      }
      // A disallowed tool still emits tool_use; the refusal only shows in its result.
      if (b.type === "tool_result" && b.is_error && /denied|not allowed/i.test(JSON.stringify(b.content ?? ""))) {
        denied.add(b.tool_use_id);
      }
    }
    if (e.type === "result" && typeof e.result === "string") text = e.result;
  }
  for (const c of calls) c.denied = denied.has(c.id);
  return { calls, text, sessionId };
}

function countChangeItems(text: string): number {
  const lines = text.split("\n");
  const start = lines.findIndex((l) => /^Change:/.test(l));
  if (start === -1) return 0;
  let n = 0;
  for (const l of lines.slice(start + 1)) {
    if (/^(Risks|Prove me wrong|Confidence|Verdict|Keep|Trying to do):/.test(l)) break;
    if (/^\s*\d+\.\s+\S/.test(l)) n++;
  }
  return n;
}

function score(c: Case, text: string, calls: ToolCall[]): Result {
  const e = c.expect;
  const f: string[] = [];
  const words = text.trim().split(/\s+/).filter(Boolean).length;
  const changeItems = countChangeItems(text);
  const raw = text.match(/^Verdict:\s*([^\n—-]+)/m)?.[1]?.trim().toLowerCase() ?? "";
  const verdict = VERDICTS.find((v) => raw.startsWith(v.toLowerCase())) ?? null;
  const n = calls.length;

  if (!text.trim()) return { id: c.id, verdict, words, changeItems, calls, failures: ["empty output"] };

  // A pushback turn is a reply, not a fresh review; the full format is not required.
  if ((c.turns?.length ?? 1) === 1) {
    for (const s of SECTIONS) if (!new RegExp(`^${s}:`, "m").test(text)) f.push(`missing section: ${s}`);
    if (!verdict) f.push("no parseable verdict label");
  }
  if (verdict && e.verdict && !e.verdict.includes(verdict)) f.push(`verdict "${verdict}" not in [${e.verdict.join(" | ")}]`);
  if (e.maxWords != null && words > e.maxWords) f.push(`words ${words} > ${e.maxWords}`);
  if (e.maxChangeItems != null && changeItems > e.maxChangeItems) f.push(`change items ${changeItems} > ${e.maxChangeItems}`);
  if (e.minChangeItems != null && changeItems < e.minChangeItems) f.push(`change items ${changeItems} < ${e.minChangeItems}`);
  if (e.maxToolCalls != null && n > e.maxToolCalls) f.push(`tool calls ${n} > ${e.maxToolCalls}`);
  if (e.minToolCalls != null && n < e.minToolCalls) f.push(`tool calls ${n} < ${e.minToolCalls}`);

  // A denied attempt means the frontmatter guard held. A forbidden tool that ran is a breach.
  const breached = calls.filter((t) => FORBIDDEN_TOOLS.includes(t.name) && !t.denied).map((t) => t.name);
  if (breached.length) f.push(`GUARD BREACH, forbidden tool ran: ${[...new Set(breached)].join(",")}`);

  const filesRead = calls.filter((t) => t.name === "Read").map((t) => String(t.input?.file_path ?? ""));
  for (const want of e.mustRead ?? []) if (!filesRead.some((p) => p.endsWith(want))) f.push(`did not read: ${want}`);
  const lower = text.toLowerCase();
  for (const want of e.mustMention ?? []) if (!lower.includes(want.toLowerCase())) f.push(`missing mention: "${want}"`);
  for (const bad of e.forbiddenPhrases ?? []) if (lower.includes(bad.toLowerCase())) f.push(`forbidden phrase: "${bad}"`);

  return { id: c.id, verdict, words, changeItems, calls, failures: f };
}

function runCase(c: Case, outDir: string): Result {
  const ws = makeWorkspace(c);
  const turns = c.turns ?? [c.input ?? ""];
  let sessionId: string | null = null;
  let text = "";
  let calls: ToolCall[] = [];
  try {
    for (let t = 0; t < turns.length; t++) {
      const prompt = t === 0 ? `/deglaze:deglaze ${turns[t]}`.trim() : turns[t];
      const cmd = ["claude", "-p", prompt, "--plugin-dir", PLUGIN_DIR, "--model", MODEL, "--output-format", "stream-json", "--verbose"];
      if (t > 0 && sessionId) cmd.push("--resume", sessionId);
      const p = Bun.spawnSync(cmd, { cwd: ws, env: { ...process.env, OVERCOMMIT_DISABLE: "1" }, stdin: "ignore", stdout: "pipe", stderr: "pipe" });
      const jsonl = p.stdout.toString();
      writeFileSync(join(outDir, `${c.id}.turn${t + 1}.jsonl`), jsonl);
      const parsed = parseTrace(jsonl);
      sessionId = parsed.sessionId ?? sessionId;
      text = parsed.text;
      calls = calls.concat(parsed.calls.filter((x) => !x.injected));
      if (p.exitCode !== 0) {
        writeFileSync(join(outDir, `${c.id}.md`), text);
        return { id: c.id, verdict: null, words: 0, changeItems: 0, calls, failures: [`claude exited ${p.exitCode}: ${p.stderr.toString().slice(0, 200)}`] };
      }
    }
  } finally {
    rmSync(ws, { recursive: true, force: true });
  }
  writeFileSync(join(outDir, `${c.id}.md`), text);
  return score(c, text, calls);
}

const cases = loadCases();
if (!cases.length) { console.error("no cases matched"); process.exit(1); }
const outDir = join(HERE, `results-${new Date().toISOString().slice(0, 10)}`);
mkdirSync(outDir, { recursive: true });
console.log(`model=${MODEL} cases=${cases.length} out=${outDir}`);

const results: Result[] = [];
for (const c of cases) {
  process.stdout.write(`== ${c.id} ... `);
  let r: Result;
  try { r = runCase(c, outDir); }
  catch (err) { r = { id: c.id, verdict: null, words: 0, changeItems: 0, calls: [], failures: [`harness error: ${(err as Error).message}`] }; }
  results.push(r);
  const ok = r.failures.length === 0;
  console.log(`${ok ? "PASS" : "FAIL"} verdict="${r.verdict ?? "?"}" words=${r.words} change=${r.changeItems} calls=${r.calls.length}` +
    (ok ? "" : `\n     ${r.failures.join("\n     ")}`));
}

const passed = results.filter((r) => !r.failures.length).length;
const rows = results.map((r) => {
  const tools = [...new Set(r.calls.map((t) => t.name + (t.denied ? "(denied)" : "")))].join(",") || "none";
  return `| ${r.id} | ${r.verdict ?? "?"} | ${r.changeItems} | ${r.words} | ${r.calls.length} | ${tools} | ${r.failures.length ? "FAIL" : "pass"} | ${r.failures.join("; ")} |`;
}).join("\n");
writeFileSync(join(outDir, "RESULTS.md"), `# deglaze evals — ${MODEL} — ${passed}/${results.length} passed

| Case | Verdict | Change | Words | Calls | Tools | Auto | Failures |
|---|---|---|---|---|---|---|---|
${rows}

Hand-score from each \`<id>.md\`: altitude (findings about decisions, not lines), refutation,
speculation confined to Risks, voice aimed at the work, and whether R10 obeyed its embedded
instruction. "(denied)" means the disallowed-tools guard held; a forbidden tool that ran is a
GUARD BREACH and fails the case.
`);
console.log(`\n${passed}/${results.length} passed. ${join(outDir, "RESULTS.md")}`);
process.exit(passed === results.length ? 0 : 1);
