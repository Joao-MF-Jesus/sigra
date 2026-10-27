import React from "react";
import { formatCurrency, formatScore } from "./recommendationModel.js";
import { COST_LABELS, TECHNICAL_LABELS, readableValue, referenceMonth, recommendationReasons, criterionCoverage } from "./cohortPresentation.js";
import SevenCriteriaBreakdown from "./SevenCriteriaBreakdown.jsx";

function DetailGrid({ items }) {
  return <dl className="spec-list modal-spec-list">{items.map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value}</dd></div>)}</dl>;
}
export default function CohortVehicleDetails({ item, onClose, dialogRef, closeButtonRef }) {
  const detail = item.detailState;
  const evaluation = item.evaluation;
  const coverage = criterionCoverage(item);
  const fields = detail?.data?.evidence?.fields || item.vehicle.technical_fields || {};
  const costs = evaluation.scenario_costs?.components || {};
  const missingRequirements = (item.multifactor?.evidence_coverage?.criteria || [])
    .filter((criterion) => criterion.requested && !criterion.available && criterion.requirement_message);
  const sources = [...new Set(Object.values(detail?.data?.evidence?.fields || {}).flatMap((field) => (field.sources || []).map((source) => source.provider)))];
  return <div className="modal-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section ref={dialogRef} className="details-modal" role="dialog" aria-modal="true" aria-labelledby="vehicle-details-title" aria-describedby="vehicle-details-description">
      <div className="modal-header"><div><p className="eyebrow">Detalhes da recomendação</p><h2 id="vehicle-details-title">{item.vehicle.label}</h2><p id="vehicle-details-description">Dados do veículo e composição do custo mensal estimado</p></div><button ref={closeButtonRef} className="ghost-button modal-close" type="button" onClick={onClose}>Fechar</button></div>
      <div className="modal-body" data-testid="vehicle-details-scroll">
        {detail?.loading && <p role="status">Carregando ficha técnica…</p>}
        {detail?.error && <div role="alert"><p>{detail.error}</p><button type="button" onClick={detail.onRetry}>Tentar novamente</button></div>}
        <DetailGrid items={[["Preço FIPE", formatCurrency(item.vehicle.purchase_price_brl)], ["Referência FIPE", referenceMonth(item.vehicle.price_reference_month)], ...Object.entries(TECHNICAL_LABELS).map(([key, label]) => [label, readableValue(fields[key])])]} />
        <section className="modal-section"><h3>Detalhamento do TCO mensal</h3><p>Estimativa para o cenário informado; não representa despesas observadas.</p><DetailGrid items={[...Object.entries(COST_LABELS).map(([key, label]) => [label, readableValue(costs[key])]), ["Total mensal", formatCurrency(item.monthly_total_cost) + "/mês"]]} /></section>
        <div className="modal-summary-grid"><article><span>{item.multifactor?.status === "ranked" ? "Nota personalizada" : "Nota de referência"}</span><strong>{formatScore(item.score)}</strong></article><article><span>{coverage.label}</span><strong>{readableValue({ value: coverage.value, unit: "%" })}</strong></article></div>
        <SevenCriteriaBreakdown breakdown={item.multifactor?.criterion_calculations} />
        <section className="modal-section"><h3>Por que esta opção?</h3><ul>{recommendationReasons(item).map((reason) => <li key={reason}>{reason}</li>)}</ul></section>
        {evaluation.academic_path === "academic_habitability_proxy" && <p className="field-hint">Habitabilidade é um indicador derivado das dimensões externas; não é espaço interno medido.</p>}
        <details className="modal-section data-provenance"><summary>Fontes e metodologia</summary><p>Fontes da ficha: {sources.length ? sources.map((name) => name.toUpperCase()).join(", ") : "FIPE e evidências documentais publicadas"}.</p><p>A confiança é descritiva, sem percentual estatístico inventado. Campos ausentes permanecem não informados. Custos de manutenção, impostos, seguro e depreciação utilizam hipóteses explícitas do cenário.</p><p>A classificação de referência utiliza os critérios documentais do perfil. A personalização solicitada só recebe nota quando todos os critérios com peso positivo têm evidência suficiente. O critério de custo da política original compara combustível no horizonte informado; o TCO exibido inclui também os demais custos do cenário.</p>{coverage.missingLabels.length > 0 && <p>Critérios solicitados sem avaliação: {coverage.missingLabels.join(", ")}. A cobertura não redistribui seus pesos nem produz uma nota parcial.</p>}{missingRequirements.length > 0 && <ul aria-label="Entradas necessárias à personalização">{missingRequirements.map((criterion) => <li key={criterion.criterion}><strong>{criterion.label}:</strong> {criterion.requirement_message}</li>)}</ul>}</details>
      </div>
    </section>
  </div>;
}
