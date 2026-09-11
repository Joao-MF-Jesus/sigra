import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  requestIntegratedGoldCatalog,
  requestVehicleCostSimulation,
} from "../src/api/sigraApi.js";
import {
  buildSimulationPayload,
  catalogErrorPresentation,
  complementPercentage,
  createSimulationForm,
  fuelPriceOriginLabel,
  suggestedGoldVehicleSk,
  simulationErrorPresentation,
  uniqueGoldVehicles,
  validateSimulationForm,
} from "../src/features/vehicle-cost-simulation/simulationModel.js";

function validForm() {
  return {
    ...createSimulationForm({ monthly_mileage: "1250", fuel_price: "6.19" }),
    state_code: "SP",
    municipality: "Campinas",
    reference_week_start: "2026-08-03",
    vehicle_sk: "42",
  };
}

test("sugestões editáveis reaproveitam somente parâmetros já informados pelo cliente", () => {
  const form = createSimulationForm({ monthly_mileage: "1250", fuel_price: "6.19" });
  assert.equal(form.monthly_distance_km, "1250");
  assert.equal(form.manual_fuel_price_brl, "6.19");
  assert.equal(form.price_mode, "manual");
  assert.equal(form.city_percentage, "50");
  assert.equal(form.highway_percentage, "50");
});

test("percentuais pareados mantêm exatamente cem sem cálculo financeiro no cliente", () => {
  assert.equal(complementPercentage("37.25"), "62.75");
  assert.equal(complementPercentage("100"), "0");
  assert.equal(complementPercentage("100.01"), null);
});

test("validação impede percentuais incoerentes e valores não positivos", () => {
  const invalid = validateSimulationForm({
    ...validForm(),
    monthly_distance_km: "0",
    city_percentage: "60",
    highway_percentage: "30",
    horizon_months: "0",
  });
  assert.equal(invalid.isValid, false);
  assert.ok(invalid.errors.monthly_distance_km);
  assert.ok(invalid.errors.highway_percentage);
  assert.ok(invalid.errors.horizon_months);
});

test("payload usa strings decimais e separa preço manual do modo ANP", () => {
  const manual = buildSimulationPayload(validForm());
  assert.equal(manual.monthly_distance_km, "1250");
  assert.equal(manual.manual_fuel_price_brl, "6.19");
  assert.deepEqual(manual.vehicle_sks, [42]);
  assert.equal(manual.max_results, 1);

  const anp = buildSimulationPayload({ ...validForm(), price_mode: "anp" });
  assert.equal("manual_fuel_price_brl" in anp, false);
});

test("identidade Gold só é sugerida quando marca, modelo e ano são inequívocos", () => {
  const catalog = [
    { vehicle_sk: 42, brand_name: "VW - Volkswagen", model_name: "Polo", model_year: 2024 },
    { vehicle_sk: 42, brand_name: "VW - Volkswagen", model_name: "Polo", model_year: 2024, fuel_scenario_code: "ethanol_hydrated" },
  ];
  assert.equal(uniqueGoldVehicles(catalog).length, 1);
  assert.equal(suggestedGoldVehicleSk({ brand: "Volkswagen", model: "Polo", year: 2024 }, catalog), "42");
  assert.equal(suggestedGoldVehicleSk({ brand: "Volkswagen", model: "Polo", year: 2023 }, catalog), "");
});

test("cliente percorre todas as páginas da listagem Gold ativa", async () => {
  const urls = [];
  const pages = [
    { items: [{ vehicle_sk: 1 }], total: 2 },
    { items: [{ vehicle_sk: 2 }], total: 2 },
  ];
  const items = await requestIntegratedGoldCatalog({ fetchImpl: async (url) => {
    urls.push(url);
    return { ok: true, status: 200, json: async () => pages.shift() };
  } });
  assert.deepEqual(items.map((item) => item.vehicle_sk), [1, 2]);
  assert.match(urls[0], /\/api\/v1\/integrated-vehicle-cost\/vehicles\?/);
  assert.match(urls[1], /offset=1/);
});

