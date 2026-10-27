import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformSync } from "esbuild";
import { buildMultifactorProfile, selectDerivedConfiguration, updatePersonalizationProfile, resetMultifactorWeightFields, DERIVED_PERSONALIZATION, DERIVED_BASE_CONFIGURATION as BASE, DERIVED_EXPANDED_CONFIGURATION as EXPANDED, MULTIFACTOR_DEFAULT_WEIGHTS } from "../src/features/recommendations/multifactorRecommendationModel.js";
import { validateCohortRecommendation } from "../src/features/recommendations/cohortRecommendationModel.js";
import { recommendationReview } from "../src/features/recommendations/recommendationWizardModel.js";
import { requestRecommendations } from "../src/api/sigraApi.js";

const registry = JSON.parse(readFileSync(new URL("../../backend/app/academic_cohort/derived_configurations_v1.json", import.meta.url), "utf8"));
const original = { vehicle_type: "car", use_case: "app", budget: "1000000", monthly_limit: "100000", monthly_mileage: "1000", fuel_price: "6", recommendation_strategy: "cost_benefit", cost_scenario: "base",
  multifactor_enabled: true, multifactor_policy_version: DERIVED_PERSONALIZATION, multifactor_monthly_distance_km: "1000", multifactor_city_percentage: "50", multifactor_highway_percentage: "50", multifactor_state_code: "SP", multifactor_reference_week_start: "2026-09-01", multifactor_fuel_strategy: "gasoline_c_common", multifactor_price_mode: "manual", multifactor_manual_fuel_price_brl: "6", multifactor_horizon_months: "12", ...Object.fromEntries(Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([k,v]) => ["weight_"+k,v])) };
const metadata = { candidate_source: "academic_v6", strategies: ["cost_benefit", "lowest_cost"], snapshot_id: "00000000-0000-0000-0000-000000000060", profiles: Object.fromEntries(["cidade","app","trabalho","suv","familia","estrada"].map((key) => [key,{weights:{price:"1"}}])), alternative_personalization: { available: true, configuration_registry: registry } };
const modules = new Map();
function load(url) {
  if (modules.has(url.href)) return modules.get(url.href).exports;
  const { code } = transformSync(readFileSync(url,"utf8"),{loader:"jsx",format:"cjs",define:{"import.meta.env":"{}"}});
  const module = {exports:{}}; modules.set(url.href,module);
  const native = createRequire(fileURLToPath(url));
  new Function("require","module","exports",code)((name) => name.startsWith(".") ? load(new URL(name,url)) : native(name),module,module.exports);
  return module.exports;
}
function render(relative, props, named="default") { return renderToStaticMarkup(React.createElement(load(new URL("../src/features/"+relative,import.meta.url))[named],props)); }

