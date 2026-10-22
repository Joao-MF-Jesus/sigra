import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { cohortWeights, validateCohortRecommendation } from "../src/features/recommendations/cohortRecommendationModel.js";
import { requestRecommendations, requestRecommendationMetadata } from "../src/api/sigraApi.js";
import { firstStepWithError } from "../src/features/recommendations/recommendationWizardModel.js";
import { FIELD_LABELS } from "../src/features/academic/academicModel.js";

const metadata = { candidate_source: "academic_v6", strategies: ["cost_benefit", "lowest_cost"], snapshot_id: "a35ad2e1-9b70-4f7a-adf6-5ad001a13dc4", profiles: {
  app: { weights: { urban_fuel: "0.35", passenger_space: "0.25", cargo: "0.20", price: "0.20" } },
  familia: { weights: { seats: "0.2", cargo: "0.25", safety: "0.35", price: "0.2" } },
} };
const profile = { vehicle_type: "car", use_case: "app", budget: "200000", monthly_limit: "5000",
  monthly_mileage: "1000", fuel_price: "6", recommendation_strategy: "cost_benefit", multifactor_enabled: false };

test("footprint never labels mirror envelope as body width", () => {
  assert.equal(FIELD_LABELS.footprint, "Área externa com espelhos");
  assert.equal(FIELD_LABELS.width_mm, "Largura da carroceria");
});

test("main recommendation sends explicit cohort namespace and every live input, never Gold simulation", async () => {
  const validation = validateCohortRecommendation(profile, metadata);
  assert.equal(validation.isValid, true);
  assert.equal(validation.payload.candidate_source, "academic_v6");
  assert.equal(validation.payload.academic_options.scenario, "base");
  assert.equal(validation.payload.monthly_mileage, 1000);
  assert.equal(validation.payload.fuel_price, 6);
  assert.equal(validation.payload.multifactor_profile, undefined);
  let captured;
  const data = await requestRecommendations(validation.payload, { fetchImpl: async (url, options) => {
    captured = { url, body: JSON.parse(options.body) };
    return { ok: true, json: async () => ({ candidate_source: "academic_v6", recommendations: [], eligible_count: 0 }) };
  } });
  assert.match(captured.url, /\/recommendations\?envelope=true$/);
  assert.deepEqual(captured.body, validation.payload);
  assert.equal(data.eligible_count, 0);
});

test("weights and scenario are user inputs and remain per profile", () => {
  const changed = { ...profile, cost_scenario: "high", cohort_weights: { app: { urban_fuel: 0, passenger_space: 0, cargo: 0, price: 1 } } };
  const payload = validateCohortRecommendation(changed, metadata).payload;
  assert.equal(payload.academic_options.scenario, "high");
  assert.equal(payload.academic_options.criterion_weights.price, 1);
  assert.deepEqual(cohortWeights({ ...changed, use_case: "familia" }, metadata), metadata.profiles.familia.weights);
});

for (const [label, patch] of [
  ["zero mileage", { monthly_mileage: 0 }], ["negative budget", { budget: -1 }],
  ["missing fuel", { fuel_price: "" }], ["unsupported legacy priority", { recommendation_strategy: "comfort_space" }],
  ["unknown scenario", { cost_scenario: "observed" }],
  ["all zero weights", { cohort_weights: { app: { urban_fuel: 0, passenger_space: 0, cargo: 0, price: 0 } } }],
  ["negative weight", { cohort_weights: { app: { price: -1 } } }],
]) test(label + " is rejected, not silently ignored", () => {
  assert.equal(validateCohortRecommendation({ ...profile, ...patch }, metadata).isValid, false);
});

test("source metadata comes from the backend, not public vehicles or an academic-tab flag", async () => {
  let url;
  assert.deepEqual(await requestRecommendationMetadata({ fetchImpl: async (value) => {
    url = value; return { ok: true, json: async () => metadata };
  } }), metadata);
  assert.match(url, /\/recommendations\/metadata$/);
});

test("cohort validation points to the correct wizard steps", () => {
  assert.equal(firstStepWithError({ cohort_weights: "invalid" }), 3);
  assert.equal(firstStepWithError({ cost_scenario: "invalid" }), 2);
});

test("main UI integrates the motor, removes academic navigation and isolates operational IDs", () => {
  const read = (path) => readFileSync(new URL("../src/" + path, import.meta.url), "utf8");
  const app = read("App.jsx"), header = read("AppHeader.jsx");
  const results = read("features/recommendations/CohortRecommendationResults.jsx");
  assert.doesNotMatch(header, /nav-academic|Teste acadêmico/);
  assert.match(app, /validateCohortRecommendation/);
  assert.match(app, /requestRecommendations\(validation.payload/);
  assert.match(app, /recommendationAbortController.current\?\.abort\(\)/);
  assert.doesNotMatch(app, /Dados carregados da base demonstrativa/);
  assert.match(app, /Cadastro operacional carregado/);
  assert.match(results, /RecommendationDetails item=\{\{ \.\.\.detail.item/);
  assert.match(results, /result.snapshot_id/);
  assert.match(results, /Custos estimados para sua rotina/);
  assert.match(results, /documentary_eligible_count/);
  assert.doesNotMatch(results, /onCompare|onParts|\/expenses|\/user-vehicles|requestAcademicEvaluation/);
});
