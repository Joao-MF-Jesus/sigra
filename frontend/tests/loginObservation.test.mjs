import test from "node:test";
import assert from "node:assert/strict";
import { createLoginObservation, loginErrorMessage } from "../src/features/session/loginObservation.js";

const API = "http://127.0.0.1:8011";
const SECRET = "synthetic-secret-never-log";
function fixture({ realFetch = async () => ({ status: 200, ok: true, type: "cors" }), writerFails = false } = {}) {
  const events = []; const realCalls = [];
  const fetchImpl = (url, options) => {
    realCalls.push({ url, options }); return realFetch(url, options);
  };
  const observer = createLoginObservation({ apiUrl: API,
    location: { origin: "http://127.0.0.1:14185", search: "?sigra_login_observe=v1" }, cookieEnabled: true,
    fetchImpl, newId: () => "11111111-1111-4111-8111-111111111111", now: () => 100,
    writeEvent: event => { events.push(event); if (writerFails) return Promise.reject(new Error(SECRET)); } });
  return { observer, events, realCalls };
}

test("observação é opt-in e exclusiva da origem 14185 e API 8011", () => {
  const base = { apiUrl: API, location: { origin: "http://127.0.0.1:14185", search: "?sigra_login_observe=v1" } };
  for (const change of [ { apiUrl: "http://127.0.0.1:8010" }, { location: { ...base.location, origin: "http://127.0.0.1:14184" } },
    { location: { ...base.location, search: "" } }, { location: { ...base.location, search: "?sigra_login_observe=v2" } } ]) {
    assert.equal(createLoginObservation({ ...base, ...change }), null);
  }
});

test("login usa o fetch original sem alterar destino, payload, credenciais ou resultado", async () => {
  const response = { status: 200, ok: true, type: "cors" };
  const { observer, events, realCalls } = fixture({ realFetch: async () => response });
  const options = { method: "POST", credentials: "include", headers: { "X-SIGRA-CSRF": "1", Authorization: SECRET } };
  Object.defineProperty(options, "body", { get() { throw new Error("Diagnostic read of password body"); } });
  assert.equal(await observer.fetchImpl(`${API}/auth/login`, options), response);
  assert.equal(realCalls[0].options, options);
  assert.equal(realCalls[0].url, `${API}/auth/login`);
  const request = events.find(e => e.event === "request_start");
  assert.equal(request.credentials_included, true);
  assert.equal(request.csrf_marker_present, true);
  assert.doesNotMatch(JSON.stringify(events), new RegExp(SECRET));
});

test("validação nativa registra somente flags, nunca valor ou comprimento da senha", () => {
  const { observer, events } = fixture();
  const target = { type: "password", validity: { tooShort: true, valueMissing: false } };
  Object.defineProperty(target, "value", { get() { throw new Error("Credential value read"); } });
  observer.buttonClick(); observer.nativeInvalid(target);
  const invalid = events.at(-1);
  assert.equal(invalid.field, "password"); assert.equal(invalid.too_short, true);
  assert.equal(Object.hasOwn(invalid, "value"), false); assert.equal(Object.hasOwn(invalid, "length"), false);
});

test("401 e 422 são observados sem ler resposta de erro ou credenciais", async () => {
  for (const status of [401, 422]) {
    const response = { status, ok: false, type: "cors", json() { throw new Error("Diagnostic response-body read"); } };
    const { observer, events } = fixture({ realFetch: async () => response });
    await observer.fetchImpl(`${API}/auth/login`, { method: "POST", credentials: "include" });
    observer.failure({ status, message: SECRET });
    assert.equal(events.find(e => e.event === "response_received").http_status, status);
    assert.equal(events.at(-1).backend_message, null);
    assert.doesNotMatch(JSON.stringify(events), new RegExp(SECRET));
  }
});

test("falha de transporte preserva a exceção original sem registrar mensagem arbitrária", async () => {
  const failure = new TypeError(SECRET);
  const { observer, events } = fixture({ realFetch: async () => { throw failure; } });
  await assert.rejects(observer.fetchImpl(`${API}/auth/login`, {}), error => error === failure);
  assert.equal(events.at(-1).error_type, "TypeError");
  assert.doesNotMatch(JSON.stringify(events), new RegExp(SECRET));
});

