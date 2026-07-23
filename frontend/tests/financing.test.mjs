import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  requestFinancingComparison,
  requestFinancingMetadata,
  requestFinancingSimulation,
  requestReverseFinancingSimulation,
} from "../src/api/sigraApi.js";
import {
  FINANCING_DISCLAIMER,
  MAX_COMPARISON_SCENARIOS,
  applyFinancingFormChange,
  canAddFinancingScenario,
  comparisonCriteriaLabels,
  formatComparisonValue,
  getAcquisitionStatusLabel,
  getCompatibilityLabel,
  getComparisonDifferenceLabel,
  getComparisonScopeLabel,
  getFinancialContextMessage,
  getFinancialContextStatusLabel,
  getFinancingStatusLabel,
  getInstallmentPlanSummary,
  getMonthlyBudgetStatusLabel,
  removeFinancingScenario,
  validateFinancingForm,
} from "../src/features/financing/financingModel.js";

const validForm = {
  vehicle_type: "car", price_mode: "catalog", vehicle_id: "1", vehicle_price: "", negotiated_price: "", down_payment: "10000", term_months: "36",
  rate_mode: "monthly", monthly_interest_rate_percent: "1.8", effective_cost_rate_percent: "", effective_cost_rate_period: "", effective_rate_includes_additional_costs: "",
  upfront_fees: "300", financed_fees: "500", financed_insurance: "100", financed_services: "50", desired_max_installment: "1000", maximum_installment: "900",
  available_monthly_budget: "1800", estimated_monthly_vehicle_cost: "620", offer_name: "Banco A", institution_name: "Instituicao A", offer_reference: "ABC", offer_date: "2026-07-21", notes: "",
};

