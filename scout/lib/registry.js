// Intent registry: load, compose, validate, version (AGENTS.md section 3).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { features, stemPhrase, tokens } from "./text.js";

const RISK = new Set(["low", "medium", "high"]);
const ID_GRAMMAR = /^([A-Z]+|[a-z0-9-]+\.[a-z0-9-]+)$/;

function readJson(path) {
  return JSON.parse(readFileSync(path, "utf-8"));
}

/** Load one registry source: a JSON file, a directory of per-intent files, or an object. */
function loadOne(source) {
  if (typeof source === "object" && source !== null) return source;
  const st = statSync(source);
  if (st.isDirectory()) {
    const intents = readdirSync(source)
      .filter((f) => f.endsWith(".json"))
      .sort()
      .map((f) => readJson(join(source, f)));
    return { version: 1, intents };
  }
  return readJson(source);
}

/** Validate one intent record; throws with a clear message on a contract violation. */
export function validateIntent(intent) {
  const where = `intent ${intent?.id ?? "?"}`;
  if (!intent || typeof intent.id !== "string" || !ID_GRAMMAR.test(intent.id))
    throw new Error(`${where}: id must follow category.name grammar (or be GENERAL)`);
  if (!RISK.has(intent.riskClass)) throw new Error(`${where}: riskClass must be low|medium|high`);
  if (!Array.isArray(intent.examples) || intent.examples.length === 0)
    throw new Error(`${where}: examples are mandatory`);
  for (const key of ["capabilities", "surfaces", "roles"])
    if (!Array.isArray(intent[key])) throw new Error(`${where}: ${key} must be an array`);
  if (typeof intent.version !== "number") throw new Error(`${where}: version must be a number`);
  return intent;
}

/**
 * Build the in-memory registry. `source` may be a path, a directory, an object,
 * or an array of those (composition: later sources override earlier ids).
 */
export function loadRegistry(source) {
  const sources = Array.isArray(source) ? source : [source];
  const byId = new Map();
  let registryVersion = 0;
  for (const s of sources) {
    const reg = loadOne(s);
    registryVersion += Number(reg.version ?? 1);
    for (const intent of reg.intents ?? []) byId.set(intent.id, validateIntent(intent));
  }
  if (!byId.has("GENERAL")) {
    byId.set("GENERAL", {
      id: "GENERAL",
      category: "general",
      description: "Safe fallback. Responds conversationally and never routes to tools.",
      parameters: { type: "object", properties: {} },
      capabilities: [],
      riskClass: "low",
      surfaces: ["*"],
      roles: ["*"],
      examples: ["hello"],
      version: 1,
    });
  }
  return compile([...byId.values()], registryVersion);
}

/** Pre-compute everything Stage 1 needs so a scan is pure set lookups. */
function compile(intents, registryVersion) {
  const df = new Map();
  const docs = [];
  for (const intent of intents) {
    for (const text of [...intent.examples, intent.description ?? ""]) {
      const f = features(text);
      docs.push(f);
      for (const t of f) df.set(t, (df.get(t) ?? 0) + 1);
    }
  }
  const N = docs.length;
  const idf = (t) => Math.log(1 + N / (1 + (df.get(t) ?? 0)));

  const compiled = intents.map((intent) => {
    const idTokens =
      intent.id === "GENERAL"
        ? []
        : [...new Set(tokens(intent.id.replace(/[.\-_]/g, " ")))];
    const triggers = (intent.triggers ?? []).map((t) =>
      typeof t === "string" ? { phrase: stemPhrase(t), weight: 0.6 } : { phrase: stemPhrase(t.phrase), weight: t.weight ?? 0.6 },
    );
    const negatives = (intent.negativeTriggers ?? []).map((t) => stemPhrase(t));
    return {
      intent,
      idTokens,
      triggers,
      negatives,
      examples: intent.examples.map((e) => features(e)),
      description: features(intent.description ?? ""),
    };
  });
  return { intents: compiled, byId: new Map(compiled.map((c) => [c.intent.id, c])), idf, registryVersion };
}
