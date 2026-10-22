// Guard stage: five independent layers, each pass | warn | block
// (AGENTS.md section 6, docs/risk-and-policy.md).

const LEVELS = ["low", "medium", "high", "block"];
const up = (level, n = 1) => LEVELS[Math.min(LEVELS.indexOf(level) + n, 2)];

// ---------------------------------------------------------------- 1. injection
const PATTERNS = [
  { kind: "pattern", re: /\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|the|your|my|these|those)\b[^.\n]{0,30}\b(instruction|instructions|rules?|prompt|policy|policies|guidelines?|user|system)\b/i, evidence: "instruction-override" },
  { kind: "pattern", re: /\b(ignore|disregard)\s+(previous|prior|above|everything|all)\b/i, evidence: "instruction-override" },
  { kind: "pattern", re: /<\/?\s*(system|assistant|user|developer)\s*>/i, evidence: "embedded-role-tag" },
  { kind: "pattern", re: /\[\/?INST\]|<<\s*SYS\s*>>|<\|im_start\|>|<\|im_end\|>/i, evidence: "embedded-control-token" },
  { kind: "role-drift", re: /\b(you are now|from now on you are|act as|pretend (to be|you are)|roleplay as)\b[^.\n]{0,40}\b(system|admin|administrator|developer|root|unrestricted|jailbroken|dan|database admin|supervisor|manager)\b/i, evidence: "role-drift" },
  { kind: "role-drift", re: /\b(unrestricted|developer|god|jailbreak|dan)\s+mode\b/i, evidence: "mode-switch" },
  { kind: "pattern", re: /\b(reveal|show|print|dump|leak|expose|list)\b[^.\n]{0,30}\b(api keys?|credentials|stored passwords|all passwords|secrets|access tokens?|system prompt|hidden instructions?)\b/i, evidence: "secret-exfiltration" },
  { kind: "pattern", re: /\b(drop|truncate|delete from|alter)\s+(table|database|schema)\b|\bdrop the\s+\w+\s+table\b/i, evidence: "destructive-sql" },
  { kind: "tool-ref", re: /\b(grant|give|make)\s+(me|myself|us)\s+(admin|root|superuser|full access|owner)\b/i, evidence: "privilege-escalation" },
];

// Bidi overrides, zero-width characters, or their escaped spellings smuggled in text.
const CONTROL_CHARS = /[‪-‮⁦-⁩​-‏﻿]|\\u(202[a-e]|206[6-9]|200[b-f]|feff)/i;
const TOOL_TOKEN = /\b[a-z][a-z0-9]*(?:_[a-z0-9]+){1,}\b/g;

/** Out-of-band tool refs: snake_case tool names the current capability set cannot reach. */
function toolRefs(prompt, knownTools) {
  const hits = [];
  for (const m of String(prompt).toLowerCase().matchAll(TOOL_TOKEN)) {
    const name = m[0];
    if (!knownTools.has(name) && /(admin|internal|root|sudo|shell|exec|db|database|panel|debug|secret|key)/.test(name)) hits.push(name);
  }
  return hits;
}

export function injectionCheck(prompt, { knownTools = new Set(), tight = false } = {}) {
  const evidence = [];
  let kind = null;
  for (const p of PATTERNS) {
    if (p.re.test(prompt)) {
      evidence.push(p.evidence);
      kind = kind ?? p.kind;
    }
  }
  if (CONTROL_CHARS.test(prompt)) {
    evidence.push("control-characters");
    kind = kind ?? "pattern";
  }
  const refs = toolRefs(prompt, knownTools);
  if (refs.length) {
    evidence.push("out-of-band-tool");
    kind = kind ?? "tool-ref";
  }
  // Markdown "IMPORTANT" blocks that address the model are a soft signal; tight packs block on them.
  if (tight && /(^|\n)\s*#+\s*(important|note to (the )?(ai|assistant|model)|system)\b/i.test(prompt)) {
    evidence.push("markdown-directive");
    kind = kind ?? "pattern";
  }
  const score = Math.min(1, evidence.length * 0.5);
  const detected = evidence.length > 0 && (score >= (tight ? 0.5 : 0.5));
  return {
    layer: "injection",
    result: detected ? "block" : "pass",
    injection: { detected, kind: detected ? kind : null, score, evidence },
    reason: detected ? `Possible prompt injection (${evidence.join(", ")})` : undefined,
  };
}

// ---------------------------------------------------------------- 2. policy gate
function cmp(value, rule) {
  if (rule == null) return true;
  if (typeof rule !== "object") return value === rule;
  if (rule.gt !== undefined && !(value > rule.gt)) return false;
  if (rule.gte !== undefined && !(value >= rule.gte)) return false;
  if (rule.lt !== undefined && !(value < rule.lt)) return false;
  if (rule.max !== undefined && !(value <= rule.max)) return false;
  if (rule.min !== undefined && !(value >= rule.min)) return false;
  if (rule.in !== undefined && !rule.in.includes(value)) return false;
  return true;
}

