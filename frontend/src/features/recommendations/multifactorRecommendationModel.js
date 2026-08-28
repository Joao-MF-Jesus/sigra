export const MULTIFACTOR_DEFAULT_WEIGHTS = Object.freeze({
  total_cost: "25",
  usage_fit: "20",
  comfort: "10",
  safety: "15",
  performance: "10",
  efficiency: "10",
  legacy_quality: "10",
});

export const MULTIFACTOR_WEIGHT_FIELDS = Object.freeze(
  Object.keys(MULTIFACTOR_DEFAULT_WEIGHTS),
);

const WEIGHT_LABELS = Object.freeze({
  total_cost: "Custo no cenário",
  usage_fit: "Adequação ao uso",
  comfort: "Conforto",
  safety: "Segurança",
  performance: "Desempenho rodoviário",
  efficiency: "Economia e eficiência",
  legacy_quality: "Qualidade histórica",
});

export const MULTIFACTOR_WEIGHT_DESCRIPTIONS = Object.freeze({
  total_cost: "Favorece menor custo de combustível no cenário informado.",
  usage_fit: "Mede a compatibilidade com a forma de uso selecionada.",
  comfort: "Considera apenas evidências de conforto disponíveis.",
  safety: "Prioriza os indicadores de segurança do catálogo.",
  performance: "Valoriza a resposta esperada em uso rodoviário.",
  efficiency: "Compara consumo e eficiência publicados.",
  legacy_quality: "Resume manutenção, confiabilidade, peças e revenda sem repetir custo ou adequação.",
});

const DECIMAL_PATTERN = /^\d+(?:\.\d+)?$/;

function decimalString(value) {
  const normalized = String(value ?? "").trim().replace(",", ".");
  if (!DECIMAL_PATTERN.test(normalized)) return null;
  const numeric = Number(normalized);
  return Number.isFinite(numeric) ? normalized : null;
}

function positiveDecimal(value, label, errors, field, { allowZero = false } = {}) {
  const normalized = decimalString(value);
  if (normalized === null || (allowZero ? Number(normalized) < 0 : Number(normalized) <= 0)) {
    errors[field] = `${label} deve ser um decimal ${allowZero ? "não negativo" : "maior que zero"}.`;
    return null;
  }
  return normalized;
}

export function buildMultifactorProfile(profile, budget) {
  if (!profile.multifactor_enabled) return { errors: {}, payload: null, isValid: true };
  const errors = {};
  const weights = {};
  let weightTotal = 0;
  for (const code of MULTIFACTOR_WEIGHT_FIELDS) {
    const field = `weight_${code}`;
    const value = positiveDecimal(profile[field], WEIGHT_LABELS[code], errors, field, { allowZero: true });
    if (value !== null) {
      if (Number(value) > 100) errors[field] = "O peso deve ser menor ou igual a 100.";
      weights[code] = value;
      weightTotal += Number(value);
    }
  }
  if (weightTotal <= 0) errors.multifactor_weights = "Ao menos um peso deve ser maior que zero.";

  const cityPercentage = positiveDecimal(profile.multifactor_city_percentage, "Percentual urbano", errors, "multifactor_city_percentage", { allowZero: true });
  const highwayPercentage = positiveDecimal(profile.multifactor_highway_percentage, "Percentual rodoviário", errors, "multifactor_highway_percentage", { allowZero: true });
  if (cityPercentage !== null && highwayPercentage !== null && Math.abs(Number(cityPercentage) + Number(highwayPercentage) - 100) > 1e-9) {
    errors.multifactor_percentages = "Os percentuais urbano e rodoviário devem totalizar 100%.";
  }
  const stateCode = String(profile.multifactor_state_code || "").trim().toUpperCase();
  if (!/^[A-Z]{2}$/.test(stateCode)) errors.multifactor_state_code = "Informe a UF com duas letras.";
  const week = String(profile.multifactor_reference_week_start || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(week)) errors.multifactor_reference_week_start = "Informe a semana de referência.";
  const horizon = Number(profile.multifactor_horizon_months);
  if (!Number.isInteger(horizon) || horizon < 1 || horizon > 120) errors.multifactor_horizon_months = "O horizonte deve ser um inteiro entre 1 e 120 meses.";
  const fuelStrategy = profile.multifactor_fuel_strategy;
  if (!["gasoline_c_common", "ethanol_hydrated", "lowest_projected_cost"].includes(fuelStrategy)) errors.multifactor_fuel_strategy = "Selecione uma estratégia de combustível válida.";

  const priceMode = profile.multifactor_price_mode;
  if (!["anp", "manual"].includes(priceMode)) errors.multifactor_price_mode = "Selecione a origem do preço.";
  const manualPrice = priceMode === "manual"
    ? positiveDecimal(profile.multifactor_manual_fuel_price_brl, "Preço manual", errors, "multifactor_manual_fuel_price_brl")
    : null;
  const monthlyDistance = positiveDecimal(profile.multifactor_monthly_distance_km, "Distância mensal", errors, "multifactor_monthly_distance_km");

  const cityConsumption = String(profile.multifactor_city_consumption_km_l || "").trim()
    ? positiveDecimal(profile.multifactor_city_consumption_km_l, "Consumo urbano", errors, "multifactor_city_consumption_km_l")
    : null;
  const highwayConsumption = String(profile.multifactor_highway_consumption_km_l || "").trim()
    ? positiveDecimal(profile.multifactor_highway_consumption_km_l, "Consumo rodoviário", errors, "multifactor_highway_consumption_km_l")
    : null;

  if (Number(budget) > 200000 && !profile.allow_budget_above_200k) {
    errors.allow_budget_above_200k = "Autorize explicitamente a análise acima de R$ 200 mil.";
  }

  const isValid = Object.keys(errors).length === 0;
  return {
    errors,
    isValid,
    payload: isValid ? {
      enabled: true,
      allow_budget_above_200k: Boolean(profile.allow_budget_above_200k),
      scenario: {
        monthly_distance_km: monthlyDistance,
        city_percentage: cityPercentage,
        highway_percentage: highwayPercentage,
        state_code: stateCode,
        municipality: String(profile.multifactor_municipality || "").trim() || null,
        reference_week_start: week,
        fuel_strategy: fuelStrategy,
        horizon_months: horizon,
        manual_fuel_price_brl: manualPrice,
        city_consumption_km_l: cityConsumption,
        highway_consumption_km_l: highwayConsumption,
      },
      weights,
    } : null,
  };
}

export function resetMultifactorWeightFields(profile) {
  return Object.fromEntries(
    MULTIFACTOR_WEIGHT_FIELDS.map((code) => [`weight_${code}`, MULTIFACTOR_DEFAULT_WEIGHTS[code]]),
  );
}

export function multifactorWeightSummary(profile) {
  const entries = MULTIFACTOR_WEIGHT_FIELDS.map((code) => ({
    code,
    label: WEIGHT_LABELS[code],
    description: MULTIFACTOR_WEIGHT_DESCRIPTIONS[code],
    value: Number(decimalString(profile[`weight_${code}`]) || 0),
  }));
  const total = entries.reduce((sum, item) => sum + item.value, 0);
  return {
    total,
    entries: entries.map((item) => ({
      ...item,
      normalizedPercentage: total > 0 ? (item.value / total) * 100 : 0,
    })),
  };
}
