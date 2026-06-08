/*
   Refinement-to-serve trace selection — pure, framework-free, unit-tested.

   Given the placed constellation nodes, the backend's refinement traces
   (A's feedback -> refined decision -> served to B), and the currently focused
   node index, decide which single trace to highlight and which node indices its
   endpoints map to. Kept out of the React tree so the selection rule can be
   tested without a DOM (see agent_trace.test.js).

   Returns null when the focused node is not the target of any trace (or is a
   grouped overflow node). Otherwise returns { trace, fromIdx, toIdx } where an
   index is -1 if that endpoint is not among the visible nodes (collapsed into
   the overflow group or outside the window) — the renderer degrades gracefully.
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MetatronTrace = api;
})(typeof self !== "undefined" ? self : this, function () {
  function activeTraceForFocus(nodes, traces, focusIdx) {
    if (!Array.isArray(nodes) || !Array.isArray(traces)) return null;
    const focus = nodes[focusIdx];
    if (!focus || focus.kind !== "agent") return null;

    const toId = focus.agent.id;
    const incoming = traces.filter((t) => t.to === toId);
    if (!incoming.length) return null;

    const idxOfAgent = (id) =>
      nodes.findIndex((n) => n.kind === "agent" && n.agent.id === id);

    // Prefer a trace whose source is currently on screen so the full A->B path can
    // be drawn; otherwise fall back to the first and let the source side degrade.
    const chosen = incoming.find((t) => idxOfAgent(t.from) !== -1) || incoming[0];
    return { trace: chosen, fromIdx: idxOfAgent(chosen.from), toIdx: focusIdx };
  }

  return { activeTraceForFocus };
});
