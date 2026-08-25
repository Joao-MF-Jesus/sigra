import React from "react";
import { formatCurrency, formatScore, getMultifactorUnavailablePresentation } from "./recommendationModel.js";

function versionRows(sources = {}) {
  return [
    ["Gold integrada", sources.integrated_dataset_version],
    ["Gold FIPE", sources.fipe_dataset_version],
    ["PBEV shadow", sources.pbev_dataset_version],
    ["ANP shadow", sources.anp_dataset_version],
  ].filter(([, value]) => value);
}

export default function MultifactorBreakdown({ item, compact = false }) {
  const multifactor = item?.multifactor;
  if (!multifactor?.enabled) return null;
  if (multifactor.status !== "ranked") return <section className="multifactor-breakdown unavailable" data-testid="multifactor-unavailable"><h4>Evidência multifator não disponível</h4><p>{getMultifactorUnavailablePresentation(multifactor.reason_code)}</p><small>O veículo continua visível no baseline, sem nota multifator inventada.</small></section>;
  const cost = multifactor.cost || {};
  const rows = compact ? (multifactor.components || []).slice(0, 3) : (multifactor.components || []);
  return <section className="multifactor-breakdown" data-testid="multifactor-breakdown">
    <h4>Ranking multifator #{multifactor.position}</h4>
    <p>Nota {formatScore(multifactor.final_score)} · baseline #{multifactor.baseline_position} ({formatScore(multifactor.baseline_score)})</p>
    <p><strong>Custo de combustível projetado:</strong> {formatCurrency(cost.projected_horizon_cost_brl)} em {cost.horizon_months} meses</p>
    <div className="multifactor-components">
      {rows.map((row) => <div key={row.component}><span>{row.label}</span><span>{formatScore(row.raw_score)} × {row.normalized_weight_percentage}%</span><strong>{formatScore(row.contribution)}</strong></div>)}
    </div>
    {!compact && <>
      <p className="field-hint">O custo acima representa combustível no cenário informado, não um TCO completo. O cenário mixed_1000_v1 é apenas a referência analítica de comparação.</p>
      <dl className="multifactor-sources">{versionRows(cost.sources).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      {[...(multifactor.warnings || []), ...(multifactor.limitations || [])].length > 0 && <ul>{[...(multifactor.warnings || []), ...(multifactor.limitations || [])].map((message) => <li key={message}>{message}</li>)}</ul>}
    </>}
  </section>;
}
