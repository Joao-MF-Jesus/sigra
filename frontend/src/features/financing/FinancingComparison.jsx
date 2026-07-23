import React from "react";
import {
  comparisonCriteriaLabels,
  formatComparisonValue,
  getComparisonDifferenceLabel,
  getComparisonScopeLabel,
  getFinancialContextMessage,
  getFinancialContextStatusLabel,
} from "./financingModel.js";

const currency = (value) => new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value || 0));

export default function FinancingComparison({ savedScenarios, result, loading, error, notice, onCompare, onRemove, onClear }) {
  const labels = comparisonCriteriaLabels();
  const details = result?.highlight_details || {};
  const context = result?.comparison_context || {};
  const contextStatus = context.monthly_commitment_comparison_status;
  const financialContextComparable = context.financial_context_comparable === true;
  return <section className="financing-comparison" data-testid="financing-comparison">
    <div className="comparison-heading"><div><p className="eyebrow">Comparação de propostas</p><h3>Cenários salvos ({savedScenarios.length}/10)</h3></div><div className="comparison-actions"><button type="button" className="ghost-button" onClick={onClear} disabled={!savedScenarios.length}>Limpar</button><button type="button" data-testid="compare-financing-scenarios" onClick={onCompare} disabled={loading || savedScenarios.length < 2}>{loading ? "Comparando..." : "Comparar cenários"}</button></div></div>
    {savedScenarios.length < 2 && <p className="section-note">Calcule e adicione pelo menos dois cenários. Altere entrada, prazo, taxa ou proposta antes de calcular novamente.</p>}
    {notice && <div className="financing-warning">{notice}</div>}
    {savedScenarios.length > 0 && <div className="saved-scenarios">{savedScenarios.map((scenario, index) => <div key={`${scenario.name}-${index}`}><strong>{scenario.name}</strong><span>{scenario.payload.term_months} meses</span><span>{currency(scenario.result.maximum_installment_in_schedule)}/mês</span><span>{scenario.result.budget_commitment_percentage == null ? "Comprometimento não calculado" : `${Number(scenario.result.budget_commitment_percentage).toLocaleString("pt-BR")}% do orçamento`}</span><button type="button" className="ghost-button" onClick={() => onRemove(index)}>Remover</button></div>)}</div>}
    {error && <div className="api-error">{error}</div>}
    {result && <>
      <div className="comparison-context-grid">
        <div className="comparison-scope"><span>Escopo da comparação</span><strong>{getComparisonScopeLabel(context.comparison_scope || result.comparison_scope)}</strong></div>
        <div className="comparison-scope"><span>Contexto mensal</span><strong>{getFinancialContextStatusLabel(contextStatus)}</strong></div>
      </div>
      {result.warnings?.slice(1).map((warning) => <div className="financing-warning" key={warning}>{warning}</div>)}
      <div className="comparison-highlights">{Object.entries(details).map(([criterion, detail]) => {
        const names = detail?.scenario_names || [];
        if (!names.length) return null;
        const value = formatComparisonValue(detail, currency);
        const difference = getComparisonDifferenceLabel(detail, context.comparison_scope || result.comparison_scope, result.scenario_count, currency, financialContextComparable);
        return <div className="comparison-highlight" data-testid={`highlight-${criterion}`} key={criterion}>
          <span>{labels[criterion] || criterion}</span>
          {detail.is_tie ? <>
            <strong>Empate em {value}</strong>
            <div className="comparison-tie-list">{names.map((name) => <span className="comparison-chip" key={name}>{name}</span>)}</div>
          </> : <>
            <strong>{names[0]}</strong>
            <b>{value}</b>
          </>}
          {difference && <small>{difference}</small>}
        </div>;
      })}
      {(result.suppressed_highlights || []).map((item) => <div className="comparison-highlight comparison-highlight-suppressed" data-testid={`suppressed-${item.criterion}`} key={item.criterion}>
        <span>{labels[item.criterion] || item.criterion}</span>
        <strong>{getFinancialContextStatusLabel(item.reason)}</strong>
        <p>{getFinancialContextMessage(item.reason)}</p>
      </div>)}</div>
      <p className="financing-disclaimer">Os destaques comparam critérios isolados. Menor parcela não significa automaticamente menor custo total ou melhor proposta.</p>
    </>}
  </section>;
}
