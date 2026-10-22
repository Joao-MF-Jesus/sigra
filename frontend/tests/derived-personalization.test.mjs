import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformSync } from "esbuild";
import { MULTIFACTOR_DEFAULT_WEIGHTS, DERIVED_PERSONALIZATION, REFERENCE_PERSONALIZATION, DERIVED_DIMENSIONS, buildMultifactorProfile, multifactorWeightSummary } from "../src/features/recommendations/multifactorRecommendationModel.js";
import { validateCohortRecommendation } from "../src/features/recommendations/cohortRecommendationModel.js";
import { recommendationReview } from "../src/features/recommendations/recommendationWizardModel.js";

const profile = { vehicle_type: "car", use_case: "app", budget: "1000000", monthly_limit: "100000", monthly_mileage: "1000", fuel_price: "6", recommendation_strategy: "cost_benefit",
  multifactor_enabled: true, multifactor_monthly_distance_km: "1000", multifactor_city_percentage: "50", multifactor_highway_percentage: "50",
  multifactor_state_code: "SP", multifactor_reference_week_start: "2026-09-01", multifactor_fuel_strategy: "gasoline_c_common",
  multifactor_price_mode: "manual", multifactor_manual_fuel_price_brl: "6", multifactor_horizon_months: "12",
  ...Object.fromEntries(Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([key, value]) => ["weight_" + key, value])) };
const modules = new Map();
function load(url) {
  if (modules.has(url.href)) return modules.get(url.href).exports;
  const { code } = transformSync(readFileSync(url, "utf8"), { loader: "jsx", format: "cjs", define: { "import.meta.env": "{}" } });
  const module = { exports: {} };
  modules.set(url.href, module);
  const native = createRequire(fileURLToPath(url));
  new Function("require", "module", "exports", code)((name) => name.startsWith(".") ? load(new URL(name, url)) : native(name), module, module.exports);
  return module.exports;
}
function render(name, props) {
  return renderToStaticMarkup(React.createElement(load(new URL("../src/features/recommendations/" + name + ".jsx", import.meta.url)).default, props));
}
test("alternative never silently replaces reference; request selection is explicit", () => {
  assert.equal(buildMultifactorProfile(profile).payload.policy_version, undefined);
  assert.equal(buildMultifactorProfile({ ...profile, multifactor_policy_version: REFERENCE_PERSONALIZATION }).payload.policy_version, undefined);
  const derived = buildMultifactorProfile({ ...profile, multifactor_policy_version: DERIVED_PERSONALIZATION, weight_performance: "0" });
  assert.equal(derived.payload.policy_version, DERIVED_PERSONALIZATION);
  assert.equal(derived.payload.weights.performance, "0");
  assert.equal(derived.payload.weights.total_cost, "25");
  assert.equal(buildMultifactorProfile({ ...profile, multifactor_policy_version: "invented" }).isValid, false);
});
test("method selector is unavailable by default and reference stays selected when enabled", () => {
  const props = { profile, errors: {}, onChange: () => {}, onResetWeights: () => {}, candidateSource: "academic_v6" };
  assert.doesNotMatch(render("MultifactorProfileFields", props), /id="multifactor_policy_version"/);
  const html = render("MultifactorProfileFields", { ...props, alternativeEnabled: true });
  assert.match(html, new RegExp('value="' + REFERENCE_PERSONALIZATION + '" selected'));
  assert.match(html, /Alternativa acadêmica derivada/);
  assert.match(html, /Conforto/);
});
test("stale alternative is rejected but user can explicitly return to reference", () => {
  const html = render("MultifactorProfileFields", { profile: { ...profile, multifactor_policy_version: DERIVED_PERSONALIZATION }, errors: { multifactor_policy_version: "Alternativa desabilitada" }, candidateSource: "academic_v6", alternativeEnabled: false });
  assert.match(html, /id="multifactor_policy_version"/);
  assert.match(html, /aria-invalid="true"/);
  assert.match(html, /Alternativa desabilitada/);
  assert.match(html, new RegExp('value="' + DERIVED_PERSONALIZATION + '" disabled="" selected=""'));
});
test("effective names match the versioned backend contract", () => {
  const contract = JSON.parse(readFileSync(new URL("../../backend/app/academic_cohort/derived_personalization_v1.json", import.meta.url), "utf8"));
  assert.equal(contract.version, DERIVED_PERSONALIZATION);
  assert.equal(contract.enabled_by_default, false);
  assert.deepEqual(Object.fromEntries(Object.entries(DERIVED_DIMENSIONS).map(([key, value]) => [key, value[0]])), Object.fromEntries(Object.entries(contract.dimensions).map(([key, value]) => [key, value.label])));
});
test("all seven effective names reflect actual evidence, not original unsupported assessments", () => {
  const derived = { ...profile, multifactor_policy_version: DERIVED_PERSONALIZATION };
  const summary = multifactorWeightSummary(derived);
  assert.deepEqual(summary.entries.map((r) => r.label), Object.values(DERIVED_DIMENSIONS).map((r) => r[0]));
  const html = render("MultifactorProfileFields", { profile: derived, errors: {}, alternativeEnabled: true, candidateSource: "academic_v6" });
  assert.match(html, /não é avaliação de conforto/);
  assert.match(html, /não é avaliação rodoviária/);
  assert.match(html, /não comprova confiabilidade/);
  assert.match(html, /não são independentes/);
  assert.match(html, /peso zero exclui explicitamente/);
});
test("client refuses stale disabled alternative and never changes weights automatically", () => {
  const derived = { ...profile, multifactor_policy_version: DERIVED_PERSONALIZATION };
  const metadata = { strategies: ["cost_benefit", "lowest_cost"], snapshot_id: "00000000-0000-0000-0000-000000000060", profiles: { app: { weights: { urban_fuel: "0.35", passenger_space: "0.25", cargo: "0.20", price: "0.20" } } } };
  assert.equal(validateCohortRecommendation(derived, metadata).isValid, false);
  const result = validateCohortRecommendation(derived, { ...metadata, alternative_personalization: { available: true } });
  assert.equal(result.isValid, true);
  assert.equal(result.payload.multifactor_profile.policy_version, DERIVED_PERSONALIZATION);
  assert.equal(result.payload.multifactor_profile.weights.safety, "15");
});
test("review explicitly identifies alternative without announcing success", () => {
  const text = recommendationReview({ ...profile, multifactor_policy_version: DERIVED_PERSONALIZATION }).at(-1)[1];
  assert.match(text, /Solicitado.*alternativa acadêmica derivada v1/);
  assert.doesNotMatch(text, /Ativado|aprovado/);
});
test("modal distinguishes unknown from explicit absence, zero exclusion and methodological dependence", () => {
  // Fictitious presentation fixture, not a catalogue or production score.
  const html = render("SevenCriteriaBreakdown", { breakdown: { version: DERIVED_PERSONALIZATION, final_score: null, calculated_requested_count: 5, requested_count: 6,
    dependencies: ["fuel overlap", "scenario price"], excluded_dimensions: [{ label: "Relação massa/potência com gasolina" }],
    criteria: [{ criterion: "safety", label: DERIVED_DIMENSIONS.safety[0], requested: true, available: false, normalized_weight_percentage: "15", raw_score: null, contribution: null, limitation: "test limitation", requirement_message: "Falta quantidade de airbags.",
      inputs_used: { esc: { label: "ESC comprovadamente ausente", value: false, unit: "bool", nature: "observed" }, airbags: { label: "Airbags", value: null, unit: "count", nature: "unavailable" } } }] } });
  assert.match(html, /alternativa acadêmica derivada v1/);
  assert.match(html, /não são duas evidências independentes/);
  assert.match(html, /excluídas explicitamente por peso zero/);
  assert.match(html, /Não avaliada/);
  assert.match(html, /Não informado/);
  assert.match(html, />Não · evidência observada/);
  assert.match(html, /Não é teste de colisão/);
  assert.doesNotMatch(html, /nota neutra|50\/100/);
});

