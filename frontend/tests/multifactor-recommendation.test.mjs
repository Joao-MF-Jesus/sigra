import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  MULTIFACTOR_DEFAULT_WEIGHTS,
  buildMultifactorProfile,
  multifactorWeightSummary,
  resetMultifactorWeightFields,
} from "../src/features/recommendations/multifactorRecommendationModel.js";
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
  allow_budget_above_200k: false,
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

test("orçamento acima de 200 mil exige autorização explícita", () => {
  const denied = buildMultifactorProfile(multifactor, 250000);
  assert.equal(denied.isValid, false);
  assert.ok(denied.errors.allow_budget_above_200k);
  assert.equal(buildMultifactorProfile({ ...multifactor, allow_budget_above_200k: true }, 250000).isValid, true);
});

test("pesos são editáveis, normalizados para apresentação e restauráveis", () => {
  const profile = { ...multifactor, weight_total_cost: "1", weight_usage_fit: "1" };
  const summary = multifactorWeightSummary(profile);
  assert.equal(summary.total, 57);
  assert.ok(summary.entries.every((item) => Number.isFinite(item.normalizedPercentage)));
  assert.deepEqual(resetMultifactorWeightFields(profile), Object.fromEntries(Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([code, value]) => [`weight_${code}`, value])));
});

test("frontend coleta parâmetros e exibe explicação sem duplicar fórmula financeira", () => {
  const fields = readFileSync(new URL("../src/features/recommendations/MultifactorProfileFields.jsx", import.meta.url), "utf8");
  const breakdown = readFileSync(new URL("../src/features/recommendations/MultifactorBreakdown.jsx", import.meta.url), "utf8");
  const model = readFileSync(new URL("../src/features/recommendations/multifactorRecommendationModel.js", import.meta.url), "utf8");
  assert.match(fields, /Perfil multifator opcional/);
  assert.match(fields, /Os cálculos financeiros são realizados exclusivamente pelo backend/);
  assert.match(breakdown, /Custo de combustível projetado/);
  assert.match(breakdown, /mixed_1000_v1 é apenas a referência analítica/);
  assert.match(breakdown, /integrated_dataset_version/);
  assert.doesNotMatch(`${fields}\n${model}`, /monthly_fuel_cost|annual_fuel_cost|fuel_cost_per_km/);
});
