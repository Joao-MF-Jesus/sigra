import { shouldRequestCarRecommendations } from "../../domain/vehicleTypes.js";
import { buildMultifactorProfile } from "./multifactorRecommendationModel.js";

export const VALID_USE_CASES = ["cidade", "familia", "trabalho", "estrada", "app", "suv"];
export const VALID_STRATEGIES = [
  "lowest_cost",
  "budget_economy",
  "cost_benefit",
  "balanced",
  "comfort_space",
  "best_within_budget",
];

const NUMERIC_RULES = {
  budget: { label: "Orçamento", min: 0, exclusive: true },
  monthly_limit: { label: "Limite mensal", min: 0, exclusive: true },
  monthly_mileage: { label: "Quilometragem mensal", min: 0, exclusive: false },
  fuel_price: { label: "Preço do combustível", min: 0, exclusive: true },
};

export function validateRecommendationProfile(profile) {
  const errors = {};
  const payload = {};

  if (!shouldRequestCarRecommendations(profile.vehicle_type)) {
    errors.vehicle_type = "O recomendador de motocicletas ainda está em desenvolvimento.";
  }

  Object.entries(NUMERIC_RULES).forEach(([field, rule]) => {
    const raw = profile[field];
    if (raw === "" || raw === null || raw === undefined) {
      errors[field] = `${rule.label} é obrigatório.`;
      return;
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      errors[field] = `${rule.label} deve ser um número válido.`;
    } else if (rule.exclusive ? value <= rule.min : value < rule.min) {
      errors[field] = rule.exclusive
        ? `${rule.label} deve ser maior que zero.`
        : `${rule.label} deve ser maior ou igual a zero.`;
    } else {
      payload[field] = value;
    }
  });

  if (!VALID_USE_CASES.includes(profile.use_case)) {
    errors.use_case = "Selecione uma forma de uso válida.";
  } else {
    payload.use_case = profile.use_case;
  }
  if (!VALID_STRATEGIES.includes(profile.recommendation_strategy)) {
    errors.recommendation_strategy = "Selecione uma prioridade válida.";
  } else {
    payload.recommendation_strategy = profile.recommendation_strategy;
  }

  const multifactor = buildMultifactorProfile(profile, payload.budget);
  Object.assign(errors, multifactor.errors);
  if (multifactor.payload) payload.multifactor_profile = multifactor.payload;

  return { errors, payload, isValid: Object.keys(errors).length === 0 };
}

export function isRecommendationSubmitDisabled({ loading, vehicleType }) {
  return Boolean(loading) || !shouldRequestCarRecommendations(vehicleType);
}

export function shouldMarkResultsStale(hasCalculated) {
  return Boolean(hasCalculated);
}

export function isLatestRequest(responseRequestId, currentRequestId) {
  return responseRequestId === currentRequestId;
}