test("recuperação de sessão distingue login bem sucedido de reconhecimento posterior", async () => {
  for (const user of [null, { id: "synthetic-id", name: "Participante fictício TLS A", email: SECRET }]) {
    const { observer, events } = fixture();
    observer.success({ id: SECRET, name: "Participante fictício TLS A", email: SECRET });
    await observer.checkSession(async options => {
      await options.fetchImpl(`${API}/auth/session`, { credentials: "include", method: "GET" });
      return { user };
    });
    assert.equal(events.at(-1).authenticated, Boolean(user));
    assert.equal(events.at(-1).reference_label, user ? "TLS_A" : "NONE");
    assert.doesNotMatch(JSON.stringify(events), /synthetic-id|synthetic-secret/);
  }
});

test("falha no registro diagnóstico não altera o resultado de autenticação", async () => {
  const response = { status: 200, ok: true, type: "cors" };
  const { observer } = fixture({ writerFails: true, realFetch: async () => response });
  assert.equal(await observer.fetchImpl(`${API}/auth/login`, {}), response);
  await new Promise(resolve => setTimeout(resolve, 0));
});

test("URLs não autorizadas passam sem observação ou exposição de query", async () => {
  const { observer, events } = fixture();
  for (const url of [`${API}/auth/login?token=${SECRET}`, `${API}/auth/register`, "http://127.0.0.1:8010/auth/login"]) {
    await observer.fetchImpl(url, {});
  }
  assert.equal(events.length, 1);
});

test("mensagem do backend é allowlist exata e os textos anteriores da interface são preservados", () => {
  const { observer, events } = fixture();
  observer.failure({ status: 403, message: "Origem da operação não autorizada" });
  assert.equal(events.at(-1).backend_message, "Origem da operação não autorizada");
  assert.equal(loginErrorMessage({ status: 401 }), "E-mail ou senha incorretos.");
  assert.match(loginErrorMessage({ status: 422 }), /12 a 256/);
});

test("rejeições HTTP não são apresentadas como falha de rede nem expõem erros arbitrários", () => {
  for (const status of [403, 500, 503]) {
    const message = loginErrorMessage({ status, message: SECRET });
    assert.match(message, new RegExp(`HTTP ${status}`));
    assert.doesNotMatch(message, new RegExp(SECRET));
    assert.doesNotMatch(message, /bloqueios de CORS/);
  }
  assert.match(loginErrorMessage({ status: 403, message: "Origem da operação não autorizada" }), /Origem da operação não autorizada.*HTTP 403/);
  assert.match(loginErrorMessage({ status: 503, message: "Persistência de participantes indisponível. A migration precisa ser aplicada pelo responsável." }), /Persistência de participantes indisponível.*HTTP 503/);
});

test("falhas sem resposta HTTP não presumem rejeição da senha ou erro do banco", () => {
  const network = loginErrorMessage(new TypeError(SECRET));
  assert.match(network, /não foi disponibilizado um status HTTP/);
  assert.doesNotMatch(network, /E-mail ou senha incorretos|HTTP 0|migration|synthetic-secret/);
  assert.match(loginErrorMessage({ name: "AbortError", message: SECRET }), /interrompida/);
  assert.doesNotMatch(loginErrorMessage({ status: "503", message: SECRET }), /HTTP 503|synthetic-secret/);
  assert.doesNotMatch(loginErrorMessage(undefined), /synthetic-secret/);
});

test("observação conserva o status de erro HTTP e distingue-o de falha de transporte", async () => {
  for (const status of [403, 500, 503]) {
    const { observer, events } = fixture({ realFetch: async () => ({ status, ok: false, type: "cors" }) });
    await observer.fetchImpl(`${API}/auth/login`, { method: "POST", credentials: "include" });
    observer.failure({ status, message: SECRET });
    assert.equal(events.find(e => e.event === "response_received").http_status, status);
    assert.equal(events.some(e => e.event === "request_failed"), false);
    assert.equal(events.at(-1).http_status, status);
    assert.match(events.at(-1).ui_message, new RegExp(`HTTP ${status}`));
    assert.doesNotMatch(JSON.stringify(events), new RegExp(SECRET));
  }
});
