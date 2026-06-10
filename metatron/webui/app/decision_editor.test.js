"use strict";
const test = require("node:test");
const assert = require("node:assert");
const { validateDecisionForm } = require("./decision_editor.js");

test("requires pattern, scope, and rationale", () => {
  assert.strictEqual(validateDecisionForm({ pattern: "", scope: "app", rationale: "r" }).ok, false);
  assert.strictEqual(validateDecisionForm({ pattern: "p", scope: "", rationale: "r" }).ok, false);
  assert.strictEqual(validateDecisionForm({ pattern: "p", scope: "app", rationale: "" }).ok, false);
  assert.strictEqual(validateDecisionForm({ pattern: "p", scope: "app", rationale: "r" }).ok, true);
});

test("trims whitespace-only fields to invalid", () => {
  assert.strictEqual(validateDecisionForm({ pattern: "  ", scope: "app", rationale: "r" }).ok, false);
});

test("parseKeywords splits, trims, dedupes and caps", () => {
  const { parseKeywords } = require("./decision_editor.js");
  assert.deepStrictEqual(parseKeywords(" s3, presigned ,S3,, upload "), ["s3", "presigned", "upload"]);
  assert.deepStrictEqual(parseKeywords(""), []);
  assert.deepStrictEqual(parseKeywords(null), []);
  const many = Array.from({ length: 15 }, (_, i) => "k" + i).join(",");
  assert.strictEqual(parseKeywords(many).length, 10);
});
