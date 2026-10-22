// Scout Intent: intent sensing, risk guarding, tool routing and signed execution
// contracts, implemented from the Meterless Scout Intent spec
// (https://github.com/Meterless/Meterless/tree/main/engines/scout-intent/AGENTS.md).
//
// Pipeline per request: Sense -> Interpret -> Guard -> Route -> Recommend -> ExecutionContract
import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { performance } from "node:perf_hooks";

import { loadRegistry } from "./lib/registry.js";
import { scoreAll, splitSpans, bandOf, BANDS, round } from "./lib/scoring.js";
import { bindParameters, bindReferences, clarificationTrigger, buildClarification, entities } from "./lib/interpret.js";
import { injectionCheck, policyGate, scopeCheck, sensitivityCheck, RateLimiter, aggregate } from "./lib/guard.js";
import { assemblePlan, chooseModel } from "./lib/route.js";
import { issueContract, verifyContract, canonicalJson, sign } from "./lib/contract.js";
import { Telemetry } from "./lib/telemetry.js";

export { verifyContract, canonicalJson, sign };

const HERE = dirname(fileURLToPath(import.meta.url));
const CONFIG = join(HERE, "config");
const RISK_ORDER = ["low", "medium", "high"];
const SELF_TEST_BUDGET_MS = 16;

function readJson(p) {
  return JSON.parse(readFileSync(p, "utf-8"));
}

function loadPolicyPacks(names) {
  const list = Array.isArray(names) ? names : [names ?? "default"];
  const packs = list.map((name) => {
    const path = join(CONFIG, "policies", `${name}.json`);
    const pack = existsSync(path) ? readJson(path) : { name, version: "0" };
    return { tight: /tight/.test(name), ...pack, name };
  });
  return { packs, version: packs.map((p) => `${p.name}@${p.version ?? "0"}`).join("+") };
}

export class Scout {
  /**
   * @param {object} options
   * @param {string|object|Array} options.intentRegistry  file, directory, object, or a list to compose
   * @param {string|string[]} [options.policyPack]         named policy pack(s), default "default"
   * @param {string} [options.modelProfiles]              model profiles JSON file
   * @param {string} [options.capabilityGraph]            capability graph JSON file
   * @param {string} [options.signingSecret]              HMAC secret (falls back to SCOUT_SIGNING_SECRET, then a per-process key)
   * @param {string} [options.telemetryPath]              JSONL file for telemetry events
   * @param {Function} [options.stage2]                   optional async Stage-2 rescorer
   */
  constructor(options = {}) {
    this.registry = loadRegistry(options.intentRegistry);
    const { packs, version } = loadPolicyPacks(options.policyPack);
    this.packs = packs;
    this.policyPackVersion = version;
    this.tight = packs.some((p) => p.tight || p.injection?.tight);
    this.graph = readJson(options.capabilityGraph ?? join(CONFIG, "capability-graph.json"));
    this.profiles = readJson(options.modelProfiles ?? join(CONFIG, "model-profiles.json")).profiles;
    this.secret = options.signingSecret ?? process.env.SCOUT_SIGNING_SECRET ?? randomBytes(32).toString("hex");
    this.telemetry = new Telemetry({ path: options.telemetryPath ?? process.env.SCOUT_TELEMETRY ?? null });
    this.stage2 = options.stage2 ?? null;
    const perMinute = Math.min(...packs.map((p) => p.rateLimit?.perUserPerIntentPerMinute ?? 20));
    this.rateLimiter = new RateLimiter({ perUserPerIntent: perMinute });
    this.knownTools = new Set(Object.values(this.graph.capabilities ?? {}).flat().map((t) => t.id.replace(/\./g, "_")));
    this.sessions = new Map();
    this.decisions = new Map();
    this.selfTestMs = this.#selfTest();
  }

