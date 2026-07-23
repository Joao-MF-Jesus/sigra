import React from "react";
import {
  FINANCING_DISCLAIMER,
  getAcquisitionStatusLabel,
  getCompatibilityLabel,
  getFinancingStatusLabel,
  getInstallmentPlanSummary,
  getMonthlyBudgetStatusLabel,
} from "./financingModel.js";

const currency = (value) => value === null || value === undefined ? "Não calculado" : new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(value);

function Metric({ label, value, emphasis = false, testId }) {
  return <div className={emphasis ? "financing-metric emphasis" : "financing-metric"} data-testid={testId}><span>{label}</span><strong>{value}</strong></div>;
}

export default function FinancingResult({ mode, result, isStale = false, canAddComparison = true, comparisonLimitReached = false, onAddComparison }) {
  if (!result) return <section className="financing-empty"><strong>Preencha os dados da proposta para simular.</strong><p>A parcela, os encargos e o desembolso mensal serão apresentados separadamente.</p></section>;
  const reverse = mode === "reverse";
  const overallStatus = result.overall_status;
  const financingStatus = result.financing_status;
  const monthlyBudgetStatus = result.monthly_budget_status;
  const installmentSummary = getInstallmentPlanSummary(result, currency);
  const insufficientCosts = financingStatus === "insufficient_for_financed_costs";
  const hasFinancedAdditionalCosts = result.has_financed_additional_costs ?? Number(result.financed_additional_costs || 0) > 0;
  const cetIncludesCosts = result.rate?.input_mode === "informed_effective_cost_rate" && result.rate?.effective_rate_includes_additional_costs === true;
  const visibleWarnings = (result.warnings || []).filter((warning) => !(insufficientCosts && warning.includes("parcela maxima informada")));

  return <section className={`financing-result ${isStale ? "stale" : ""}`} aria-live="polite" data-testid="financing-result">
    {isStale && <div className="stale-warning" data-testid="financing-stale-warning"><strong>Resultado desatualizado</strong><span>Os dados foram alterados. Recalcule a simulação.</span></div>}
    {insufficientCosts && <div className="financing-warning"><strong>Custos adicionais fora da capacidade</strong><p>A parcela máxima informada não é suficiente para financiar os custos adicionais desta proposta.</p></div>}
    <div className="financing-result-header"><div><p className="eyebrow">Resultado estimado</p><h3>{reverse ? "Capacidade aproximada de compra" : result.offer?.name || "Cenário calculado"}</h3></div><span className={`compatibility-badge ${overallStatus}`}>{getCompatibilityLabel(overallStatus)}</span></div>
    <div className="financing-metrics">
      {reverse ? <>
        <Metric label="Preço máximo aproximado" value={currency(result.maximum_vehicle_price)} emphasis />
        <Metric label="Capacidade matemática financiável" value={currency(result.maximum_financed_amount)} />
        <Metric label="Custos adicionais solicitados" value={currency(result.required_financed_additional_costs)} />
        <Metric label="Principal disponível para o veículo" value={currency(result.available_vehicle_principal)} />
        <Metric label="Valor efetivamente financiado" value={currency(result.total_financed_amount)} />
        <Metric label="Parcela regular" value={currency(result.regular_installment)} testId="financing-regular-installment" />
        <Metric label="Maior parcela do cronograma" value={currency(result.maximum_installment_in_schedule)} emphasis />
        <Metric label="Total estimado da aquisição" value={currency(result.total_acquisition_outflow)} testId="financing-total-acquisition" />
      </> : <>
        <Metric label="Preço utilizado" value={currency(result.price_used)} />
        <Metric label="Preço de catálogo" value={currency(result.catalog_price)} />
        <Metric label="Preço manual" value={currency(result.manual_price)} />
        <Metric label="Preço negociado" value={currency(result.negotiated_price)} />
        <Metric label="Entrada" value={currency(result.down_payment)} />
        <Metric label="Principal do veículo financiado" value={currency(result.financed_vehicle_principal)} />
        <Metric label="Custos adicionais financiados" value={currency(result.financed_additional_costs)} />
        <Metric label="Valor total financiado" value={currency(result.total_financed_amount)} />
        <Metric label="Parcela regular" value={currency(result.regular_installment)} testId="financing-regular-installment" />
        <Metric label="Maior parcela do cronograma" value={currency(result.maximum_installment_in_schedule)} emphasis />
        <Metric label="Total das parcelas" value={currency(result.total_installments)} />
        <Metric label="Total pago na aquisição" value={currency(result.total_acquisition_outflow)} testId="financing-total-acquisition" />
        <Metric label="Acréscimo total do financiamento" value={currency(result.total_financing_addition)} />
        {result.interest_estimate != null && <Metric label="Estimativa de juros" value={currency(result.interest_estimate)} />}
        <Metric label="Diferença para compra à vista" value={currency(result.difference_from_cash_price)} />
      </>}
      <Metric label="Custo mensal do veículo" value={currency(result.estimated_monthly_vehicle_cost)} />
      <Metric label="Desembolso mensal total" value={currency(result.total_monthly_outflow)} emphasis />
      <Metric label="Margem mensal restante" value={currency(result.monthly_budget_remaining)} />
      <Metric label="Comprometimento do orçamento" value={result.budget_commitment_percentage == null ? "Não calculado" : `${Number(result.budget_commitment_percentage).toLocaleString("pt-BR")}%`} />
    </div>
    <div className="installment-summary"><strong>Composição das parcelas</strong><p>{installmentSummary}</p><small>O limite considera a maior parcela exibida no cronograma.</small></div>
    <div className="financial-status-grid"><div><span>Situação da aquisição</span><strong>{getAcquisitionStatusLabel(financingStatus)}</strong></div><div><span>Situação da parcela</span><strong>{getFinancingStatusLabel(financingStatus)}</strong></div><div><span>Situação do orçamento mensal</span><strong>{getMonthlyBudgetStatusLabel(monthlyBudgetStatus)}</strong></div><div><span>Situação geral</span><strong>{getCompatibilityLabel(overallStatus)}</strong></div></div>
    <div className="rate-summary"><strong>Taxa considerada</strong><p>{result.rate?.input_mode === "informed_effective_cost_rate" ? `CET informado; equivalente mensal de ${result.rate.effective_monthly_rate_percent}%` : `${result.rate?.effective_monthly_rate_percent}% ao mês`}</p><small>{result.rate?.note}</small></div>
    {cetIncludesCosts && <p className="section-note">O CET informado já representa os custos adicionais declarados como incluídos.</p>}
    {!cetIncludesCosts && hasFinancedAdditionalCosts && result.additional_costs_considered_separately && <p className="section-note">Custos adicionais financiados foram considerados separadamente.</p>}
    {result.is_demonstration_data && <p className="financing-warning">O preço de referência vem de dados demonstrativos ou ainda não sincronizados.</p>}
    {visibleWarnings.length > 0 && <ul className="financing-warnings">{visibleWarnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>}
    {!reverse && <button type="button" className="ghost-button" data-testid="add-financing-comparison" disabled={!canAddComparison} onClick={onAddComparison}>{comparisonLimitReached ? "Limite de 10 cenários atingido" : isStale ? "Recalcule para adicionar" : "Adicionar este cenário à comparação"}</button>}
    <p className="financing-disclaimer" data-testid="financing-credit-disclaimer">{FINANCING_DISCLAIMER}</p>
  </section>;
}