function jsonResponse(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

test("formulario direto valida carro e mantem valores financeiros explicitos", () => {
  const result = validateFinancingForm(validForm, "direct");
  assert.equal(result.isValid, true);
  assert.equal(result.payload.vehicle_type, "car");
  assert.equal(result.payload.vehicle_id, 1);
  assert.equal(result.payload.down_payment, 10000);
  assert.equal(result.payload.monthly_interest_rate_percent, 1.8);
  assert.equal(result.payload.financed_fees, 500);
  assert.equal(result.payload.amortization_method, "price");
});

test("selecao de motocicleta usa o mesmo simulador sem chamar recomendacao", () => {
  const result = validateFinancingForm({ ...validForm, vehicle_type: "motorcycle", vehicle_id: "3" }, "direct");
  assert.equal(result.isValid, true);
  assert.equal(result.payload.vehicle_type, "motorcycle");
  assert.equal(result.payload.vehicle_id, 3);
});

test("preco manual e preco negociado sao contratos distintos", () => {
  const manual = validateFinancingForm({ ...validForm, price_mode: "manual", vehicle_price: "42000", vehicle_id: "" }, "direct");
  assert.equal(manual.isValid, true);
  assert.equal(manual.payload.vehicle_price, 42000);
  assert.equal(manual.payload.vehicle_id, undefined);
  const negotiated = validateFinancingForm({ ...validForm, negotiated_price: "55000" }, "direct");
  assert.equal(negotiated.payload.negotiated_price, 55000);
});

test("troca entre catalogo e manual limpa fontes de preco incompatíveis", () => {
  const manual = applyFinancingFormChange({ ...validForm, negotiated_price: "55000" }, "price_mode", "manual");
  assert.equal(manual.vehicle_id, "");
  assert.equal(manual.negotiated_price, "");
  const catalog = applyFinancingFormChange({ ...manual, vehicle_price: "42000" }, "price_mode", "catalog");
  assert.equal(catalog.vehicle_price, "");
});

test("troca de veiculo remove preco negociado anterior", () => {
  const next = applyFinancingFormChange({ ...validForm, negotiated_price: "55000" }, "vehicle_id", "2");
  assert.equal(next.vehicle_id, "2");
  assert.equal(next.negotiated_price, "");
});

test("preco negociado oculto nao e enviado no modo manual", () => {
  const result = validateFinancingForm({ ...validForm, price_mode: "manual", vehicle_id: "1", vehicle_price: "42000", negotiated_price: "39000" }, "direct");
  assert.equal(result.isValid, true);
  assert.equal(result.payload.vehicle_price, 42000);
  assert.equal(result.payload.vehicle_id, undefined);
  assert.equal(result.payload.negotiated_price, undefined);
});

test("campos vazios e valores nao finitos impedem simulacao", () => {
  const result = validateFinancingForm({ ...validForm, down_payment: "", monthly_interest_rate_percent: "Infinity", term_months: "36.5" }, "direct");
  assert.equal(result.isValid, false);
  assert.ok(result.errors.down_payment);
  assert.ok(result.errors.monthly_interest_rate_percent);
  assert.ok(result.errors.term_months);
});

test("taxa zero precisa ser informada explicitamente e ausencia de taxa falha", () => {
  const zero = validateFinancingForm({ ...validForm, monthly_interest_rate_percent: "0" }, "direct");
  assert.equal(zero.isValid, true);
  assert.equal(zero.payload.monthly_interest_rate_percent, 0);
  const absent = validateFinancingForm({ ...validForm, monthly_interest_rate_percent: "" }, "direct");
  assert.equal(absent.isValid, false);
});

test("modo CET exige periodo e declaracao sobre custos adicionais", () => {
  const invalid = validateFinancingForm({ ...validForm, rate_mode: "effective", effective_cost_rate_percent: "24" }, "direct");
  assert.equal(invalid.isValid, false);
  assert.ok(invalid.errors.effective_cost_rate_period);
  assert.ok(invalid.errors.effective_rate_includes_additional_costs);
  const valid = validateFinancingForm({ ...validForm, rate_mode: "effective", effective_cost_rate_percent: "24", effective_cost_rate_period: "annual", effective_rate_includes_additional_costs: "yes", financed_fees: "0", financed_insurance: "0", financed_services: "0" }, "direct");
  assert.equal(valid.isValid, true);
  assert.equal(valid.payload.effective_rate_includes_additional_costs, true);
  assert.equal(valid.payload.monthly_interest_rate_percent, undefined);
});

test("CET com custos incluidos remove valores antigos e bloqueia dupla contagem", () => {
  const changed = applyFinancingFormChange(validForm, "effective_rate_includes_additional_costs", "yes");
  assert.equal(changed.financed_fees, "0");
  assert.equal(changed.financed_insurance, "0");
  assert.equal(changed.financed_services, "0");
  const invalid = validateFinancingForm({ ...validForm, rate_mode: "effective", effective_cost_rate_percent: "24", effective_cost_rate_period: "annual", effective_rate_includes_additional_costs: "yes" }, "direct");
  assert.equal(invalid.isValid, false);
  assert.ok(invalid.errors.financed_fees);
  const form = readFileSync(new URL("../src/features/financing/FinancingForm.jsx", import.meta.url), "utf8");
  assert.match(form, /disabled=\{cetIncludesAdditionalCosts\}/);
});

test("simulacao reversa envia parcela maxima e nao exige preco", () => {
  const result = validateFinancingForm({ ...validForm, vehicle_id: "", price_mode: "manual", vehicle_price: "" }, "reverse");
  assert.equal(result.isValid, true);
  assert.equal(result.payload.maximum_installment, 900);
  assert.equal(result.payload.vehicle_price, undefined);
});

test("simulacao reversa aceita parcela maxima zero explicitamente", () => {
  const result = validateFinancingForm({ ...validForm, maximum_installment: "0" }, "reverse");
  assert.equal(result.isValid, true);
  assert.equal(result.payload.maximum_installment, 0);
});

test("API usa endpoints independentes para direta, reversa, comparacao e metadata", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => { calls.push({ url, options }); return jsonResponse({ ok: true }); };
  await requestFinancingMetadata({ fetchImpl });
  await requestFinancingSimulation({ vehicle_type: "car" }, { fetchImpl });
  await requestReverseFinancingSimulation({ vehicle_type: "car" }, { fetchImpl });
  await requestFinancingComparison([{ offer_name: "A" }, { offer_name: "B" }], { fetchImpl });
  assert.match(calls[0].url, /\/financing\/metadata$/);
  assert.match(calls[1].url, /\/financing\/simulate$/);
  assert.match(calls[2].url, /\/financing\/reverse-simulate$/);
  assert.match(calls[3].url, /\/financing\/compare$/);
  assert.equal(JSON.parse(calls[3].options.body).scenarios.length, 2);
});

