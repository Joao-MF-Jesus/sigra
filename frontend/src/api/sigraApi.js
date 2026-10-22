import { API_URL } from "../config/runtime.js";

export function sessionFetch(url, options = {}) {
  if (!String(url).startsWith(`${API_URL}/`)) return fetch(url, options);
  const headers = new Headers(options.headers);
  if (!["GET", "HEAD", "OPTIONS"].includes((options.method || "GET").toUpperCase())) headers.set("X-SIGRA-CSRF", "1");
  return fetch(url, { ...options, credentials: "include", headers });
}

export function createEmptyFinancialSummary() {
  return {
    total_expenses: 0,
    total_maintenance: 0,
    total_cost: 0,
    expenses_by_category: {},
    pending_maintenances: 0,
  };
}

export function resolveOperationalUserId(user) {
  if (!user) return null;
  const candidate = Number(user.id);
  return Number.isSafeInteger(candidate) && candidate > 0 ? candidate : null;
}

export async function requestOperationalData(user, { signal, fetchImpl = fetch } = {}) {
  const userId = resolveOperationalUserId(user);
  if (userId === null) {
    return {
      requested: false,
      expenses: [],
      summary: createEmptyFinancialSummary(),
    };
  }

  const [expenses, summary] = await Promise.all([
    requestJson("/expenses", { signal, fetchImpl }),
    requestJson(`/reports/financial-summary?user_id=${encodeURIComponent(userId)}`, { signal, fetchImpl }),
  ]);
  if (!Array.isArray(expenses) || !summary || typeof summary !== "object" || Array.isArray(summary)) {
    throw new Error("A API retornou dados operacionais inválidos.");
  }
  return { requested: true, expenses, summary };
}

