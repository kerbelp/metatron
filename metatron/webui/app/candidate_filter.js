/*
   Client-side filter for the candidate curation queue — pure, non-mutating.

   Exports:
     filterCandidates(items, { verdict, scope, query }) -> filtered array
     scopesOf(items) -> sorted array of distinct non-empty scope values
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MetatronCandidateFilter = api;
})(typeof self !== "undefined" ? self : this, function () {

  function filterCandidates(items, opts) {
    if (opts === undefined) opts = {};
    var verdict = opts.verdict !== undefined ? opts.verdict : "";
    var scope = opts.scope !== undefined ? opts.scope : "";
    var query = opts.query !== undefined ? opts.query : "";
    var q = query.trim().toLowerCase();

    return items.filter(function (item) {
      if (verdict && item.triage !== verdict) return false;
      if (scope && item.scope !== scope) return false;
      if (q) {
        var haystack = [
          item.pattern || "",
          item.scope || "",
          item.rationale || ""
        ].join(" ").toLowerCase();
        if (haystack.indexOf(q) === -1) return false;
      }
      return true;
    });
  }

  function scopesOf(items) {
    var seen = {};
    items.forEach(function (item) {
      if (item.scope) seen[item.scope] = true;
    });
    return Object.keys(seen).sort();
  }

  return { filterCandidates: filterCandidates, scopesOf: scopesOf };
});
