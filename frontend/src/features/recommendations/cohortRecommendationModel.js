import { validateRecommendationProfile } from "./recommendationValidation.js";
import { DERIVED_PERSONALIZATION } from "./multifactorRecommendationModel.js";
import { unavailablePriorityMessage } from "./recommendationPriorityModel.js";

export const CRITERION_LABELS = {
  urban_fuel: "Combustível mensal", footprint: "Dimensões com espelhos",
  price: "Preço de compra", passenger_space: "Habitabilidade derivada",
  cargo: "Porta-malas", seats: "Lugares", payload: "Carga útil",
  operating_cost: "TCO de cenário", highway_consumption: "Consumo rodoviário",
  safety: "Evidência de segurança", mass_power: "Relação massa/potência",
  clearance: "Vão livre", interior_proxy: "Geometria externa derivada",
  transmission: "Transmissão (sem preferência, peso zero)",
};

export function cohortWeights(profile, metadata) {
  const defaults = metadata.profiles?.[profile.use_case]?.weights || {};
  return Object.fromEntries(Object.entries(defaults).map(([key, value]) =>
    [key, profile.cohort_weights?.[profile.use_case]?.[key] ?? value]));
}

export function validateCohortRecommendation(profile, metadata) {
  const validation = validateRecommendationProfile(profile);
  const errors = { ...validation.errors };
  if (profile.multifactor_enabled && profile.multifactor_policy_version === DERIVED_PERSONALIZATION && metadata.alternative_personalization?.available !== true) errors.multifactor_policy_version = "A alternativa acadêmica está desabilitada no servidor; selecione a referência original.";
  if (profile.multifactor_enabled && profile.multifactor_policy_version === DERIVED_PERSONALIZATION
      && metadata.alternative_personalization?.configuration_registry
      && !metadata.alternative_personalization.configuration_registry.configurations?.[profile.multifactor_configuration_id]) errors.multifactor_configuration_id = "Escolha explicitamente Base ou Ampliada antes de calcular.";
  const weights = cohortWeights(profile, metadata);
  if (!(Number(profile.monthly_mileage) > 0)) errors.monthly_mileage = "Quilometragem mensal deve ser maior que zero para este cenário.";
  const priorityError = unavailablePriorityMessage(profile.recommendation_strategy, { ...metadata, candidate_source: "academic_v6" });
  if (priorityError) errors.recommendation_strategy = priorityError;
  if (!metadata.snapshot_id || !Object.keys(weights).length) errors.cohort_weights = "Metodologia da coorte indisponível.";
  const numbers = Object.values(weights).map(Number);
  if (numbers.some((n) => !Number.isFinite(n) || n < 0) || numbers.reduce((a, b) => a + b, 0) <= 0) errors.cohort_weights = "Use pesos não negativos, com soma maior que zero.";
  if (!["low", "base", "high"].includes(profile.cost_scenario || "base")) errors.cost_scenario = "Selecione um cenário válido.";
  const payload = {
    ...validation.payload, candidate_source: "academic_v6",
    academic_options: { snapshot_id: metadata.snapshot_id, scenario: profile.cost_scenario || "base",
      criterion_weights: Object.fromEntries(Object.entries(weights).map(([key, value]) => [key, Number(value)])) },
  };
  return { errors, payload, isValid: Object.keys(errors).length === 0 };
}
