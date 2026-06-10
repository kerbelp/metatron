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

  // Comma-separated keywords input -> clean list. Mirrors the server's
  // sanitize_keywords (trim, drop empties, case-insensitive dedupe, cap 10) so
  // what the form previews is what gets stored.
  function parseKeywords(text) {
    if (typeof text !== "string") return [];
    const out = [];
    const seen = new Set();
    for (const part of text.split(",")) {
      const kw = part.trim();
      if (!kw || seen.has(kw.toLowerCase())) continue;
      out.push(kw);
      seen.add(kw.toLowerCase());
      if (out.length >= 10) break;
    }
    return out;
  }

  return { validateDecisionForm, parseKeywords };
});
