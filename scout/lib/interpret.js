// Interpret stage: bind parameters and entity references, decide on clarification
// (AGENTS.md sections 4.6 and 5).

import { normalise } from "./text.js";

/** Phrase words in order with at most two extra words between them ("don't really like"). */
function wordsIn(words, phrase) {
  for (let i = 0; i < words.length; i++) {
    if (words[i] !== phrase[0]) continue;
    let j = i;
    let k = 1;
    for (; k < phrase.length; k++) {
      const next = words.slice(j + 1, j + 4).indexOf(phrase[k]);
      if (next < 0) break;
      j = j + 1 + next;
    }
    if (k === phrase.length) return true;
  }
  return false;
}

const NUMBER_WORDS = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, twenty: 20 };

// Anaphora that cannot be resolved without conversation context.
const UNRESOLVED = /\b(the thing|that thing|this thing|the stuff|we (talked|spoke|discussed) about|as (we )?discussed|the usual|like last time|same as (before|last time)|you know what|from last time|my (problem|issue) from last time)\b/i;

function parseMoney(text) {
  const m = String(text).match(/\$\s?(\d+(?:[.,]\d+)?)\s*(k|m)?\b/i);
  if (!m) return undefined;
  let v = parseFloat(m[1].replace(",", "."));
  if (/k/i.test(m[2] ?? "")) v *= 1_000;
  if (/m/i.test(m[2] ?? "")) v *= 1_000_000;
  return v;
}

function firstInteger(text) {
  const m = String(text).match(/\b(\d{1,4})\b(?!\s*(?:k|m)\b)/i);
  if (m) return parseInt(m[1], 10);
  const w = String(text).toLowerCase().match(new RegExp(`\\b(${Object.keys(NUMBER_WORDS).join("|")})\\b`));
  return w ? NUMBER_WORDS[w[1]] : undefined;
}

/** Proper-noun entities: capitalised words that are not the first word of a sentence. */
export function entities(prompt) {
  const out = [];
  const words = String(prompt).split(/\s+/);
  for (let i = 1; i < words.length; i++) {
    const w = words[i].replace(/[^A-Za-z0-9-]/g, "");
    const prev = words[i - 1];
    if (/^[A-Z][a-zA-Z0-9]+$/.test(w) && !/[.!?]$/.test(prev) && !/^(I|Q[1-4])$/.test(w)) out.push(w);
  }
  return [...new Set(out)];
}

/** Bind parameters for one intent using its schema plus optional `x-bind` regexes. */
export function bindParameters(intent, prompt) {
  const schema = intent.parameters ?? { properties: {} };
  const props = schema.properties ?? {};
  const params = {};
  const lower = String(prompt).toLowerCase();
  const ents = entities(prompt);

  for (const [name, spec] of Object.entries(props)) {
    const bind = intent["x-bind"]?.[name];
    if (bind?.regex) {
      const m = String(prompt).match(new RegExp(bind.regex, bind.flags ?? "i"));
      if (m) {
        const v = m[bind.group ?? 1] ?? m[0];
        params[name] = bind.upper ? v.toUpperCase() : v;
        continue;
      }
    }
    if (bind?.map) {
      const words = normalise(prompt).split(" ");
      for (const [value, phrases] of Object.entries(bind.map)) {
        if (phrases.some((p) => lower.includes(p.toLowerCase()) || wordsIn(words, normalise(p).split(" ")))) {
          params[name] = value;
          break;
        }
      }
      if (params[name] !== undefined) continue;
    }
    if (spec.enum) {
      const hit = spec.enum.find((e) => new RegExp(`\\b${e}s?\\b`, "i").test(lower));
      if (hit !== undefined) params[name] = hit;
    } else if (spec.type === "integer") {
      const n = firstInteger(prompt);
      if (n !== undefined && (spec.minimum === undefined || n >= spec.minimum) && (spec.maximum === undefined || n <= spec.maximum)) params[name] = n;
    } else if (spec.type === "number") {
      const v = parseMoney(prompt);
      if (v !== undefined) params[name] = v;
    } else if (spec.type === "string") {
      if (/^(account|recipient|subject|customer)$/.test(name) && ents.length) params[name] = ents[0];
      else if (name === "stage") {
        const m = lower.match(/\b(\w+)\s+stage\b/) ?? lower.match(/\bto\s+(closed-won|closed-lost|negotiation|proposal|discovery)\b/);
        if (m) params[name] = m[1];
      }
    }
  }
  for (const [name, spec] of Object.entries(props)) {
    if (params[name] === undefined && spec.default !== undefined) params[name] = spec.default;
  }
  return params;
}

/** Entity references found in the prompt, plus anaphora we could not resolve. */
export function bindReferences(prompt, context) {
  const references = [];
  for (const m of String(prompt).matchAll(/\b(ORD-\d{3,})\b/gi)) references.push({ type: "order", id: m[1].toUpperCase() });
  for (const e of entities(prompt)) if (!/^ORD/i.test(e)) references.push({ type: "entity", id: e });
  const unresolved = !context?.resolved && UNRESOLVED.test(prompt) ? [String(prompt).match(UNRESOLVED)[0]] : [];
  return { references, unresolved };
}

/**
 * Clarification rules (docs/scoring.md):
 *  1 top-1 in the Low band            2 top-1/top-2 within 0.05 in the Medium band
 *  3 required parameters or references cannot be bound
 *  4 high-risk intent below 0.95
 * plus: an entity is named but no action is recognised (rule 3, action unbound).
 */
export function clarificationTrigger({ top1, top2, band, intent, params, refs, isMulti, hasEntity }) {
  if (refs.unresolved.length) return "params";
  if (band === "low") return "low-band";
  if (!isMulti && band === "medium" && top2 && top1.score - top2.score <= 0.05) return "tie";
  const required = intent.parameters?.required ?? [];
  if (band !== "reject" && required.some((r) => params[r] === undefined)) return "params";
  if (band === "reject" && hasEntity) return "params";
  if (intent.riskClass === "high" && top1.score < 0.95) return "high-risk";
  return null;
}

export function buildClarification(trigger, candidates, registry, refs) {
  const options = candidates
    .filter((c) => c.intent !== "GENERAL")
    .slice(0, 4)
    .map((c) => ({ label: registry.byId.get(c.intent).intent.description.split(/[.;—]/)[0].trim(), intent: c.intent }));
  const question =
    trigger === "params" && refs.unresolved.length
      ? `I don't have the earlier conversation. What does "${refs.unresolved[0]}" refer to?`
      : trigger === "params"
        ? "I need a bit more detail. What would you like me to do, and for which order or account?"
        : trigger === "high-risk"
          ? "This action is high risk. Please confirm exactly what you want me to do."
          : "Did you mean one of these?";
  return { trigger, question, options };
}