export function policyGate(intentId, params, user, surface, pack) {
  const rule = pack.intents?.[intentId];
  if (!rule) return { layer: "policy", result: "pass" };
  const allow = rule.allow ?? {};
  if (allow.roles && !allow.roles.includes("*") && !allow.roles.includes(user.role))
    return { layer: "policy", result: "block", reason: `Role "${user.role}" may not invoke ${intentId}` };
  if (allow.surfaces && !allow.surfaces.includes(surface))
    return { layer: "policy", result: "block", reason: `${intentId} is not allowed on surface "${surface}"` };
  for (const [p, bound] of Object.entries(allow.params ?? {})) {
    if (params[p] !== undefined && !cmp(params[p], bound))
      return { layer: "policy", result: "block", reason: `Parameter ${p}=${params[p]} is outside the allowed bound` };
  }
  for (const combo of rule.deny?.["param-combinations"] ?? []) {
    if (Object.entries(combo).every(([p, r]) => params[p] !== undefined && cmp(params[p], r)))
      return { layer: "policy", result: "block", reason: `Denied parameter combination for ${intentId}` };
  }
  const approvals = [];
  for (const cond of rule["require-approval"] ?? []) {
    if (Object.entries(cond).every(([p, r]) => params[p] !== undefined && cmp(params[p], r))) approvals.push("operator-review");
  }
  return { layer: "policy", result: approvals.length ? "warn" : "pass", approvals };
}

// ---------------------------------------------------------------- 3. scope
export function scopeCheck(intent, user, surface) {
  const roleOk = intent.roles.includes("*") || intent.roles.includes(user.role);
  const surfaceOk = intent.surfaces.includes("*") || intent.surfaces.includes(surface);
  if (!roleOk) return { layer: "scope", result: "block", reason: `Role "${user.role}" is outside ${intent.id}'s scope` };
  if (!surfaceOk) return { layer: "scope", result: "block", reason: `${intent.id} cannot be invoked from "${surface}"` };
  return { layer: "scope", result: "pass" };
}

// ---------------------------------------------------------------- 4. PII / sensitivity
const PII = [
  { kind: "email", re: /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi },
  { kind: "card", re: /\b(?:\d[ -]?){13,16}\b/g },
  { kind: "national-id", re: /\b\d{6}-\d{2}-\d{4}\b/g },
  { kind: "phone", re: /(?:\+?\d{1,3}[ -]?)?(?:\(?\d{2,4}\)?[ -]?)\d{3,4}[ -]?\d{3,4}\b/g },
  { kind: "credential", re: /\b(?:sk|nvapi|ghp|xox[bap])-[A-Za-z0-9_-]{8,}|\bpassword\s*(?:is|:|=)\s*\S+/gi },
];

export function sensitivityCheck(prompt) {
  const redactions = [];
  let redacted = String(prompt);
  for (const { kind, re } of PII) {
    const found = redacted.match(re);
    if (found?.length) {
      // order ids like ORD-1042 are business references, not PII
      const real = found.filter((m) => !/^ord/i.test(m.trim()) && m.replace(/\D/g, "").length >= (kind === "phone" ? 9 : 0));
      if (!real.length) continue;
      redactions.push({ kind, count: real.length });
      for (const m of real) redacted = redacted.split(m).join(`[${kind.toUpperCase()}]`);
    }
  }
  return {
    layer: "sensitivity",
    result: redactions.some((r) => r.kind === "credential") ? "warn" : redactions.length ? "warn" : "pass",
    redactions,
    redacted,
    dataClass: redactions.length ? "pii" : "internal",
  };
}

// ---------------------------------------------------------------- 5. rate limit
export class RateLimiter {
  constructor({ perUserPerIntent = 20, windowMs = 60_000, clock = () => Date.now() } = {}) {
    this.limit = perUserPerIntent;
    this.windowMs = windowMs;
    this.clock = clock;
    this.hits = new Map();
  }
  check(userId, intentId) {
    const key = `${userId}|${intentId}`;
    const now = this.clock();
    const list = (this.hits.get(key) ?? []).filter((t) => now - t < this.windowMs);
    list.push(now);
    this.hits.set(key, list);
    return list.length > this.limit
      ? { layer: "rate-limit", result: "block", reason: `Rate limit: more than ${this.limit} ${intentId} requests per minute` }
      : { layer: "rate-limit", result: "pass" };
  }
}

/** Aggregate layer outputs into one risk object. Any block blocks; each warn lifts one level. */
export function aggregate(baseRisk, layers) {
  const flags = [];
  let level = baseRisk;
  let reason;
  let approvals = [];
  let redactions = [];
  for (const l of layers) {
    if (l.redactions?.length) redactions = l.redactions;
    if (l.approvals?.length) approvals = approvals.concat(l.approvals);
    if (l.result === "block") {
      flags.push(l.layer);
      reason = reason ?? l.reason;
      level = "block";
    } else if (l.result === "warn" && level !== "block") {
      flags.push(l.layer);
      level = up(level);
    }
  }
  if (level === "high" && baseRisk === "high") approvals = [...new Set([...approvals, "operator-review"])];
  return { level, flags, redactions, approvals: [...new Set(approvals)], ...(reason ? { reason } : {}) };
}
