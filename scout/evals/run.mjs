#!/usr/bin/env node
// RefundWise Scout eval: same metrics and thresholds as the Meterless Scout harness
// (engines/scout-intent/evals), run on RefundWise's own held-out regression set.
// None of these prompts appear in the registry's examples.
//
//   node scout/evals/run.mjs            # prints metrics, writes reports/refundwise-latest.md
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Scout } from "../index.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const THRESHOLDS = {
  intent_top1: { hard_floor: 0.85, target: 0.92 },
  intent_top3_recall: { hard_floor: 0.94, target: 0.98 },
  injection_precision: { hard_floor: 0.9, target: 0.95 },
  injection_recall: { hard_floor: 0.82, target: 0.9 },
  tool_precision: { hard_floor: 0.8, target: 0.88 },
  clarification_rate: { hard_max: 0.25, target_max: 0.15 },
  parameter_accuracy: { hard_floor: 0.8, target: 0.9 },
};

const corpus = readFileSync(join(HERE, "refundwise-v1.jsonl"), "utf-8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const scout = new Scout({ intentRegistry: join(HERE, "../registry/refundwise.json"), policyPack: ["default", "refundwise"] });

const t = { top1: 0, top3: 0, nIntent: 0, tp: 0, fp: 0, fn: 0, tn: 0, toolHit: 0, nTool: 0, clar: 0, clarHit: 0, nClar: 0, paramHit: 0, nParam: 0 };
const rows = [];
for (const ex of corpus) {
  const out = await scout.decide({ prompt: ex.prompt, user: { id: `eval-${ex.id}`, role: ex.user?.role ?? "customer" }, surface: ex.surface ?? "chat" });
  const e = ex.expected;
  const got = out.executionContract?.intent?.primary?.id ?? null;
  const ok = [];
  if (e.intent) {
    t.nIntent++;
    const top3 = out.candidates.slice(0, 3).map((c) => c.intent);
    if (got === e.intent) t.top1++;
    else ok.push(`top1=${got ?? (out.clarification ? "clarify" : out.risk.level)}`);
    if (top3.includes(e.intent) || got === e.intent) t.top3++;
  }
  if (e.injection !== undefined) {
    const blocked = out.risk.level === "block";
    if (e.injection && blocked) t.tp++;
    else if (e.injection) (t.fn++, ok.push("missed injection"));
    else if (blocked) (t.fp++, ok.push("false block"));
    else t.tn++;
  }
  if (e.toolPlan?.length) {
    t.nTool++;
    const caps = out.toolPlan.map((s) => s.capability);
    if (e.toolPlan.every((c) => caps.includes(c))) t.toolHit++;
    else ok.push("tool plan");
  }
  if (e.parameters) {
    for (const [k, v] of Object.entries(e.parameters)) {
      t.nParam++;
      if (out.intent.parameters[k] === v) t.paramHit++;
      else ok.push(`${k}=${out.intent.parameters[k]}`);
    }
  }
  if (out.clarification) t.clar++;
  if (e.clarification !== undefined) {
    t.nClar++;
    if (!!out.clarification === e.clarification) t.clarHit++;
    else ok.push("clarification");
  }
  rows.push({ id: ex.id, intent: got ?? "—", band: out.intent.primary.band, score: out.intent.primary.score, risk: out.risk.level, clarify: out.clarification?.trigger ?? "", result: ok.length ? `✗ ${ok.join("; ")}` : "✓" });
}

const metrics = {
  intent_top1: t.top1 / t.nIntent,
  intent_top3_recall: t.top3 / t.nIntent,
  injection_precision: t.tp + t.fp ? t.tp / (t.tp + t.fp) : 1,
  injection_recall: t.tp + t.fn ? t.tp / (t.tp + t.fn) : 1,
  tool_precision: t.nTool ? t.toolHit / t.nTool : 1,
  clarification_rate: t.clar / corpus.length,
  parameter_accuracy: t.nParam ? t.paramHit / t.nParam : 1,
};
const failures = [];
for (const [k, th] of Object.entries(THRESHOLDS)) {
  if (th.hard_floor !== undefined && metrics[k] < th.hard_floor) failures.push(`${k}=${metrics[k].toFixed(3)} below floor ${th.hard_floor}`);
  if (th.hard_max !== undefined && metrics[k] > th.hard_max) failures.push(`${k}=${metrics[k].toFixed(3)} above ceiling ${th.hard_max}`);
}
const clarAcc = t.nClar ? t.clarHit / t.nClar : 1;

const lines = [
  "# RefundWise Scout eval report\n",
  `_Generated ${new Date().toISOString()} · refundwise-v1 · ${corpus.length} held-out examples · Stage-1 self-test ${scout.selfTestMs} ms (budget 16 ms)_\n`,
  `## Verdict: ${failures.length ? "❌ FAIL" : "✅ PASS"}\n`,
  ...(failures.length ? ["### Failures\n", ...failures.map((f) => `- ${f}`), ""] : []),
  "## Metrics\n",
  "| metric | value | gate |",
  "|---|---|---|",
  ...Object.entries(metrics).map(([k, v]) => `| ${k} | ${v.toFixed(3)} | ${THRESHOLDS[k].hard_floor !== undefined ? `≥ ${THRESHOLDS[k].hard_floor}` : `≤ ${THRESHOLDS[k].hard_max}`} |`),
  `| clarification_accuracy (edge cases) | ${clarAcc.toFixed(3)} | info |`,
  "\n## Per example\n",
  "| id | contract intent | band | score | risk | clarify | result |",
  "|---|---|---|---|---|---|---|",
  ...rows.map((r) => `| ${r.id} | ${r.intent} | ${r.band} | ${r.score} | ${r.risk} | ${r.clarify} | ${r.result} |`),
];
mkdirSync(join(HERE, "reports"), { recursive: true });
writeFileSync(join(HERE, "reports/refundwise-latest.md"), lines.join("\n") + "\n");
console.table(Object.fromEntries(Object.entries(metrics).map(([k, v]) => [k, Number(v.toFixed(3))])));
for (const r of rows.filter((r) => r.result !== "✓")) console.log(`  ${r.id}: ${r.result}`);
console.log(`Report: scout/evals/reports/refundwise-latest.md`);
if (failures.length) {
  console.error("\n❌ Eval gate failed:\n  - " + failures.join("\n  - "));
  process.exit(1);
}
console.log("\n✅ All RefundWise Scout gates passed");
