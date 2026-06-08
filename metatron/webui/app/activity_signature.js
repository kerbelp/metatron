/*
   Substantive signature of the agent-activity payload — pure, unit-tested.

   The live impact view polls /api/agent-activity on a timer. The payload carries
   volatile fields (each agent's `mins` / `last_active` drift every second), so a
   naive equality check would report "changed" on every poll and force a needless
   re-render. This reduces the payload to what actually matters for the view — which
   engineers are present, how much each has received/sent, and which refinement
   traces exist — so the poller only updates state when something real changes.
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MetatronActivitySig = api;
})(typeof self !== "undefined" ? self : this, function () {
  function activitySignature(data) {
    if (!data) return "";
    const agents = (data.agents || [])
      .map((a) => [a.id, a.status, a.decisions_received, a.feedback_sent,
                   (a.served || []).length].join(":"))
      .join("|");
    const traces = (data.traces || [])
      .map((t) => t.from + ">" + t.to + ":" + t.decision_id)
      .join("|");
    return [data.total_agents, data.total_served, data.total_feedback, agents, traces].join("#");
  }
  return { activitySignature };
});
