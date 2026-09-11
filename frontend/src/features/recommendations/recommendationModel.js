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

const RECOMMENDATION_ERROR_PRESENTATIONS = Object.freeze({
  validation: Object.freeze({
    kind: "validation",
    title: "Revise os dados informados",
    message: "Algum parâmetro não foi aceito. Confira o formulário antes de tentar novamente.",
    retryable: false,
  }),
  conflict: Object.freeze({
    kind: "conflict",
    title: "Não foi possível identificar o veículo",
    message: "Há mais de uma correspondência possível. O SIGRA não escolheu uma delas automaticamente.",
    retryable: false,
  }),
  unavailable: Object.freeze({
    kind: "unavailable",
    title: "Dados de referência temporariamente indisponíveis",
    message: "Não foi possível carregar os veículos para a comparação personalizada. Tente novamente mais tarde.",
    retryable: true,
  }),
  error: Object.freeze({
    kind: "error",
    title: "Não foi possível calcular a recomendação",
    message: "O serviço não concluiu a análise. Tente novamente sem alterar os dados já preenchidos.",
    retryable: true,
  }),
});

export function getRecommendationErrorPresentation(error) {
  if (error?.status === 422) return RECOMMENDATION_ERROR_PRESENTATIONS.validation;
  if (error?.status === 409 || error?.code === "multifactor_gold_identity_conflict") {
    return RECOMMENDATION_ERROR_PRESENTATIONS.conflict;
  }
  if (error?.status === 503 || error?.code === "multifactor_gold_unavailable") {
    return RECOMMENDATION_ERROR_PRESENTATIONS.unavailable;
  }
  return RECOMMENDATION_ERROR_PRESENTATIONS.error;
}

const MULTIFACTOR_UNAVAILABLE_PRESENTATIONS = Object.freeze({
  LEGACY_IDENTITY_UNAVAILABLE: "A identidade deste veículo está incompleta no catálogo de recomendação.",
  GOLD_IDENTITY_NOT_FOUND: "Não há uma correspondência publicada e inequívoca para este veículo.",
  GOLD_IDENTITY_AMBIGUOUS: "Mais de uma correspondência publicada representa este veículo; nenhuma foi escolhida automaticamente.",
  MULTIFACTOR_EVIDENCE_UNAVAILABLE: "Falta evidência publicada para calcular todos os critérios selecionados.",
});

export function getMultifactorUnavailablePresentation(reasonCode, identityDiagnostic) {
  const identityMessages = {
    coverage_absent: "Este veículo ainda não tem cobertura na Gold publicada. Isso não indica reprovação por orçamento.",
    identity_mismatch: "A chave ou a versão do catálogo diverge da identidade publicada. Nenhuma associação foi forçada.",
    identity_unresolved: "Falta uma chave comum ou um mapeamento de versão validado para confirmar a identidade.",
    required_identity_missing: "Falta um campo obrigatório para confirmar a identidade deste veículo.",
    scenario_evidence_unavailable: "A identidade está publicada, mas falta evidência para o cenário solicitado.",
  };
  if (reasonCode !== "MULTIFACTOR_EVIDENCE_UNAVAILABLE" || identityDiagnostic?.rejection_reason) {
    const message = identityMessages[identityDiagnostic?.rejection_reason];
    if (message) return message;
  }
  return MULTIFACTOR_UNAVAILABLE_PRESENTATIONS[reasonCode]
    || "A evidência necessária para o ranking multifator não está disponível.";
}

export function getMultifactorCoverage(recommendations = [], metadata) {
  const items = Array.isArray(recommendations) ? recommendations : [];
  const requested = metadata?.multifactor_profile?.enabled === true
    || items.some((item) => item?.multifactor?.enabled === true);
  // Count actual scores, not the request flag or potentially stale metadata.
  const rankedCount = items.filter((item) => {
    const value = item?.multifactor?.final_score;
    return item?.multifactor?.status === "ranked"
      && value !== null && value !== undefined && value !== ""
      && typeof value !== "boolean" && Number.isFinite(Number(value));
  }).length;
  return {
    requested,
    rankedCount,
    originalCount: items.length - rankedCount,
    total: items.length,
    hasScores: rankedCount > 0,
  };
}
