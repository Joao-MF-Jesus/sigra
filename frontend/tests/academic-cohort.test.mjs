import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { requestAcademicMetadata, requestAcademicVehiclePage, requestAcademicCatalog, requestAcademicVehicleDetail, requestAcademicEvaluation } from "../src/api/sigraApi.js";
import { ACADEMIC_PROFILES, ACADEMIC_SCENARIOS, DEFAULT_ACADEMIC_FORM, academicPayload, academicCurrency, academicValue, academicError, createAcademicRequestGate } from "../src/features/academic/academicModel.js";
import { initialAcademicMode, CARPEDIA_UI_ENABLED } from "../src/config/runtime.js";

// Synthetic data stays exclusively in tests, never used as an application fallback.
const snapshot = "11111111-1111-4111-8111-111111111111";
const envelope = { mode: "academic_only", operationally_active: false, recommended: false, snapshot_id: snapshot, cohort_fingerprint: "a".repeat(64) };
const vehicle = (id) => ({ mode: "academic_only", operationally_active: false, recommended: false, catalog_id: id, label: `Veículo de teste ${id}`, fipe_code: "002150-4", year_code: "2018-5", purchase_price_brl: "60000.00", price_reference_month: "2026-09" });
const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const page = (items, total, offset = 0) => ({ ...envelope, items, total, offset, limit: 20 });
const evaluation = () => ({ ...envelope, profile: "app", scenario: "base", eligible_ids: [36, 37], eligible_count: 2, returned_ids: [36], groups: { groupA: { ranking: [{ id: 36, preview_score: "65.20" }], diagnostic_only: true } }, evaluations: { 36: { id: 36, profile: "app", scenario: "base", academic_test_ready: true, operationally_active: false, recommended: false } }, limitations: [] });

test("entrada acadêmica é explícita; modo operacional e CarPedia permanecem separados", () => {
  assert.equal(initialAcademicMode(""), false);
  assert.equal(initialAcademicMode("#academic"), true);
  assert.equal(CARPEDIA_UI_ENABLED, false);
  assert.equal(ACADEMIC_PROFILES.length, 6);
  assert.deepEqual(ACADEMIC_SCENARIOS.map(([key]) => key), ["low", "base", "high"]);
});

test("payload envia somente os parâmetros reais, preservando Decimal como string", () => {
  const form = { ...DEFAULT_ACADEMIC_FORM, purchase: "90000.10", monthly: "1750.00", monthly_mileage: "9999", fuel_price: "12", vehicle_id: 36 };
  assert.deepEqual(academicPayload(form, snapshot), { profile: "app", scenario: "base", limit: 10, snapshot_id: snapshot, max_purchase_price_brl: "90000.10", max_monthly_tco_brl: "1750.00" });
  assert.equal("max_monthly_tco_brl" in academicPayload(DEFAULT_ACADEMIC_FORM, snapshot), false);
});

for (const value of ["-1", "0", "NaN", "Infinity", "1.234", "1,00"]) {
  test(`filtro financeiro inválido é rejeitado: ${value}`, () => {
    assert.throws(() => academicPayload({ ...DEFAULT_ACADEMIC_FORM, monthly: value }, snapshot));
  });
}
test("perfil, cenário e limite inválidos falham fechados", () => {
  for (const form of [{ profile: "inventado" }, { scenario: "custom" }, { limit: "61" }, { limit: "1.5" }]) assert.throws(() => academicPayload({ ...DEFAULT_ACADEMIC_FORM, ...form }, snapshot));
});

test("ausência não vira custo zero nem ausência explícita de equipamento", () => {
  assert.equal(academicCurrency(null), "Indisponível");
  assert.equal(academicCurrency(""), "Indisponível");
  assert.equal(academicValue({ value: null, unit: "bool" }), "Indisponível");
  assert.equal(academicValue({ value: false, unit: "bool" }), "Não");
  assert.match(academicCurrency("1642.02"), /1\.642,02/);
});

