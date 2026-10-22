#!/usr/bin/env node
// Scout CLI used by the Python agent: reads one request as JSON on stdin and writes the
// decision as JSON on stdout. The signing key comes from SCOUT_SIGNING_SECRET.
//
//   echo '{"prompt":"Refund ORD-1042, it arrived broken","user":{"id":"C003","role":"customer"}}' | node scout/cli.js
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Scout } from "./index.js";

const HERE = dirname(fileURLToPath(import.meta.url));

let raw = "";
for await (const chunk of process.stdin) raw += chunk;
const req = JSON.parse(raw || "{}");

const scout = new Scout({
  intentRegistry: req.intentRegistry ?? join(HERE, "registry", "refundwise.json"),
  policyPack: req.policyPack ?? ["default", "refundwise"],
});
const decision = await scout.decide({
  prompt: req.prompt ?? "",
  user: req.user ?? { id: "anonymous", role: "customer" },
  surface: req.surface ?? "chat",
  context: req.context,
});
process.stdout.write(JSON.stringify({ ...decision, selfTestMs: scout.selfTestMs }));
