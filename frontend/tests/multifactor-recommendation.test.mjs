import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  MULTIFACTOR_DEFAULT_WEIGHTS,
  MULTIFACTOR_WEIGHT_DESCRIPTIONS,
  buildMultifactorProfile,
  multifactorWeightSummary,
  resetMultifactorWeightFields,
} from "../src/features/recommendations/multifactorRecommendationModel.js";
import { getMultifactorCoverage, getMultifactorUnavailablePresentation } from "../src/features/recommendations/recommendationModel.js";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformSync } from "esbuild";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { validateRecommendationProfile } from "../src/features/recommendations/recommendationValidation.js";

const legacy = {
  vehicle_type: "car",
  budget: "70000",
  monthly_limit: "1200",
  use_case: "cidade",
  recommendation_strategy: "cost_benefit",
  monthly_mileage: "1000",
  fuel_price: "6",
};

const multifactor = {
  ...legacy,
  multifactor_enabled: true,
  multifactor_monthly_distance_km: "1250.50",
  multifactor_city_percentage: "65",
  multifactor_highway_percentage: "35",
  multifactor_fuel_strategy: "lowest_projected_cost",
  multifactor_price_mode: "anp",
  multifactor_manual_fuel_price_brl: "",
  multifactor_horizon_months: "24",
  multifactor_state_code: "sp",
  multifactor_municipality: "Campinas",
  multifactor_reference_week_start: "2026-08-10",
  multifactor_city_consumption_km_l: "",
  multifactor_highway_consumption_km_l: "",
  ...Object.fromEntries(Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([code, value]) => [`weight_${code}`, value])),
};

test("perfil desativado preserva byte a byte o payload histórico", () => {
  const expected = validateRecommendationProfile(legacy);
  const disabled = validateRecommendationProfile({ ...multifactor, multifactor_enabled: false });
  assert.equal(disabled.isValid, true);
  assert.deepEqual(disabled.payload, expected.payload);
  assert.equal("multifactor_profile" in disabled.payload, false);
});

test("perfil multifator envia um cenário comum e pesos como decimais textuais", () => {
  const result = validateRecommendationProfile(multifactor);
  assert.equal(result.isValid, true);
  assert.equal(result.payload.multifactor_profile.enabled, true);
  assert.equal(result.payload.multifactor_profile.scenario.monthly_distance_km, "1250.50");
  assert.equal(result.payload.multifactor_profile.scenario.state_code, "SP");
  assert.equal(result.payload.multifactor_profile.scenario.fuel_strategy, "lowest_projected_cost");
  assert.equal(result.payload.multifactor_profile.weights.total_cost, "25");
});

test("percentuais inválidos, pesos nulos e não finitos bloqueiam envio", () => {
  const percentages = buildMultifactorProfile({ ...multifactor, multifactor_city_percentage: "60" }, 70000);
  assert.equal(percentages.isValid, false);
  assert.ok(percentages.errors.multifactor_percentages);
  const zeros = buildMultifactorProfile({ ...multifactor, ...Object.fromEntries(Object.keys(MULTIFACTOR_DEFAULT_WEIGHTS).map((code) => [`weight_${code}`, "0"])) }, 70000);
  assert.equal(zeros.isValid, false);
  assert.ok(zeros.errors.multifactor_weights);
  const invalid = buildMultifactorProfile({ ...multifactor, weight_total_cost: "Infinity" }, 70000);
  assert.equal(invalid.isValid, false);
  assert.ok(invalid.errors.weight_total_cost);
});

test("orçamento acima de 200 mil não exige autorização especial", () => {
  const result = validateRecommendationProfile({ ...multifactor, budget: "250000" });
  assert.equal(result.isValid, true);
  assert.equal(result.payload.budget, 250000);
  assert.equal("allow_budget_above_200k" in result.payload.multifactor_profile, false);
});

test("pesos são editáveis, normalizados para apresentação e restauráveis", () => {
  const profile = { ...multifactor, weight_total_cost: "1", weight_usage_fit: "1" };
  const summary = multifactorWeightSummary(profile);
  assert.equal(summary.total, 57);
  assert.ok(summary.entries.every((item) => Number.isFinite(item.normalizedPercentage)));
  assert.deepEqual(resetMultifactorWeightFields(profile), Object.fromEntries(Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([code, value]) => [`weight_${code}`, value])));
  assert.match(MULTIFACTOR_WEIGHT_DESCRIPTIONS.total_cost, /custo de combustível/i);
  assert.match(MULTIFACTOR_WEIGHT_DESCRIPTIONS.legacy_quality, /sem repetir custo ou adequação/i);
});

