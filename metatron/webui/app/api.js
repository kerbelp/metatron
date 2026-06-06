/*
   MetatronAPI — single data-access module.
   One function per endpoint, wired to the live Metatron web API
   (metatron/webui/server.py). The UI talks only to this object.
*/
(function () {
  const J = (url) =>
    fetch(url).then((r) => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  const P = (url, body) =>
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    }).then((r) => {
      if (!r.ok) throw new Error(r.status);
      return r.json();
    });
  const qs = (o) =>
    Object.entries(o)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
      .join("&");

  const API = {
    getRepos() {
      return J("/api/repos");
    },

    getStats(repo) {
      return J("/api/stats?" + qs({ repo }));
    },

    getPriors(repo, { status = "", scope = "", origin = "", search = "", confidence = "", page = 1, page_size = 8 } = {}) {
      // The server filters by status/scope/origin/search; confidence isn't a server
      // filter, so narrow the returned page client-side when it's set.
      return J("/api/priors?" + qs({ repo, status, scope, origin, search, page, page_size })).then((d) => {
        if (confidence) d.items = (d.items || []).filter((p) => p.confidence === confidence);
        return d;
      });
    },

    getUsage(repo) {
      // Normalize the server's usage_summary keys to the names the impact view uses.
      return J("/api/usage?" + qs({ repo })).then((u) => ({
        ...u,
        coverage: u.coverage_rate,
        hit_rate: u.coverage_rate,
        avg_served: u.avg_results,
        served_priors: Math.round((u.avg_results || 0) * (u.total_queries || 0)),
      }));
    },

    getAgentActivity(repo, windowMins = 30) {
      return J("/api/agent-activity?" + qs({ repo, window: windowMins }));
    },

    getLeaderboard(repo) {
      return J("/api/leaderboard?" + qs({ repo }));
    },

    getFeedback(repo) {
      return J("/api/feedback?" + qs({ repo }));
    },

    getFeedbackEvents(repo, status = "all") {
      return J("/api/feedback-events?" + qs({ repo, status }));
    },

    getOrigins(repo) {
      return J("/api/origins?" + qs({ repo }));
    },

    getIngestCost(repo) {
      return J("/api/ingest-cost?" + qs({ repo }));
    },

    approvePrior(id) {
      return P(`/api/priors/${id}/approve`);
    },

    rejectPrior(id) {
      return P(`/api/priors/${id}/reject`);
    },

    approveRecommended(repo) {
      return P("/api/priors/approve-recommended", { repo });
    },

    refineFeedback(eventId) {
      return P(`/api/feedback/${eventId}/refine`);
    },
  };

  window.MetatronAPI = API;
})();