test("performance details show fuel, documented mass definition and capture limitation without exposing hashes", () => {
  const html = render("SevenCriteriaBreakdown", { breakdown: { version: DERIVED_PERSONALIZATION,
    final_score: "80", calculated_requested_count: 7, requested_count: 7, criteria: [{
      criterion: "performance", label: DERIVED_DIMENSIONS.performance[0], available: true,
      value: "9.653846153846", unit: "kg/cv",
      raw_score: "70", contribution: "7", normalized_weight_percentage: "10",
      inputs_used: { weight_kg: { label: "Massa da versão", value: "1255", unit: "kg", nature: "observed",
        supplementary_evidence: { representation: "normalized_public_document_reader_capture", manifest_sha256: "private-technical-hash" } },
        power_gasoline_cv: { label: "Potência com gasolina", value: "130", unit: "cv", nature: "observed" } }
    }] } });
  assert.match(html, /ordem de marcha/);
  assert.match(html, /potência nominal com gasolina/);
  assert.match(html, /não é aceleração medida/);
  assert.match(html, /9,65 kg\/cv/);
  assert.match(html, /PDF original teve acesso bloqueado/);
  assert.doesNotMatch(html, /private-technical-hash/);
});

test("unknown exact-version mass remains a visible blocker, not a fabricated score", () => {
  const html = render("SevenCriteriaBreakdown", { breakdown: { version: DERIVED_PERSONALIZATION,
    final_score: null, calculated_requested_count: 6, requested_count: 7, criteria: [{
      criterion: "performance", label: DERIVED_DIMENSIONS.performance[0], available: false, requested: true,
      requirement_message: "Falta massa em ordem de marcha comprovada para o Focus Fastback SE Plus 2018.",
      inputs_used: { weight_kg: { label: "Massa da versão", value: null, unit: "kg", nature: "unavailable" } }
    }] } });
  assert.match(html, /Focus Fastback SE Plus 2018/);
  assert.match(html, /6 de 7/);
  assert.match(html, /Não avaliada/);
  assert.doesNotMatch(html, /50\/100/);
});
