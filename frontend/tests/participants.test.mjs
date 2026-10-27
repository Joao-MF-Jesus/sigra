import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { requestLogin, requestRegistration, requestLogout, requestRecommendations, requestTestHistory, requestTestFeedback, requestFinancingSimulation } from "../src/api/sigraApi.js";

test("cadastro não envia papel; sessão é cookie e requisições mutáveis têm proteção de origem", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, json: async () => ({ id: 7, role: "participant" }) };
  };
  await requestRegistration({ name: "Participante", email: "person@example.test", password: "synthetic-password" }, { fetchImpl });
  await requestLogin({ email: "person@example.test", password: "synthetic-password" }, { fetchImpl });
  for (const { options } of calls) {
    assert.equal(options.credentials, "include");
    assert.equal(options.headers["X-SIGRA-CSRF"], "1");
    assert.equal(Object.hasOwn(JSON.parse(options.body), "role"), false);
  }
  const result = await requestLogout({ fetchImpl: async (_, options) => {
    assert.equal(options.credentials, "include"); return { ok: true, status: 204 };
  } });
  assert.equal(result, null);
});

test("login encaminha uma senha fictícia existente de oito caracteres sem alterar credenciais", async () => {
  const credentials = { email: "legacy@example.test", password: "OldPass8" };
  await requestLogin(credentials, { fetchImpl: async (url, options) => {
    assert.match(url, /\/auth\/login$/);
    assert.deepEqual(JSON.parse(options.body), credentials);
    assert.equal(options.credentials, "include");
    assert.equal(options.headers["X-SIGRA-CSRF"], "1");
    return { ok: true, status: 200, json: async () => ({ role: "participant" }) };
  } });
});

test("mínimo de doze caracteres é exclusivo do cadastro; login continua obrigatório e limitado", () => {
  const auth = readFileSync(new URL("../src/features/session/AuthPanel.jsx", import.meta.url), "utf8");
  assert.match(auth, /required type="password" minLength=\{register \? 12 : 1\} maxLength=\{256\}/);
  assert.match(auth, /register && <small>Use uma senha de pelo menos 12 caracteres/);
  assert.doesNotMatch(auth, /noValidate/);
});

test("participante registra execução no servidor; visitante mantém motor stateless", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({ recommendations: [] }) }; };
  const preferences = { use_case: "cidade", budget: 70000 };
  await requestRecommendations(preferences, { fetchImpl, recordTest: true });
  await requestRecommendations(preferences, { fetchImpl });
  assert.match(calls[0].url, /\/api\/v1\/test-runs\/recommendation$/);
  assert.match(calls[1].url, /\/recommendations\?envelope=true$/);
  assert.deepEqual(JSON.parse(calls[0].options.body), preferences);
  assert.equal(Object.hasOwn(JSON.parse(calls[0].options.body), "user_id"), false);
});

test("histórico não recebe ID do usuário e avaliação não aceita resultado calculado no cliente", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({}) }; };
  await requestTestHistory(20, { fetchImpl });
  await requestTestFeedback("test-id", { rating: 4, comment: "Claro" }, { fetchImpl });
  assert.match(calls[0].url, /limit=20&offset=20&compact=true$/);
  assert.equal(calls[0].options.credentials, "include");
  assert.doesNotMatch(calls[0].url, /user_id/);
  assert.deepEqual(JSON.parse(calls[1].options.body), { rating: 4, comment: "Claro" });
  assert.equal(calls[1].options.method, "PATCH");
});

test("financiamento registrado mantém payload e não muda fórmula", async () => {
  await requestFinancingSimulation({ vehicle_price: "40000" }, { recordTest: true, fetchImpl: async (url, options) => {
    assert.match(url, /\/api\/v1\/test-runs\/financing$/);
    assert.deepEqual(JSON.parse(options.body), { vehicle_price: "40000" });
    return { ok: true, json: async () => ({}) };
  } });
});

test("telas reutilizam visual, não persistem senha/sessão no localStorage nem permitem auto-admin", () => {
  const auth = readFileSync(new URL("../src/features/session/AuthPanel.jsx", import.meta.url), "utf8");
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const history = readFileSync(new URL("../src/features/session/TestHistory.jsx", import.meta.url), "utf8");
  assert.match(auth, /login-panel/);
  assert.match(auth, /autoComplete=\{register \? "new-password" : "current-password"\}/);
  assert.doesNotMatch(auth, /role:|localStorage/);
  assert.doesNotMatch(app, /localStorage\.setItem\("sigra-session"/);
  assert.match(app, /requestSession/);
  assert.match(history, /user\.role === "admin"/);
  assert.match(history, /requestTestDetail/);
});
