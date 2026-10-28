import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { transformSync } from "esbuild";
import { MULTIFACTOR_DEFAULT_WEIGHTS, buildMultifactorProfile } from "../src/features/recommendations/multifactorRecommendationModel.js";
import { readableValue } from "../src/features/recommendations/cohortPresentation.js";

// Fictitious transport fixture ONLY for presentation tests, never runtime data.
const labels = ["Custo de combustível", "Adequação ao uso", "Conforto", "Segurança", "Desempenho", "Eficiência", "Qualidade histórica"];
const fixture = {
  final_score: null, calculated_requested_count: 2, requested_count: 7,
  criteria: Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([key, weight], index) => ({
    criterion: key, label: labels[index], requested: true,
    normalized_weight_percentage: weight, available: index === 0 || index === 5,
    raw_score: index === 0 ? "80" : index === 5 ? "60" : null,
    contribution: index === 0 ? "20" : index === 5 ? "6" : null,
    requirement_message: "Falta evidência comprovada para este critério.",
    inputs_used: index === 0 ? {
      price: { label: "Preço informado", value: "6", unit: "BRL/l", nature: "user_input" },
      distance: { label: "Quilometragem mensal", value: "1000", unit: "km/month", nature: "user_input" },
      consumption: { label: "Consumo urbano", value: "12.5", unit: "km/l", nature: "observed", sources: [{ provider: "pbev", sha256: "not-for-main-ui" }] },
    } : {},
    normalization: index === 0 ? { minimum: "400", maximum: "600", population_ids: [9001, 9002] } : null,
  })),
};
const modules = new Map();
function load(url) {
  // SSR reads JSON as data; CSS is exercised by the real browser suite.
  if (url.pathname.endsWith(".json")) return JSON.parse(readFileSync(url, "utf8"));
  if (url.pathname.endsWith(".css")) { readFileSync(url, "utf8"); return {}; }
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

test("diagnostics show all seven weights, no partial total and five unavailable criteria", () => {
  const html = render("SevenCriteriaBreakdown", { breakdown: fixture });
  assert.match(html, /2 de 7 critérios/);
  assert.match(html, /não formam uma nota final/);
  assert.match(html, /não são redistribuídos/);
  assert.equal((html.match(/<h4>/g) || []).length, 7);
  assert.equal((html.match(/Não avaliada/g) || []).length, 5);
  assert.equal((html.match(/Não calculada<\/dd>/g) || []).length, 5);
  assert.match(html, /20 pontos/);
  assert.match(html, /6 pontos/);
  assert.doesNotMatch(html, /26 pontos|not-for-main-ui|9001|9002/);
});
test("ranked contributions and diagnostic-only contributions are explicitly distinct", () => {
  const html = render("SevenCriteriaBreakdown", { breakdown: { ...fixture, final_score: "26" } });
  assert.match(html, /compõem a nota personalizada/);
  assert.match(html, /Contribuição à nota/);
  assert.doesNotMatch(html, /sem soma final|não formam uma nota final/);
});
test("inputs display Portuguese units and source nature, not fingerprints", () => {
  const html = render("SevenCriteriaBreakdown", { breakdown: fixture });
  assert.match(html, /R\$\s6,00\/l/);
  assert.match(html, /1\.000 km\/mês/);
  assert.match(html, /12,5 km\/l/);
  assert.match(html, /informado por você/);
  assert.match(html, /evidência observada/);
  assert.match(html, /Fontes: pbev/);
  assert.match(html, /<details[^>]*><summary>Dados utilizados/);
  assert.doesNotMatch(html, /<details[^>]*open|not-for-main-ui/);
  assert.equal(readableValue({ value: "12", unit: "month" }), "12 meses");
});
test("unrequested missing criterion stays unassessed, not a neutral score", () => {
  const criteria = fixture.criteria.map((row) => row.criterion === "comfort" ? { ...row, requested: false, normalized_weight_percentage: "0", contribution: "0" } : row);
  const html = render("SevenCriteriaBreakdown", { breakdown: { ...fixture, criteria } });
  assert.match(html, /Critério sem peso.*ausência de evidência continua preservada/);
  assert.match(html, /0 pontos/);
  assert.equal((html.match(/Não avaliada/g) || []).length, 5);
});
test("quality subcalculations remain scenario estimates, not historical observations", () => {
  const criteria = fixture.criteria.map((row) => row.criterion === "legacy_quality" ? { ...row, calculated_subcriteria: { maintenance_score: { score: "45" }, resale_score: { score: "70" } } } : row);
  const html = render("SevenCriteriaBreakdown", { breakdown: { ...fixture, criteria } });
  assert.match(html, /Manutenção: 45\/100 \(estimativa de cenário\)/);
  assert.match(html, /Desvalorização: 70\/100 \(estimativa de cenário\)/);
  assert.match(html, /Não comprova confiabilidade nem disponibilidade de peças/);
});
test("optional consumption errors are accessible and prevent sending invalid parameters", () => {
  const profile = { multifactor_enabled: true, multifactor_monthly_distance_km: "1000", multifactor_city_percentage: "50", multifactor_highway_percentage: "50",
    multifactor_state_code: "SP", multifactor_municipality: "", multifactor_reference_week_start: "2026-09-01", multifactor_fuel_strategy: "gasoline_c_common",
    multifactor_price_mode: "manual", multifactor_manual_fuel_price_brl: "6", multifactor_horizon_months: "12",
    multifactor_city_consumption_km_l: "-1", multifactor_highway_consumption_km_l: "0",
    ...Object.fromEntries(Object.entries(MULTIFACTOR_DEFAULT_WEIGHTS).map(([key, value]) => ["weight_" + key, value])) };
  const result = buildMultifactorProfile(profile);
  assert.equal(result.isValid, false);
  const html = render("MultifactorProfileFields", { profile, errors: result.errors, onChange: () => {}, onResetWeights: () => {} });
  for (const field of ["multifactor_city_consumption_km_l", "multifactor_highway_consumption_km_l"]) {
    assert.match(html, new RegExp('id="' + field + '"[^>]*aria-invalid="true"'));
    assert.match(html, new RegExp('id="' + field + '-error"'));
  }
});
test("absent diagnostic transport does not create replacement UI or invented scores", () => {
  assert.equal(render("SevenCriteriaBreakdown", { breakdown: null }), "");
});