test("erro 422 permanece erro de validacao recuperavel", async () => {
  await assert.rejects(
    requestFinancingSimulation({}, { fetchImpl: async () => jsonResponse({ detail: "taxa obrigatoria" }, 422) }),
    /taxa obrigatoria/,
  );
});

test("comparacao usa rotulos neutros e nao elege proposta opaca", () => {
  const labels = comparisonCriteriaLabels();
  assert.equal(labels.lowest_installment, "Menor parcela");
  assert.equal(labels.lowest_total_acquisition_outflow, "Menor custo total da aquisição");
  assert.equal(labels.lowest_total_installments, "Menor total das parcelas");
  assert.equal(Object.keys(labels).length, 7);
  assert.equal(new Set(Object.values(labels)).size, 7);
  assert.equal(labels.lowest_interest_and_financed_costs, undefined);
  const component = readFileSync(new URL("../src/features/financing/FinancingComparison.jsx", import.meta.url), "utf8");
  assert.match(component, /Menor parcela não significa automaticamente menor custo total/);
  assert.doesNotMatch(component, /Melhor proposta:/);
});

test("comparacao exibe escopo, valores e diferenca sem economia enganosa", () => {
  const currency = (value) => `R$ ${Number(value).toLocaleString("pt-BR", { minimumFractionDigits: 2 })}`;
  const detail = { value: 1776.04, difference_to_next: 203.60, unit: "currency_monthly", is_tie: false };
  assert.match(formatComparisonValue(detail, currency), /1\.776,04 por mês/);
  assert.match(
    getComparisonDifferenceLabel(detail, "same_vehicle_same_price", 2, currency),
    /203,60 abaixo da outra proposta/,
  );
  assert.match(
    getComparisonDifferenceLabel(detail, "different_vehicles", 2, currency),
    /^Diferença de .* para o próximo cenário\.$/,
  );
  assert.equal(getComparisonScopeLabel("same_vehicle_same_price"), "Mesmo veículo e mesma base de preço");
  assert.equal(getComparisonScopeLabel("different_vehicles"), "Veículos diferentes");
  const component = readFileSync(new URL("../src/features/financing/FinancingComparison.jsx", import.meta.url), "utf8");
  assert.match(component, /highlight_details/);
  assert.match(component, /Escopo da comparação/);
  assert.match(component, /result\.warnings\?\.slice\(1\)/);
  assert.match(component, /formatComparisonValue/);
  assert.match(component, /getComparisonDifferenceLabel/);
});

test("comprometimento mensal permanece destaque quando contexto e comparavel", () => {
  assert.equal(getFinancialContextStatusLabel("comparable"), "Contextos mensais comparáveis");
  assert.match(getFinancialContextMessage("comparable"), /mesmo orçamento e o mesmo custo mensal/);
  const component = readFileSync(new URL("../src/features/financing/FinancingComparison.jsx", import.meta.url), "utf8");
  assert.match(component, /data-testid=\{`highlight-\$\{criterion\}`\}/);
  assert.match(component, /budget_commitment_percentage/);
});

