import { DERIVED_CONFIGURATION_LABELS } from "./multifactorRecommendationModel.js";

export const RECOMMENDATION_WIZARD_STEPS = Object.freeze([
  Object.freeze({ id: "need", label: "Necessidade", shortLabel: "Uso" }),
  Object.freeze({ id: "budget", label: "Orçamento", shortLabel: "Orçamento" }),
  Object.freeze({ id: "priorities", label: "Prioridades", shortLabel: "Prioridades" }),
  Object.freeze({ id: "advanced", label: "Ajustes opcionais", shortLabel: "Ajustes" }),
  Object.freeze({ id: "review", label: "Revisão", shortLabel: "Revisão" }),
]);

const ERROR_STEP = Object.freeze({
  vehicle_type: "need",
  use_case: "need",
  budget: "budget",
  monthly_limit: "budget",
  recommendation_strategy: "priorities",
  monthly_mileage: "priorities",
  fuel_price: "priorities",
  cost_scenario: "priorities",
  cohort_weights: "advanced",
});

export function clampWizardStep(index) {
  const numeric = Number(index);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(RECOMMENDATION_WIZARD_STEPS.length - 1, Math.trunc(numeric)));
}

export function nextWizardStep(index) {
  return clampWizardStep(clampWizardStep(index) + 1);
}

export function previousWizardStep(index) {
  return clampWizardStep(clampWizardStep(index) - 1);
}

export function firstStepWithError(errors = {}) {
  for (const [field, message] of Object.entries(errors)) {
    if (!message) continue;
    const explicit = ERROR_STEP[field];
    if (explicit) return RECOMMENDATION_WIZARD_STEPS.findIndex((step) => step.id === explicit);
    if (field.startsWith("multifactor_") || field.startsWith("weight_")) {
      return RECOMMENDATION_WIZARD_STEPS.findIndex((step) => step.id === "advanced");
    }
  }
  return -1;
}

export function wizardProgress(index) {
  const current = clampWizardStep(index);
  return {
    current,
    currentNumber: current + 1,
    total: RECOMMENDATION_WIZARD_STEPS.length,
    percentage: ((current + 1) / RECOMMENDATION_WIZARD_STEPS.length) * 100,
  };
}

export function recommendationReview(profile = {}) {
  const useLabels = {
    cidade: "Cidade",
    familia: "Família",
    trabalho: "Trabalho",
    estrada: "Estrada",
    app: "Aplicativo",
    suv: "Espaço e versatilidade",
  };
  const strategyLabels = {
    lowest_cost: "Menor custo possível",
    budget_economy: "Economia dentro do orçamento",
    cost_benefit: "Custo-benefício",
    balanced: "Equilíbrio geral",
    comfort_space: "Conforto e espaço",
    best_within_budget: "Melhor categoria dentro do orçamento",
  };
  return [
    ["Categoria", profile.vehicle_type === "motorcycle" ? "Motocicleta" : "Automóvel"],
    ["Uso principal", useLabels[profile.use_case] || "Não informado"],
    ["Orçamento", profile.budget ? `R$ ${profile.budget}` : "Não informado"],
    ["Limite mensal", profile.monthly_limit ? `R$ ${profile.monthly_limit}` : "Não informado"],
    ["Prioridade", strategyLabels[profile.recommendation_strategy] || "Não informada"],
    ["Rotina", `${profile.monthly_mileage || "0"} km/mês · combustível a R$ ${profile.fuel_price || "0"}`],
    ["Perfil multifator", profile.multifactor_enabled ? (profile.multifactor_policy_version === "academic-derived-seven-v1" ? `Solicitado — alternativa acadêmica derivada v1; ${DERIVED_CONFIGURATION_LABELS[profile.multifactor_configuration_id] || "configuração não selecionada"}; depende das evidências` : "Solicitado — depende das evidências dos critérios") : "Desativado — ranking histórico"],
  ];
}
