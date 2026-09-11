import React from "react";
import { formatCurrency, formatScore, getMultifactorUnavailablePresentation } from "./recommendationModel.js";

export default function MultifactorBreakdown({ item, compact = false }) {
  const multifactor = item?.multifactor;
  if (!multifactor?.enabled) return null;
  // The ranking has one consolidated notice; keep the individual reason in details.
  if (multifactor.status !== "ranked" && compact) return null;
  if (multifactor.status !== "ranked") return <section className="multifactor-breakdown unavailable" data-testid="multifactor-unavailable"><h4>Comparação personalizada indisponível</h4><p>{getMultifactorUnavailablePresentation(multifactor.reason_code, multifactor.identity_diagnostic)}</p><small>O veículo continua visível na classificação original, sem nota inventada.</small></section>;
  const cost = multifactor.cost || {};
  const rows = compact ? (multifactor.components || []).slice(0, 3) : (multifactor.components || []);
  return <section className="multifactor-breakdown" data-testid="multifactor-breakdown">
    <h4>Ranking multifator #{multifactor.position}</h4>
    <p>Nota {formatScore(multifactor.final_score)} · posição original #{multifactor.baseline_position} ({formatScore(multifactor.baseline_score)})</p>
    <p><strong>Custo de combustível projetado:</strong> {formatCurrency(cost.projected_horizon_cost_brl)} em {cost.horizon_months} meses</p>
    <div className="multifactor-components">
      {rows.map((row) => <div key={row.component}><span>{row.label}</span><span>{formatScore(row.raw_score)} × {row.normalized_weight_percentage}%</span><strong>{formatScore(row.contribution)}</strong></div>)}
    </div>
    {!compact && <>
      <p className="field-hint">O custo acima representa combustível no cenário informado, não o custo total de propriedade. A referência analítica serve apenas para comparação e não impõe parâmetros ao usuário.</p>
      <details className="data-provenance"><summary>Sobre os dados</summary><p>Fontes de referência: FIPE, PBEV e ANP.</p></details>
      {[...(multifactor.warnings || []), ...(multifactor.limitations || [])].length > 0 && <ul>{[...(multifactor.warnings || []), ...(multifactor.limitations || [])].map((message) => <li key={message}>{message}</li>)}</ul>}
    </>}
  </section>;
}
