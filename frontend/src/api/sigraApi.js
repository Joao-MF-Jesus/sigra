import { API_URL } from "../config/runtime.js";

export async function requestRecommendations(profile, { signal, fetchImpl = fetch } = {}) {
  const response = await fetchImpl(`${API_URL}/recommendations?envelope=true`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(profile),
    signal,
  });

  if (!response.ok) {
    let detail = "";
    try {
      const body = await response.json();
      detail = typeof body?.detail === "string" ? body.detail : "";
    } catch {
      // The HTTP status remains the useful diagnostic when the body is not JSON.
    }
    throw new Error(detail || `Falha ao calcular recomendação (HTTP ${response.status}).`);
  }

  const data = await response.json();
  if (Array.isArray(data)) {
    return { recommendations: data, has_viable_options: data.some((item) => item?.is_best_choice) };
  }
  if (!data || !Array.isArray(data.recommendations)) {
    throw new Error("A API retornou uma resposta de recomendação inválida.");
  }
  return data;
}

export async function requestMotorcycles({ signal, fetchImpl = fetch } = {}) {
  const response = await fetchImpl(`${API_URL}/motorcycles`, { signal });
  if (!response.ok) throw new Error(`Falha ao carregar motocicletas (HTTP ${response.status}).`);
  const data = await response.json();
  if (!Array.isArray(data)) throw new Error("A API retornou uma lista de motocicletas inválida.");
  return data;
}

export async function requestMotorcycleCatalog({ signal, fetchImpl = fetch, includeLegacy = false } = {}) {
  const legacyQuery = includeLegacy ? "&include_legacy=true" : "";
  const response = await fetchImpl(`${API_URL}/motorcycles?envelope=true${legacyQuery}`, { signal });
  if (!response.ok) throw new Error(`Falha ao carregar motocicletas (HTTP ${response.status}).`);
  const data = await response.json();
  if (Array.isArray(data)) {
    return {
      module_version: null,
      algorithm_version: null,
      weights_version: null,
      derived_metrics_method_version: null,
      total_found: data.length,
      returned: data.length,
      valid_records: data.filter((item) => item?.record_status !== "incomplete").length,
      invalid_records: data.filter((item) => item?.record_status === "incomplete").length,
      invalid_record_summary: [],
      motorcycles: data,
    };
  }
  if (!data || !Array.isArray(data.motorcycles)) {
    throw new Error("A API retornou um catálogo de motocicletas inválido.");
  }
  return data;
}

async function requestJson(path, { method = "GET", payload, signal, fetchImpl = fetch } = {}) {
  const response = await fetchImpl(`${API_URL}${path}`, {
    method,
    headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    signal,
  });
  if (!response.ok) {
    let detail = "";
    let code = "";
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") {
        detail = body.detail;
      } else if (body?.detail && typeof body.detail === "object") {
        detail = typeof body.detail.message === "string" ? body.detail.message : "";
        code = typeof body.detail.code === "string" ? body.detail.code : "";
      }
    } catch {
      // Keep the status as the diagnostic when the response is not JSON.
    }
    const error = new Error(detail || `A API recusou a operação (HTTP ${response.status}).`);
    error.name = "SigraApiError";
    error.status = response.status;
    error.code = code;
    throw error;
  }
  return response.json();
}

export async function requestIntegratedGoldCatalog({ signal, fetchImpl = fetch } = {}) {
  const items = [];
  const limit = 100;
  let offset = 0;
  let total = 0;

  do {
    const page = await requestJson(
      `/api/v1/integrated-vehicle-cost/vehicles?limit=${limit}&offset=${offset}&sort_by=brand_name&sort_direction=asc`,
      { signal, fetchImpl },
    );
    if (!page || !Array.isArray(page.items) || !Number.isInteger(page.total) || page.total < 0) {
      throw new Error("A API retornou um catálogo Gold integrado inválido.");
    }
    items.push(...page.items);
    total = page.total;
    offset += page.items.length;
    if (page.items.length === 0 && offset < total) {
      throw new Error("A paginação do catálogo Gold integrado não avançou.");
    }
  } while (offset < total);

  return items;
}

export function requestVehicleCostSimulation(payload, options = {}) {
  return requestJson("/api/v1/integrated-vehicle-cost/simulate", {
    ...options,
    method: "POST",
    payload,
  });
}

export function requestFinancingMetadata(options = {}) {
  return requestJson("/financing/metadata", options);
}

export function requestFinancingSimulation(payload, options = {}) {
  return requestJson("/financing/simulate", { ...options, method: "POST", payload });
}

export function requestReverseFinancingSimulation(payload, options = {}) {
  return requestJson("/financing/reverse-simulate", { ...options, method: "POST", payload });
}

export function requestFinancingComparison(scenarios, options = {}) {
  return requestJson("/financing/compare", { ...options, method: "POST", payload: { scenarios } });
}

export { API_URL };
