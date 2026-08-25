import React from "react";
import ConfidenceIndicator from "./ConfidenceIndicator.jsx";
import { formatCurrency, formatScore, getConfidence, getMaintenanceMetric, getPartsMetric, getRecommendationStatusLabel } from "./recommendationModel.js";
import VehicleCostSimulationPanel from "../vehicle-cost-simulation/VehicleCostSimulationPanel.jsx";
import MultifactorBreakdown from "./MultifactorBreakdown.jsx";

function DetailGrid({ items }) {
  return <dl className="spec-list modal-spec-list">{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>;
}

export default function RecommendationDetails({ item, metadata, profile, onClose, onParts, onCompare }) {
  if (!item) return null;
  const vehicle = item.vehicle;
  const confidence = item.confidence || item.recommendation_summary?.confidence || {};
  const confidenceView = getConfidence(item);
  const maintenance = getMaintenanceMetric(item);
  const parts = getPartsMetric(item);
  const tco = item.tco || {};
  const confidenceDetails = [
    ...(confidence.reasons || []),
    ...(confidence.limitations || []),
    ...(confidence.missing_fields || []).map((field) => `Campo ausente: ${field}.`),
  ];
  return <div className="modal-overlay" role="presentation" onClick={onClose}><section className="details-modal" role="dialog" aria-modal="true" aria-labelledby="vehicle-details-title" onClick={(event) => event.stopPropagation()}>
    <div className="modal-header"><div><p className="eyebrow">Detalhes da recomendação</p><h2 id="vehicle-details-title">{vehicle.brand} {vehicle.model}</h2><p>{vehicle.year}</p></div><button className="ghost-button modal-close" type="button" onClick={onClose}>Fechar</button></div>
    <DetailGrid items={[["Ano", vehicle.year], ["Preço de referência", formatCurrency(vehicle.price)], ["Consumo", `${vehicle.fuel_efficiency_km_l} km/l`], [maintenance.label, maintenance.value], [parts.label, parts.value], ["Confiabilidade mecânica", formatScore(vehicle.reliability_score)]]} />
    <section className="modal-section"><h3>Detalhamento do TCO mensal</h3><DetailGrid items={[["Combustível", formatCurrency(tco.monthly_fuel_cost)], ["Manutenção", formatCurrency(tco.monthly_maintenance_cost)], ["IPVA", formatCurrency(tco.monthly_ipva_cost)], ["Seguro", formatCurrency(tco.monthly_insurance_cost)], ["Depreciação", formatCurrency(tco.monthly_depreciation_cost)], ["Total mensal", formatCurrency(tco.total_monthly_cost)]]} /></section>
    <div className="modal-summary-grid"><article><span>Status</span><strong>{getRecommendationStatusLabel(item.recommendation_status)}</strong></article><article><span>Nota SIGRA</span><strong>{formatScore(item.score)}</strong></article><article><span>Financeiro</span><strong>{formatScore(item.score_components?.financial_score)}</strong></article>{Number.isFinite(Number(item.decision_score)) && <article><span>Índice complementar de valor</span><strong>{formatScore(item.decision_score)}</strong></article>}</div>
    {Number.isFinite(Number(item.decision_score)) && <p className="field-hint">Indicador complementar que combina compatibilidade e valor percebido. Ele não determina isoladamente a posição no ranking.</p>}
    <section className="modal-section confidence-details"><h3>Confiança dos dados</h3><ConfidenceIndicator item={item} /><p>A Nota SIGRA mede a compatibilidade do veículo com o perfil informado. A confiança mede a cobertura, atualidade e qualidade dos dados utilizados.</p>{confidenceDetails.length > 0 && <ul>{confidenceDetails.map((text) => <li key={text}>{text}</li>)}</ul>}<p>{confidence.disclaimer}</p><p>Referência temporal: {metadata?.data_reference || "não informada"}. Confiança classificada como {confidenceView.level}.</p></section>
    <section className="modal-section"><h3>Explicação completa</h3><ul>{(item.explanations || []).map((text) => <li key={text}>{text}</li>)}</ul></section>
    <MultifactorBreakdown item={item} />
    <section className="modal-section recommendation-simulation-context" aria-labelledby="vehicle-simulation-title"><h3 id="vehicle-simulation-title">Simule este veículo no seu cenário</h3><p>Use a mesma necessidade de deslocamento para aprofundar o custo de combustível. O cálculo permanece no backend e não altera o ranking nem a Gold publicada.</p></section>
    <VehicleCostSimulationPanel vehicle={vehicle} profile={profile} />
    <div className="modal-actions"><button className="ghost-button" type="button" onClick={() => onParts(item)}>Ver peças</button><button className="ghost-button" type="button" onClick={() => onCompare(item)}>Comparar</button></div>
  </section></div>;
}
