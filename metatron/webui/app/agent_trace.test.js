"use strict";

const test = require("node:test");
const assert = require("node:assert");
const { activeTraceForFocus } = require("./agent_trace.js");

const agent = (id) => ({ kind: "agent", key: id, agent: { id, name: id }, status: "serving" });
const group = () => ({ kind: "group", key: "group", members: [], status: "idle" });
const trace = (from, to, extra = {}) => ({
  from, from_name: from, to, to_name: to, decision_id: "d", pattern: "use httpRequest", ...extra,
});

test("returns the trace and both node indices when the focused node is its target", () => {
  const nodes = [agent("a1"), agent("b1")];
  const res = activeTraceForFocus(nodes, [trace("a1", "b1")], 1);
  assert.ok(res);
  assert.strictEqual(res.trace.from, "a1");
  assert.strictEqual(res.fromIdx, 0);
  assert.strictEqual(res.toIdx, 1);
});

test("returns null when the focused node is not the target of any trace", () => {
  const nodes = [agent("a1"), agent("b1")];
  assert.strictEqual(activeTraceForFocus(nodes, [trace("a1", "b1")], 0), null);
});

test("returns null when the focused node is a grouped (overflow) node", () => {
  const nodes = [group(), agent("b1")];
  assert.strictEqual(activeTraceForFocus(nodes, [trace("a1", "b1")], 0), null);
});

test("degrades gracefully: trace returned with fromIdx -1 when the source is not visible", () => {
  const nodes = [agent("b1")]; // a1 collapsed into overflow / outside window
  const res = activeTraceForFocus(nodes, [trace("a1", "b1")], 0);
  assert.ok(res);
  assert.strictEqual(res.fromIdx, -1);
  assert.strictEqual(res.toIdx, 0);
  assert.strictEqual(res.trace.from_name, "a1");
});

test("prefers a trace whose source is visible when several target the focused node", () => {
  const nodes = [agent("a1"), agent("b1")];
  const traces = [trace("x9", "b1"), trace("a1", "b1")]; // x9 not among nodes
  const res = activeTraceForFocus(nodes, traces, 1);
  assert.strictEqual(res.trace.from, "a1");
  assert.strictEqual(res.fromIdx, 0);
});
