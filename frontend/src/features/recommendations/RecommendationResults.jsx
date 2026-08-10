import React from "react";
import VehicleCard from "./VehicleCard.jsx";

export default function RecommendationResults({ state, showAll, onToggleShowAll, onRetry, onDetails, onParts, onCompare }) {
  const { recommendations = [], metadata, loading, error, stale, hasCalculated } = state;
  const processing = metadata?.vehicle_processing;
  const visible = showAll ? recommendations : recommendations.slice(0, 6);
  if (!hasCalculated && !loading) return <div className="recommendation-empty-state"><strong>Preencha o perfil e calcule sua recomendação.</strong><p>O SIGRA só executará a análise quando você solicitar.</p></div>;
  return <>
    {loading && <div className="recommendation-state" role="status">Calculando a recomendação...</div>}
    {stale && <div className="stale-alert" data-testid="recommendation-stale-warning" role="status">Os parâmetros foram alterados. Calcule novamente para atualizar os resultados.</div>}
    {error && <div className="api-error" role="alert"><p>{error}</p><button type="button" className="ghost-button" onClick={onRetry} disabled={loading}>Tentar novamente</button></div>}
    {metadata?.has_viable_options === false && recommendations.length > 0 && <aside className="viability-alert" role="status"><strong>Nenhuma opção atende integralmente aos limites informados.</strong><p>Os veículos abaixo são apresentados para comparação.</p></aside>}
    {processing && <div className="processing-summary"><p>{processing.evaluated} de {processing.total_found} veículos foram avaliados.</p>{processing.ignored > 0 && <p>{processing.ignored} registros foram desconsiderados devido a dados incompletos ou inválidos.</p>}</div>}
    {hasCalculated && !loading && !error && recommendations.length === 0 && <div className="recommendation-empty-state"><strong>{processing?.evaluated === 0 ? "Nenhum veículo válido pôde ser avaliado." : "Nenhuma recomendação foi encontrada."}</strong><p>Revise os parâmetros ou consulte os detalhes técnicos da base.</p></div>}
    {recommendations.length > 0 && <div className="recommendation-grid" data-testid="recommendation-results">{visible.map((item, index) => <VehicleCard key={item.vehicle.id} item={item} index={index} onDetails={onDetails} onParts={onParts} onCompare={onCompare} />)}</div>}
    {recommendations.length > 6 && <div className="show-more-row"><button className="ghost-button" type="button" onClick={onToggleShowAll}>{showAll ? "Mostrar menos veículos" : `Ver mais veículos (${recommendations.length - 6})`}</button></div>}
  </>;
}
