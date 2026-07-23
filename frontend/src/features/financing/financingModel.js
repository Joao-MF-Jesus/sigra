export const FINANCING_DISCLAIMER = "Esta é uma simulação estimada e não representa proposta ou aprovação de crédito.";
export const MAX_COMPARISON_SCENARIOS = 10;

const REQUIRED_MONEY_FIELDS = ["down_payment", "upfront_fees", "financed_fees", "financed_insurance", "financed_services"];
const OPTIONAL_MONEY_FIELDS = ["desired_max_installment", "available_monthly_budget", "estimated_monthly_vehicle_cost"];

function parseNumber(value, { required = false, minimum = 0, greaterThan = false } = {}) {
  if (value === "" || value === null || value === undefined) {
    return required ? { error: "Campo obrigatório." } : { value: undefined };
  }
  const number = Number(value);
  if (!Number.isFinite(number)) return { error: "Informe um número válido." };
  if (greaterThan ? number <= minimum : number < minimum) {
    return { error: greaterThan ? `Deve ser maior que ${minimum}.` : `Não pode ser menor que ${minimum}.` };
  }
  return { value: number };
}

export function validateFinancingForm(form, mode = "direct") {
  const errors = {};
  const payload = { vehicle_type: form.vehicle_type, amortization_method: "price" };
  if (!["car", "motorcycle"].includes(form.vehicle_type)) errors.vehicle_type = "Selecione uma categoria válida.";

  if (mode === "direct") {
    if (form.price_mode === "catalog") {
      const vehicleId = parseNumber(form.vehicle_id, { required: true, minimum: 0, greaterThan: true });
      if (vehicleId.error) errors.vehicle_id = "Selecione um veículo.";
      else payload.vehicle_id = vehicleId.value;
      const negotiated = parseNumber(form.negotiated_price, { minimum: 0, greaterThan: true });
      if (negotiated.error) errors.negotiated_price = negotiated.error;
      else if (negotiated.value !== undefined) payload.negotiated_price = negotiated.value;
    } else {
      const price = parseNumber(form.vehicle_price, { required: true, minimum: 0, greaterThan: true });
      if (price.error) errors.vehicle_price = price.error;
      else payload.vehicle_price = price.value;
    }
  }

  for (const field of REQUIRED_MONEY_FIELDS) {
    const parsed = parseNumber(form[field], { required: true, minimum: 0 });
    if (parsed.error) errors[field] = parsed.error;
    else payload[field] = parsed.value;
  }
  for (const field of OPTIONAL_MONEY_FIELDS) {
    if (field === "desired_max_installment" && mode === "reverse") continue;
    const parsed = parseNumber(form[field], { minimum: 0 });
    if (parsed.error) errors[field] = parsed.error;
    else if (parsed.value !== undefined) payload[field] = parsed.value;
  }

  const term = parseNumber(form.term_months, { required: true, minimum: 1 });
  if (term.error || !Number.isInteger(term.value) || term.value > 120) errors.term_months = "Informe um prazo inteiro entre 1 e 120 meses.";
  else payload.term_months = term.value;

  if (mode === "reverse") {
    const maximum = parseNumber(form.maximum_installment, { required: true, minimum: 0 });
    if (maximum.error) errors.maximum_installment = maximum.error;
    else payload.maximum_installment = maximum.value;
  }

  if (form.rate_mode === "monthly") {
    const rate = parseNumber(form.monthly_interest_rate_percent, { required: true, minimum: 0 });
    if (rate.error || rate.value > 100) errors.monthly_interest_rate_percent = "Informe a taxa mensal entre 0 e 100%.";
    else payload.monthly_interest_rate_percent = rate.value;
  } else if (form.rate_mode === "effective") {
    const rate = parseNumber(form.effective_cost_rate_percent, { required: true, minimum: 0 });
    if (rate.error || rate.value > 1000) errors.effective_cost_rate_percent = "Informe o CET entre 0 e 1000%.";
    else payload.effective_cost_rate_percent = rate.value;
    if (!["monthly", "annual"].includes(form.effective_cost_rate_period)) errors.effective_cost_rate_period = "Selecione o período do CET.";
    else payload.effective_cost_rate_period = form.effective_cost_rate_period;
    if (!["yes", "no"].includes(form.effective_rate_includes_additional_costs)) errors.effective_rate_includes_additional_costs = "Informe se o CET inclui os custos adicionais.";
    else {
      payload.effective_rate_includes_additional_costs = form.effective_rate_includes_additional_costs === "yes";
      if (payload.effective_rate_includes_additional_costs) {
        for (const field of ["financed_fees", "financed_insurance", "financed_services"]) {
          if (payload[field] > 0) errors[field] = "Este custo já está representado pelo CET informado.";
        }
      }
    }
  } else {
    errors.rate_mode = "Selecione taxa mensal ou CET informado.";
  }

  if (mode === "direct") {
    if (form.offer_name.trim()) payload.offer_name = form.offer_name.trim();
    if (form.institution_name.trim()) payload.institution_name = form.institution_name.trim();
    if (form.offer_reference.trim()) payload.offer_reference = form.offer_reference.trim();
    if (form.offer_date) payload.offer_date = form.offer_date;
    const price = payload.negotiated_price ?? payload.vehicle_price;
    if (price !== undefined && payload.down_payment > price) errors.down_payment = "A entrada não pode superar o preço utilizado.";
  }
  if (form.notes.trim()) payload.notes = form.notes.trim();
  return { isValid: Object.keys(errors).length === 0, errors, payload };
}

