// Capability comes from /recommendations/metadata, not vehicle category or proxies.
export const RECOMMENDATION_PRIORITIES = Object.freeze([
  { value: "lowest_cost", label: "Menor custo possível" },
  { value: "budget_economy", label: "Economia dentro do orçamento" },
  { value: "cost_benefit", label: "Custo-benefício" },
  { value: "balanced", label: "Equilíbrio geral" },
  { value: "comfort_space", label: "Conforto e espaço" },
  { value: "best_within_budget", label: "Melhor categoria dentro do orçamento" },
]);

const MISSING_LEGACY_ASSESSMENTS = {
  budget_economy: "faltam notas históricas de confiabilidade, peças e categoria usadas nesta prioridade",
  balanced: "faltam notas históricas de confiabilidade, disponibilidade de peças e categoria, além das avaliações originais de uso, conforto, espaço e segurança",
  comfort_space: "faltam as avaliações originais de conforto, espaço, segurança e categoria",
  best_within_budget: "faltam notas históricas de categoria, confiabilidade e avaliações originais de conforto e segurança",
};

export function recommendationPriorityOptions(metadata) {
  const academic = metadata?.candidate_source === "academic_v6";
  const supported = new Set(Array.isArray(metadata?.strategies) ? metadata.strategies : []);
  return RECOMMENDATION_PRIORITIES.map((option) => ({
    ...option,
    available: !academic || supported.has(option.value),
  }));
}

export function unavailablePriorityMessage(strategy, metadata) {
  const option = recommendationPriorityOptions(metadata).find((row) => row.value === strategy);
  if (option?.available) return "";
  const options = recommendationPriorityOptions(metadata).filter((row) => row.available);
  const reason = Array.isArray(metadata?.strategies)
    ? MISSING_LEGACY_ASSESSMENTS[strategy] || "o servidor não oferece esta prioridade para a coorte carregada"
    : "o servidor ainda não confirmou as prioridades disponíveis";
  return `${option?.label || "Esta prioridade"} está indisponível: ${reason}. ${options.length
    ? `Escolha explicitamente ${options.map((row) => row.label).join(" ou ")}.`
    : "Nenhuma prioridade está confirmada; tente carregar a metodologia novamente."} Nenhuma prioridade alternativa foi aplicada.`;
}