test("no preset is selected from profile or missing evidence", () => {
  assert.equal(validateCohortRecommendation(original,metadata).isValid,false);
  assert.match(validateCohortRecommendation(original,metadata).errors.multifactor_configuration_id,/explicitamente/);
  assert.equal(original.weight_safety,"15");
  const html = render("recommendations/MultifactorProfileFields.jsx",{profile:original,errors:{},candidateSource:"academic_v6",alternativeEnabled:true,configurationRegistry:registry});
  assert.match(html, /value="" selected=""/);
  assert.match(html, /proposta para este perfil/);
  assert.match(html, /opção explícita/);
  assert.match(html, /class="multifactor-grid" data-testid="derived-configuration-control"/);
  assert.match(html, /<div class="multifactor-field"><label class="field-label" for="multifactor_configuration_id">/);
});
test("preset is uniformly applied only by explicit selection and transported with zeros", async () => {
  const before = structuredClone(original);
  for (const id of [BASE,EXPANDED]) {
    const profile = selectDerivedConfiguration(original,id,registry);
    const validation = validateCohortRecommendation(profile,metadata);
    assert.equal(validation.isValid,true);
    const result = validation.payload.multifactor_profile;
    assert.equal(result.configuration_id,id);
    assert.deepEqual(result.weights,registry.configurations[id].weights);
    await requestRecommendations(validation.payload,{recordTest:true,fetchImpl:async (url,options) => {
      assert.match(url,/test-runs\/recommendation$/);
      assert.deepEqual(JSON.parse(options.body).multifactor_profile,result);
      return {ok:true,json:async()=>({recommendations:[]})};
    }});
  }
  assert.deepEqual(original,before);
});
test("switching profiles preserves selected configuration and explicit adjustments", () => {
  const base = selectDerivedConfiguration(original,BASE,registry);
  const changed = updatePersonalizationProfile(base,"weight_performance","5",registry);
  for (const use of ["cidade","app","trabalho","suv","familia","estrada"]) {
    const moved = updatePersonalizationProfile(changed,"use_case",use,registry);
    assert.equal(moved.multifactor_configuration_id,BASE);
    assert.equal(moved.weight_performance,"5");
    assert.equal(moved.weight_safety,"0");
    assert.equal(buildMultifactorProfile(moved).payload.weights.performance,"5");
  }
});
test("restoring weights restores selected preset, not silent seven-weight fallback", () => {
  const base = selectDerivedConfiguration(original,BASE,registry);
  assert.deepEqual(resetMultifactorWeightFields({...base,weight_safety:"20"},registry),Object.fromEntries(Object.entries(registry.configurations[BASE].weights).map(([k,v])=>["weight_"+k,v])));
  assert.throws(()=>selectDerivedConfiguration(original,"invented",registry));
  assert.throws(()=>selectDerivedConfiguration(original,BASE,null));
  assert.equal(updatePersonalizationProfile(base,"multifactor_policy_version","user-profile-multifactor-v1",registry).multifactor_configuration_id,"");
});
test("preset selection rejects nonfinite and out-of-range server vectors", () => {
  for (const value of ["NaN", "Infinity", "-1", "101"]) {
    const invalid = structuredClone(registry);
    invalid.configurations[BASE].weights.performance = value;
    assert.throws(() => selectDerivedConfiguration(original, BASE, invalid));
  }
});
test("equivalent decimal representations are not reported as adjusted weights", () => {
  const profile = selectDerivedConfiguration(original, EXPANDED, registry);
  const html = render("recommendations/MultifactorProfileFields.jsx", {
    profile: { ...profile, weight_total_cost: "25.0000" }, errors: {},
    candidateSource: "academic_v6", alternativeEnabled: true, configurationRegistry: registry,
  });
  assert.match(html, /Vetor fixo da configuração selecionada/);
  assert.doesNotMatch(html, /Pesos ajustados explicitamente/);
});
test("summary and review distinguish actual metrics, adjusted weights and incomparable scores", () => {
  const base = selectDerivedConfiguration(original,BASE,registry);
  const props = {profile:{...base,weight_performance:"5"},errors:{},candidateSource:"academic_v6",alternativeEnabled:true,configurationRegistry:registry};
  const html = render("recommendations/MultifactorProfileFields.jsx",props);
  assert.match(html,/Base — cinco dimensões/);
  assert.match(html,/Pesos ajustados explicitamente/);
  assert.match(html,/não os requisitos documentais/);
  assert.match(html,/não devem ser comparadas diretamente/);
  assert.match(html,/step="0.0001"/);
  assert.match(recommendationReview(base).at(-1)[1],/Base — cinco dimensões/);
});
test("results details and stored history identify the exact server configuration without rerunning", () => {
  const configuration = {configuration_id:BASE,label:registry.configurations[BASE].label,comparison_warning:registry.comparison_warning,weights_adjusted:true};
  const result = {multifactor_profile:{configuration},recommendations:[]};
  const history = render("session/TestHistory.jsx",{run:{id:"test-only",kind:"recommendation",created_at:"2026-10-09T00:00:00Z",presented_results:result,parameters:{multifactor_profile:{configuration_id:BASE}},system_version:"test",method_version:DERIVED_PERSONALIZATION}},"StoredResult");
  assert.match(history,/Configuração registrada: Base/);
  assert.match(history,/não um novo cálculo/);
  assert.match(history,/Pesos ajustados explicitamente/);
  const html = render("recommendations/SevenCriteriaBreakdown.jsx",{breakdown:{configuration,final_score:null,requested_count:7,calculated_requested_count:6,criteria:[{criterion:"performance",label:"Relação massa\/potência",requested:true,available:false,requirement_message:"Falta massa em ordem de marcha comprovada para o Focus Fastback SE Plus 2018.",inputs_used:{}}]}});
  assert.match(html,/Focus Fastback SE Plus 2018/);
  assert.match(html,/Não avaliada/);
  assert.doesNotMatch(html,/0\/100/);
});

