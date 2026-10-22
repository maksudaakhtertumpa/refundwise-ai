// Route stage (capability graph) and model-profile routing (AGENTS.md sections 7 and 8.1).

/**
 * Pick one tool per capability, applying the selection rules in priority order:
 * permissions, availability, surface preference, cost/latency budget, local-first tie-break.
 */
export function assemblePlan(capabilities, graph, { user, surface, params, latencyBudgetMs = 5_000 } = {}) {
  const plan = [];
  const unresolved = [];
  for (const capability of capabilities) {
    let tools = (graph.capabilities?.[capability] ?? []).slice();
    tools = tools.filter((t) => !t.permissions || t.permissions.includes("*") || t.permissions.includes(user.role));
    tools = tools.filter((t) => t.available !== false);
    if (!tools.length) {
      unresolved.push(capability);
      continue;
    }
    tools.sort((a, b) => {
      const sa = (a.surfaces ?? []).includes(surface) ? 0 : 1;
      const sb = (b.surfaces ?? []).includes(surface) ? 0 : 1;
      if (sa !== sb) return sa - sb;
      const la = (a.latencyMs ?? 0) <= latencyBudgetMs ? 0 : 1;
      const lb = (b.latencyMs ?? 0) <= latencyBudgetMs ? 0 : 1;
      if (la !== lb) return la - lb;
      if ((a.cost ?? 0) !== (b.cost ?? 0)) return (a.cost ?? 0) - (b.cost ?? 0);
      return (a.local ? 0 : 1) - (b.local ? 0 : 1);
    });
    plan.push({ capability, tool: tools[0].id, input: { ...params }, local: !!tools[0].local });
  }
  return { plan, unresolved };
}

/** Choose a model profile: required capabilities, data-class clearance, then budget. */
export function chooseModel(profiles, { needs = [], dataClass = "internal", preferReasoning = false } = {}) {
  let ok = profiles.filter((p) => needs.every((n) => (p.capabilities ?? []).includes(n)));
  ok = ok.filter((p) => (p.dataClasses ?? []).includes(dataClass));
  if (!ok.length) return null;
  ok.sort((a, b) => {
    if (preferReasoning) {
      const ra = (a.capabilities ?? []).includes("reasoning") ? 0 : 1;
      const rb = (b.capabilities ?? []).includes("reasoning") ? 0 : 1;
      if (ra !== rb) return ra - rb;
    }
    return (a.costPer1kTokens ?? 0) - (b.costPer1kTokens ?? 0) || (a.latencyP95Ms ?? 0) - (b.latencyP95Ms ?? 0);
  });
  const p = ok[0];
  return { id: p.id, provider: p.provider, model: p.model };
}
