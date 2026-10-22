import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformSync } from "esbuild";
import { validateCohortRecommendation } from "../src/features/recommendations/cohortRecommendationModel.js";
import { MULTIFACTOR_DEFAULT_WEIGHTS } from "../src/features/recommendations/multifactorRecommendationModel.js";
import { readableValue, referenceMonth, cohortCoverage, criterionCoverage, exclusionExplanation } from "../src/features/recommendations/cohortPresentation.js";
import { recommendationReview } from "../src/features/recommendations/recommendationWizardModel.js";
import { formatCurrency, formatScore } from "../src/features/recommendations/recommendationModel.js";
const read = (path) => readFileSync(new URL("../src/" + path, import.meta.url), "utf8");
const metadata = { strategies: ["cost_benefit", "lowest_cost"], snapshot_id: "a35ad2e1-9b70-4f7a-adf6-5ad001a13dc4", profiles: { app: { weights: { urban_fuel: "0.35", passenger_space: "0.25", cargo: "0.20", price: "0.20" } } } };
const profile = { vehicle_type: "car", use_case: "app", budget: "200000", monthly_limit: "10000", monthly_mileage: "1000", fuel_price: "6", recommendation_strategy: "cost_benefit", multifactor_enabled: true,
  multifactor_monthly_distance_km: "1500", multifactor_city_percentage: "25", multifactor_highway_percentage: "75", multifactor_state_code: "SP", multifactor_municipality: "Campinas", multifactor_reference_week_start: "2026-09-01", multifactor_fuel_strategy: "gasoline_c_common", multifactor_price_mode: "manual", multifactor_manual_fuel_price_brl: "6.5", multifactor_horizon_months: "24", multifactor_city_consumption_km_l: "", multifactor_highway_consumption_km_l: "", ...Object.fromEntries(Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([key, value]) => ["weight_" + key, value])) };
test("original controls send the seven original weights and the full scenario to the cohort", () => {
  const result = validateCohortRecommendation(profile, metadata);
  assert.equal(result.isValid, true);
  assert.deepEqual(result.payload.multifactor_profile.weights, MULTIFACTOR_DEFAULT_WEIGHTS);
  assert.equal(result.payload.multifactor_profile.scenario.monthly_distance_km, "1500");
  assert.equal(result.payload.multifactor_profile.scenario.city_percentage, "25");
  assert.equal(result.payload.multifactor_profile.scenario.manual_fuel_price_brl, "6.5");
  assert.equal(result.payload.multifactor_profile.scenario.horizon_months, 24);
  assert.equal(result.payload.multifactor_profile.scenario.municipality, "Campinas");
});
test("toggle off preserves baseline and does not send personalized controls", () => {
  const result = validateCohortRecommendation({ ...profile, multifactor_enabled: false }, metadata);
  assert.equal(result.isValid, true);
  assert.equal(result.payload.multifactor_profile, undefined);
});
test("invalid route percentages and original weights fail closed", () => {
  assert.equal(validateCohortRecommendation({ ...profile, multifactor_city_percentage: "100" }, metadata).isValid, false);
  assert.equal(validateCohortRecommendation({ ...profile, weight_safety: "-1" }, metadata).isValid, false);
});
test("currency, units and absent values are presented in Portuguese without fabricated zero", () => {
  assert.match(readableValue({ value: "1477.96", unit: "BRL/month" }), /R\$\s1\.477,96\/mês/);
  assert.equal(readableValue({ value: "10.8", unit: "km/l" }), "10,8 km/l");
  assert.equal(readableValue({ value: "1750", unit: "mm" }), "1.750 mm");
  assert.equal(readableValue({ value: "7.52", unit: "m2" }), "7,52 m²");
  assert.equal(readableValue({ value: null, unit: "count" }), "Não informado");
  assert.equal(formatCurrency(null), "Não informado");
  assert.equal(formatScore(null), "Não informado");
  assert.equal(referenceMonth("2026-09"), "setembro de 2026");
});
test("coverage does not claim personalization when no final score exists", () => {
  assert.deepEqual(cohortCoverage([{ multifactor: { status: "unavailable", final_score: null } }, { multifactor: { status: "ranked", final_score: "60" } }]), { scored: 1, original: 1 });
});
test("same form, cards and modal classes are reused without academic report UI", () => {
  const form = read("features/recommendations/RecommendationForm.jsx");
  const results = read("features/recommendations/CohortRecommendationResults.jsx");
  const details = read("features/recommendations/CohortVehicleDetails.jsx");
  assert.match(form, /<MultifactorProfileFields/);
  assert.doesNotMatch(form, /<CohortPreferenceFields/);
  const renderedForm = render("RecommendationForm", { profile, errors: {}, loading: false, candidateMetadata: { candidate_source: "operational" }, onChange() {}, onSubmit() {}, onResetMultifactorWeights() {} });
  for (const strategy of ["lowest_cost", "budget_economy", "cost_benefit", "balanced", "comfort_space", "best_within_budget"]) assert.match(renderedForm, new RegExp(`value="${strategy}"`));
  assert.match(results, /<RecommendationResults/);
  assert.match(results, /<RecommendationDetails/);
  assert.doesNotMatch(results, /AcademicCard|AcademicDetail|academic-hash/);
  assert.match(details, /className="details-modal"/);
  assert.match(details, /className="modal-body"/);
  assert.match(details, /Fontes e metodologia/);
  assert.doesNotMatch(details, /sha256|contract_version|formula|timestamp|IDs internos|Comparação personalizada indisponível/);
});