test("criterion details distinguish entered weights from their normalized percentages", () => {
  const breakdown = {final_score:40,requested_count:1,calculated_requested_count:1,criteria:[{
    criterion:"comfort",label:"Capacidade do porta-malas",requested:true,available:true,
    input_weight:"25",normalized_weight_percentage:"50",raw_score:"80",contribution:"40",inputs_used:{},
  }]};
  const html = render("recommendations/SevenCriteriaBreakdown.jsx",{breakdown});
  assert.match(html,/<dt>Peso informado<\/dt><dd>25<\/dd>/);
  assert.match(html,/<dt>Peso efetivo normalizado<\/dt><dd>50 %<\/dd>/);
  assert.doesNotMatch(html,/Peso solicitado/);
  const historical = structuredClone(breakdown);
  delete historical.criteria[0].input_weight;
  const old = render("recommendations/SevenCriteriaBreakdown.jsx",{breakdown:historical});
  assert.doesNotMatch(old,/Peso informado/); // No reconstructed historical input.
  assert.match(old,/Peso efetivo normalizado/);
});

test("stored history exposes the actual choices saved before ranking without participant identifiers", () => {
  const run = {id:"synthetic-history-only",kind:"recommendation",created_at:"2026-10-10T00:00:00Z",
    presented_results:{recommendations:[]},parameters:{use_case:"app"},system_version:"test",method_version:"test",
    study_session:{id:"must-not-be-displayed-session-id",scenario_id:"C",familiarity:"medium",
      priorities:["total_cost","usage_fit","efficiency"]}};
  const html = render("session/TestHistory.jsx",{run},"StoredResult");
  assert.match(html, /Escolhas registradas antes do resultado/);
  assert.match(html, /Cenário do roteiro<\/dt><dd>C<\/dd>/);
  assert.match(html, /Familiaridade com veículos<\/dt><dd>Média<\/dd>/);
  assert.match(html, /Custo no cenário/);
  assert.match(html, /Adequação ao uso/);
  assert.match(html, /Economia e eficiência/);
  assert.doesNotMatch(html, /must-not-be-displayed-session-id/);
  assert.match(html, /não substituem os pesos/);
  const empty = render("session/TestHistory.jsx",{run:{...run,study_session:{...run.study_session,priorities:[]}}},"StoredResult");
  assert.match(empty, /Nenhuma prioridade declarada/);
  const legacy = render("session/TestHistory.jsx",{run:{...run,study_session:null}},"StoredResult");
  assert.doesNotMatch(legacy, /Escolhas registradas antes do resultado/);
});

test("missing derived inputs are not described as missing original assessments", () => {
  for (const [policy, expected, rejected] of [
    [DERIVED_PERSONALIZATION,"dados necessários às métricas derivadas","notas comprovadas do método original"],
    ["user-profile-multifactor-v1","notas comprovadas do método original","dados necessários às métricas derivadas"],
  ]) {
    const html = render("recommendations/CohortRecommendationResults.jsx",{
      state:{status:"success",recommendations:[],metadata:{multifactor_profile:{enabled:true,policy_version:policy,
        missing_criteria:[{label:"Massa documentada",affected_result_count:1}]}}},
    });
    assert.ok(html.includes(expected));
    assert.ok(!html.includes(rejected));
    assert.match(html,/Classificação de referência preservada/);
    assert.match(html,/sem redistribuir pesos ausentes/);
  }
});
