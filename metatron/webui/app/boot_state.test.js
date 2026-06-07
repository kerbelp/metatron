"use strict";

const test = require("node:test");
const assert = require("node:assert");
const { bootScreenState } = require("./boot_state.js");

const TIMEOUT = 10000;

test("fresh load shows the loading splash", () => {
  assert.strictEqual(
    bootScreenState({ loading: true, error: null, repos: null, elapsedMs: 0, timeoutMs: TIMEOUT }),
    "loading"
  );
});

test("still loading under the timeout stays on the splash", () => {
  assert.strictEqual(
    bootScreenState({ loading: true, error: null, repos: null, elapsedMs: 5000, timeoutMs: TIMEOUT }),
    "loading"
  );
});

test("loading past the timeout surfaces a timeout state", () => {
  assert.strictEqual(
    bootScreenState({ loading: true, error: null, repos: null, elapsedMs: TIMEOUT, timeoutMs: TIMEOUT }),
    "timeout"
  );
  assert.strictEqual(
    bootScreenState({ loading: true, error: null, repos: null, elapsedMs: TIMEOUT + 2000, timeoutMs: TIMEOUT }),
    "timeout"
  );
});

test("loading with no configured timeout never times out", () => {
  assert.strictEqual(
    bootScreenState({ loading: true, error: null, repos: null, elapsedMs: 999999 }),
    "loading"
  );
});

test("a fetch error surfaces the error state", () => {
  assert.strictEqual(
    bootScreenState({ loading: false, error: new Error("boom"), repos: null }),
    "error"
  );
});

test("an error while still loading is reported as error, not loading", () => {
  assert.strictEqual(
    bootScreenState({ loading: true, error: new Error("boom"), repos: null, elapsedMs: 0, timeoutMs: TIMEOUT }),
    "error"
  );
});

test("an error wins over a concurrent timeout", () => {
  assert.strictEqual(
    bootScreenState({ loading: true, error: new Error("boom"), repos: null, elapsedMs: TIMEOUT * 2, timeoutMs: TIMEOUT }),
    "error"
  );
});

test("an empty catalog reports empty, not an endless splash", () => {
  assert.strictEqual(
    bootScreenState({ loading: false, error: null, repos: [], elapsedMs: 0, timeoutMs: TIMEOUT }),
    "empty"
  );
});

test("a populated catalog is ready", () => {
  assert.strictEqual(
    bootScreenState({ loading: false, error: null, repos: ["github.com/acme/app"] }),
    "ready"
  );
});

test("finished loading with no array yet stays on the splash", () => {
  // Defensive: data resolved but not shaped as a repo list — keep waiting, don't crash.
  assert.strictEqual(
    bootScreenState({ loading: false, error: null, repos: null }),
    "loading"
  );
});
