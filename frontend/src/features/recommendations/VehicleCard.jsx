import React from "react";
import ConfidenceIndicator from "./ConfidenceIndicator.jsx";
import { formatCurrency, formatScore, getMaintenanceMetric, getPartsMetric, getRankingPresentation, getRecommendationStatusLabel } from "./recommendationModel.js";
import MultifactorBreakdown from "./MultifactorBreakdown.jsx";
import { readableValue, referenceMonth, recommendationReasons, cohortImagePath, criterionCoverage } from "./cohortPresentation.js";

function imagePath(vehicle) {
  return vehicle.image_url || `/cars/${vehicle.brand}-${vehicle.model}-${vehicle.year}`.toLowerCase().replaceAll(" ", "-").replaceAll(".", "") + ".svg";
}

function handleImageError(event) {
  event.currentTarget.style.display = "none";
  event.currentTarget.parentElement?.classList.add("image-failed");
}

export default function VehicleCard({ item, index, onDetails, onParts, onCompare }) {
  const cohort = item.vehicle.identity_namespace === "academic_v6";
  const coverage = cohort ? criterionCoverage(item) : null;
  const image = cohort ? cohortImagePath(item.vehicle.label) : imagePath(item.vehicle);
  const maintenance = getMaintenanceMetric(item);
  const parts = getPartsMetric(item);
  const ranking = getRankingPresentation(item, index);
  const strengths = (item.category_awards || []).map((award) => award.label).slice(0, 2);
  const cautions = [...new Set(item.penalties || [])].slice(0, 1);
  return (
    <article className={`vehicle-card ranking-${ranking.tone} ${item.recommendation_status === "not_recommended" ? "not-recommended" : ""} ${item.is_best_choice ? "best-choice" : ""} ${item.is_best_available_reference ? "comparative-reference" : ""}`}>
      <div className={`car-image-wrap${!image ? " image-failed" : ""}`}>{image && <img className="car-image" src={image} alt={cohort ? item.vehicle.label : `${item.vehicle.brand} ${item.vehicle.model} ${item.vehicle.year}`} onError={handleImageError} />}<span className="car-image-fallback">Imagem demonstrativa indisponível</span></div>
      <div className="card-rank">{cohort ? `#${index + 1} ${item.multifactor?.status === "ranked" ? "COMPARAÇÃO PERSONALIZADA" : "COMPARAÇÃO DE REFERÊNCIA"}` : ranking.label}</div>
      <div className="vehicle-topline"><div><h3>{cohort ? item.vehicle.label : `${item.vehicle.brand} ${item.vehicle.model}`}</h3><p>{cohort ? `FIPE · ${referenceMonth(item.vehicle.price_reference_month)}` : item.vehicle.year}</p></div><strong><span>{cohort && item.multifactor?.status !== "ranked" ? "Nota de referência" : "Nota SIGRA"}</span>{formatScore(item.score)}</strong></div>
      {cohort ? <div className="confidence-indicator compact"><span>{coverage.label}</span><strong>{readableValue({ value: coverage.value, unit: "%" })}</strong></div> : <ConfidenceIndicator item={item} compact />}
      <div className="metrics recommendation-metrics">
        {cohort ? <>
          <span><small>Preço FIPE</small>{formatCurrency(item.vehicle.purchase_price_brl)}</span>
          <span><small>Custo mensal estimado</small>{formatCurrency(item.monthly_total_cost)}/mês</span>
          <span><small>Consumo urbano</small>{readableValue(item.vehicle.technical_fields?.consumption_city)}</span>
          <span><small>Porta-malas</small>{readableValue(item.vehicle.technical_fields?.cargo_l)}</span>
        </> : <>
        <span><small>Status</small>{getRecommendationStatusLabel(item.recommendation_status)}</span>
        <span><small>TCO mensal</small>{formatCurrency(item.tco?.total_monthly_cost ?? item.monthly_cost)}</span>
        <span><small>{maintenance.label}</small>{maintenance.value}</span>
        <span><small>{parts.label}</small>{parts.value}</span>
        </>}
      </div>
      {!cohort && <MultifactorBreakdown item={item} compact />}
      <section className="card-section"><h4>Por que foi recomendado?</h4>{cohort ? <ul>{recommendationReasons(item).map((reason) => <li key={reason}>{reason}</li>)}</ul> : <p>Principal vantagem: {item.recommendation_summary?.main_advantage || "compatibilidade com o perfil informado"}.</p>}</section>
      {cohort ? <p className="field-hint">Custos estimados. Habitabilidade, quando utilizada, é um indicador derivado.</p> : <>
      <div className="card-columns"><section className="card-section"><h4>Pontos fortes</h4><ul>{(strengths.length ? strengths : ["Perfil analisado pelos critérios definidos"]).map((text) => <li key={text}>{text}</li>)}</ul></section><section className="card-section"><h4>Atenção</h4>{cautions.length ? <ul>{cautions.map((text) => <li key={text}>{text}</li>)}</ul> : <p>Sem alerta relevante para este perfil.</p>}</section></div>
      </>}
      <div className="card-actions"><button className="ghost-button" type="button" onClick={() => onDetails(item)}>Detalhes</button>{!cohort && <><button className="ghost-button" type="button" onClick={() => onParts(item)}>Peças</button><button className="ghost-button" type="button" onClick={() => onCompare(item)}>Comparar</button></>}</div>
    </article>
  );
}