export function applyFinancingFormChange(form, field, value) {
  const next = { ...form, [field]: value };
  if (field === "vehicle_type") {
    next.vehicle_id = "";
    next.vehicle_price = "";
    next.negotiated_price = "";
  }
  if (field === "price_mode") {
    if (value === "manual") {
      next.vehicle_id = "";
      next.negotiated_price = "";
    } else {
      next.vehicle_price = "";
    }
  }
  if (field === "vehicle_id") next.negotiated_price = "";
  if (field === "rate_mode") {
    if (value === "monthly") {
      next.effective_cost_rate_percent = "";
      next.effective_cost_rate_period = "";
      next.effective_rate_includes_additional_costs = "";
    } else {
      next.monthly_interest_rate_percent = "";
    }
  }
  if (field === "effective_rate_includes_additional_costs" && value === "yes") {
    next.financed_fees = "0";
    next.financed_insurance = "0";
    next.financed_services = "0";
  }
  return next;
}

export function canAddFinancingScenario(savedScenarios, result, isStale) {
  return Boolean(result) && !isStale && savedScenarios.length < MAX_COMPARISON_SCENARIOS;
}

export function removeFinancingScenario(savedScenarios, indexToRemove) {
  return savedScenarios.filter((_, index) => index !== indexToRemove);
}

export function getInstallmentPlanSummary(result, formatValue = String) {
  const regular = Number(result?.regular_installment ?? 0);
  const final = Number(result?.final_installment ?? regular);
  const regularCount = Number(result?.number_of_regular_installments ?? 0);
  if (regular === 0 && final === 0) return "Sem parcelas de financiamento.";
  if (Math.round(regular * 100) === Math.round(final * 100)) {
    return `${regularCount + 1} parcelas de ${formatValue(regular)}`;
  }
  return `${regularCount} parcelas de ${formatValue(regular)} e uma parcela final de ${formatValue(final)}`;
}

export function getFinancingStatusLabel(status) {
  return ({
    financing_required: "Limite de parcela não informado.",
    zero_financing_required: "Não há parcela de financiamento.",
    within_installment_limit: "Maior parcela dentro do limite informado.",
    over_installment_limit: "Maior parcela acima do limite informado.",
    insufficient_for_financed_costs: "A parcela máxima não cobre os custos adicionais informados.",
  })[status] || "Situação da parcela não informada.";
}

export function getAcquisitionStatusLabel(status) {
  if (status === "zero_financing_required") return "Compra não exige financiamento.";
  if (status === "insufficient_for_financed_costs") return "Compra limitada ao valor disponível de entrada.";
  return "Aquisição utiliza financiamento.";
}

export function getMonthlyBudgetStatusLabel(status) {
  return ({
    within_budget: "Custos mensais dentro do orçamento.",
    near_limit: "Custos mensais próximos do limite.",
    over_monthly_budget: "Os custos mensais estimados excedem o orçamento informado.",
    insufficient_input: "Orçamento mensal não pôde ser avaliado.",
  })[status] || "Situação mensal não informada.";
}

