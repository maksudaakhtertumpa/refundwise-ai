// Sense stage: Stage-1 deterministic trigger scan + optional Stage-2 merge
// (AGENTS.md section 4, docs/scoring.md).
import { features, normalise, stemPhrase } from "./text.js";

export const WEIGHTS = { lexical: 0.4, semantic: 0.35, contextual: 0.2, recency: 0.05 };
export const BANDS = { high: 0.8, medium: 0.55, low: 0.4 };

export function bandOf(score, bands = BANDS) {
  if (score >= bands.high) return "high";
  if (score >= bands.medium) return "medium";
  if (score >= bands.low) return "low";
  return "reject";
}

/** idf-weighted Dice similarity between two feature sets. */
function dice(a, b, idf) {
  let inter = 0;
  let wa = 0;
  let wb = 0;
  for (const f of a) wa += idf(f);
  for (const f of b) {
    const w = idf(f);
    wb += w;
    if (a.has(f)) inter += w;
  }
  return wa + wb === 0 ? 0 : (2 * inter) / (wa + wb);
}

/** Trigger phrase tokens appear in order, allowing up to `maxGap` extra words between them. */
function phraseIn(toks, phrase, maxGap = 2) {
  for (let i = 0; i < toks.length; i++) {
    if (toks[i] !== phrase[0]) continue;
    let j = i;
    let ok = true;
    for (let k = 1; k < phrase.length; k++) {
      let found = -1;
      for (let g = j + 1; g <= Math.min(toks.length - 1, j + 1 + maxGap); g++) {
        if (toks[g] === phrase[k]) {
          found = g;
          break;
        }
      }
      if (found < 0) {
        ok = false;
        break;
      }
      j = found;
    }
    if (ok) return true;
  }
  return false;
}

/**
 * lexical(intent) in [0, 1]: noisy-OR of four independent lexical signals:
 *   example n-gram overlap, intent-id tokens, registry trigger phrases, description words.
 * Returns the score plus the evidence that produced it (for replay / telemetry).
 */
export function lexical(entry, promptFeatures, stemmedPrompt, idf) {
  let sEx = 0;
  for (const ex of entry.examples) sEx = Math.max(sEx, dice(promptFeatures, ex, idf));

  let sId = 0;
  if (entry.idTokens.length) {
    const hit = entry.idTokens.filter((t) => promptFeatures.has(t)).length;
    sId = 0.85 * (hit / entry.idTokens.length);
  }

  let sTrig = 0;
  const matched = [];
  const padded = ` ${stemmedPrompt} `;
  const toks = stemmedPrompt.split(" ");
  for (const t of entry.triggers) {
    if (t.phrase && phraseIn(toks, t.phrase.split(" "))) {
      sTrig += t.weight;
      matched.push(t.phrase);
    }
  }
  sTrig = Math.min(1, sTrig);

  const sDesc = 0.5 * dice(promptFeatures, entry.description, idf);

  let score = 1 - (1 - sEx) * (1 - sId) * (1 - sTrig) * (1 - sDesc);
  // Negative triggers: phrases that mean "not this intent" (e.g. "track" for not-received).
  for (const n of entry.negatives) if (n && padded.includes(` ${n} `)) score *= 0.6;
  return { score, signals: { example: sEx, id: sId, trigger: sTrig, description: sDesc }, matched };
}

/**
 * Score every intent in the registry for one text span.
 * stage2 (optional) returns { [intentId]: { semantic, contextual } }; when it is
 * absent Stage 1 stands on its own: final = lexical + 0.05 * recency - riskPenalty
 * (implementer's choice: lexical carries the unobserved semantic/contextual share,
 * so an exact trigger match can still reach the High band without a model).
 */
export function scoreAll(registry, text, { recent = new Set(), penalties = new Map(), stage2 = null } = {}) {
  const pf = features(text);
  const sp = stemPhrase(text);
  const out = [];
  for (const entry of registry.intents) {
    const lex = lexical(entry, pf, sp, registry.idf);
    const rec = recent.has(entry.intent.id) ? 1 : 0;
    const pen = penalties.get(entry.intent.id) ?? 0;
    let final;
    let stage2Used = false;
    const s2 = stage2?.[entry.intent.id];
    if (s2) {
      stage2Used = true;
      final =
        WEIGHTS.lexical * lex.score +
        WEIGHTS.semantic * (s2.semantic ?? 0) +
        WEIGHTS.contextual * (s2.contextual ?? 0) +
        WEIGHTS.recency * rec -
        pen;
    } else {
      final = lex.score + WEIGHTS.recency * rec - pen;
    }
    final = Math.max(0, Math.min(1, final));
    out.push({ intent: entry.intent.id, score: round(final), lexical: round(lex.score), signals: lex.signals, matched: lex.matched, stage2: stage2Used });
  }
  out.sort((a, b) => b.score - a.score || a.intent.localeCompare(b.intent));
  return out;
}

/** Split a prompt into candidate spans for multi-intent detection. */
export function splitSpans(prompt) {
  const parts = String(prompt)
    .split(/\s*(?:;|,\s*and\s+|,\s*then\s+|\band then\b|\band also\b|,|\band\b|\bthen\b)\s*/i)
    .map((s) => s.trim())
    .filter((s) => normalise(s).split(" ").filter(Boolean).length >= 2);
  return parts;
}

export function round(x) {
  return Math.round(x * 10000) / 10000;
}
