"use strict";

const test = require("node:test");
const assert = require("node:assert");
const { activitySignature } = require("./activity_signature.js");

const base = () => ({
  total_agents: 1, total_served: 3, total_feedback: 1,
  agents: [{ id: "a", status: "serving", decisions_received: 3, feedback_sent: 1,
             served: [{ id: "d1" }], mins: 0.2, last_active: "2026-06-08T10:00:00Z" }],
  traces: [],
});

test("ignores volatile time fields (mins / last_active) so a quiet poll is unchanged", () => {
  const a = base();
  const b = base();
  b.agents[0].mins = 4.7;                       // time marched on
  b.agents[0].last_active = "2026-06-08T10:05:00Z";
  assert.strictEqual(activitySignature(a), activitySignature(b));
});

test("changes when a new engineer appears", () => {
  const a = base();
  const b = base();
  b.total_agents = 2;
  b.agents.push({ id: "z", status: "serving", decisions_received: 1, feedback_sent: 0, served: [] });
  assert.notStrictEqual(activitySignature(a), activitySignature(b));
});

test("changes when a new refinement trace appears", () => {
  const a = base();
  const b = base();
  b.traces = [{ from: "a", to: "z", decision_id: "d1" }];
  assert.notStrictEqual(activitySignature(a), activitySignature(b));
});

test("changes when an engineer is served more decisions", () => {
  const a = base();
  const b = base();
  b.total_served = 4;
  b.agents[0].decisions_received = 4;
  assert.notStrictEqual(activitySignature(a), activitySignature(b));
});

test("empty / null input is a stable empty signature", () => {
  assert.strictEqual(activitySignature(null), activitySignature(undefined));
});
