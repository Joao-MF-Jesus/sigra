import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { CARPEDIA_UI_ENABLED } from "../src/config/runtime.js";
import {
  RECOMMENDATION_WIZARD_STEPS,
  firstStepWithError,
  nextWizardStep,
  previousWizardStep,
  recommendationReview,
  wizardProgress,
} from "../src/features/recommendations/recommendationWizardModel.js";

test("fluxo guiado avança, volta e preserva os parâmetros do usuário", () => {
  const profile = { vehicle_type: "car", use_case: "cidade", budget: "70000", monthly_limit: "1200", recommendation_strategy: "cost_benefit", monthly_mileage: "1000", fuel_price: "6", multifactor_enabled: false };
  assert.equal(RECOMMENDATION_WIZARD_STEPS.length, 5);
  assert.equal(nextWizardStep(0), 1);
  assert.equal(previousWizardStep(1), 0);
  assert.equal(nextWizardStep(4), 4);
  assert.equal(previousWizardStep(0), 0);
  assert.equal(wizardProgress(2).percentage, 60);
  assert.equal(profile.budget, "70000");
  assert.match(recommendationReview(profile).find(([label]) => label === "Orçamento")[1], /70000/);
});

test("erros devolvem o usuário à etapa correspondente", () => {
  assert.equal(firstStepWithError({ budget: "Obrigatório" }), 1);
  assert.equal(firstStepWithError({ monthly_mileage: "Inválido" }), 2);
  assert.equal(firstStepWithError({ weight_cost: "Inválido" }), 3);
  assert.equal(firstStepWithError({}), -1);
});

test("experiência V2 usa cabeçalho, hero, revisão e estados progressivos", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  const header = readFileSync(new URL("../src/AppHeader.jsx", import.meta.url), "utf8");
  const form = readFileSync(new URL("../src/features/recommendations/RecommendationForm.jsx", import.meta.url), "utf8");
  const results = readFileSync(new URL("../src/features/recommendations/RecommendationResults.jsx", import.meta.url), "utf8");
  assert.match(app, /Um carro que faz sentido para a sua vida/);
  assert.match(app, /recommendation-workbench/);
  assert.match(header, /aria-expanded=\{menuOpen\}/);
  assert.match(header, /aria-current=\{activeTab === item\.id \? "page"/);
  assert.match(form, /Etapa \{progress\.currentNumber\} de \{progress\.total\}/);
  assert.match(form, /Revise antes de calcular/);
  assert.match(form, /Voltar e ajustar/);
  assert.match(results, /recommendation-skeleton-grid/);
});

test("tokens graphite e bronze e breakpoints não criam layout estreito", () => {
  const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  for (const color of ["#101214", "#191c1f", "#22262a", "#34383d", "#b7793e", "#ce9255", "#f3f0ea", "#aaa7a1"]) {
    assert.match(styles.toLowerCase(), new RegExp(color));
  }
  assert.match(styles, /--content-max:\s*1760px/);
  assert.match(styles, /\.workspace-v2[\s\S]*width:\s*100%/);
  assert.match(styles, /@media \(max-width: 880px\)/);
  assert.match(styles, /@media \(max-width: 620px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /min-height:\s*44px/);
});

test("CarPedia permanece explicitamente desabilitada no navegador", () => {
  const api = readFileSync(new URL("../src/api/sigraApi.js", import.meta.url), "utf8");
  assert.equal(CARPEDIA_UI_ENABLED, false);
  assert.doesNotMatch(api, /carpedia/i);
  assert.doesNotMatch(api, /api[_-]?key|authorization/i);
});

test("frontend não introduz fórmula financeira nem persiste o perfil guiado", () => {
  const form = readFileSync(new URL("../src/features/recommendations/RecommendationForm.jsx", import.meta.url), "utf8");
  const wizard = readFileSync(new URL("../src/features/recommendations/recommendationWizardModel.js", import.meta.url), "utf8");
  assert.doesNotMatch(`${form}\n${wizard}`, /localStorage|sessionStorage|fetch\(/);
  assert.doesNotMatch(`${form}\n${wizard}`, /monthly_fuel_cost_brl\s*=|total_monthly_cost\s*=/);
  assert.match(form, /Gold publicada permanece somente leitura/);
});