export function getCompatibilityLabel(status) {
  return ({
    compatible: "Compatível com os limites informados",
    near_limit: "Próximo dos limites informados",
    over_installment_limit: "Maior parcela acima do limite",
    over_monthly_budget: "Desembolso acima do orçamento",
    insufficient_input: "Compatibilidade parcial por falta de dados",
    zero_financing_required: "Financiamento não necessário",
    insufficient_for_financed_costs: "Parcela insuficiente para os custos",
  })[status] || "Status não informado";
}

export function comparisonCriteriaLabels() {
  return {
    lowest_installment: "Menor parcela",
    lowest_total_acquisition_outflow: "Menor custo total da aquisição",
    lowest_total_financing_addition: "Menor acréscimo total do financiamento",
    lowest_total_installments: "Menor total das parcelas",
    shortest_term: "Menor prazo",
    lowest_budget_commitment: "Menor comprometimento mensal",
    highest_down_payment: "Maior entrada",
  };
}

export function getComparisonScopeLabel(scope) {
  return ({
    same_vehicle_same_price: "Mesmo veículo e mesma base de preço",
    same_vehicle_different_price: "Mesmo veículo com preços diferentes",
    different_vehicles: "Veículos diferentes",
    mixed_manual_and_catalog: "Preço manual e catálogo combinados",
    different_acquisition_scenarios: "Cenários de aquisição diferentes",
  })[scope] || "Escopo não informado";
}

export function getFinancialContextStatusLabel(status) {
  return ({
    comparable: "Contextos mensais comparáveis",
    different_monthly_budgets: "Orçamentos mensais diferentes",
    different_vehicle_cost_bases: "Custos mensais do veículo diferentes",
    different_budget_and_vehicle_cost: "Orçamentos e custos mensais diferentes",
    insufficient_budget_data: "Orçamento mensal incompleto",
    insufficient_vehicle_cost_data: "Custo mensal do veículo incompleto",
    insufficient_financial_context: "Contexto financeiro incompleto",
  })[status] || "Contexto financeiro não informado";
}

export function getFinancialContextMessage(status) {
  return ({
    comparable: "Os percentuais usam o mesmo orçamento e o mesmo custo mensal do veículo.",
    different_monthly_budgets: "Os cenários usam orçamentos mensais diferentes. Compare os percentuais individualmente.",
    different_vehicle_cost_bases: "Os cenários usam custos mensais do veículo diferentes. Compare os percentuais individualmente.",
    different_budget_and_vehicle_cost: "Os cenários usam orçamentos e custos mensais distintos. Compare os percentuais individualmente.",
    insufficient_budget_data: "Falta orçamento mensal em pelo menos um cenário. Não há vencedor para comprometimento.",
    insufficient_vehicle_cost_data: "Falta custo mensal do veículo em pelo menos um cenário. Não há vencedor para comprometimento.",
    insufficient_financial_context: "Os dados mensais são insuficientes. Não há vencedor para comprometimento.",
  })[status] || "O comprometimento mensal deve ser analisado em cada cenário.";
}

export function formatComparisonValue(detail, formatCurrency) {
  if (detail?.value === null || detail?.value === undefined) return "Valor não disponível";
  if (detail.unit === "months") return `${detail.value} ${Number(detail.value) === 1 ? "mês" : "meses"}`;
  if (detail.unit === "percentage") return `${Number(detail.value).toLocaleString("pt-BR")}%`;
  const formatted = formatCurrency(detail.value);
  return detail.unit === "currency_monthly" ? `${formatted} por mês` : formatted;
}

export function getComparisonDifferenceLabel(detail, scope, scenarioCount, formatCurrency, financialContextComparable = true) {
  if (detail?.difference_to_next === null || detail?.difference_to_next === undefined || detail.is_tie) return "";
  let value;
  if (detail.unit === "months") value = `${detail.difference_to_next} meses`;
  else if (detail.unit === "percentage") value = `${Number(detail.difference_to_next).toLocaleString("pt-BR")} p.p.`;
  else value = formatCurrency(detail.difference_to_next);

  const directlyEquivalent = scope === "same_vehicle_same_price" && financialContextComparable;
  if (!directlyEquivalent) return `Diferença de ${value} para o próximo cenário.`;
  if (scenarioCount === 2 && ["currency", "currency_monthly"].includes(detail.unit)) {
    return detail.unit === "currency_monthly"
      ? `${value} abaixo da outra proposta.`
      : `Economia estimada de ${value}.`;
  }
  return `Diferença para o próximo cenário: ${value}.`;
}
