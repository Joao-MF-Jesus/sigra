export const ACADEMIC_PROFILES = Object.freeze([
  ["cidade", "Cidade"], ["app", "Aplicativo"], ["trabalho", "Trabalho"],
  ["suv", "Espaço/capacidade"], ["familia", "Família"], ["estrada", "Estrada"],
]);
export const ACADEMIC_SCENARIOS = Object.freeze([["low", "Baixo"], ["base", "Base"], ["high", "Alto"]]);
export const DEFAULT_ACADEMIC_FORM = Object.freeze({ profile: "app", scenario: "base", limit: "10", purchase: "", monthly: "" });
export const NATURE_LABELS = Object.freeze({ observed: "Observado", derived: "Derivado", derived_academic: "Derivado acadêmico", scenario_estimate: "Estimativa de cenário", scenario_parameter: "Parâmetro de cenário", unavailable: "Indisponível" });
export const FIELD_LABELS = Object.freeze({ fuel: "Combustível", transmission: "Transmissão", seats: "Lugares", cargo_l: "Porta-malas", length_mm: "Comprimento", width_mm: "Largura da carroceria", width_with_mirrors_mm: "Largura com espelhos", wheelbase_mm: "Entre-eixos", consumption_city: "Consumo urbano PBEV", consumption_highway: "Consumo rodoviário PBEV", airbags: "Airbags", abs: "ABS", esc: "ESC", urban_fuel: "Combustível urbano", highway_fuel: "Combustível rodoviário", passenger_space: "Habitabilidade", cargo: "Porta-malas", price: "Preço", footprint: "Área externa com espelhos", operating_cost: "Custo de operação", safety: "Segurança", ground_clearance: "Vão livre", maintenance: "Manutenção", ipva: "IPVA", insurance: "Seguro", depreciation: "Depreciação" });

export function academicPayload(form, snapshotId) {
  if (!ACADEMIC_PROFILES.some(([key]) => key === form.profile) || !ACADEMIC_SCENARIOS.some(([key]) => key === form.scenario)) throw new Error("Selecione um perfil e cenário válidos.");
  const limit = Number(form.limit);
  if (!Number.isInteger(limit) || limit < 1 || limit > 60) throw new Error("O limite por grupo deve estar entre 1 e 60.");
  const payload = { profile: form.profile, scenario: form.scenario, limit, snapshot_id: snapshotId };
  for (const [input, key] of [["purchase", "max_purchase_price_brl"], ["monthly", "max_monthly_tco_brl"]]) {
    const raw = String(form[input] ?? "").trim();
    if (!raw) continue;
    if (!/^\d+(?:\.\d{1,2})?$/.test(raw) || Number(raw) <= 0 || !Number.isFinite(Number(raw))) throw new Error("Os limites devem ser valores positivos em reais, com até duas casas decimais.");
    payload[key] = raw; // Decimal transport string; never recompute prices or TCO here.
  }
  return payload;
}

export function academicNumber(value, options = {}) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean" || !Number.isFinite(Number(value))) return "Indisponível";
  return Number(value).toLocaleString("pt-BR", { maximumFractionDigits: 2, ...options });
}
export const academicCurrency = (value) => academicNumber(value, { style: "currency", currency: "BRL" });
export function academicValue(field) {
  if (field?.value === null || field?.value === undefined) return "Indisponível";
  if (typeof field.value === "boolean") return field.value ? "Sim" : "Não";
  const value = typeof field.value === "object" ? "Consulte a proveniência" : String(field.value);
  return `${value}${field.unit && field.unit !== "text" && field.unit !== "bool" ? ` ${field.unit}` : ""}`;
}
export function academicError(error) {
  if (error?.status === 404) return "Modo acadêmico ou snapshot indisponível. Confira a configuração do backend acadêmico.";
  if (error?.status === 503) return "A coorte acadêmica não está disponível no backend. Nenhuma fixture ou catálogo operacional será usado como substituto.";
  return error?.message || "Não foi possível carregar a coorte acadêmica. Tente novamente.";
}

// Both abort and generation checks are needed: transports may finish after abort.
export function createAcademicRequestGate() {
  let generation = 0;
  let controller;
  return {
    cancel() { generation += 1; controller?.abort(); },
    begin() {
      controller?.abort();
      controller = new AbortController();
      const current = ++generation;
      const signal = controller.signal;
      return { signal, isCurrent: () => current === generation && !signal.aborted };
    },
  };
}