const modules = new Map();
function loadComponentModule(url) {
  if (modules.has(url.href)) return modules.get(url.href).exports;
  const { code } = transformSync(readFileSync(url, "utf8"), { loader: "jsx", format: "cjs", define: { "import.meta.env": "{}" } });
  const module = { exports: {} };
  modules.set(url.href, module);
  const nativeRequire = createRequire(fileURLToPath(url));
  new Function("require", "module", "exports", code)((name) => name.startsWith(".") ? loadComponentModule(new URL(name, url)) : nativeRequire(name), module, module.exports);
  return module.exports;
}
function render(name, props) {
  const component = loadComponentModule(new URL(`../src/features/recommendations/${name}.jsx`, import.meta.url)).default;
  return renderToStaticMarkup(React.createElement(component, props));
}
const presentationItem = { vehicle: { label: "Veículo de teste 2020", catalog_id: 9999, identity_namespace: "academic_v6", operational_vehicle_id: null, purchase_price_brl: "44003", price_reference_month: "2026-09", technical_fields: { consumption_city: { value: "10.8", unit: "km/l" }, cargo_l: { value: "300", unit: "l" } } }, score: "62", monthly_total_cost: "1477.96", baseline_score: "62", explanations: [{ criterion: "price", contribution: "12" }], evaluation: { coverage: { weighted: "0.75" }, scenario_costs: { components: { fuel: { value: "500", unit: "BRL/month" } } } }, multifactor: { status: "unavailable", final_score: null }, detailState: { data: { evidence: { fields: { width_mm: { value: "1750", unit: "mm", sources: [{ provider: "carpedia", sha256: "secret-source-hash", locator: "raw-path" }] } } } } } };
test("rendered card preserves the original layout and hides technical metadata and unrelated operations", () => {
  const html = render("VehicleCard", { item: presentationItem, index: 0, onDetails: () => {} });
  assert.match(html, /vehicle-card/);
  assert.match(html, /1\.477,96\/mês/);
  assert.match(html, /setembro de 2026/);
  assert.match(html, /10,8 km\/l/);
  assert.doesNotMatch(html, /secret-source-hash|9999|raw-path|Meu carro|>Peças<|>Comparar</);
});
test("rendered details retain costs, readable units and collapsed provenance without identity warnings", () => {
  const html = render("CohortVehicleDetails", { item: presentationItem, onClose: () => {} });
  assert.match(html, /details-modal/);
  assert.match(html, /1\.750 mm/);
  assert.match(html, /1\.477,96\/mês/);
  assert.match(html, /<details[^>]*><summary>Fontes e metodologia/);
  assert.doesNotMatch(html, /secret-source-hash|raw-path|9999|Comparação personalizada indisponível|<details[^>]*open/);
  const absent = render("CohortVehicleDetails", { item: { ...presentationItem, evaluation: { ...presentationItem.evaluation, coverage: null } }, onClose: () => {} });
  assert.match(absent, /Cobertura da personalização<\/span><strong>Não informado/);
});

