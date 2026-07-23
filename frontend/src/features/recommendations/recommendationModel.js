export function formatCurrency(value) {
  if (!Number.isFinite(Number(value))) return "Não informado";
  return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(Number(value));
}

export function formatScore(value) {
  if (!Number.isFinite(Number(value))) return "Não informado";
  return `${Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 2 })}/100`;
}

export function getMaintenanceMetric(item) {
  const score = item?.score_components?.maintenance_score;
  if (Number.isFinite(Number(score))) {
    return { label: "Nota de manutenção", value: formatScore(score), source: "maintenance_score" };
  }
  const annualCost = item?.vehicle?.annual_maintenance_cost;
  if (Number.isFinite(Number(annualCost))) {
    return {
      label: "Custo anual estimado de manutenção",
      value: formatCurrency(annualCost),
      source: "annual_maintenance_cost",
    };
  }
  return { label: "Nota de manutenção", value: "Não informada", source: "missing" };
}

export function getPartsMetric(item) {
  const value = item?.vehicle?.parts_availability_score;
  return { label: "Disponibilidade de peças", value: formatScore(value) };
}

const STATUS_LABELS = Object.freeze({
  recommended: "Recomendado",
  good_option: "Boa opção",
  attention: "Opção com ressalvas",
  not_recommended: "Não recomendado",
});

export function getRecommendationStatusLabel(status) {
  return STATUS_LABELS[status] || "Status não informado";
}

export function getRankingPresentation(item, index) {
  const position = `#${index + 1}`;
  if (item?.is_best_choice) {
    return { label: `${position} MELHOR ESCOLHA`, tone: "best-choice" };
  }
  if (item?.is_best_available_reference) {
    return { label: `${position} MELHOR ALTERNATIVA COMPARATIVA`, tone: "comparative" };
  }
  if (item?.has_viable_options === false) {
    return { label: `${position} ALTERNATIVA COMPARATIVA`, tone: "comparative" };
  }
  if (item?.recommendation_status === "not_recommended") {
    return { label: `${position} NO RANKING`, tone: "not-recommended" };
  }
  if (item?.recommendation_status === "attention") {
    return { label: `${position} OPÇÃO COM RESSALVAS`, tone: "attention" };
  }
  if (item?.recommendation_status === "good_option") {
    return { label: `${position} BOA OPÇÃO`, tone: "good-option" };
  }
  if (item?.recommendation_status === "recommended") {
    return { label: `${position} RECOMENDADO`, tone: "recommended" };
  }
  return { label: `${position} NO RANKING`, tone: "neutral" };
}

export function getRankingLabel(item, index) {
  return getRankingPresentation(item, index).label;
}

export function confidenceView(confidence = {}) {
  const score = Number(confidence.score ?? confidence.data_confidence_score);
  const normalizedScore = Number.isFinite(score) ? score : null;
  const rawLevel = String(confidence.level ?? confidence.data_confidence_level ?? "").toLowerCase();
  let level = rawLevel;
  if (!["baixa", "moderada", "alta"].includes(level)) {
    if (normalizedScore === null) level = "não informada";
    else if (normalizedScore >= 75) level = "alta";
    else if (normalizedScore >= 50) level = "moderada";
    else level = "baixa";
  }
  return { level, score: normalizedScore };
}

export function getConfidence(item) {
  return confidenceView({
    ...(item?.confidence || item?.recommendation_summary?.confidence || {}),
    score: item?.confidence?.score ?? item?.recommendation_summary?.confidence?.score,
    level: item?.confidence?.level ?? item?.recommendation_summary?.confidence?.level,
  });
}
