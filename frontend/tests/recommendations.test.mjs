import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { requestMotorcycleCatalog, requestMotorcycles, requestRecommendations } from "../src/api/sigraApi.js";
import { getConfidence, getMaintenanceMetric, getRankingLabel, getRecommendationErrorPresentation, getRecommendationStatusLabel } from "../src/features/recommendations/recommendationModel.js";
import { isLatestRequest, isRecommendationSubmitDisabled, shouldMarkResultsStale, validateRecommendationProfile } from "../src/features/recommendations/recommendationValidation.js";
import { formatMotorcycleValue, formatReferenceDate, getDataSourceLabel, getMotorcycleCategoryLabel, getMotorcycleDataGroupLabel, getMotorcycleEconomicStatusLabel, getMotorcycleEligibilityLabel, getMotorcycleMetricStatusLabel, getMotorcycleReadinessLabel, getRiderExperienceLabel, getVisibleEconomicEstimates, getVisibleMotorcycleMetrics, groupMotorcycleSources, isDemonstrationMotorcycle, isIncompleteMotorcycle } from "../src/features/motorcycles/motorcycleModel.js";
import { resolveVehicleModule, shouldRequestCarRecommendations } from "../src/features/motorcycles/motorcycleValidation.js";
import { isEnabled } from "../src/config/runtime.js";

const validProfile = { vehicle_type: "car", budget: "70000", monthly_limit: "1200", use_case: "cidade", recommendation_strategy: "cost_benefit", monthly_mileage: "1000", fuel_price: "6" };

test("modo público oculta login e áreas persistentes sem credenciais pré-preenchidas", () => {
  const source = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(source, /Ambiente demonstrativo em modo somente leitura/);
  assert.match(source, /!PUBLIC_DEMO_MODE && !currentUser/);
  assert.match(source, /!PUBLIC_DEMO_MODE && currentUser\?\.role === "admin"/);
  assert.match(source, /if \(!PUBLIC_DEMO_MODE\) loadOperationalData/);
  assert.doesNotMatch(source, /admin123|usuario123/);
  assert.equal(isEnabled("true"), true);
  assert.equal(isEnabled("false"), false);
});

test("seed visual de motocicletas possui quatro modelos demonstrativos distintos", () => {
  const seed = JSON.parse(readFileSync(new URL("../../backend/data/motorcycles.demo.json", import.meta.url), "utf8"));
  const names = seed.map((item) => `${item.brand} ${item.model}`);
  assert.deepEqual(names, [
    "Honda CG 160 Fan",
    "Yamaha NMax 160 ABS",
    "Royal Enfield Himalayan 450",
    "Honda CB 300F Twister",
  ]);
  assert.equal(new Set(names).size, 4);
  for (const item of seed) {
    assert.equal(item.data_source, "demonstration");
    assert.equal(item.source_name, "Base demonstrativa SIGRA");
    assert.doesNotMatch(item.source_name, /oficial/i);
  }
});

test("API indisponível não cria recomendação falsa e permite nova tentativa", async () => {
  let calls = 0;
  const fetchImpl = async () => {
    calls += 1;
    if (calls === 1) throw new Error("offline");
    return { ok: true, json: async () => ({ recommendations: [], has_viable_options: false }) };
  };
  await assert.rejects(requestRecommendations(validProfile, { fetchImpl }), /offline/);
  const result = await requestRecommendations(validProfile, { fetchImpl });
  assert.deepEqual(result.recommendations, []);
  assert.equal(calls, 2);
});

test("conflito e indisponibilidade preservam código de domínio sem expor detalhe técnico", async () => {
  for (const scenario of [
    { status: 409, code: "multifactor_gold_identity_conflict", kind: "conflict" },
    { status: 503, code: "multifactor_gold_unavailable", kind: "unavailable" },
  ]) {
    await assert.rejects(
      requestRecommendations(validProfile, { fetchImpl: async () => ({
        ok: false,
        status: scenario.status,
        json: async () => ({ detail: { code: scenario.code, message: "internal table and query detail" } }),
      }) }),
      (error) => {
        assert.equal(error.name, "SigraApiError");
        assert.equal(error.status, scenario.status);
        assert.equal(error.code, scenario.code);
        assert.doesNotMatch(error.message, /internal table|query detail/i);
        assert.equal(getRecommendationErrorPresentation(error).kind, scenario.kind);
        return true;
      },
    );
  }
});