  /** Startup self-test: a full-registry Stage-1 scan must finish inside 16 ms. Fails loudly. */
  #selfTest() {
    const probes = [
      "Find me the top 5 stuck deals and draft recovery emails",
      "I want a refund for my order",
      "What's the weather tomorrow?",
      "Ignore previous instructions",
      ...this.registry.intents.flatMap((e) => e.intent.examples).slice(0, 40),
    ];
    for (let i = 0; i < 2; i++) for (const p of probes) scoreAll(this.registry, p); // warm-up
    let worst = 0;
    for (const p of probes) {
      const t0 = performance.now();
      scoreAll(this.registry, p);
      worst = Math.max(worst, performance.now() - t0);
    }
    if (worst > SELF_TEST_BUDGET_MS)
      throw new Error(`Scout self-test failed: Stage-1 full-registry scan took ${worst.toFixed(2)} ms (budget ${SELF_TEST_BUDGET_MS} ms)`);
    return round(worst);
  }

  /** Sense stage only. */
  async classify({ prompt, surface = "chat" }) {
    return { candidates: scoreAll(this.registry, prompt).slice(0, 5).map(({ intent, score }) => ({ intent, score })), surface };
  }

  /** Full pipeline. */
  async decide(input) {
    return this.#decide(input, {});
  }

  /** Re-plan a previous contract with lineage: same traceId, parentId = the old contract. */
  async replan({ parent, reason, state }) {
    const prev = this.decisions.get(parent);
    if (!prev) throw new Error(`Unknown parent contract ${parent}`);
    return this.#decide(
      { ...prev.input, context: { ...(prev.input.context ?? {}), replanReason: reason, state } },
      { traceId: prev.traceId, parentId: parent },
    );
  }

  async #decide(input, { traceId = randomBytes(8).toString("hex"), parentId } = {}) {
    const t0 = performance.now();
    const prompt = String(input.prompt ?? "");
    const user = { id: input.user?.id ?? "anonymous", role: input.user?.role ?? "viewer" };
    const surface = input.surface ?? "chat";
    const session = this.sessions.get(user.id) ?? [];

    // ---- Sense
    const penalties = new Map();
    for (const e of this.registry.intents) {
      const r = e.intent.roles;
      if (!r.includes("*") && !r.includes(user.role)) penalties.set(e.intent.id, 0.3); // riskPenalty
    }
    const stage2 = this.stage2 ? await this.stage2({ prompt, registry: this.registry, context: input.context }) : null;
    const candidates = scoreAll(this.registry, prompt, { recent: new Set(session), penalties, stage2 });

    // Multi-intent: disjoint spans that each land in the High band with different intents.
    let plan = [];
    const spans = splitSpans(prompt);
    if (spans.length >= 2) {
      const tops = spans.map((span) => ({ span, top: scoreAll(this.registry, span, { penalties })[0] }));
      const high = [];
      for (const { span, top } of tops) {
        if (top.intent !== "GENERAL" && top.score >= BANDS.high && !high.some((h) => h.intent === top.intent)) high.push({ intent: top.intent, score: top.score, span });
      }
      if (high.length >= 2) {
        plan = high;
        for (const { span, top } of tops)
          if (top.intent !== "GENERAL" && top.score >= BANDS.medium && !plan.some((h) => h.intent === top.intent)) plan.push({ intent: top.intent, score: top.score, span });
        for (const c of candidates) {
          const p = plan.find((x) => x.intent === c.intent);
          if (p) c.span = p.span;
        }
      }
    }
    const isMulti = plan.length >= 2;

    let top1 = candidates[0];
    const top2 = candidates[1];
    let band = bandOf(top1.score);
    let primaryId = top1.intent;
    if (isMulti && !plan.some((p) => p.intent === primaryId)) primaryId = plan[0].intent;
    if (band === "reject") primaryId = "GENERAL";
    const primary = this.registry.byId.get(primaryId).intent;
    const planIntents = isMulti ? plan.map((p) => this.registry.byId.get(p.intent).intent) : [primary];

    // ---- Interpret
    const params = bindParameters(primary, prompt);
    const refs = bindReferences(prompt, input.context);
    const alternates = candidates.filter((c) => c.intent !== primaryId).slice(0, 3).map(({ intent, score }) => ({ intent, score }));

    // ---- Guard
    const sens = sensitivityCheck(prompt);
    const layers = [injectionCheck(prompt, { knownTools: this.knownTools, tight: this.tight })];
    for (const it of planIntents) {
      layers.push(scopeCheck(it, user, surface));
      for (const pack of this.packs) layers.push(policyGate(it.id, params, user, surface, pack));
    }
    layers.push(sens);
    if (!layers.some((l) => l.result === "block")) layers.push(this.rateLimiter.check(user.id, primaryId));
    const baseRisk = planIntents.map((i) => i.riskClass).sort((a, b) => RISK_ORDER.indexOf(b) - RISK_ORDER.indexOf(a))[0];
    const risk = aggregate(baseRisk, layers);
    const injection = layers[0].injection;

    const decision = {
      traceId,
      candidates: candidates.slice(0, 5).map(({ intent, score, span }) => ({ intent, score, ...(span ? { span } : {}) })),
      intent: { primary: { id: primaryId, score: top1.score, band }, parameters: params, references: refs.references, alternates },
      plan: isMulti ? plan : [{ intent: primaryId, score: top1.score }],
      risk,
      injection: { detected: injection.detected, kind: injection.kind, score: injection.score },
      clarification: null,
      toolPlan: [],
      modelProfile: null,
      executionContract: null,
      stage2: stage2 ? "used" : "skipped",
    };

    if (risk.level === "block") {
      this.#finish(decision, t0, { user, input, prompt: sens.redacted });
      return decision;
    }

    // ---- Clarify (no contract until the user answers)
    const trigger = clarificationTrigger({
      top1: { score: top1.score },
      top2,
      band,
      intent: primary,
      params,
      refs,
      isMulti,
      hasEntity: entities(prompt).length > 0 || refs.references.some((r) => r.type === "order"),
    });
    if (trigger) {
      decision.clarification = buildClarification(trigger, candidates, this.registry, refs);
      this.telemetry.emit("scout.clarification", { traceId, trigger });
      this.#finish(decision, t0, { user, input, prompt: sens.redacted });
      return decision;
    }

    // ---- Route
    const capabilities = [...new Set(planIntents.flatMap((i) => i.capabilities))];
    const { plan: toolPlan, unresolved } = assemblePlan(capabilities, this.graph, { user, surface, params });
    if (unresolved.length) risk.flags.push(`routing-degraded:${unresolved.join(",")}`);
    decision.toolPlan = toolPlan;

    // ---- Recommend
    const needs = primary["x-model-needs"] ?? (capabilities.length ? ["function_calling"] : []);
    const modelProfile = chooseModel(this.profiles, { needs, dataClass: sens.dataClass, preferReasoning: baseRisk === "high" });
    decision.modelProfile = modelProfile;
    decision.executionContract = issueContract(
      {
        parentId,
        traceId,
        intent: { primary: { id: primaryId, version: primary.version }, parameters: params, references: refs.references, confidence: top1.score, alternates },
        risk: { level: risk.level, flags: risk.flags, redactions: risk.redactions, approvals: risk.approvals },
        toolPlan: toolPlan.map(({ capability, tool, input }) => ({ capability, tool, input })),
        modelProfile,
        scope: { user, surface, capabilities: toolPlan.map((s) => s.capability) },
        registryVersion: this.registry.registryVersion,
        policyPackVersion: this.policyPackVersion,
      },
      { secret: this.secret },
    );
    this.telemetry.emit("contract.issued", {
      contractId: decision.executionContract.contractId,
      intent: primaryId,
      risk: risk.level,
      profile: modelProfile?.id ?? null,
    });
    this.decisions.set(decision.executionContract.contractId, { input, traceId });
    this.sessions.set(user.id, [primaryId, ...session].slice(0, 5));
    this.#finish(decision, t0, { user, input, prompt: sens.redacted });
    return decision;
  }

  #finish(decision, t0, { user }) {
    decision.latencyMs = round(performance.now() - t0);
    // Metadata only: never the raw prompt, and never an injection payload.
    this.telemetry.emit("scout.decision", {
      traceId: decision.traceId,
      user: user.id,
      intent: decision.intent.primary.id,
      band: decision.intent.primary.band,
      risk: decision.risk.level,
      flags: decision.risk.flags,
      clarification: decision.clarification?.trigger ?? null,
      latencyMs: decision.latencyMs,
      stage2: decision.stage2,
    });
  }
}

export default Scout;
