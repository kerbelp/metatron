/*
   Boot-screen state machine — pure, framework-free, unit-tested.

   Decides what the app should show before a repository is selected, given the
   state of the /api/repos fetch. Extracted from the React tree so the logic can
   be tested without a DOM (see boot_state.test.js) and so the splash can never
   spin forever: an empty catalog or a hung API both resolve to a visible message.

   Returns one of:
     "loading" — still fetching, within the timeout; show the splash
     "timeout" — still fetching past timeoutMs; the API is not responding
     "error"   — the fetch failed
     "empty"   — fetch succeeded but the catalog has no repositories
     "ready"   — fetch succeeded and at least one repository exists
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MetatronBoot = api;
})(typeof self !== "undefined" ? self : this, function () {
  function bootScreenState({ loading, error, repos, elapsedMs, timeoutMs } = {}) {
    // A failed fetch always wins — even mid-load or past the timeout.
    if (error) return "error";
    if (loading) {
      if (timeoutMs != null && elapsedMs != null && elapsedMs >= timeoutMs) {
        return "timeout";
      }
      return "loading";
    }
    // Settled with no error. Defensive: if the payload isn't a list yet, wait.
    if (!Array.isArray(repos)) return "loading";
    return repos.length === 0 ? "empty" : "ready";
  }

  return { bootScreenState };
});
