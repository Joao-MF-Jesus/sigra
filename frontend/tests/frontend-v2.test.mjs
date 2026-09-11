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
  assert.match(app, /Encontre o veículo certo para você\./);
  assert.match(app, /Informe seu orçamento, sua rotina e suas prioridades\. O SIGRA compara as opções e explica cada recomendação\./);
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
  assert.match(styles, /\.recommendation-grid[\s\S]*minmax\(min\(360px, 100%\), 1fr\)/);
  assert.match(styles, /@media \(max-width: 880px\)/);
  assert.match(styles, /@media \(max-width: 620px\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(styles, /min-height:\s*44px/);
});

test("jornada responsiva usa largura do contêiner sem truncar etapas ou criar scroll interno", () => {
  const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  const form = readFileSync(new URL("../src/features/recommendations/RecommendationForm.jsx", import.meta.url), "utf8");
  const multifactor = readFileSync(new URL("../src/features/recommendations/MultifactorProfileFields.jsx", import.meta.url), "utf8");
  assert.match(styles, /container-name:\s*recommendation-builder/);
  assert.match(styles, /container-name:\s*multifactor-profile/);
  assert.match(styles, /@container recommendation-builder \(min-width: 600px\)/);
  assert.match(styles, /@container multifactor-profile \(min-width: 640px\)/);
  assert.match(styles, /\.recommendation-builder\s*\{[\s\S]*?overflow:\s*visible/);
  assert.match(styles, /\.multifactor-grid\s*\{[\s\S]*?grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(styles, /\.wizard-actions button\s*\{[\s\S]*?min-height:\s*48px/);
  assert.doesNotMatch(styles.match(/\.wizard-progress button em\s*\{[\s\S]*?\}/)?.[0] || "", /ellipsis/);
  assert.match(form, /className="field-label"/);
  assert.match(form, /\{step\.label\}<\/em>/);
  assert.match(multifactor, /multifactor-toggle/);
  assert.match(multifactor, /form-field multifactor-field/);
});

test("CarPedia permanece explicitamente desabilitada no navegador", () => {
  const api = readFileSync(new URL("../src/api/sigraApi.js", import.meta.url), "utf8");
  assert.equal(CARPEDIA_UI_ENABLED, false);
  assert.doesNotMatch(api, /carpedia/i);
  assert.doesNotMatch(api, /api[_-]?key|authorization/i);
});

test("gutters móveis não acumulam o padding legado nem comprimem o multifator", () => {
  const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  const mobile = styles.slice(styles.lastIndexOf("@media (max-width: 620px)"));
  assert.match(mobile, /\.app-shell\s*\{[^}]*padding:\s*0 0 32px;/);
  assert.match(mobile, /\.workspace-v2\s*\{[^}]*padding:\s*24px 12px 0;/);
  assert.match(mobile, /\.wizard-step\s*\{[^}]*padding:\s*18px 12px;/);
  assert.match(mobile, /\.recommendation-builder \.multifactor-profile\s*\{[^}]*padding:\s*12px !important;/);
});

test("auditoria responsiva preserva métricas por controle e todas as etapas antes das assertions", () => {
  const spec = readFileSync(new URL("../e2e/recommendation-v2.spec.js", import.meta.url), "utf8");
  assert.match(spec, /fits: control\.scrollWidth <= control\.clientWidth \+ 1/);
  assert.match(spec, /controlsFit: controlMetrics\.every\(\(control\) => control\.fits\)/);
  for (const property of ["locator", "name", "label", "selectedText", "containerBox", "clientWidth", "scrollWidth", "offsetWidth", "containerCss"]) {
    assert.match(spec, new RegExp(`${property}:`));
  }
  assert.match(spec, /responsive-measurements-\$\{stage\}/);
  assert.ok(spec.indexOf('await inspect("revisao")') < spec.indexOf("of measurements) assertLayout"));
  assert.match(spec, /expect\(audit\.controlsFit,[^\n]+\)\.toBe\(true\)/);
  assert.match(spec, /const widthLayers = \[/);
  assert.match(spec, /toBeGreaterThanOrEqual\(audit\.viewportClientWidth - 24\)/);
  assert.match(spec, /toBeGreaterThanOrEqual\(audit\.viewportClientWidth - 80\)/);
  assert.match(spec, /toHaveAccessibleName\("Origem do preço"\)/);
});

test("frontend não introduz fórmula financeira nem persiste o perfil guiado", () => {
  const form = readFileSync(new URL("../src/features/recommendations/RecommendationForm.jsx", import.meta.url), "utf8");
  const wizard = readFileSync(new URL("../src/features/recommendations/recommendationWizardModel.js", import.meta.url), "utf8");
  assert.doesNotMatch(`${form}\n${wizard}`, /localStorage|sessionStorage|fetch\(/);
  assert.doesNotMatch(`${form}\n${wizard}`, /monthly_fuel_cost_brl\s*=|total_monthly_cost\s*=/);
  assert.match(form, /dados publicados permanecem somente leitura/);
  assert.doesNotMatch(form, /allow_budget_above_200k|200 mil/);
});

test("shell operacional fluido separa largura de leitura e só divide colunas com espaço para os cards", () => {
  const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  assert.match(css, /\.workspace-v2:has\(\.recommendation-workbench\)\s*\{[^}]*max-width:\s*2480px/);
  assert.match(css, /container:\s*recommendation-workspace \/ inline-size/);
  assert.match(css, /@container recommendation-workspace \(min-width: 1406px\)/);
  assert.match(css, /grid-template-columns:\s*minmax\(0, 640px\) minmax\(0, 1fr\)/);
  assert.match(css, /\.experience-hero\s*\{[^}]*width:\s*min\(1480px, 100%\)/);
  assert.doesNotMatch(css, /(?:transform:\s*scale\(|(?:^|[;{])\s*zoom:)/m);
  assert.doesNotMatch(css, /overflow-x:\s*hidden/);
});

test("detalhes usam 100dvh com um único corpo rolável e cabeçalho fora do scroll", () => {
  const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  const details = readFileSync(new URL("../src/features/recommendations/RecommendationDetails.jsx", import.meta.url), "utf8");
  assert.match(css, /max-height:\s*calc\(100dvh - 48px\)/);
  assert.match(css, /grid-template-rows:\s*auto minmax\(0, 1fr\)/);
  assert.match(css, /\.modal-body\s*\{[^}]*min-height:\s*0;[^}]*overflow:\s*auto/);
  assert.match(css, /@container vehicle-details \(max-width: 639px\)/);
  assert.match(css, /\.modal-body \.vehicle-simulation-form button\s*\{[^}]*min-height:\s*48px/);
  assert.ok(details.indexOf('className="modal-header"') < details.indexOf('className="modal-body"'));
  assert.match(details, /document\.body\.style\.overflowY = previousOverflowY/);
});
