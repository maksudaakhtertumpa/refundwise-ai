// Text normalisation shared by every Scout stage.
// Pure functions, no I/O, so the Stage-1 scan stays well inside its 16 ms budget.

const STOPWORDS = new Set(
  (
    "a an the and or but if of to in on at by for with from into over under about " +
    "is are was were be been being am do does did done have has had having " +
    "i me my mine we us our you your he she it its they them their this that these those " +
    "what which who whom whose when where why how can could would should will shall may might must " +
    "please pls hi hello hey thanks thank just also still yet so very really any some all " +
    "there here then than too not no yes ok okay get got let lets s t"
  ).split(" "),
);

// Lexical synonyms (spec: "trigger phrases, synonyms, n-grams"), mapped to one stem.
const SYNONYMS = {
  mail: "email", "e-mail": "email", emails: "email",
  reimburse: "refund", reimbursement: "refund", refunds: "refund", refunded: "refund",
  versus: "compar", vs: "compar",
  wheres: "whereis", parcel: "package", parcels: "package", delivery: "deliver", delivered: "deliver",
};

/** Lower-case, strip punctuation (keep $ % . inside numbers), collapse spaces. */
export function normalise(text) {
  return String(text ?? "")
    .toLowerCase()
    .replace(/[’']/g, "")
    .replace(/(\d)[.,](\d)/g, "$1$2")
    .replace(/[^a-z0-9$%\s-]/g, " ")
    .replace(/-/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** Very small suffix stemmer: enough to join deal/deals, recover/recovery, arrive/arrived. */
export function stem(word) {
  let w = word;
  if (SYNONYMS[w]) return SYNONYMS[w];
  if (w.length <= 3) return w;
  if (w.endsWith("ies") && w.length > 4) return w.slice(0, -3) + "y";
  if (w.endsWith("ison") && w.length > 6) return w.slice(0, -4);
  if (w.endsWith("ation") && w.length > 7) return w.slice(0, -5) + "at";
  if (w.endsWith("ery") && w.length > 5) return w.slice(0, -3) + "er";
  if (w.endsWith("ing") && w.length > 5) w = w.slice(0, -3);
  else if (w.endsWith("ed") && w.length > 4) w = w.slice(0, -2);
  else if (w.endsWith("es") && w.length > 4 && /(ss|sh|ch|x|z)es$/.test(w)) w = w.slice(0, -2);
  else if (w.endsWith("s") && !w.endsWith("ss") && w.length > 3) w = w.slice(0, -1);
  if (w.endsWith("e") && w.length > 4) w = w.slice(0, -1);
  return w;
}

/** Content tokens: normalised, stop words removed, stemmed. */
export function tokens(text) {
  return normalise(text)
    .split(" ")
    .filter((t) => t && !STOPWORDS.has(t))
    .map(stem);
}

/** Unigram + bigram features for similarity scoring. */
export function features(text) {
  const toks = tokens(text);
  const out = new Set(toks);
  for (let i = 0; i < toks.length - 1; i++) out.add(`${toks[i]} ${toks[i + 1]}`);
  return out;
}

/** Stemmed phrase, used to match registry trigger phrases against stemmed prompts. */
export function stemPhrase(text) {
  return tokens(text).join(" ");
}
