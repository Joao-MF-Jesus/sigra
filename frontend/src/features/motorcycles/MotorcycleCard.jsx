import React from "react";
import {
  formatMotorcycleValue,
  formatReferenceDate,
  getDataSourceLabel,
  getMotorcycleCategoryLabel,
  getMotorcycleDataGroupLabel,
  getMotorcycleEconomicEstimateLabel,
  getMotorcycleEconomicStatusLabel,
  getMotorcycleEligibilityLabel,
  getMotorcycleMetricLabel,
  getMotorcycleMetricStatusLabel,
  getMotorcycleReadinessLabel,
  getVisibleEconomicEstimates,
  getVisibleMotorcycleMetrics,
  groupMotorcycleSources,
  isDemonstrationMotorcycle,
  isIncompleteMotorcycle,
} from "./motorcycleModel.js";


function booleanLabel(value) {
  return typeof value === "boolean" ? (value ? "Sim" : "Não") : "Não informado";
}


export default function MotorcycleCard({ motorcycle, showTechnical = false }) {
  const specifications = motorcycle.specifications || {};
  const incomplete = isIncompleteMotorcycle(motorcycle);
  const sourceGroups = Object.entries(groupMotorcycleSources(motorcycle.data_sources));
  const derivedMetrics = getVisibleMotorcycleMetrics(motorcycle.derived_metrics);
  const economicEstimates = getVisibleEconomicEstimates(motorcycle.economic_estimates);
  const coverage = motorcycle.coverage || {};
  const blockingIssues = motorcycle.blocking_issues || coverage.blocking_issues || [];
  const informationalIssues = motorcycle.informational_issues || coverage.informational_issues || [];

  return <article className={`motorcycle-card ${incomplete ? "incomplete" : ""}`}>
    <div className="vehicle-topline">
      <div><h3>{motorcycle.brand} {motorcycle.model}{motorcycle.version ? ` ${motorcycle.version}` : ""}</h3><p>{motorcycle.year}</p></div>
      <div className="motorcycle-card-badges">
        {isDemonstrationMotorcycle(motorcycle) && <span className="demonstration-badge">Dado demonstrativo</span>}
        <span className={`eligibility-badge eligibility-${motorcycle.eligibility_status || "unknown"}`}>{getMotorcycleEligibilityLabel(motorcycle.eligibility_status)}</span>
      </div>
    </div>

    {motorcycle.eligibility_status === "incomplete" && <p className="incomplete-reason">Registro ainda não possui dados suficientes para futura avaliação.</p>}
    {motorcycle.eligibility_status === "demonstration_only" && <p className="incomplete-reason">Registro demonstrativo, mantido fora de futuras avaliações.</p>}

    <dl className="spec-list compact" aria-label="Ficha objetiva da motocicleta">
      <div><dt>Categoria</dt><dd>{getMotorcycleCategoryLabel(specifications.motorcycle_category)}</dd></div>
      <div><dt>Cilindrada</dt><dd>{formatMotorcycleValue(specifications.engine_displacement_cc, " cc")}</dd></div>
      <div><dt>Potência</dt><dd>{formatMotorcycleValue(specifications.power_cv, " cv")}</dd></div>
      <div><dt>Torque</dt><dd>{formatMotorcycleValue(specifications.torque_nm, " Nm")}</dd></div>
      <div><dt>Peso em ordem de marcha</dt><dd>{formatMotorcycleValue(specifications.wet_weight_kg, " kg")}</dd></div>
      <div><dt>Altura do assento</dt><dd>{formatMotorcycleValue(specifications.seat_height_mm, " mm")}</dd></div>
      <div><dt>Tanque</dt><dd>{formatMotorcycleValue(specifications.tank_capacity_l, " l")}</dd></div>
      <div><dt>Transmissão</dt><dd>{formatMotorcycleValue(specifications.transmission_type)}</dd></div>
      <div><dt>Marchas</dt><dd>{formatMotorcycleValue(specifications.gear_count)}</dd></div>
      <div><dt>Transmissão final</dt><dd>{formatMotorcycleValue(specifications.final_drive_type)}</dd></div>
      <div><dt>ABS</dt><dd>{booleanLabel(specifications.has_abs)}</dd></div>
      <div><dt>CBS</dt><dd>{booleanLabel(specifications.has_cbs)}</dd></div>
      <div><dt>Controle de tração</dt><dd>{booleanLabel(specifications.has_traction_control)}</dd></div>
      <div><dt>Consumo urbano</dt><dd>{formatMotorcycleValue(motorcycle.city_consumption, " km/l")}</dd></div>
      <div><dt>Consumo rodoviário</dt><dd>{formatMotorcycleValue(motorcycle.road_consumption, " km/l")}</dd></div>
      <div><dt>Manutenção anual estimada</dt><dd>{motorcycle.annual_maintenance_cost == null ? "Estimativa de manutenção anual ainda não disponível." : formatMotorcycleValue(motorcycle.annual_maintenance_cost, " BRL")}</dd></div>
      <div><dt>Referência do preço</dt><dd>{formatReferenceDate(motorcycle.price_reference_date)}</dd></div>
    </dl>

    <section className="motorcycle-card-section" data-testid="motorcycle-coverage">
      <h4>Cobertura e elegibilidade</h4>
      <p>Campos objetivos: <strong>{formatMotorcycleValue(coverage.objective_field_coverage_percent, "%")}</strong> · cobertura mínima piloto: <strong>{formatMotorcycleValue(coverage.pilot_required_source_coverage_percent, "%")}</strong> · grupos complementares: <strong>{formatMotorcycleValue(coverage.complementary_source_coverage_percent, "%")}</strong></p>
      <p>Prontidão futura: <strong>{getMotorcycleReadinessLabel(coverage.future_recommendation_readiness)}</strong>. Este indicador não é uma Nota SIGRA.</p>
      {coverage.missing_objective_fields?.length > 0 && <p>Campos ausentes: {coverage.missing_objective_fields.join(", ")}.</p>}
      {coverage.missing_pilot_source_groups?.length > 0 && <p>Grupos mínimos ausentes: {coverage.missing_pilot_source_groups.map(getMotorcycleDataGroupLabel).join(", ")}.</p>}
      {coverage.missing_complementary_source_groups?.length > 0 && <p>Grupos complementares ainda ausentes: {coverage.missing_complementary_source_groups.map(getMotorcycleDataGroupLabel).join(", ")}.</p>}
      {blockingIssues.length > 0 && <details className="motorcycle-eligibility-details"><summary>Impedimentos estruturais</summary><ul>{blockingIssues.map((reason) => <li key={`${reason.code}-${reason.field}`}>{reason.message}</li>)}</ul></details>}
      {informationalIssues.length > 0 && <details className="motorcycle-eligibility-details"><summary>Observações por grupo</summary><ul>{informationalIssues.map((reason) => <li key={`${reason.code}-${reason.field}`}>{reason.message}</li>)}</ul></details>}
    </section>

    <section className="motorcycle-card-section"><h4>Fontes por grupo</h4>{sourceGroups.length === 0
      ? <p>Fontes agrupadas ainda não cadastradas. Dados legados não são usados como fonte canônica.</p>
      : sourceGroups.map(([group, sources]) => <div className="motorcycle-source-group" key={group}>
        <strong>{getMotorcycleDataGroupLabel(group)}</strong>
        {sources.map((source) => <p key={source.id}>
          {source.is_primary ? "Principal: " : "Complementar: "}{source.source_name || getDataSourceLabel(source.source_type)}
          {source.source_type === "demonstration" && <span className="source-demonstration-label"> · demonstrativa neste grupo</span>}
          {` · confiança ${formatMotorcycleValue(source.confidence, "/100")} · referência ${formatReferenceDate(source.reference_date)}`}
          {source.source_url && <> · <a className="source-link" href={source.source_url} target="_blank" rel="noreferrer">consultar</a></>}
        </p>)}
      </div>)}</section>

    <section className="motorcycle-card-section"><h4>Indicadores derivados</h4>{derivedMetrics.length === 0
      ? <p>Indicador ainda não calculado.</p>
      : <ul className="motorcycle-metric-list">{derivedMetrics.map((metric) => <li key={metric.id}><strong>{getMotorcycleMetricLabel(metric.metric_name)}</strong>: {metric.metric_value ?? metric.metric_text_value} <span>{getMotorcycleMetricStatusLabel(metric.metric_status)} · método {metric.method_version}</span></li>)}</ul>}</section>

    <section className="motorcycle-card-section"><h4>Estimativas econômicas</h4>{economicEstimates.length === 0
      ? <p>Estimativa de depreciação ainda não disponível.</p>
      : <ul className="motorcycle-metric-list">{economicEstimates.map((estimate) => <li key={estimate.id}><strong>{getMotorcycleEconomicEstimateLabel(estimate.estimate_name)}</strong>: {estimate.estimate_value}% ao ano <span>{getMotorcycleEconomicStatusLabel(estimate.status)} · método {estimate.method_version} · referência {formatReferenceDate(estimate.reference_date)}</span></li>)}</ul>}</section>

    {showTechnical && <details className="motorcycle-card-section motorcycle-legacy-data" data-testid="motorcycle-legacy-data">
      <summary>Dados legados (deprecated)</summary>
      <pre>{JSON.stringify(motorcycle.legacy_data || {}, null, 2)}</pre>
    </details>}
  </article>;
}