test("apresentação de erro distingue validação, conflito, indisponibilidade e falha genérica", () => {
  assert.equal(getRecommendationErrorPresentation({ status: 422 }).kind, "validation");
  assert.equal(getRecommendationErrorPresentation({ status: 409 }).kind, "conflict");
  assert.equal(getRecommendationErrorPresentation({ status: 503 }).kind, "unavailable");
  assert.equal(getRecommendationErrorPresentation(new Error("offline")).kind, "error");
});

test("experiência cobre jornada, estados explícitos, acessibilidade e integração com simulador", () => {
  const page = readFileSync(new URL("../src/features/recommendations/RecommendationPage.jsx", import.meta.url), "utf8");
  const results = readFileSync(new URL("../src/features/recommendations/RecommendationResults.jsx", import.meta.url), "utf8");
  const form = readFileSync(new URL("../src/features/recommendations/RecommendationForm.jsx", import.meta.url), "utf8");
  const details = readFileSync(new URL("../src/features/recommendations/RecommendationDetails.jsx", import.meta.url), "utf8");
  const styles = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  assert.match(page, /Jornada da recomendação/);
  for (const state of ["ready", "loading", "empty", "success"]) {
    assert.match(results, new RegExp(`recommendation-state-${state}`));
  }
  assert.match(results, /recommendation-state-\$\{error\.kind\}/);
  assert.match(form, /aria-invalid/);
  assert.match(form, /aria-describedby/);
  assert.match(details, /VehicleCostSimulationPanel/);
  assert.match(details, /Simule este veículo no seu cenário/);
  assert.match(styles, /\.recommendation-form input:focus-visible/);
  assert.match(styles, /@media \(max-width: 760px\)/);
});

test("sem opção viável usa alternativa comparativa, não melhor escolha", () => {
  const item = { is_best_choice: false, is_best_available_reference: true };
  assert.match(getRankingLabel(item, 0), /ALTERNATIVA COMPARATIVA/);
  assert.doesNotMatch(getRankingLabel(item, 0), /MELHOR ESCOLHA/);
});

test("manutenção nunca usa disponibilidade de peças", () => {
  const item = { vehicle: { annual_maintenance_cost: 3200, parts_availability_score: 99 }, score_components: {} };
  const metric = getMaintenanceMetric(item);
  assert.equal(metric.source, "annual_maintenance_cost");
  assert.doesNotMatch(metric.label, /peças/i);
  assert.doesNotMatch(metric.value, /99/);
});

test("confiança aparece com nível e pontuação", () => {
  assert.deepEqual(getConfidence({ confidence: { score: 61, level: "moderada" } }), { score: 61, level: "moderada" });
});

test("campos vazios e não finitos impedem envio", () => {
  const empty = validateRecommendationProfile({ ...validProfile, budget: "", fuel_price: "Infinity" });
  assert.equal(empty.isValid, false);
  assert.ok(empty.errors.budget);
  assert.ok(empty.errors.fuel_price);
});

test("botão fica bloqueado durante carregamento", () => {
  assert.equal(isRecommendationSubmitDisabled({ loading: true, vehicleType: "car" }), true);
  assert.equal(isRecommendationSubmitDisabled({ loading: false, vehicleType: "car" }), false);
});

test("resposta antiga não pode substituir a mais recente", () => {
  assert.equal(isLatestRequest(1, 2), false);
  assert.equal(isLatestRequest(2, 2), true);
});

test("motocicleta não valida payload para o recomendador de carros", () => {
  const result = validateRecommendationProfile({ ...validProfile, vehicle_type: "motorcycle" });
  assert.equal(result.isValid, false);
  assert.ok(result.errors.vehicle_type);
  assert.equal(isRecommendationSubmitDisabled({ loading: false, vehicleType: "motorcycle" }), true);
});

test("alteração posterior marca resultado como desatualizado", () => {
  assert.equal(shouldMarkResultsStale(true), true);
  assert.equal(shouldMarkResultsStale(false), false);
});

