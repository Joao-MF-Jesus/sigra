import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformSync } from "esbuild";
import { recommendationPriorityOptions, unavailablePriorityMessage } from "../src/features/recommendations/recommendationPriorityModel.js";
import { validateCohortRecommendation } from "../src/features/recommendations/cohortRecommendationModel.js";

const profile = { vehicle_type: "car", budget: "70000", monthly_limit: "1800", use_case: "cidade",
  recommendation_strategy: "cost_benefit", monthly_mileage: "1000", fuel_price: "6", multifactor_enabled: false };
const metadata = { candidate_source: "academic_v6", snapshot_id: "00000000-0000-0000-0000-000000000060",
  strategies: ["cost_benefit", "lowest_cost"], profiles: { cidade: { weights: { price: "1" } } } };
const modules = new Map();
function load(url) {
  // SSR reads JSON as data; CSS is exercised by the real browser suite.
  if (url.pathname.endsWith(".json")) return JSON.parse(readFileSync(url, "utf8"));
  if (url.pathname.endsWith(".css")) { readFileSync(url, "utf8"); return {}; }
  if (modules.has(url.href)) return modules.get(url.href).exports;
  const { code } = transformSync(readFileSync(url, "utf8"), { loader: "jsx", format: "cjs", define: { "import.meta.env": "{}" } });
  const module = { exports: {} }; modules.set(url.href, module);
  const native = createRequire(fileURLToPath(url));
  new Function("require", "module", "exports", code)((name) => name.startsWith(".") ? load(new URL(name, url)) : native(name), module, module.exports);
  return module.exports;
}
function render(selected, source = metadata) {
  const Form = load(new URL("../src/features/recommendations/RecommendationForm.jsx", import.meta.url)).default;
  return renderToStaticMarkup(React.createElement(Form, { profile: { ...profile, recommendation_strategy: selected },
    candidateMetadata: source, errors: {}, loading: false, onChange() {}, onSubmit() {}, onResetMultifactorWeights() {} }));
}

test("server metadata determines which cohort priorities are available", () => {
  const options = recommendationPriorityOptions(metadata);
  assert.deepEqual(options.filter((row) => row.available).map((row) => row.value), ["lowest_cost", "cost_benefit"]);
  assert.equal(recommendationPriorityOptions({ ...metadata, strategies: ["lowest_cost"] }).filter((r) => r.available).length, 1);
  assert.equal(recommendationPriorityOptions({ candidate_source: "operational" }).filter((r) => r.available).length, 6);
});

for (const strategy of ["balanced", "comfort_space", "budget_economy", "best_within_budget"]) {
  test(`unavailable ${strategy} is preserved and rejected, never replaced`, () => {
    const original = { ...profile, recommendation_strategy: strategy };
    const before = structuredClone(original);
    const result = validateCohortRecommendation(original, metadata);
    assert.equal(result.isValid, false);
    assert.equal(result.payload.recommendation_strategy, strategy);
    assert.match(result.errors.recommendation_strategy, /indisponível/);
    assert.match(result.errors.recommendation_strategy, /Escolha explicitamente/);
    assert.match(result.errors.recommendation_strategy, /Nenhuma prioridade alternativa foi aplicada/);
    assert.deepEqual(original, before);
  });
}

test("missing or empty capabilities fail closed, never assume a priority works", () => {
  for (const strategies of [undefined, [], "cost_benefit"]) {
    const source = { ...metadata, strategies };
    assert.equal(validateCohortRecommendation(profile, source).isValid, false);
    assert.equal(recommendationPriorityOptions(source).some((r) => r.available), false);
  }
  assert.match(unavailablePriorityMessage("cost_benefit", { ...metadata, strategies: undefined }), /ainda não confirmou/);
});

test("supported priorities remain explicit in payload for every scenario", () => {
  for (const strategy of metadata.strategies) for (const scenario of ["low", "base", "high"]) {
    const result = validateCohortRecommendation({ ...profile, recommendation_strategy: strategy, cost_scenario: scenario }, metadata);
    assert.equal(result.isValid, true);
    assert.equal(result.payload.recommendation_strategy, strategy);
    assert.equal(result.payload.academic_options.scenario, scenario);
  }
});

test("legacy balance is visibly disabled, preserves stale selection and blocks advance and submit", () => {
  const html = render("balanced");
  assert.match(html, /value="balanced" disabled="" selected="">Equilíbrio geral — indisponível nesta coorte/);
  assert.match(html, /id="recommendation-strategy" aria-invalid="true"/);
  assert.match(html, /id="recommendation-strategy-error" role="alert"/);
  assert.match(html, /data-testid="recommendation-next-priorities"[^>]*disabled=""/);
  assert.match(html, /data-testid="recommendation-submit"[^>]*disabled=""/);
  assert.match(html, /Escolha explicitamente Menor custo possível ou Custo-benefício/);
});

test("cohort presentation distinguishes reference priority from explicit personalization", () => {
  const html = render("cost_benefit");
  assert.match(html, /Disponíveis nesta coorte: Menor custo possível e Custo-benefício/);
  assert.match(html, /classificação de referência por critérios documentados/);
  assert.match(html, /TCO estimado dentro de cada grupo comparável/);
  assert.match(html, /Se você ativar a personalização/);
  assert.doesNotMatch(html, /data-testid="recommendation-next-priorities"[^>]*disabled=""/);
  assert.match(html, /não fornecem notas originais de conforto, confiabilidade ou categoria/);
});

test("operational flow retains all original labels and selectable priorities", () => {
  const html = render("balanced", { candidate_source: "operational" });
  assert.match(html, /value="balanced" selected="">Equilíbrio geral/);
  assert.doesNotMatch(html, /indisponível nesta coorte|Disponíveis nesta coorte/);
  assert.doesNotMatch(html, /data-testid="recommendation-next-priorities"[^>]*disabled=""/);
});
