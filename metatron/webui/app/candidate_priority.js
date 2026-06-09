/*
   Verdict-priority sort for the candidate review queue — pure, unit-tested.

   prioritizeCandidates(items) returns a new array sorted so that AI-approved
   candidates surface first, followed by borderline, then rejected, then
   untriaged (triage === "none" or absent). Stable within each tier: input order
   (newest-first from the server) is preserved among items of equal rank.
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MetatronCandidatePriority = api;
})(typeof self !== "undefined" ? self : this, function () {
  const RANK = { approve: 0, borderline: 1, reject: 2, none: 3 };

  function verdictRank(triage) {
    if (triage === undefined || triage === null) return 3;
    return RANK[triage] !== undefined ? RANK[triage] : 3;
  }

  function prioritizeCandidates(items) {
    return items
      .map(function (item, index) { return { item: item, index: index }; })
      .sort(function (a, b) {
        const ra = verdictRank(a.item.triage);
        const rb = verdictRank(b.item.triage);
        if (ra !== rb) return ra - rb;
        return a.index - b.index;
      })
      .map(function (entry) { return entry.item; });
  }

  return { prioritizeCandidates };
});