test("rótulos de status e ranking são semanticamente coerentes", () => {
  assert.equal(getRecommendationStatusLabel("recommended"), "Recomendado");
  assert.equal(getRecommendationStatusLabel("good_option"), "Boa opção");
  assert.equal(getRecommendationStatusLabel("attention"), "Opção com ressalvas");
  assert.equal(getRecommendationStatusLabel("not_recommended"), "Não recomendado");
  assert.equal(getRankingLabel({ recommendation_status: "not_recommended", has_viable_options: true }, 4), "#5 NO RANKING");
  assert.doesNotMatch(getRankingLabel({ recommendation_status: "not_recommended", has_viable_options: true }, 4), /RECOMENDADO/);
  assert.equal(getRankingLabel({ recommendation_status: "good_option", has_viable_options: true }, 2), "#3 BOA OPÇÃO");
  assert.equal(getRankingLabel({ recommendation_status: "attention", has_viable_options: true }, 1), "#2 OPÇÃO COM RESSALVAS");
  assert.equal(getRankingLabel({ recommendation_status: "recommended", has_viable_options: false }, 3), "#4 ALTERNATIVA COMPARATIVA");
  assert.equal(getRankingLabel({ is_best_available_reference: true, has_viable_options: false }, 0), "#1 MELHOR ALTERNATIVA COMPARATIVA");
  assert.equal(getRankingLabel({ recommendation_status: "unknown" }, 0), "#1 NO RANKING");
});

test("card e detalhes usam a mesma tradução centralizada de status", () => {
  const card = readFileSync(new URL("../src/features/recommendations/VehicleCard.jsx", import.meta.url), "utf8");
  const details = readFileSync(new URL("../src/features/recommendations/RecommendationDetails.jsx", import.meta.url), "utf8");
  assert.match(card, /getRecommendationStatusLabel\(item\.recommendation_status\)/);
  assert.match(details, /getRecommendationStatusLabel\(item\.recommendation_status\)/);
  assert.equal(getRecommendationStatusLabel("good_option"), "Boa opção");
});

test("módulos de automóvel e motocicleta permanecem isolados", async () => {
  assert.equal(resolveVehicleModule("car"), "cars");
  assert.equal(resolveVehicleModule("motorcycle"), "motorcycles");
  assert.equal(shouldRequestCarRecommendations("car"), true);
  assert.equal(shouldRequestCarRecommendations("motorcycle"), false);
  let requestedUrl = "";
  const list = await requestMotorcycles({ fetchImpl: async (url) => {
    requestedUrl = url;
    return { ok: true, json: async () => [] };
  } });
  assert.deepEqual(list, []);
  assert.match(requestedUrl, /\/motorcycles$/);
  assert.doesNotMatch(requestedUrl, /recommendations/);
});

test("alternar de motocicleta para automóvel restaura o módulo de carros", () => {
  const journey = ["car", "motorcycle", "car"].map(resolveVehicleModule);
  assert.deepEqual(journey, ["cars", "motorcycles", "cars"]);
  assert.equal(shouldRequestCarRecommendations("car"), true);
});

test("tela de motocicletas não apresenta linguagem de recomendação", () => {
  const page = readFileSync(new URL("../src/features/motorcycles/MotorcyclePage.jsx", import.meta.url), "utf8");
  assert.match(page, /Módulo em desenvolvimento/);
  assert.doesNotMatch(page, /Nota SIGRA/);
  assert.doesNotMatch(page, /Ranking/);
  assert.doesNotMatch(page, /Melhor escolha/);
});

test("categorias, experiência e origem de motocicletas são traduzidas", () => {
  assert.equal(getMotorcycleCategoryLabel("underbone"), "Cub/Underbone");
  assert.equal(getMotorcycleCategoryLabel("sport"), "Esportiva");
  assert.equal(getRiderExperienceLabel("beginner"), "Iniciante");
  assert.equal(getRiderExperienceLabel("intermediate"), "Intermediário");
  assert.equal(getDataSourceLabel("demonstration"), "Demonstrativo");
  assert.equal(isDemonstrationMotorcycle({ is_demonstration: true }), true);
  assert.equal(isDemonstrationMotorcycle({ data_source: "demonstration" }), false);
  assert.equal(isDemonstrationMotorcycle({ eligibility_status: "eligible", data_sources: [{ source_type: "demonstration", is_primary: false }] }), false);
});

test("card de motocicleta identifica explicitamente dado demonstrativo", () => {
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.match(card, /Dado demonstrativo/);
});

