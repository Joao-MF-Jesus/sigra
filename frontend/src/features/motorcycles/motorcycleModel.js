export const MOTORCYCLE_CATEGORY_LABELS = Object.freeze({
  scooter: "Scooter",
  underbone: "Cub/Underbone",
  street: "Urbana",
  naked: "Naked",
  trail: "Trail",
  adventure: "Adventure",
  custom: "Custom",
  sport: "Esportiva",
  touring: "Touring",
});

export const RIDER_EXPERIENCE_LABELS = Object.freeze({
  beginner: "Iniciante",
  intermediate: "Intermediário",
  experienced: "Experiente",
});

export const DATA_SOURCE_LABELS = Object.freeze({
  demonstration: "Demonstrativo",
  estimated: "Estimado",
  official: "Oficial",
  user_reported: "Relatado por usuário",
});

export const MOTORCYCLE_DATA_GROUP_LABELS = Object.freeze({
  identity: "Identificação",
  market_price: "Preço de referência",
  technical_specs: "Ficha técnica",
  consumption: "Consumo",
  maintenance: "Manutenção",
  reliability: "Confiabilidade",
  parts_availability: "Disponibilidade de peças",
  safety_equipment: "Equipamentos de segurança",
  ergonomics: "Ergonomia",
  taxes: "Impostos",
  insurance: "Seguro",
  derived_metrics: "Indicadores derivados",
});

export const MOTORCYCLE_ELIGIBILITY_LABELS = Object.freeze({
  eligible: "Estrutura elegível",
  incomplete: "Dados incompletos",
  insufficient_confidence: "Confiança insuficiente",
  demonstration_only: "Somente demonstração",
  excluded_by_domain_rule: "Fora do domínio inicial",
  unsupported_category: "Categoria não suportada",
  outdated_data: "Dados desatualizados",
});

export const MOTORCYCLE_READINESS_LABELS = Object.freeze({
  structurally_ready: "Estrutura pronta para futura metodologia",
  missing_economic_data: "Dados econômicos ainda incompletos",
  missing_methodological_data: "Dados metodológicos ainda incompletos",
  insufficient_source_confidence: "Confiança das fontes insuficiente",
  demonstration_only: "Somente demonstração",
  not_ready: "Ainda não pronta",
});

export const MOTORCYCLE_METRIC_LABELS = Object.freeze({
  urban_score: "Indicador urbano",
  road_score: "Indicador rodoviário",
  passenger_comfort_score: "Conforto do passageiro",
  luggage_score: "Capacidade de bagagem",
  ergonomics_score: "Ergonomia",
  beginner_friendliness_score: "Facilidade para iniciantes",
  safety_score: "Segurança",
  maintenance_score: "Manutenção",
  parts_availability_score: "Disponibilidade de peças",
  reliability_score: "Confiabilidade",
  recommended_experience: "Faixa de experiência legada",
});

export const MOTORCYCLE_METRIC_STATUS_LABELS = Object.freeze({
  uncalculated: "Não calculado",
  demonstration: "Demonstrativo",
  unvalidated: "Não validado",
  calculated: "Calculado por método informado",
  deprecated: "Descontinuado",
});

export const MOTORCYCLE_ECONOMIC_STATUS_LABELS = Object.freeze({
  demonstration: "Demonstrativa",
  unvalidated: "Não validada",
  calculated: "Calculada por serviço versionado",
  deprecated: "Descontinuada",
});

export const MOTORCYCLE_ECONOMIC_ESTIMATE_LABELS = Object.freeze({
  depreciation_rate_annual_percent: "Taxa anual estimada de depreciação",
});

export function getMotorcycleCategoryLabel(value) {
  return MOTORCYCLE_CATEGORY_LABELS[value] || "Categoria não informada";
}

export function getRiderExperienceLabel(value) {
  return RIDER_EXPERIENCE_LABELS[value] || "Experiência não informada";
}

export function getDataSourceLabel(value) {
  return DATA_SOURCE_LABELS[value] || "Origem não informada";
}

export function getMotorcycleDataGroupLabel(value) {
  return MOTORCYCLE_DATA_GROUP_LABELS[value] || "Grupo não informado";
}

export function getMotorcycleEligibilityLabel(value) {
  return MOTORCYCLE_ELIGIBILITY_LABELS[value] || "Elegibilidade não avaliada";
}

export function getMotorcycleReadinessLabel(value) {
  return MOTORCYCLE_READINESS_LABELS[value] || "Prontidão futura não avaliada";
}

export function getMotorcycleMetricLabel(value) {
  return MOTORCYCLE_METRIC_LABELS[value] || "Indicador derivado";
}

export function getMotorcycleMetricStatusLabel(value) {
  return MOTORCYCLE_METRIC_STATUS_LABELS[value] || "Status não informado";
}

export function getMotorcycleEconomicStatusLabel(value) {
  return MOTORCYCLE_ECONOMIC_STATUS_LABELS[value] || "Status não informado";
}

export function getMotorcycleEconomicEstimateLabel(value) {
  return MOTORCYCLE_ECONOMIC_ESTIMATE_LABELS[value] || "Estimativa econômica";
}

export function isDemonstrationMotorcycle(motorcycle) {
  return motorcycle?.is_demonstration === true || motorcycle?.eligibility_status === "demonstration_only";
}

export function isIncompleteMotorcycle(motorcycle) {
  return motorcycle?.record_status === "incomplete" || motorcycle?.eligibility_status === "incomplete" || !motorcycle?.specifications;
}

export function groupMotorcycleSources(sources = []) {
  return sources.reduce((groups, source) => {
    const key = source?.data_group || "unknown";
    const next = [...(groups[key] || []), source].sort((left, right) => Number(right?.is_primary) - Number(left?.is_primary));
    return { ...groups, [key]: next };
  }, {});
}

export function getVisibleMotorcycleMetrics(metrics = []) {
  return metrics.filter((metric) => ["demonstration", "unvalidated"].includes(metric?.metric_status));
}

export function getVisibleEconomicEstimates(estimates = []) {
  return estimates.filter((estimate) => ["demonstration", "unvalidated"].includes(estimate?.status));
}

export function formatMotorcycleValue(value, suffix = "") {
  if (value === null || value === undefined || value === "") return "Não informado";
  return `${value}${suffix}`;
}

export function formatReferenceDate(value) {
  if (!value) return "Não informada";
  const [year, month, day] = String(value).slice(0, 10).split("-");
  if (!year || !month || !day) return "Não informada";
  return `${day}/${month}/${year}`;
}
