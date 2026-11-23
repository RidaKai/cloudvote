// Tests unitaires : npm test
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import worker, { callClose } from "../src/index.js";

const env = {
  RENDER_URL: "https://render.example",
  CLOSE_SECRET: "dev-secret",
  BACKOFF_MS: "0", // pas d'attente pendant les tests
};

let calls;
function mockFetch(responses) {
  calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    const r = responses[Math.min(calls.length - 1, responses.length - 1)];
    if (r instanceof Error) throw r;
    return new Response(r.body ?? "", { status: r.status });
  };
}

beforeEach(() => {
  console.log = console.warn = () => {}; // silence des journaux pendant les tests
});

test("appelle POST /internal/close avec le secret", async () => {
  mockFetch([{ status: 200, body: '{"closed_positions":3}' }]);
  const r = await callClose(env);
  assert.equal(r.ok, true);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://render.example/internal/close");
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, "Bearer dev-secret");
});

test("réessaie quand Render se réveille (502 puis 200)", async () => {
  mockFetch([{ status: 502 }, { status: 200, body: "{}" }]);
  const r = await callClose(env);
  assert.equal(r.attempt, 2);
});

test("réessaie après un timeout réseau", async () => {
  const timeout = new Error("The operation was aborted due to timeout");
  timeout.name = "TimeoutError";
  mockFetch([timeout, { status: 200, body: "{}" }]);
  const r = await callClose(env);
  assert.equal(r.attempt, 2);
});

test("ne réessaie pas si le secret est refusé (401)", async () => {
  mockFetch([{ status: 401 }]);
  await assert.rejects(callClose(env), /CLOSE_SECRET/);
  assert.equal(calls.length, 1);
});

test("échoue après 3 essais si Render reste indisponible", async () => {
  mockFetch([{ status: 503 }]);
  await assert.rejects(callClose(env), /3 essais/);
  assert.equal(calls.length, 3);
});

test("refuse de démarrer sans CLOSE_SECRET", async () => {
  mockFetch([{ status: 200 }]);
  await assert.rejects(callClose({ RENDER_URL: "https://x" }), /CLOSE_SECRET manquant/);
  assert.equal(calls.length, 0);
});

test("supprime le / final de RENDER_URL", async () => {
  mockFetch([{ status: 200 }]);
  await callClose({ ...env, RENDER_URL: "https://render.example/" });
  assert.equal(calls[0].url, "https://render.example/internal/close");
});

test("aucun endpoint public : fetch renvoie 404", async () => {
  const res = await worker.fetch(new Request("https://worker.example/"), env, {});
  assert.equal(res.status, 404);
});

test("scheduled() lance la clôture via waitUntil", async () => {
  mockFetch([{ status: 200, body: "{}" }]);
  let pending;
  const ctx = { waitUntil: (p) => (pending = p) };
  await worker.scheduled({ cron: "*/30 * * * *", scheduledTime: Date.now() }, env, ctx);
  await pending;
  assert.equal(calls.length, 1);
});