test("metadados são solicitados no prefixo oficial, sem cadastro operacional", async () => {
  const urls = [];
  const result = await requestAcademicMetadata({ fetchImpl: async (url) => { urls.push(url); return ok({ ...envelope, selected_count: 60, profile_counts: { app: 60 }, limitations: [] }); } });
  assert.equal(result.selected_count, 60);
  assert.equal(new URL(urls[0]).pathname, "/api/v1/academic-cohort/metadata");
});

test("catálogo completo carrega 60 únicos em três páginas e fixa snapshot", async () => {
  const requests = [];
  const items = await requestAcademicCatalog({ snapshotId: snapshot, expectedCount: 60, fingerprint: envelope.cohort_fingerprint, fetchImpl: async (url) => {
    const query = new URL(url).searchParams;
    assert.equal(query.get("snapshot_id"), snapshot);
    const offset = Number(query.get("offset"));
    requests.push(offset);
    return ok(page(Array.from({ length: 20 }, (_, index) => vehicle(offset + index + 1)), 60, offset));
  } });
  assert.deepEqual(requests, [0, 20, 40]);
  assert.equal(items.length, 60);
  assert.equal(new Set(items.map((item) => item.catalog_id)).size, 60);
});

test("catálogo vazio não recebe fixture ou fallback", async () => {
  assert.deepEqual(await requestAcademicCatalog({ fetchImpl: async () => ok(page([], 0)) }), []);
});

for (const kind of ["duplicate", "empty", "total", "snapshot", "fingerprint"]) {
  test(`paginação rejeita inconsistência ${kind}`, async () => {
    let call = 0;
    await assert.rejects(requestAcademicCatalog({ snapshotId: snapshot, fetchImpl: async () => {
      call += 1;
      if (call === 1) return ok(page([vehicle(36)], 2));
      const result = page(kind === "empty" ? [] : [vehicle(kind === "duplicate" ? 36 : 37)], kind === "total" ? 3 : 2, 1);
      if (kind === "snapshot") result.snapshot_id = "different";
      if (kind === "fingerprint") result.cohort_fingerprint = "b".repeat(64);
      return ok(result);
    } }));
  });
}

test("página inválida ou com ativação operacional não é aceita", async () => {
  await assert.rejects(requestAcademicVehiclePage({ fetchImpl: async () => ok(page([{ ...vehicle(36), operationally_active: true }], 1)) }));
  await assert.rejects(requestAcademicMetadata({ fetchImpl: async () => ok({ ...envelope, operationally_active: true }) }));
});

test("detalhe usa catalog_id somente no endpoint acadêmico e snapshot correto", async () => {
  let requested;
  await requestAcademicVehicleDetail(36, { snapshotId: snapshot, fetchImpl: async (url) => {
    requested = new URL(url);
    return ok({ ...envelope, vehicle: vehicle(36), evidence: { fields: {} }, evaluations: {} });
  } });
  assert.equal(requested.pathname, "/api/v1/academic-cohort/vehicles/36");
  assert.equal(requested.searchParams.get("snapshot_id"), snapshot);
  await assert.rejects(requestAcademicVehicleDetail(36, { fetchImpl: async () => ok({ ...envelope, vehicle: vehicle(37), evidence: { fields: {} }, evaluations: {} }) }));
});

test("avaliação mantém elegíveis distintos dos apresentados, sem recompor ranking", async () => {
  let request;
  const body = academicPayload(DEFAULT_ACADEMIC_FORM, snapshot);
  const result = await requestAcademicEvaluation(body, { fetchImpl: async (url, options) => { request = { url, options }; return ok(evaluation()); } });
  assert.equal(new URL(request.url).pathname, "/api/v1/academic-cohort/evaluate");
  assert.equal(request.options.method, "POST");
  assert.deepEqual(JSON.parse(request.options.body), body);
  assert.equal(result.eligible_count, 2);
  assert.equal(result.returned_ids.length, 1);
  assert.equal(result.groups.groupA.ranking[0].preview_score, "65.20");
});