test("catálogo de motocicletas usa endpoint próprio e envelope auditável", async () => {
  let requestedUrl = "";
  const catalog = await requestMotorcycleCatalog({ fetchImpl: async (url) => {
    requestedUrl = url;
    return { ok: true, json: async () => ({ module_version: "0.3.1", algorithm_version: null, weights_version: null, derived_metrics_method_version: null, total_found: 2, returned: 2, valid_records: 1, invalid_records: 1, invalid_record_summary: [{ id: 2, issue_count: 1 }], motorcycles: [{ id: 1 }] }) };
  } });
  assert.match(requestedUrl, /\/motorcycles\?envelope=true$/);
  assert.doesNotMatch(requestedUrl, /recommendations/);
  assert.equal(catalog.valid_records, 1);
  assert.equal(catalog.returned, 2);
  assert.equal(catalog.invalid_records, 1);
  assert.equal(catalog.invalid_record_summary[0].id, 2);
  assert.equal(catalog.motorcycles[0].id, 1);
  assert.equal(catalog.module_version, "0.3.1");
  assert.equal(catalog.algorithm_version, null);
  assert.equal(catalog.weights_version, null);
});

test("manutenção ausente e zero explícito permanecem semanticamente distintos", () => {
  assert.equal(formatMotorcycleValue(null, " BRL"), "Não informado");
  assert.equal(formatMotorcycleValue(0, " BRL"), "0 BRL");
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.match(card, /annual_maintenance_cost == null/);
  assert.match(card, /Estimativa de manutenção anual ainda não disponível/);
  assert.doesNotMatch(card, /annual_maintenance_cost \|\| 0/);
});

test("cobertura 0.3.1 separa piloto, complementares e prontidão futura", () => {
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.match(card, /pilot_required_source_coverage_percent/);
  assert.match(card, /missing_pilot_source_groups/);
  assert.match(card, /complementary_source_coverage_percent/);
  assert.match(card, /missing_complementary_source_groups/);
  assert.match(card, /future_recommendation_readiness/);
  assert.equal(getMotorcycleReadinessLabel("missing_economic_data"), "Dados econômicos ainda incompletos");
  assert.match(card, /Este indicador não é uma Nota SIGRA/);
});

test("consumo ausente é estrutural e manutenção ausente permanece complementar", () => {
  assert.equal(getMotorcycleDataGroupLabel("consumption"), "Consumo");
  assert.equal(getMotorcycleDataGroupLabel("maintenance"), "Manutenção");
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.match(card, /Grupos mínimos ausentes/);
  assert.match(card, /Grupos complementares ainda ausentes/);
  assert.doesNotMatch(card, /missing_complementary_source_groups.*Impedimentos estruturais/);
});

test("contrato canônico não depende de aliases e legado fica no modo técnico", () => {
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(card, /motorcycle\.(data_source|data_confidence|source_name|source_reference|reliability_score|parts_availability_score)\b/);
  assert.match(card, /motorcycle\.legacy_data \|\| \{\}/);
  assert.match(card, /showTechnical &&/);
});

test("normalização demonstrativa esperada não usa nome de teste nem fonte oficial fictícia", () => {
  const seed = readFileSync(new URL("../../scripts/seed_motorcycles.py", import.meta.url), "utf8");
  assert.match(seed, /CB 300F Twister/);
  assert.match(seed, /Base demonstrativa SIGRA/);
  assert.match(seed, /--confirm-normalization/);
  assert.doesNotMatch(seed, /source_name = "Fabricante Exemplo"/);
});

