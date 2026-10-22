// Structured telemetry events (AGENTS.md section 9). Never logs raw injection payloads.
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

export class Telemetry {
  constructor({ path = null } = {}) {
    this.path = path;
    this.events = [];
    if (path) mkdirSync(dirname(path), { recursive: true });
  }
  emit(event, fields) {
    const record = { ts: new Date().toISOString(), event, ...fields };
    this.events.push(record);
    if (this.events.length > 500) this.events.shift();
    if (this.path) appendFileSync(this.path, JSON.stringify(record) + "\n");
    return record;
  }
}
