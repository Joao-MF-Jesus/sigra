import React, { useEffect, useRef, useState } from "react";
import { requestAcademicVehicleDetail } from "../../api/sigraApi.js";
import { academicError, createAcademicRequestGate } from "../academic/academicModel.js";
import RecommendationResults from "./RecommendationResults.jsx";
import RecommendationDetails from "./RecommendationDetails.jsx";
import { cohortCoverage, exclusionExplanation } from "./cohortPresentation.js";

export default function CohortRecommendationResults({ state, onRetry, showAll, onToggleShowAll, profile }) {
  const [detail, setDetail] = useState(null);
  const gate = useRef(createAcademicRequestGate());
  const result = state.metadata;
  useEffect(() => { gate.current.cancel(); setDetail(null); return () => gate.current.cancel(); }, [result]);
  async function openDetails(item) {
    const request = gate.current.begin();
    setDetail({ item, loading: true, data: null, error: "" });
    try {
      const data = await requestAcademicVehicleDetail(item.vehicle.catalog_id, { snapshotId: result.snapshot_id, signal: request.signal });
      if (data.cohort_fingerprint !== result.cohort_fingerprint) throw new Error("Snapshot divergente");
      if (request.isCurrent()) setDetail({ item, loading: false, data, error: "" });
    } catch (error) {
      if (request.isCurrent()) setDetail({ item, loading: false, data: null, error: academicError(error) });
    }
  }
  const groups = state.recommendations.reduce((all, row) => { (all[row.comparison_group] ||= []).push(row); return all; }, {});
  const coverage = cohortCoverage(state.recommendations);
  return <>
    <div className="section-heading result-heading"><p className="eyebrow">Resultado explicado</p><h2>{coverage.scored ? "Comparação multifator para o cenário informado" : "Opções para o perfil informado"}</h2><p className="section-note">Custos estimados para sua rotina. As posições comparam veículos com evidências equivalentes.</p></div>
    <ol className="recommendation-journey" aria-label="Jornada da recomendação"><li><strong>Informe</strong><span>necessidade e limites</span></li><li><strong>Entenda</strong><span>ranking e evidências</span></li><li><strong>Aprofunde</strong><span>detalhes e custos</span></li></ol>
    {result?.candidate_source === "academic_v6" && <div className="processing-summary"><p data-testid="cohort-recommendation-summary">{result.considered_count} veículos considerados · {result.documentary_eligible_count} com evidência para este perfil · {result.eligible_count} dentro dos limites.</p></div>}
    {result?.multifactor_profile?.policy_version === "academic-derived-seven-v1" && <p className="section-note">Alternativa acadêmica derivada v1, selecionada explicitamente. Capacidade, equipamentos, massa/potência e custos estimados não são as avaliações originais de conforto, desempenho ou qualidade histórica.</p>}
    {result?.multifactor_profile?.configuration && <p className="section-note" data-testid="result-configuration">Configuração: {result.multifactor_profile.configuration.label}.{result.multifactor_profile.configuration.weights_adjusted ? " Pesos ajustados explicitamente." : ""} {result.multifactor_profile.configuration.comparison_warning}</p>}
    {result?.multifactor_profile?.excluded_dimensions?.length > 0 && <p className="section-note">Dimensões excluídas explicitamente por peso zero: {result.multifactor_profile.excluded_dimensions.map((key) => result.multifactor_profile.alternative?.dimensions?.[key]?.label || "Dimensão excluída").join(", ")}. Os demais pesos seguem somente a normalização da configuração enviada.</p>}
    {result?.multifactor_profile?.enabled && <aside className="processing-summary multifactor-summary" data-testid="multifactor-summary" role="status"><p><strong>{coverage.scored ? "Personalização aplicada:" : "Classificação de referência preservada:"}</strong> {coverage.scored} veículos pontuados; {coverage.original} na ordem de referência.</p>{coverage.original > 0 && <p>Nenhuma nota foi inventada. Os critérios da classificação de referência não substituem os critérios da sua personalização.</p>}{result.multifactor_profile.missing_criteria?.filter((row) => row.affected_result_count > 0).length > 0 && <p>Sem avaliação por falta de {result.multifactor_profile.policy_version === "academic-derived-seven-v1" ? "dados necessários às métricas derivadas" : "notas comprovadas do método original"}: {result.multifactor_profile.missing_criteria.filter((row) => row.affected_result_count > 0).map((row) => `${row.label} (${row.affected_result_count} veículos)`).join("; ")}. A cobertura mostrada considera somente os critérios com peso positivo, sem redistribuir pesos ausentes.</p>}{result.multifactor_profile.unavailable_messages?.map((message) => <p key={message}>{message}</p>)}</aside>}
    {Object.keys(groups).length ? Object.entries(groups).map(([key, rows], index) => <section key={key}>
      {Object.keys(groups).length > 1 && <h3>Grupo de comparação {index + 1}</h3>}
      <RecommendationResults state={{ ...state, recommendations: rows }} showAll={showAll} onToggleShowAll={onToggleShowAll} onRetry={onRetry} onDetails={openDetails} suppressMultifactorSummary />
    </section>) : <RecommendationResults state={state} showAll={showAll} onToggleShowAll={onToggleShowAll} onRetry={onRetry} onDetails={openDetails} suppressMultifactorSummary />}
    {result?.excluded?.length > 0 && <details className="data-provenance"><summary>Por que alguns veículos ficaram fora?</summary><ul>{result.excluded.map((row) => <li key={row.catalog_id}>{row.label}: {exclusionExplanation(row)}</li>)}</ul></details>}
    {detail && <RecommendationDetails item={{ ...detail.item, detailState: { ...detail, onRetry: () => openDetails(detail.item) } }} metadata={result} profile={profile} onClose={() => { gate.current.cancel(); setDetail(null); }} />}
  </>;
}
