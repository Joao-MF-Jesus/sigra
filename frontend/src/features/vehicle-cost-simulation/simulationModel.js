const DECIMAL_PATTERN = /^\d+(?:[.,]\d+)?$/;
const INTEGER_PATTERN = /^\d+$/;

export const FUEL_OPTIONS = Object.freeze([
  { value: "gasoline_c_common", label: "Gasolina comum" },
  { value: "gasoline_c_additized", label: "Gasolina aditivada" },
  { value: "ethanol_hydrated", label: "Etanol hidratado" },
  { value: "lowest_projected_cost", label: "Menor custo entre evidências disponíveis" },
]);

export function createSimulationForm(profile = {}) {
  const suggestedDistance = positiveSuggestion(profile.monthly_mileage, "1000");
  const suggestedPrice = positiveSuggestion(profile.fuel_price, "");
  return {
    monthly_distance_km: suggestedDistance,
    city_percentage: "50",
    highway_percentage: "50",
    fuel_strategy: "gasoline_c_common",
    price_mode: suggestedPrice ? "manual" : "anp",
    manual_fuel_price_brl: suggestedPrice,
    horizon_months: "12",
    city_consumption_km_l: "",
    highway_consumption_km_l: "",
    state_code: "",
    municipality: "",
    reference_week_start: "",
    vehicle_sk: "",
  };
}

function positiveSuggestion(value, fallback) {
  const normalized = normalizeDecimal(value);
  return normalized && Number(normalized) > 0 ? normalized : fallback;
}

export function normalizeDecimal(value) {
  return String(value ?? "").trim().replace(",", ".");
}

function decimalError(value, { optional = false, maxDecimals = 4 } = {}) {
  const normalized = normalizeDecimal(value);
  if (!normalized) return optional ? "" : "Informe um valor.";
  if (!DECIMAL_PATTERN.test(normalized)) return "Use um número decimal válido.";
  const decimals = normalized.split(".")[1]?.length || 0;
  if (decimals > maxDecimals) return `Use no máximo ${maxDecimals} casas decimais.`;
  const numeric = Number(normalized);
  if (!Number.isFinite(numeric) || numeric <= 0) return "O valor deve ser maior que zero.";
  return "";
}

function percentageUnits(value) {
  const normalized = normalizeDecimal(value);
  if (!DECIMAL_PATTERN.test(normalized)) return null;
  const [whole, decimals = ""] = normalized.split(".");
  if (decimals.length > 2) return null;
  return Number(whole) * 100 + Number(decimals.padEnd(2, "0"));
}

export function complementPercentage(value) {
  const units = percentageUnits(value);
  if (units === null || units < 0 || units > 10000) return null;
  const complement = 10000 - units;
  return complement % 100 === 0
    ? String(complement / 100)
    : `${Math.floor(complement / 100)}.${String(complement % 100).padStart(2, "0")}`;
}

export function validateSimulationForm(form) {
  const errors = {};
  const monthlyError = decimalError(form.monthly_distance_km, { maxDecimals: 2 });
  if (monthlyError) errors.monthly_distance_km = monthlyError;

  const cityUnits = percentageUnits(form.city_percentage);
  const highwayUnits = percentageUnits(form.highway_percentage);
  if (cityUnits === null || cityUnits < 0 || cityUnits > 10000) {
    errors.city_percentage = "Informe um percentual entre 0 e 100, com até duas casas.";
  }
  if (highwayUnits === null || highwayUnits < 0 || highwayUnits > 10000) {
    errors.highway_percentage = "Informe um percentual entre 0 e 100, com até duas casas.";
  }
  if (cityUnits !== null && highwayUnits !== null && cityUnits + highwayUnits !== 10000) {
    errors.highway_percentage = "Uso urbano e rodoviário devem totalizar exatamente 100%.";
  }

  if (!FUEL_OPTIONS.some((option) => option.value === form.fuel_strategy)) {
    errors.fuel_strategy = "Selecione uma estratégia de combustível válida.";
  }
  if (form.price_mode === "manual") {
    const priceError = decimalError(form.manual_fuel_price_brl);
    if (priceError) errors.manual_fuel_price_brl = priceError;
    if (form.fuel_strategy === "lowest_projected_cost") {
      errors.fuel_strategy = "Preço manual exige um combustível específico.";
    }
  } else if (form.price_mode !== "anp") {
    errors.price_mode = "Selecione a origem do preço.";
  }

  if (!INTEGER_PATTERN.test(String(form.horizon_months || ""))) {
    errors.horizon_months = "Informe um número inteiro de meses.";
  } else {
    const horizon = Number(form.horizon_months);
    if (horizon < 1 || horizon > 120) errors.horizon_months = "Use um horizonte entre 1 e 120 meses.";
  }

  for (const field of ["city_consumption_km_l", "highway_consumption_km_l"]) {
    const error = decimalError(form[field], { optional: true });
    if (error) errors[field] = error;
  }

  if (!/^[A-Za-z]{2}$/.test(String(form.state_code || "").trim())) {
    errors.state_code = "Informe a UF com duas letras.";
  }
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(form.reference_week_start || ""))) {
    errors.reference_week_start = "Informe a semana de referência ANP.";
  }
  if (!INTEGER_PATTERN.test(String(form.vehicle_sk || "")) || Number(form.vehicle_sk) < 1) {
    errors.vehicle_sk = "Selecione um veículo para simulação.";
  }

  return { isValid: Object.keys(errors).length === 0, errors };
}