test("simulação usa o endpoint versionado e preserva códigos de domínio sanitizados", async () => {
  let request = null;
  const result = await requestVehicleCostSimulation({ vehicle_sks: [42] }, { fetchImpl: async (url, options) => {
    request = { url, options };
    return { ok: true, status: 200, json: async () => ({ results: [] }) };
  } });
  assert.deepEqual(result, { results: [] });
  assert.match(request.url, /\/api\/v1\/integrated-vehicle-cost\/simulate$/);
  assert.equal(request.options.method, "POST");

  await assert.rejects(
    requestVehicleCostSimulation({}, { fetchImpl: async () => ({
      ok: false,
      status: 409,
      json: async () => ({ detail: { code: "vehicle_cost_simulation_selection_conflict", message: "Seleção ambígua." } }),
    }) }),
    (error) => error.status === 409 && error.code === "vehicle_cost_simulation_selection_conflict" && error.message === "Seleção ambígua.",
  );
});

test("erros técnicos recebem apresentação explícita e sanitizada", () => {
  assert.equal(
    catalogErrorPresentation(),
    "Não foi possível carregar os veículos para simulação. Tente novamente ou continue informando os valores manualmente.",
  );
  assert.equal(simulationErrorPresentation({ status: 422 }), "Revise os parâmetros: um ou mais valores precisam ser corrigidos.");
  assert.equal(simulationErrorPresentation({ status: 409 }), "Há mais de uma correspondência possível para o veículo selecionado. Revise a seleção e tente novamente.");
  assert.equal(simulationErrorPresentation({ status: 503 }), "Não foi possível acessar os dados de referência para concluir a simulação. Tente novamente mais tarde.");
  assert.doesNotMatch(simulationErrorPresentation({ message: "eligible integrated Gold dataset is unavailable" }), /Gold|dataset/i);
});

test("interface exibe fontes e resultados do backend sem reproduzir fórmulas", () => {
  const panel = readFileSync(new URL("../src/features/vehicle-cost-simulation/VehicleCostSimulationPanel.jsx", import.meta.url), "utf8");
  const details = readFileSync(new URL("../src/features/recommendations/RecommendationDetails.jsx", import.meta.url), "utf8");
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(panel, /requestVehicleCostSimulation\(buildSimulationPayload\(form\)\)/);
  assert.match(panel, /monthly_fuel_cost_brl/);
  assert.match(panel, /Fontes de referência: FIPE, PBEV e ANP/);
  assert.match(panel, /Tentar novamente/);
  assert.match(panel, /catalogAttempt/);
  assert.doesNotMatch(panel, />[^<{]*(?:Gold integrada|dataset_version|mixed_1000_v1)[^<{]*</i);
  assert.match(panel, /type="date"[^>]+onInput=/);
  assert.doesNotMatch(panel, /monthly_distance_km\s*[*/]|fuel_price_per_liter_brl\s*[*/]/);
  assert.match(details, /VehicleCostSimulationPanel/);
  assert.match(app, /profile=\{profile\}/);
  assert.equal(fuelPriceOriginLabel("user_input"), "Preço informado pelo usuário");
  assert.equal(fuelPriceOriginLabel("anp_gold"), "Preço médio de referência");
});

test("seleção de outro veículo é explicitamente independente e não persiste identidade", () => {
  const panel = readFileSync(new URL("../src/features/vehicle-cost-simulation/VehicleCostSimulationPanel.jsx", import.meta.url), "utf8");
  assert.match(panel, /Simular outro veículo com cobertura/);
  assert.match(panel, /não vincula nem substitui/);
  assert.doesNotMatch(panel, /Escolha o veículo correspondente|associar automaticamente/);
  assert.doesNotMatch(panel, /localStorage|sessionStorage|request.*(?:Mapping|Identity)/);
  assert.match(panel, /vehicle_sk: suggestedGoldVehicleSk\(vehicle, unique\)/);
  assert.match(panel, /Veículo selecionado apenas para esta simulação/);
});