test("frontend coleta parâmetros e exibe explicação sem duplicar fórmula financeira", () => {
  const fields = readFileSync(new URL("../src/features/recommendations/MultifactorProfileFields.jsx", import.meta.url), "utf8");
  const breakdown = readFileSync(new URL("../src/features/recommendations/MultifactorBreakdown.jsx", import.meta.url), "utf8");
  const model = readFileSync(new URL("../src/features/recommendations/multifactorRecommendationModel.js", import.meta.url), "utf8");
  assert.match(fields, /Perfil multifator/);
  assert.match(fields, /Os cálculos financeiros são realizados exclusivamente pelo backend/);
  assert.match(breakdown, /Custo de combustível projetado/);
  assert.match(breakdown, /Fontes de referência: FIPE, PBEV e ANP/);
  assert.doesNotMatch(breakdown, /mixed_1000_v1|integrated_dataset_version/);
  assert.doesNotMatch(`${fields}\n${model}`, /monthly_fuel_cost|annual_fuel_cost|fuel_cost_per_km/);
});

test("evidência ausente permanece indisponível e nunca vira nota zero ou detalhe técnico", () => {
  assert.match(getMultifactorUnavailablePresentation("GOLD_IDENTITY_NOT_FOUND"), /correspondência publicada e inequívoca/i);
  assert.match(getMultifactorUnavailablePresentation("GOLD_IDENTITY_AMBIGUOUS"), /nenhuma foi escolhida automaticamente/i);
  const breakdown = readFileSync(new URL("../src/features/recommendations/MultifactorBreakdown.jsx", import.meta.url), "utf8");
  assert.match(breakdown, /getMultifactorUnavailablePresentation/);
  assert.match(breakdown, /sem nota inventada/i);
  assert.doesNotMatch(breakdown, /multifactor\.detail/);
});

test("campos do cenário e pesos possuem rótulos e erros acessíveis", () => {
  const fields = readFileSync(new URL("../src/features/recommendations/MultifactorProfileFields.jsx", import.meta.url), "utf8");
  assert.match(fields, /Perfil multifator/);
  assert.match(fields, /Necessidade de deslocamento/);
  assert.match(fields, /htmlFor=/);
  assert.match(fields, /aria-invalid/);
  assert.match(fields, /role="alert"/);
});

const requestedMetadata = { multifactor_profile: { enabled: true, ranked_count: 99, unavailable_count: 0 } };
const unavailableItem = (id) => ({
  vehicle: { id, brand: "Fiat", model: "Uno Attractive", year: 2018 }, score: 80,
  multifactor: { enabled: true, status: "unavailable", final_score: null,
    reason_code: "GOLD_IDENTITY_NOT_FOUND", identity_diagnostic: { rejection_reason: "coverage_absent" } },
});
const rankedItem = (id) => ({ ...unavailableItem(id), multifactor: {
  enabled: true, status: "ranked", final_score: "85.0000", position: 1,
  baseline_position: 2, baseline_score: 80, components: [], cost: {},
} });

test("contagens reconciliam com resultados efetivos, não com a flag ou metadados antigos", () => {
  assert.deepEqual(getMultifactorCoverage([rankedItem(1), unavailableItem(2)], requestedMetadata), {
    requested: true, rankedCount: 1, originalCount: 1, total: 2, hasScores: true,
  });
  assert.deepEqual(getMultifactorCoverage([unavailableItem(1), unavailableItem(2)], requestedMetadata), {
    requested: true, rankedCount: 0, originalCount: 2, total: 2, hasScores: false,
  });
  assert.equal(getMultifactorCoverage([], requestedMetadata).hasScores, false);
  assert.equal(getMultifactorCoverage([{ vehicle: { id: 1 } }]).requested, false);
  assert.equal(getMultifactorCoverage([rankedItem(1), rankedItem(2)]).originalCount, 0);
  for (const invalid of [null, undefined, "", false, "NaN"]) {
    const item = rankedItem(1);
    item.multifactor.final_score = invalid;
    assert.equal(getMultifactorCoverage([item]).rankedCount, 0);
  }
});

test("motivos diferenciam cobertura, identidade, campo obrigatório e evidência, sem inventar orçamento", () => {
  assert.match(getMultifactorUnavailablePresentation("GOLD_IDENTITY_NOT_FOUND", { rejection_reason: "coverage_absent" }), /não indica reprovação por orçamento/);
  assert.match(getMultifactorUnavailablePresentation("GOLD_IDENTITY_NOT_FOUND", { rejection_reason: "identity_mismatch" }), /versão.*diverge/);
  assert.match(getMultifactorUnavailablePresentation("LEGACY_IDENTITY_UNAVAILABLE", { rejection_reason: "required_identity_missing" }), /campo obrigatório/);
  assert.match(getMultifactorUnavailablePresentation("MULTIFACTOR_EVIDENCE_UNAVAILABLE", { rejection_reason: "scenario_evidence_unavailable" }), /cenário solicitado/);
});

