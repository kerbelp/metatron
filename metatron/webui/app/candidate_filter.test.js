"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { filterCandidates, scopesOf } = require("./candidate_filter.js");
const items = [
  { id: "a", pattern: "Use repository pattern", scope: "src/db", rationale: "keeps SQL out", triage: "approve" },
  { id: "b", pattern: "Validate webhooks", scope: "src/api", rationale: "forged events", triage: "reject" },
  { id: "c", pattern: "Cache results", scope: "src/db", rationale: "latency", triage: "approve" },
];
test("filters by verdict", () => {
  assert.deepStrictEqual(filterCandidates(items, { verdict: "approve" }).map(x=>x.id), ["a","c"]);
});
test("filters by exact scope", () => {
  assert.deepStrictEqual(filterCandidates(items, { scope: "src/api" }).map(x=>x.id), ["b"]);
});
test("query matches pattern/scope/rationale, case-insensitive", () => {
  assert.deepStrictEqual(filterCandidates(items, { query: "SQL" }).map(x=>x.id), ["a"]);
  assert.deepStrictEqual(filterCandidates(items, { query: "src/db" }).map(x=>x.id), ["a","c"]);
});
test("ANDs constraints", () => {
  assert.deepStrictEqual(filterCandidates(items, { verdict: "approve", scope: "src/db", query: "cache" }).map(x=>x.id), ["c"]);
});
test("empty options returns a new array with all items", () => {
  const out = filterCandidates(items, {});
  assert.strictEqual(out.length, 3);
  assert.notStrictEqual(out, items);
});
test("scopesOf returns sorted distinct non-empty scopes", () => {
  assert.deepStrictEqual(scopesOf(items), ["src/api", "src/db"]);
});
