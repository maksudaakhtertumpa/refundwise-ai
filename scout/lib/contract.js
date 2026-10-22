// Signed execution contracts (AGENTS.md section 8.2, docs/execution-contract.md).
import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

const B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
let lastTime = 0;
let lastRand = null;

/** Monotonic ULID: 48-bit time + 80-bit randomness, Crockford base32. */
export function ulid(now = Date.now()) {
  let rand;
  if (now === lastTime && lastRand) {
    rand = Buffer.from(lastRand);
    for (let i = rand.length - 1; i >= 0; i--) {
      if (rand[i] < 255) {
        rand[i]++;
        break;
      }
      rand[i] = 0;
    }
  } else {
    rand = randomBytes(10);
  }
  lastTime = now;
  lastRand = rand;
  let time = "";
  let t = now;
  for (let i = 0; i < 10; i++) {
    time = B32[t % 32] + time;
    t = Math.floor(t / 32);
  }
  let bits = BigInt("0x" + rand.toString("hex"));
  let r = "";
  for (let i = 0; i < 16; i++) {
    r = B32[Number(bits & 31n)] + r;
    bits >>= 5n;
  }
  return time + r;
}

/** Canonical JSON: keys sorted at every level, no whitespace (matches Python json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)). */
export function canonicalJson(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((v) => canonicalJson(v === undefined ? null : v)).join(",")}]`;
  const keys = Object.keys(value).filter((k) => value[k] !== undefined).sort();
  return `{${keys.map((k) => `${JSON.stringify(k)}:${canonicalJson(value[k])}`).join(",")}}`;
}

export function sign(contract, secret) {
  const { signature, ...body } = contract;
  return createHmac("sha256", secret).update(canonicalJson(body)).digest("hex");
}

export function issueContract(fields, { secret, ttlMs = 5 * 60_000, now = Date.now() }) {
  const contract = {
    contractId: ulid(now),
    ...(fields.parentId ? { parentId: fields.parentId } : {}),
    traceId: fields.traceId,
    intent: fields.intent,
    risk: fields.risk,
    toolPlan: fields.toolPlan,
    modelProfile: fields.modelProfile,
    scope: fields.scope,
    issuedAt: new Date(now).toISOString(),
    expiresAt: new Date(now + ttlMs).toISOString(),
    registryVersion: fields.registryVersion,
    policyPackVersion: fields.policyPackVersion,
    signedBy: "scout",
  };
  contract.signature = sign(contract, secret);
  return Object.freeze(contract);
}

/**
 * What an executor runs before acting: signature, expiry, scope and approvals.
 * Returns { ok, reason }.
 */
export function verifyContract(contract, { secret, capability, now = Date.now(), approvalsGranted = [] } = {}) {
  if (!contract || typeof contract.signature !== "string") return { ok: false, reason: "unsigned" };
  const expected = Buffer.from(sign(contract, secret), "hex");
  const got = Buffer.from(contract.signature, "hex");
  if (expected.length !== got.length || !timingSafeEqual(expected, got)) return { ok: false, reason: "bad-signature" };
  if (Date.parse(contract.expiresAt) <= now) return { ok: false, reason: "expired" };
  if (capability && !(contract.scope?.capabilities ?? []).includes(capability)) return { ok: false, reason: "scope-mismatch" };
  const needed = (contract.risk?.approvals ?? []).filter((a) => !approvalsGranted.includes(a));
  if (needed.length) return { ok: false, reason: `approval-required:${needed.join(",")}` };
  return { ok: true };
}