export function buildSimulationPayload(form) {
  const payload = {
    monthly_distance_km: normalizeDecimal(form.monthly_distance_km),
    city_percentage: normalizeDecimal(form.city_percentage),
    highway_percentage: normalizeDecimal(form.highway_percentage),
    state_code: String(form.state_code).trim().toUpperCase(),
    municipality: String(form.municipality || "").trim() || null,
    reference_week_start: form.reference_week_start,
    fuel_strategy: form.fuel_strategy,
    horizon_months: Number(form.horizon_months),
    vehicle_sks: [Number(form.vehicle_sk)],
    max_results: 1,
  };
  if (form.price_mode === "manual") {
    payload.manual_fuel_price_brl = normalizeDecimal(form.manual_fuel_price_brl);
  }
  if (String(form.city_consumption_km_l || "").trim()) {
    payload.city_consumption_km_l = normalizeDecimal(form.city_consumption_km_l);
  }
  if (String(form.highway_consumption_km_l || "").trim()) {
    payload.highway_consumption_km_l = normalizeDecimal(form.highway_consumption_km_l);
  }
  return payload;
}

function identityText(value) {
  return String(value || "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/\bvw\s*-?\s*volkswagen\b/g, "volkswagen")
    .replace(/[^a-z0-9]+/g, " ")
    .trim();
}

export function uniqueGoldVehicles(items) {
  const byVehicle = new Map();
  for (const item of Array.isArray(items) ? items : []) {
    if (!Number.isInteger(item?.vehicle_sk) || item.vehicle_sk < 1 || byVehicle.has(item.vehicle_sk)) continue;
    byVehicle.set(item.vehicle_sk, item);
  }
  return [...byVehicle.values()];
}

export function suggestedGoldVehicleSk(vehicle, items) {
  const brand = identityText(vehicle?.brand);
  const model = identityText(vehicle?.model);
  const year = Number(vehicle?.year);
  const exact = uniqueGoldVehicles(items).filter((item) => (
    identityText(item.brand_name) === brand
    && identityText(item.model_name) === model
    && Number(item.model_year) === year
  ));
  return exact.length === 1 ? String(exact[0].vehicle_sk) : "";
}

export function fuelPriceOriginLabel(origin) {
  if (origin === "anp_gold") return "Preço médio de referência";
  if (origin === "user_input") return "Preço informado pelo usuário";
  return "Origem não informada";
}

export function catalogErrorPresentation() {
  return "Não foi possível carregar os veículos para simulação. Tente novamente ou continue informando os valores manualmente.";
}

export function simulationErrorPresentation(error) {
  if (error?.status === 422) {
    return "Revise os parâmetros: um ou mais valores precisam ser corrigidos.";
  }
  if (error?.status === 409) {
    return "Há mais de uma correspondência possível para o veículo selecionado. Revise a seleção e tente novamente.";
  }
  if (error?.status === 503) {
    return "Não foi possível acessar os dados de referência para concluir a simulação. Tente novamente mais tarde.";
  }
  return "Não foi possível concluir a simulação. Tente novamente.";
}