export async function requestRecommendations(profile, { signal, fetchImpl = fetch, recordTest = false } = {}) {
  const path = recordTest ? "/api/v1/test-runs/recommendation" : "/recommendations?envelope=true";
  const response = await fetchImpl(`${API_URL}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-SIGRA-CSRF": "1" },
    body: JSON.stringify(profile),
    signal,
  });

  if (!response.ok) {
    let code = "";
    try {
      const body = await response.json();
      const candidate = body?.detail && typeof body.detail === "object"
        ? body.detail.code
        : "";
      code = typeof candidate === "string" && /^[a-z0-9_]{1,80}$/.test(candidate)
        ? candidate
        : "";
    } catch {
      // The HTTP status remains the useful diagnostic when the body is not JSON.
    }
    const error = new Error(`Falha ao calcular recomendação (HTTP ${response.status}).`);
    error.name = "SigraApiError";
    error.status = response.status;
    error.code = code;
    throw error;
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
    credentials: "include",
    headers: payload === undefined ? undefined : { "Content-Type": "application/json", "X-SIGRA-CSRF": "1" },
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
  return response.status === 204 ? null : response.json();
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
  return requestJson(options.recordTest ? "/api/v1/test-runs/fuel-simulation" : "/api/v1/integrated-vehicle-cost/simulate", {
    ...options,
    method: "POST",
    payload,
  });
}

export function requestFinancingMetadata(options = {}) {
  return requestJson("/financing/metadata", options);
}

export function requestFinancingSimulation(payload, options = {}) {
  return requestJson(options.recordTest ? "/api/v1/test-runs/financing" : "/financing/simulate", { ...options, method: "POST", payload });
}

export function requestReverseFinancingSimulation(payload, options = {}) {
  return requestJson(options.recordTest ? "/api/v1/test-runs/reverse-financing" : "/financing/reverse-simulate", { ...options, method: "POST", payload });
}

export function requestFinancingComparison(scenarios, options = {}) {
  return requestJson(options.recordTest ? "/api/v1/test-runs/financing-comparison" : "/financing/compare", { ...options, method: "POST", payload: { scenarios } });
}

export const requestSession = (options = {}) => requestJson("/auth/session", options);
export const requestLogin = (payload, options = {}) => requestJson("/auth/login", { ...options, method: "POST", payload });
export const requestRegistration = (payload, options = {}) => requestJson("/auth/register", { ...options, method: "POST", payload });
export const requestLogout = (options = {}) => requestJson("/auth/logout", { ...options, method: "POST", payload: {} });
export const requestTestHistory = (offset = 0, options = {}) => requestJson(`/api/v1/test-runs?limit=20&offset=${offset}&compact=true`, options);
export const requestTestDetail = (id, options = {}) => requestJson(`/api/v1/test-runs/${encodeURIComponent(id)}`, options);
export const requestTestFeedback = (id, payload, options = {}) => requestJson(`/api/v1/test-runs/${encodeURIComponent(id)}/feedback`, { ...options, method: "PATCH", payload });
export const requestTestQuestionnaire = (id, payload, options = {}) => requestJson(`/api/v1/test-runs/${encodeURIComponent(id)}/questionnaire`, { ...options, method: "PATCH", payload });
export const requestStudyMetadata = (options = {}) => requestJson("/api/v1/study-sessions/metadata", options);
export const requestStudyCurrent = (options = {}) => requestJson("/api/v1/study-sessions/current", options);
export const requestStudySession = (payload, options = {}) => requestJson("/api/v1/study-sessions", { ...options, method: "POST", payload });

export async function downloadTestRecords({ fetchImpl = fetch } = {}) {
  const response = await fetchImpl(`${API_URL}/api/v1/admin/test-runs.csv`, { credentials: "include" });
  if (!response.ok) throw new Error(`Não foi possível exportar os testes (HTTP ${response.status}).`);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = "sigra-testes-tcc.csv";
  link.click();
  URL.revokeObjectURL(url);
}

export { API_URL };

// Academic catalogue IDs are intentionally not accepted by operational helpers.
const ACADEMIC_PATH = "/api/v1/academic-cohort";

function assertAcademicResponse(data, snapshotId) {
  if (!data || data.mode !== "academic_only" || data.operationally_active !== false
      || data.recommended !== false || typeof data.snapshot_id !== "string"
      || typeof data.cohort_fingerprint !== "string"
      || (snapshotId && data.snapshot_id !== snapshotId)) {
    throw new Error("Resposta acadêmica incompatível com o snapshot selecionado.");
  }
  return data;
}

export function requestRecommendationMetadata(options = {}) {
  return requestJson("/recommendations/metadata", options);
}

async function academicJson(path, options = {}) {
  try {
    return assertAcademicResponse(await requestJson(`${ACADEMIC_PATH}${path}`, options), options.snapshotId);
  } catch (error) {
    if (error.name === "AbortError") throw error;
    // Never display arbitrary backend error bodies/SQL/connection strings.
    if (error.status) {
      const safe = new Error(`A API acadêmica não está disponível (HTTP ${error.status}).`);
      safe.status = error.status;
      throw safe;
    }
    if (error instanceof TypeError) throw new Error("Não foi possível conectar à API acadêmica. Confira o backend e tente novamente.");
    throw error;
  }
}

export async function requestAcademicMetadata(options = {}) {
  const data = await academicJson("/metadata", options);
  if (!Number.isSafeInteger(data.selected_count) || data.selected_count < 0 || !data.profile_counts
      || !Array.isArray(data.limitations)) throw new Error("Metadados acadêmicos inválidos.");
  return data;
}

export async function requestAcademicVehiclePage({ snapshotId, limit = 20, offset = 0, ...options } = {}) {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (snapshotId) query.set("snapshot_id", snapshotId);
  const data = await academicJson(`/vehicles?${query}`, { ...options, snapshotId });
  if (!Array.isArray(data.items) || !Number.isSafeInteger(data.total) || data.total < 0
      || data.offset !== offset || data.limit !== limit || data.items.length > limit
      || data.items.some((item) => !Number.isSafeInteger(item.catalog_id) || item.catalog_id <= 0
        || typeof item.label !== "string" || item.mode !== "academic_only"
        || item.operationally_active !== false || item.recommended !== false)) {
    throw new Error("Página do catálogo acadêmico inválida.");
  }
  return data;
}

export async function requestAcademicCatalog({ snapshotId, expectedCount, fingerprint, ...options } = {}) {
  const items = [];
  const ids = new Set();
  let total;
  do {
    const page = await requestAcademicVehiclePage({ ...options, snapshotId, limit: 20, offset: items.length });
    if ((total !== undefined && page.total !== total) || (expectedCount !== undefined && page.total !== expectedCount)
        || (fingerprint && page.cohort_fingerprint !== fingerprint)) throw new Error("O catálogo mudou durante a leitura. Recarregue os metadados.");
    snapshotId = page.snapshot_id;
    fingerprint = page.cohort_fingerprint;
    total = page.total;
    for (const item of page.items) {
      if (ids.has(item.catalog_id)) throw new Error("Identidade duplicada na paginação acadêmica.");
      ids.add(item.catalog_id);
      items.push(item);
    }
    if (items.length > total || (!page.items.length && items.length < total)) throw new Error("Paginação acadêmica incompleta.");
  } while (items.length < total);
  return items;
}

export async function requestAcademicVehicleDetail(catalogId, { snapshotId, ...options } = {}) {
  if (!Number.isSafeInteger(catalogId) || catalogId <= 0) throw new Error("ID acadêmico inválido.");
  const query = new URLSearchParams();
  if (snapshotId) query.set("snapshot_id", snapshotId);
  const data = await academicJson(`/vehicles/${catalogId}${query.size ? `?${query}` : ""}`, { ...options, snapshotId });
  if (data.vehicle?.catalog_id !== catalogId || !data.evidence?.fields || !data.evaluations) throw new Error("Detalhes acadêmicos inválidos.");
  return data;
}

export async function requestAcademicEvaluation(payload, options = {}) {
  const data = await academicJson("/evaluate", { ...options, snapshotId: payload.snapshot_id, method: "POST", payload });
  const ids = data.eligible_ids;
  const returned = data.returned_ids;
  if (data.profile !== payload.profile || data.scenario !== payload.scenario
      || !Array.isArray(ids) || new Set(ids).size !== ids.length || ids.length !== data.eligible_count
      || !Array.isArray(returned) || new Set(returned).size !== returned.length
      || !data.groups || !data.evaluations || !Array.isArray(data.limitations)) throw new Error("Avaliação acadêmica inválida.");
  const grouped = Object.values(data.groups).flatMap((group) => {
    if (!Array.isArray(group.ranking) || group.diagnostic_only !== true) throw new Error("Grupo acadêmico inválido.");
    return group.ranking.map((row) => row.id);
  });
  if (new Set(grouped).size !== grouped.length || grouped.length !== returned.length
      || grouped.some((id) => !returned.includes(id))) throw new Error("Agrupamento acadêmico inconsistente.");
  for (const id of returned) {
    const row = data.evaluations[String(id)];
    if (!ids.includes(id) || !row || row.id !== id || !row.academic_test_ready
        || row.operationally_active !== false || row.recommended !== false
        || row.profile !== payload.profile || row.scenario !== payload.scenario) throw new Error("Identidade da avaliação inconsistente.");
  }
  return data;
}