test("orcamentos diferentes ocultam vencedor e exibem estado neutro", () => {
  assert.equal(getFinancialContextStatusLabel("different_monthly_budgets"), "Orçamentos mensais diferentes");
  assert.match(getFinancialContextMessage("different_monthly_budgets"), /Compare os percentuais individualmente/);
  const component = readFileSync(new URL("../src/features/financing/FinancingComparison.jsx", import.meta.url), "utf8");
  assert.match(component, /suppressed_highlights/);
  assert.match(component, /comparison-highlight-suppressed/);
  assert.match(component, /suppressed-\$\{item\.criterion\}/);
});

test("custos mensais diferentes recebem aviso especifico", () => {
  assert.equal(getFinancialContextStatusLabel("different_vehicle_cost_bases"), "Custos mensais do veículo diferentes");
  assert.match(getFinancialContextMessage("different_vehicle_cost_bases"), /custos mensais do veículo diferentes/);
  assert.match(getFinancialContextMessage("insufficient_vehicle_cost_data"), /Falta custo mensal/);
  assert.match(getFinancialContextMessage("insufficient_budget_data"), /Falta orçamento mensal/);
});

test("contexto mensal nao comparavel nunca usa economia", () => {
  const currency = (value) => `R$ ${Number(value).toFixed(2)}`;
  const detail = { value: 1000, difference_to_next: 200, unit: "currency", is_tie: false };
  const text = getComparisonDifferenceLabel(detail, "same_vehicle_same_price", 2, currency, false);
  assert.match(text, /^Diferença de/);
  assert.doesNotMatch(text, /Economia/);
});

test("destaques independentes continuam visiveis com contexto suprimido", () => {
  const component = readFileSync(new URL("../src/features/financing/FinancingComparison.jsx", import.meta.url), "utf8");
  assert.match(component, /Object\.entries\(details\)/);
  assert.match(component, /result\.suppressed_highlights/);
  const labels = comparisonCriteriaLabels();
  for (const criterion of ["lowest_installment", "lowest_total_acquisition_outflow", "lowest_total_financing_addition", "lowest_total_installments", "shortest_term", "highest_down_payment"]) {
    assert.ok(labels[criterion]);
  }
});

test("frontend de financiamento nao consome aliases depreciados", () => {
  const files = ["financingModel.js", "FinancingComparison.jsx", "FinancingResult.jsx"];
  const source = files.map((file) => readFileSync(new URL(`../src/features/financing/${file}`, import.meta.url), "utf8")).join("\n");
  assert.doesNotMatch(source, /total_interest_and_financed_costs|estimated_installment|compatibility_status|financed_principal/);
});

test("empate e exibido com valor e nomes em chips separados", () => {
  const component = readFileSync(new URL("../src/features/financing/FinancingComparison.jsx", import.meta.url), "utf8");
  assert.match(component, /Empate em \{value\}/);
  assert.match(component, /comparison-tie-list/);
  assert.match(component, /comparison-chip/);
  assert.doesNotMatch(component, /names\.join/);
});

test("resultado mostra parcela, total, encargos e desembolso separados", () => {
  const component = readFileSync(new URL("../src/features/financing/FinancingResult.jsx", import.meta.url), "utf8");
  assert.match(component, /Parcela regular/);
  assert.match(component, /Total pago na aquisição/);
  assert.match(component, /Acréscimo total do financiamento/);
  assert.match(component, /Diferença para compra à vista/);
  assert.match(component, /Custo mensal do veículo/);
  assert.match(component, /Desembolso mensal total/);
  assert.match(component, /Maior parcela do cronograma/);
});

test("custos insuficientes recebem estado e mensagem explicitos", () => {
  assert.match(getFinancingStatusLabel("insufficient_for_financed_costs"), /não cobre os custos adicionais/);
  assert.match(getCompatibilityLabel("insufficient_for_financed_costs"), /Parcela insuficiente/);
  const component = readFileSync(new URL("../src/features/financing/FinancingResult.jsx", import.meta.url), "utf8");
  assert.match(component, /A parcela máxima informada não é suficiente para financiar os custos adicionais desta proposta\./);
  assert.match(component, /required_financed_additional_costs/);
  assert.match(component, /available_vehicle_principal/);
  assert.match(component, /maximum_installment_in_schedule/);
});