test("contagens e aviso de registros inválidos são exibidos sem inventar cards", () => {
  const list = readFileSync(new URL("../src/features/motorcycles/MotorcycleList.jsx", import.meta.url), "utf8");
  assert.match(list, /registros desta página estão disponíveis/);
  assert.match(list, /desconsiderados devido a dados inválidos ou incompletos/);
  assert.match(list, /Nenhuma motocicleta válida disponível nesta página/);
  assert.doesNotMatch(list, /Nota SIGRA|Melhor escolha|#1|ranking/i);
});

test("fallback legado calcula returned e mantém ausência de campos inventados", async () => {
  const catalog = await requestMotorcycleCatalog({ fetchImpl: async () => ({
    ok: true,
    json: async () => [
      { id: 1, record_status: "complete" },
      { id: 2, record_status: "incomplete" },
    ],
  }) });
  assert.equal(catalog.total_found, 2);
  assert.equal(catalog.returned, 2);
  assert.equal(catalog.valid_records, 1);
  assert.equal(catalog.invalid_records, 1);
  assert.deepEqual(catalog.invalid_record_summary, []);
});

test("registro incompleto e rastreabilidade são representados sem valores inventados", () => {
  assert.equal(isIncompleteMotorcycle({ record_status: "incomplete", specifications: null }), true);
  assert.equal(isIncompleteMotorcycle({ record_status: "complete", specifications: {} }), false);
  assert.equal(formatReferenceDate("2026-07-01"), "01/07/2026");
  assert.equal(formatReferenceDate(null), "Não informada");
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.match(card, /Registro ainda não possui dados suficientes/);
  assert.match(card, /source\.source_name/);
  assert.doesNotMatch(card, /motorcycle\.source_reference_date/);
  assert.match(card, /source\.source_url &&/);
  assert.doesNotMatch(card, /motorcycle\.(final_score|score|rank)\b|Melhor escolha|Recomendado/);
});

test("moto sem métricas renderiza aviso metodológico e não inventa indicadores", () => {
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.match(card, /Indicador ainda não calculado/);
  assert.match(card, /derivedMetrics\.length === 0/);
  assert.doesNotMatch(card, /motorcycle\.(final_score|score|rank)\b|ranking|Melhor escolha/i);
});

test("fontes são agrupadas com confiança e data de referência", () => {
  const grouped = groupMotorcycleSources([
    { id: 1, data_group: "identity", confidence: 80 },
    { id: 2, data_group: "technical_specs", confidence: 70 },
  ]);
  assert.equal(grouped.identity[0].id, 1);
  assert.equal(grouped.technical_specs[0].id, 2);
  assert.equal(getMotorcycleDataGroupLabel("market_price"), "Preço de referência");
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.match(card, /confiança/);
  assert.match(card, /formatReferenceDate\(source\.reference_date\)/);
});

test("estados estruturais e métricas demonstrativas recebem rótulos neutros", () => {
  assert.equal(getMotorcycleEligibilityLabel("demonstration_only"), "Somente demonstração");
  assert.equal(getMotorcycleEligibilityLabel("incomplete"), "Dados incompletos");
  assert.equal(getMotorcycleMetricStatusLabel("demonstration"), "Demonstrativo");
  assert.equal(getMotorcycleMetricStatusLabel("unvalidated"), "Não validado");
  assert.equal(getMotorcycleEconomicStatusLabel("demonstration"), "Demonstrativa");
});

test("contrato canônico filtra estados não publicáveis e separa estimativas econômicas", () => {
  assert.deepEqual(getVisibleMotorcycleMetrics([
    { id: 1, metric_status: "demonstration" },
    { id: 2, metric_status: "unvalidated" },
    { id: 3, metric_status: "deprecated" },
    { id: 4, metric_status: "calculated" },
  ]).map((item) => item.id), [1, 2]);
  assert.deepEqual(getVisibleEconomicEstimates([
    { id: 1, status: "demonstration" },
    { id: 2, status: "unvalidated" },
    { id: 3, status: "deprecated" },
  ]).map((item) => item.id), [1, 2]);
  const card = readFileSync(new URL("../src/features/motorcycles/MotorcycleCard.jsx", import.meta.url), "utf8");
  assert.match(card, /Estimativa de depreciação ainda não disponível/);
  assert.match(card, /Cobertura e elegibilidade/);
  assert.match(card, /demonstrativa neste grupo/);
  assert.match(card, /Dados legados \(deprecated\)/);
  assert.doesNotMatch(card, /motorcycle\.(final_score|score|rank)\b|Melhor escolha|#1|ranking/i);
});

test("modo técnico solicita legado explicitamente e permanece opcional", async () => {
  let requestedUrl = "";
  await requestMotorcycleCatalog({ includeLegacy: true, fetchImpl: async (url) => {
    requestedUrl = url;
    return { ok: true, json: async () => ({ motorcycles: [], total_found: 0, returned: 0, valid_records: 0, invalid_records: 0 }) };
  } });
  assert.match(requestedUrl, /include_legacy=true$/);
  const page = readFileSync(new URL("../src/features/motorcycles/MotorcyclePage.jsx", import.meta.url), "utf8");
  assert.match(page, /showTechnical/);
  assert.match(page, /Exibir dados legados no modo técnico/);
});

test("HTTP 501 do módulo não é convertido em catálogo disponível", async () => {
  await assert.rejects(
    requestMotorcycleCatalog({ fetchImpl: async () => ({ ok: false, status: 501, json: async () => ({ algorithm_version: null }) }) }),
    /HTTP 501/,
  );
});

test("página de motocicletas mantém aviso metodológico explícito", () => {
  const page = readFileSync(new URL("../src/features/motorcycles/MotorcyclePage.jsx", import.meta.url), "utf8");
  assert.match(page, /O cadastro e a estrutura de dados de motocicletas estão disponíveis/);
  assert.match(page, /O mecanismo de recomendação ainda não foi implementado/);
});