const renderedModules = new Map();
function loadJsxModule(url) {
  if (renderedModules.has(url.href)) return renderedModules.get(url.href).exports;
  // Transform source in memory, without build artifacts or package-directory scans.
  const { code } = transformSync(readFileSync(url, "utf8"), {
    loader: "jsx", format: "cjs", define: { "import.meta.env": "{}" },
  });
  const module = { exports: {} };
  renderedModules.set(url.href, module);
  const nativeRequire = createRequire(fileURLToPath(url));
  const localRequire = (name) => name.startsWith(".") ? loadJsxModule(new URL(name, url)) : nativeRequire(name);
  new Function("require", "module", "exports", code)(localRequire, module, module.exports);
  return module.exports;
}

function renderComponent(filename, props) {
  const component = loadJsxModule(new URL(`../src/features/recommendations/${filename}.jsx`, import.meta.url)).default;
  return renderToStaticMarkup(React.createElement(component, props));
}

test("zero pontuações não anuncia multifator ativo e exibe um único aviso acima dos cards", () => {
  const recommendations = [unavailableItem(1), unavailableItem(2)];
  const state = { recommendations, metadata: requestedMetadata, hasCalculated: true };
  const html = renderComponent("RecommendationPage", { vehicleType: "car", state, showAll: true });
  assert.doesNotMatch(html, /Perfil multifator ativo|Comparação multifator|Comparação personalizada indisponível/);
  assert.match(html, /0 de 2 veículos receberam pontuação multifator; 2 permaneceram/);
  assert.equal((html.match(/data-testid="multifactor-summary"/g) || []).length, 1);
  assert.ok(html.indexOf('data-testid="multifactor-summary"') < html.indexOf('data-testid="recommendation-results"'));
  const detail = renderComponent("MultifactorBreakdown", { item: recommendations[0] });
  assert.match(detail, /ainda não tem cobertura/);
  assert.match(detail, /sem nota inventada/);
  assert.equal(renderComponent("MultifactorBreakdown", { item: recommendations[0], compact: true }), "");
});

test("cobertura parcial exibe a contagem real sem esconder veículos da classificação original", () => {
  const state = { recommendations: [rankedItem(1), unavailableItem(2)], metadata: requestedMetadata, hasCalculated: true };
  const html = renderComponent("RecommendationPage", { vehicleType: "car", state, showAll: true });
  assert.match(html, /Comparação multifator para o cenário informado/);
  assert.match(html, /1 de 2 veículos receberam pontuação multifator; 1 permaneceram/);
  assert.equal((html.match(/class="vehicle-card /g) || []).length, 2);
  assert.doesNotMatch(html, /Comparação personalizada indisponível/);
});

test("modal não repete indisponibilidade e seleção de simulação não oferece vínculo manual", () => {
  const uno = unavailableItem(2);
  const before = JSON.stringify(uno);
  const html = renderComponent("RecommendationDetails", { item: uno });
  assert.doesNotMatch(html, /Comparação personalizada indisponível|Escolha o veículo correspondente|Simule este veículo/);
  assert.match(html, /Simular outro veículo com cobertura/);
  assert.match(html, /não vincula nem substitui Fiat Uno Attractive/);
  assert.match(html, /Nenhuma correspondência de identidade será salva/);
  assert.match(html, /Detalhamento do TCO mensal|Confiança dos dados/);
  assert.equal(JSON.stringify(uno), before);
  assert.equal(uno.multifactor.final_score, null);
});

test("apresentação mantém Etios pontuado por mapeamento do backend e Uno original sem recalcular", () => {
  const etios = { ...rankedItem(1), vehicle: { id: 1, brand: "Toyota", model: "Etios XLS", year: 2018 },
    monthly_viable: true, tco: { total_monthly_cost: 1642.02 } };
  etios.multifactor.identity_diagnostic = { match_method: "explicit_mapping", expected_identity: { fipe_code: "002150-4", fipe_year_code: "2018-5" } };
  const uno = { ...unavailableItem(2), monthly_viable: true, tco: { total_monthly_cost: 1322.97 } };
  const items = [etios, uno, ...Array.from({ length: 32 }, (_, index) => unavailableItem(index + 3))];
  const before = JSON.stringify(items);
  const page = renderComponent("RecommendationPage", { vehicleType: "car", state: { recommendations: items, metadata: requestedMetadata, hasCalculated: true }, showAll: true });
  assert.match(page, /1 de 34 veículos receberam pontuação multifator; 33 permaneceram/);
  assert.equal((page.match(/data-testid="multifactor-summary"/g) || []).length, 1);
  assert.doesNotMatch(page, /Comparação personalizada indisponível/);
  assert.match(renderComponent("RecommendationDetails", { item: etios }), /Ranking multifator/);
  assert.doesNotMatch(renderComponent("RecommendationDetails", { item: uno }), /Ranking multifator|Comparação personalizada indisponível/);
  assert.equal(JSON.stringify(items), before);
  assert.equal(etios.multifactor.identity_diagnostic.match_method, "explicit_mapping");
  assert.equal(uno.multifactor.identity_diagnostic.rejection_reason, "coverage_absent");
});
