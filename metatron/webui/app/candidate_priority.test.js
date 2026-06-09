"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { prioritizeCandidates } = require("./candidate_priority.js");

const ids = (xs) => xs.map((x) => x.id);

test("orders approve, then borderline, then reject, then untriaged", () => {
  const input = [
    { id: "r", triage: "reject" },
    { id: "a", triage: "approve" },
    { id: "n", triage: "none" },
    { id: "b", triage: "borderline" },
  ];
  assert.deepStrictEqual(ids(prioritizeCandidates(input)), ["a", "b", "r", "n"]);
});

test("is stable within a tier (preserves newest-first input order)", () => {
  const input = [
    { id: "a1", triage: "approve" },
    { id: "a2", triage: "approve" },
    { id: "x", triage: "none" },     // missing/none sorts last
    { id: "a3", triage: "approve" },
  ];
  assert.deepStrictEqual(ids(prioritizeCandidates(input)), ["a1", "a2", "a3", "x"]);
});

test("treats missing/unknown triage as lowest priority and does not mutate input", () => {
  const input = [{ id: "u" /* no triage */ }, { id: "a", triage: "approve" }];
  const out = prioritizeCandidates(input);
  assert.deepStrictEqual(ids(out), ["a", "u"]);
  assert.deepStrictEqual(ids(input), ["u", "a"]);  // original untouched
});