test("grupos incompatíveis permanecem separados e sem posições globais", async () => {
  const data = evaluation();
  data.returned_ids.push(37);
  data.groups.groupB = { ranking: [{ id: 37, preview_score: "99" }], diagnostic_only: true };
  data.evaluations[37] = { ...data.evaluations[36], id: 37 };
  const result = await requestAcademicEvaluation(academicPayload(DEFAULT_ACADEMIC_FORM, snapshot), { fetchImpl: async () => ok(data) });
  assert.deepEqual(Object.keys(result.groups), ["groupA", "groupB"]);
});

test("avaliação vazia é legítima e explicada sem alternativa inelegível", async () => {
  const data = { ...evaluation(), eligible_ids: [], eligible_count: 0, returned_ids: [], groups: {}, evaluations: {}, empty_reason: "No eligible vehicle" };
  assert.equal((await requestAcademicEvaluation(academicPayload(DEFAULT_ACADEMIC_FORM, snapshot), { fetchImpl: async () => ok(data) })).eligible_count, 0);
});

test("avaliação incompatível ou identidade duplicada é rejeitada", async () => {
  for (const change of [(data) => { data.scenario = "high"; }, (data) => { data.eligible_ids = [36, 36]; }, (data) => { data.evaluations[36].recommended = true; }, (data) => { data.groups.groupA.ranking[0].id = 999; }]) {
    const data = evaluation(); change(data);
    await assert.rejects(requestAcademicEvaluation(academicPayload(DEFAULT_ACADEMIC_FORM, snapshot), { fetchImpl: async () => ok(data) }));
  }
});

test("erros HTTP são sanitizados; não apresentam detalhes arbitrários", async () => {
  let caught;
  try { await requestAcademicMetadata({ fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({ detail: "postgresql://user:secret@host/database" }) }) }); } catch (error) { caught = error; }
  assert.equal(caught.status, 503);
  assert.doesNotMatch(caught.message, /secret|postgresql|user/);
  assert.match(academicError(caught), /Nenhuma fixture/);
  assert.match(academicError({ status: 404 }), /configuração do backend/);
});

test("abort é preservado, não convertido em erro de interface", async () => {
  await assert.rejects(requestAcademicMetadata({ fetchImpl: async () => { throw new DOMException("Aborted", "AbortError"); } }), { name: "AbortError" });
});

test("resposta obsoleta não substitui seleção recente, mesmo se transporte ignorar abort", () => {
  const gate = createAcademicRequestGate();
  const old = gate.begin();
  const current = gate.begin();
  assert.equal(old.isCurrent(), false);
  assert.equal(old.signal.aborted, true);
  assert.equal(current.isCurrent(), true);
  gate.cancel();
  assert.equal(current.isCurrent(), false);
});

test("cleanup e remontagem StrictMode não aceitam resposta da montagem anterior", () => {
  const gate = createAcademicRequestGate();
  const firstMount = gate.begin(); gate.cancel(); const secondMount = gate.begin();
  assert.equal(firstMount.isCurrent(), false);
  assert.equal(secondMount.isCurrent(), true);
});

test("UI acadêmica tem retry, modal sem ações operacionais e apresentação honesta", () => {
  const ui = readFileSync(new URL("../src/features/academic/AcademicPage.jsx", import.meta.url), "utf8");
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const css = readFileSync(new URL("../src/features/academic/academic.css", import.meta.url), "utf8");
  assert.doesNotMatch(app, /activeTab === "academic"/);
  assert.match(app, /CohortRecommendationResults/);
  assert.match(ui, /Tentar carregar novamente/);
  assert.match(ui, /academic_habitability_proxy/);
  assert.match(ui, /estimativa de cenário/);
  assert.match(ui, /showModal\(\)/);
  assert.match(ui, /onCancel=\{onClose\}/);
  assert.doesNotMatch(ui, /onParts|onCompare|public\.vehicles|requestRecommendations|\/user-vehicles|\/expenses|localStorage/);
  assert.match(css, /min-height: 48px/);
  assert.match(css, /100dvh/);
  assert.match(css, /minmax\(min\(100%, 300px\), 1fr\)/);
  assert.doesNotMatch(css, /transform:\s*scale|zoom:|overflow-x:\s*hidden/);
});
