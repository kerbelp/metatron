/*
   Validation logic for the decision editor form — pure, unit-tested.

   Extracted from the UI so it can be tested under node:test without a DOM.
   Exposed as MetatronDecisionEditor globally in the browser, and as a
   CommonJS module for tests.
*/
(function (root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MetatronDecisionEditor = api;
})(typeof self !== "undefined" ? self : this, function () {
  function validateDecisionForm(f) {
    const need = ["pattern", "scope", "rationale"];
    const missing = need.filter((k) => !((f[k] || "").trim()));
    return { ok: missing.length === 0, missing };
  }
  return { validateDecisionForm };
});
