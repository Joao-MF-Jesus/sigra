import React from "react";
import VehicleCard from "./VehicleCard.jsx";
import { getMultifactorCoverage } from "./recommendationModel.js";

export default function RecommendationResults({ state, showAll, onToggleShowAll, onRetry, onDetails, onParts, onCompare, suppressMultifactorSummary = false }) {
  const { recommendations = [], metadata, loading, error, stale, hasCalculated } = state;
  const processing = metadata?.vehicle_processing;
  const coverage = getMultifactorCoverage(recommendations, metadata);
  const visible = showAll ? recommendations : recommendations.slice(0, 6);
  const resultIsCurrent = !loading && !error && !stale;
  const currentTitle = coverage.requested && !coverage.hasScores
    ? "Comparação de referência — sem nota personalizada"
    : coverage.hasScores ? "Comparação personalizada calculada" : "Ranking calculado";
  if (!hasCalculated && !loading) return <div className="recommendation-empty-state recommendation-state-card" data-testid="recommendation-state-ready"><strong>Preencha o perfil e calcule sua recomendação.</strong><p>O SIGRA só executará a análise quando você solicitar.</p></div>;
  return <>
    {loading && <div className="recommendation-state recommendation-state-card loading-state" data-testid="recommendation-state-loading" role="status" aria-live="polite"><strong>Analisando o mesmo cenário para todos os veículos</strong><p>O ranking será exibido quando a resposta do backend estiver completa.</p><div className="recommendation-skeleton-grid" aria-hidden="true">{[1, 2, 3].map((item) => <span className="recommendation-skeleton" key={item}><i /><i /><i /></span>)}</div></div>}
    {stale && <div className="stale-alert" data-testid="recommendation-stale-warning" role="status">Os parâmetros foram alterados. Calcule novamente para atualizar os resultados.</div>}
    {error && <div className={`api-error recommendation-state-card ${error.kind}`} data-testid={`recommendation-state-${error.kind}`} role="alert"><strong>{error.title}</strong><p>{error.message}</p>{error.retryable && <button type="button" className="ghost-button" onClick={onRetry} disabled={loading}>Tentar novamente</button>}</div>}
    {metadata?.has_viable_options === false && recommendations.length > 0 && <aside className="viability-alert" role="status"><strong>Nenhuma opção atende integralmente aos limites informados.</strong><p>Os veículos abaixo são apresentados para comparação.</p></aside>}
    {processing && <div className="processing-summary"><p>{processing.evaluated} de {processing.total_found} veículos foram avaliados.</p>{processing.ignored > 0 && <p>{processing.ignored} registros foram desconsiderados devido a dados incompletos ou inválidos.</p>}</div>}
    {!suppressMultifactorSummary && coverage.requested && recommendations.length > 0 && <aside className="processing-summary multifactor-summary" data-testid="multifactor-summary" role="status"><p><strong>{coverage.hasScores ? "Perfil multifator aplicado parcialmente ou integralmente:" : "Ranking original preservado:"}</strong> {coverage.rankedCount} de {coverage.total} veículos receberam pontuação multifator; {coverage.originalCount} permaneceram na classificação original.</p>{coverage.originalCount > 0 && <p>Veículos sem identidade confirmada ou evidência suficiente mantêm sua nota original e a ordem relativa entre si. Isso não significa reprovação por orçamento. Nenhuma associação ou nota foi inventada.</p>}<p>Este resultado não salva suas preferências nem modifica os dados de referência.</p></aside>}
    {hasCalculated && !loading && !error && recommendations.length === 0 && <div className="recommendation-empty-state recommendation-state-card" data-testid="recommendation-state-empty"><strong>{processing?.evaluated === 0 ? "Nenhum veículo válido pôde ser avaliado." : "Nenhuma recomendação foi encontrada."}</strong><p>Revise os parâmetros ou consulte os detalhes técnicos da base.</p></div>}
    {recommendations.length > 0 && <section aria-label="Resultado da recomendação" data-testid={resultIsCurrent ? "recommendation-state-success" : "recommendation-state-previous"}><div className="recommendation-success-summary" role="status"><strong>{resultIsCurrent ? currentTitle : "Resultado anterior preservado"}</strong><span>{recommendations.length} {recommendations.length === 1 ? "veículo comparado" : "veículos comparados"}.</span></div><div className="recommendation-grid" data-testid="recommendation-results">{visible.map((item, index) => <VehicleCard key={item.vehicle.identity_namespace === "academic_v6" ? `academic:${item.vehicle.catalog_id}` : item.vehicle.id} item={item} index={index} onDetails={onDetails} onParts={onParts} onCompare={onCompare} />)}</div></section>}
    {recommendations.length > 6 && <div className="show-more-row"><button className="ghost-button" type="button" onClick={onToggleShowAll}>{showAll ? "Mostrar menos veículos" : `Ver mais veículos (${recommendations.length - 6})`}</button></div>}
  </>;
}