test("mensagens de custos adicionais sao condicionais e CET usa texto proprio", () => {
  const component = readFileSync(new URL("../src/features/financing/FinancingResult.jsx", import.meta.url), "utf8");
  assert.match(component, /hasFinancedAdditionalCosts/);
  assert.match(component, /!cetIncludesCosts && hasFinancedAdditionalCosts/);
  assert.match(component, /O CET informado já representa os custos adicionais/);
  assert.match(component, /Custos adicionais financiados foram considerados separadamente/);
});

test("parcela regular e final sao apresentadas de forma reconciliavel", () => {
  const adjusted = getInstallmentPlanSummary({ regular_installment: 778.67, number_of_regular_installments: 35, final_installment: 778.62 }, (value) => `R$ ${value.toFixed(2)}`);
  assert.equal(adjusted, "35 parcelas de R$ 778.67 e uma parcela final de R$ 778.62");
  const equal = getInstallmentPlanSummary({ regular_installment: 900, number_of_regular_installments: 35, final_installment: 900 }, String);
  assert.equal(equal, "36 parcelas de 900");
});

test("interface nao promete credito e mantem aviso visivel", () => {
  const page = readFileSync(new URL("../src/features/financing/FinancingPage.jsx", import.meta.url), "utf8");
  const result = readFileSync(new URL("../src/features/financing/FinancingResult.jsx", import.meta.url), "utf8");
  assert.match(FINANCING_DISCLAIMER, /não representa proposta ou aprovação/);
  assert.match(page, /não garante aprovação/);
  assert.match(result, /FINANCING_DISCLAIMER/);
  assert.doesNotMatch(page, /credito garantido|chance de aprovacao|instituicao recomendada/i);
});

test("status financeiro e descritivo, nao decisao de credito", () => {
  assert.equal(getCompatibilityLabel("compatible"), "Compatível com os limites informados");
  assert.equal(getCompatibilityLabel("over_monthly_budget"), "Desembolso acima do orçamento");
  assert.equal(getAcquisitionStatusLabel("zero_financing_required"), "Compra não exige financiamento.");
  assert.match(getFinancingStatusLabel("within_installment_limit"), /dentro do limite/);
  assert.match(getMonthlyBudgetStatusLabel("over_monthly_budget"), /excedem o orçamento/);
});

test("resultado alterado fica stale e nao pode ser comparado", () => {
  const page = readFileSync(new URL("../src/features/financing/FinancingPage.jsx", import.meta.url), "utf8");
  const result = readFileSync(new URL("../src/features/financing/FinancingResult.jsx", import.meta.url), "utf8");
  assert.match(page, /setIsResultStale\(true\)/);
  assert.match(page, /requestIdRef/);
  assert.match(result, /Os dados foram alterados\. Recalcule a simulação\./);
  assert.equal(canAddFinancingScenario([], { regular_installment: 1000 }, true), false);
});

test("comparacao respeita limite de dez e remocao libera nova inclusao", () => {
  const ten = Array.from({ length: MAX_COMPARISON_SCENARIOS }, (_, index) => ({ name: `C${index}` }));
  assert.equal(canAddFinancingScenario(ten, { regular_installment: 1000 }, false), false);
  const nine = removeFinancingScenario(ten, 4);
  assert.equal(nine.length, 9);
  assert.equal(canAddFinancingScenario(nine, { regular_installment: 1000 }, false), true);
  const component = readFileSync(new URL("../src/features/financing/FinancingComparison.jsx", import.meta.url), "utf8");
  assert.match(component, /Remover/);
  assert.match(component, /\/10/);
});

test("navegacao principal expoe financiamento sem substituir carros ou motos", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(app, /Financiamento/);
  assert.match(app, /activeTab === "financing"/);
  assert.match(app, /FinancingPage cars=\{safeVehicles\}/);
  assert.match(app, /RecommendationPage/);
});
