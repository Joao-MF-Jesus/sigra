import React from "react";
import { readableValue } from "./cohortPresentation.js";

const decimal = (value) => value == null ? "Não calculada" : Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 4 });
const natureLabel = { observed: "evidência observada", derived: "derivado", derived_academic: "derivado acadêmico", scenario_estimate: "estimativa de cenário", user_input: "informado por você", method_configuration: "configuração metodológica", validated_original_input: "entrada do método original", unavailable: "não informado" };
const subcriteriaLabels = { maintenance_score: "Manutenção", resale_score: "Desvalorização" };

export default function SevenCriteriaBreakdown({ breakdown }) {
  if (!breakdown?.criteria?.length) return null;
  const partial = breakdown.final_score == null;
  return <section className="modal-section" aria-label="Cálculo dos sete critérios">
    <h3>Sua personalização, critério por critério</h3>
    {breakdown.configuration && <p>Configuração: {breakdown.configuration.label}.{breakdown.configuration.weights_adjusted ? " Pesos ajustados explicitamente nesta execução." : ""} {breakdown.configuration.comparison_warning}</p>}
    {breakdown.version === "academic-derived-seven-v1" && <><p>Método: alternativa acadêmica derivada v1. Não substitui as avaliações de conforto, comportamento rodoviário ou qualidade histórica do método original.</p>{breakdown.dependencies?.map((_, index) => <p className="field-hint" key={index}>{index === 0 ? "Combustível e eficiência compartilham o mesmo consumo: não são duas evidências independentes." : "Manutenção e desvalorização são estimativas que podem acompanhar o preço FIPE; não provam confiabilidade."}</p>)}{breakdown.excluded_dimensions?.length > 0 && <p>Dimensões excluídas explicitamente por peso zero: {breakdown.excluded_dimensions.map((row) => row.label).join(", ")}.</p>}</>}
    <p>{breakdown.calculated_requested_count} de {breakdown.requested_count} critérios solicitados são calculáveis.
      {partial ? " Os subcálculos abaixo são diagnósticos: não formam uma nota final e não alteram a ordem de referência." : " As contribuições abaixo compõem a nota personalizada."}
      {" "}Os pesos de critérios ausentes não são redistribuídos.</p>
    {breakdown.criteria.map((criterion) => <article className="modal-section" key={criterion.criterion}>
      <h4>{criterion.label}</h4>
      {criterion.limitation && <p className="field-hint">{({ comfort: "Capacidade do porta-malas documentada; não mede conforto ou espaço interno.", safety: "Inventário de equipamentos: ausência comprovada difere de desconhecido. Não é teste de colisão.", performance: "Relação técnica massa/potência com gasolina; não mede comportamento rodoviário.", usage_fit: "Requisito de entrada. Mesma nota para todos os veículos igualmente compatíveis, sem distinção fictícia.", legacy_quality: "Manutenção e desvalorização são estimativas de cenário; não medem confiabilidade ou disponibilidade de peças." })[criterion.criterion] || "Calculado para o cenário informado; limitações e fontes permanecem nos dados utilizados."}</p>}
      <dl className="spec-list modal-spec-list">
        {criterion.input_weight != null && <div><dt>Peso informado</dt><dd>{decimal(criterion.input_weight)}</dd></div>}
        <div><dt>Peso efetivo normalizado</dt><dd>{decimal(criterion.normalized_weight_percentage)} %</dd></div>
        <div><dt>Nota do critério</dt><dd>{criterion.available ? decimal(criterion.raw_score) + "/100" : "Não avaliada"}</dd></div>
        {criterion.criterion === "performance" && criterion.available && criterion.value != null && <div><dt>Relação massa/potência</dt><dd>{readableValue({ value: criterion.value, unit: "kg/cv" })}</dd></div>}
        <div><dt>{partial ? "Contribuição diagnóstica (sem soma final)" : "Contribuição à nota"}</dt><dd>{criterion.contribution == null ? "Não calculada" : decimal(criterion.contribution) + " pontos"}</dd></div>
      </dl>
      {!criterion.available && <p className="field-hint">{criterion.requested ? criterion.requirement_message : "Critério sem peso: não participa da nota. A ausência de evidência continua preservada."}</p>}
      {criterion.calculated_subcriteria && Object.entries(criterion.calculated_subcriteria).map(([key, value]) => <p className="field-hint" key={key}>{subcriteriaLabels[key] || "Subcritério"}: {value.score == null ? "não calculável" : decimal(value.score) + "/100 (estimativa de cenário)"}. Não comprova confiabilidade nem disponibilidade de peças.</p>)}
      <details className="data-provenance"><summary>Dados utilizados neste critério</summary>
        <dl className="spec-list modal-spec-list">{Object.entries(criterion.inputs_used || {}).map(([key, input]) => <div key={key}><dt>{input.label}</dt><dd>{readableValue(input)} · {natureLabel[input.nature] || "entrada documentada"}</dd></div>)}</dl>
        {criterion.criterion === "performance" && criterion.inputs_used?.weight_kg?.supplementary_evidence && <p className="field-hint">Este critério utiliza massa em ordem de marcha e potência nominal com gasolina da versão documentada, somente quando ambas são comprovadas. A razão em kg/cv é um indicador técnico derivado; não é aceleração medida. As definições de massa dos fabricantes são preservadas, sem ajuste estimado.</p>}
        {criterion.criterion === "performance" && Object.values(criterion.inputs_used || {}).some((input) => input.supplementary_evidence?.representation === "normalized_public_document_reader_capture") && <p className="field-hint">Parte da fonte foi preservada como captura documental normalizada; o PDF original teve acesso bloqueado. Essa limitação permanece registrada na proveniência.</p>}
        {criterion.normalization && <p>Comparação dentro deste grupo de {criterion.normalization.population_ids.length} veículos: intervalo de {decimal(criterion.normalization.minimum)} a {decimal(criterion.normalization.maximum)}. {partial ? "Normalização apenas diagnóstica, sem reclassificação." : "Mesmo intervalo utilizado pelo motor."}{Number(criterion.normalization.minimum) === Number(criterion.normalization.maximum) ? " Entradas iguais recebem a mesma nota e não diferenciam posições." : ""}</p>}
        {[...new Set(Object.values(criterion.inputs_used || {}).flatMap((input) => (input.sources || []).map((source) => source.provider)))].length > 0 && <p>Fontes: {[...new Set(Object.values(criterion.inputs_used).flatMap((input) => (input.sources || []).map((source) => source.provider)))].join(", ")}.</p>}
      </details>
    </article>)}
  </section>;
}
