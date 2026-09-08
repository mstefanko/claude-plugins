import { readFileSync, watch } from "node:fs";
import { createHash } from "node:crypto";
import { parse } from "yaml";

export type FlagRule = {
  enabled: boolean;
  tenants: string[];
  percent: number;
};

const FLAGS_PATH = process.env.FLAGS_PATH ?? "config/flags.yaml";

let cache: Record<string, FlagRule> = load();

function load(): Record<string, FlagRule> {
  return parse(readFileSync(FLAGS_PATH, "utf8")) as Record<string, FlagRule>;
}

// The file is watched, so flipping a flag takes effect without a deploy or a restart.
watch(FLAGS_PATH, () => {
  try {
    cache = load();
  } catch {
    // Keep the last good config rather than crashing the process on a bad edit.
  }
});

/** Stable per-tenant bucket in [0, 100). */
function bucket(tenantId: string): number {
  const digest = createHash("sha256").update(tenantId).digest();
  return digest.readUInt32BE(0) % 100;
}

export function flagEnabled(name: string, tenantId: string): boolean {
  const rule = cache[name];
  if (!rule) return false;
  if (rule.enabled) return true;
  if (rule.tenants.includes(tenantId)) return true;
  return bucket(tenantId) < rule.percent;
}