test("requested coverage distinguishes five missing notes from full reference profile coverage", () => {
  const item = { ...presentationItem, multifactor: { ...presentationItem.multifactor,
    evidence_coverage: { weighted: "0.35", requested_count: 7, evaluated_count: 2,
      criteria: [{ criterion: "comfort", label: "Conforto", requested: true, available: false },
        { criterion: "safety", label: "Segurança", requested: false, available: false }] } } };
  assert.deepEqual(criterionCoverage(item), { label: "Cobertura da personalização", value: 35, missingLabels: ["Conforto"] });
  assert.match(render("VehicleCard", { item, index: 0 }), /Cobertura da personalização<\/span><strong>35 %/);
  const detail = render("CohortVehicleDetails", { item, onClose: () => {} });
  assert.match(detail, /Critérios solicitados sem avaliação: Conforto/);
  assert.doesNotMatch(detail, /Critérios solicitados sem avaliação: Conforto, Segurança/);
  assert.equal(criterionCoverage({ ...item, multifactor: null }).value, 75);
});
test("requesting personalization is never described as successful activation", () => {
  const text = recommendationReview(profile).find(([label]) => label === "Perfil multifator")[1];
  assert.match(text, /Solicitado.*evidências/);
  assert.doesNotMatch(text, /Ativado/);
});
test("documentary missing field is explained separately from monthly budget", () => {
  const text = exclusionExplanation({ reasons: ["PROFILE_DOCUMENTARY_REQUIREMENTS", "MONTHLY_BUDGET"],
    documentary_diagnostic: { message: "Falta comprovação de largura com os retrovisores abertos para este perfil." } });
  assert.match(text, /retrovisores abertos/);
  assert.match(text, /custo acima do limite mensal/);
  assert.doesNotMatch(text, /evidência obrigatória do perfil indisponível/);
});
test("one consolidated missing-criteria explanation, no activation or repeated card alert", () => {
  const missing = ["Adequação ao uso", "Conforto", "Segurança", "Desempenho rodoviário", "Qualidade histórica"];
  const item = { ...presentationItem, comparison_group: "same", multifactor: { ...presentationItem.multifactor,
    evidence_coverage: { weighted: "0.35", criteria: missing.map((label) => ({ label, requested: true, available: false })) } } };
  const html = render("CohortRecommendationResults", { state: { recommendations: [item], loading: false,
    metadata: { candidate_source: "academic_v6", considered_count: 60, documentary_eligible_count: 10, eligible_count: 1,
      multifactor_profile: { enabled: true, missing_criteria: missing.map((label) => ({ label, affected_result_count: 1 })) } } }, profile });
  assert.equal((html.match(/data-testid="multifactor-summary"/g) || []).length, 1);
  assert.match(html, /0 veículos pontuados; 1 na ordem de referência/);
  assert.match(html, /Conforto \(1 veículos\)/);
  assert.doesNotMatch(html, /Personalização aplicada|Comparação personalizada indisponível/);
});

test("precise missing inputs remain in collapsed methodology, without invented historical quality", () => {
  const message = "Manutenção e desvalorização são calculáveis no cenário; faltam confiabilidade histórica e disponibilidade comprovada de peças.";
  const item = { ...presentationItem, multifactor: { ...presentationItem.multifactor,
    evidence_coverage: { weighted: "0.35", criteria: [
      { criterion: "legacy_quality", label: "Qualidade histórica", requested: true, available: false, requirement_message: message },
      { criterion: "comfort", label: "Conforto", requested: false, available: false, requirement_message: "Não solicitado" },
    ] } } };
  const html = render("CohortVehicleDetails", { item, onClose: () => {} });
  assert.match(html, /<details[^>]*><summary>Fontes e metodologia<\/summary>/);
  assert.match(html, /aria-label="Entradas necessárias à personalização"/);
  assert.match(html, /faltam confiabilidade histórica e disponibilidade comprovada de peças/);
  assert.doesNotMatch(html, /<details[^>]* open|Não solicitado|Comparação personalizada indisponível|quality_complete|maintenance_score/);
});
