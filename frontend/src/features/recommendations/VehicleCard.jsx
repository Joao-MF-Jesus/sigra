import React from "react";
import ConfidenceIndicator from "./ConfidenceIndicator.jsx";
import { formatCurrency, formatScore, getMaintenanceMetric, getPartsMetric, getRankingPresentation, getRecommendationStatusLabel } from "./recommendationModel.js";

function imagePath(vehicle) {
  return vehicle.image_url || `/cars/${vehicle.brand}-${vehicle.model}-${vehicle.year}`.toLowerCase().replaceAll(" ", "-").replaceAll(".", "") + ".svg";
}

function handleImageError(event) {
  event.currentTarget.style.display = "none";
  event.currentTarget.parentElement?.classList.add("image-failed");
}

export default function VehicleCard({ item, index, onDetails, onParts, onCompare }) {
  const maintenance = getMaintenanceMetric(item);
  const parts = getPartsMetric(item);
  const ranking = getRankingPresentation(item, index);
  const strengths = (item.category_awards || []).map((award) => award.label).slice(0, 2);
  const cautions = [...new Set(item.penalties || [])].slice(0, 1);
  return (
    <article className={`vehicle-card ranking-${ranking.tone} ${item.recommendation_status === "not_recommended" ? "not-recommended" : ""} ${item.is_best_choice ? "best-choice" : ""} ${item.is_best_available_reference ? "comparative-reference" : ""}`}>
      <div className="car-image-wrap"><img className="car-image" src={imagePath(item.vehicle)} alt={`${item.vehicle.brand} ${item.vehicle.model} ${item.vehicle.year}`} onError={handleImageError} /><span className="car-image-fallback">Imagem demonstrativa indisponível</span></div>
      <div className="card-rank">{ranking.label}</div>
      <div className="vehicle-topline"><div><h3>{item.vehicle.brand} {item.vehicle.model}</h3><p>{item.vehicle.year}</p></div><strong><span>Nota SIGRA</span>{formatScore(item.score)}</strong></div>
      <ConfidenceIndicator item={item} compact />
      <div className="metrics recommendation-metrics">
        <span><small>Status</small>{getRecommendationStatusLabel(item.recommendation_status)}</span>
        <span><small>TCO mensal</small>{formatCurrency(item.tco?.total_monthly_cost ?? item.monthly_cost)}</span>
        <span><small>{maintenance.label}</small>{maintenance.value}</span>
        <span><small>{parts.label}</small>{parts.value}</span>
      </div>
      <section className="card-section"><h4>Por que foi recomendado?</h4><p>Principal vantagem: {item.recommendation_summary?.main_advantage || "compatibilidade com o perfil informado"}.</p></section>
      <div className="card-columns"><section className="card-section"><h4>Pontos fortes</h4><ul>{(strengths.length ? strengths : ["Perfil analisado pelos critérios definidos"]).map((text) => <li key={text}>{text}</li>)}</ul></section><section className="card-section"><h4>Atenção</h4>{cautions.length ? <ul>{cautions.map((text) => <li key={text}>{text}</li>)}</ul> : <p>Sem alerta relevante para este perfil.</p>}</section></div>
      <div className="card-actions"><button className="ghost-button" type="button" onClick={() => onDetails(item)}>Detalhes</button><button className="ghost-button" type="button" onClick={() => onParts(item)}>Peças</button><button className="ghost-button" type="button" onClick={() => onCompare(item)}>Comparar</button></div>
    </article>
  );
}
