import { formatCurrency } from "./recommendationModel.js";
import { CRITERION_LABELS } from "./cohortRecommendationModel.js";

export const COST_LABELS = { fuel: "Combustível", maintenance: "Manutenção", ipva: "IPVA", insurance: "Seguro", depreciation: "Depreciação" };
export const TECHNICAL_LABELS = { consumption_city: "Consumo urbano", consumption_highway: "Consumo rodoviário", seats: "Lugares", cargo_l: "Porta-malas", length_mm: "Comprimento", width_mm: "Largura da carroceria", wheelbase_mm: "Entre-eixos", width_with_mirrors_mm: "Largura com espelhos", body_footprint_m2: "Área da carroceria", ground_clearance_mm: "Vão livre do solo", weight_kg: "Peso", payload_kg: "Carga útil", power_gasoline_cv: "Potência com gasolina", rear_legroom_mm: "Espaço medido para pernas atrás", interior_width_mm: "Largura interna medida", fuel: "Combustível", transmission: "Câmbio", airbags: "Airbags", abs: "ABS", esc: "Controle de estabilidade" };
const VALUES = { flex: "Flex", gasoline: "Gasolina", ethanol: "Etanol", diesel: "Diesel", manual: "Manual", automatic: "Automático", cvt: "CVT" };
// Existing local demonstration illustrations only; never substitute another trim.
const IMAGE_SLUGS = new Set([
  "chevrolet-cobalt-ltz-2018", "chevrolet-onix-lt-2021", "chevrolet-prisma-lt-2018", "chevrolet-spin-lt-2019", "chevrolet-tracker-lt-2021",
  "fiat-argo-drive-2020", "fiat-cronos-drive-2020", "fiat-mobi-like-2021", "fiat-uno-attractive-2018", "ford-ecosport-se-2018", "ford-ka-se-2019",
  "honda-city-lx-2018", "honda-civic-ex-2017", "honda-fit-ex-2017", "honda-hr-v-lx-2018", "hyundai-creta-attitude-2019", "hyundai-hb20-comfort-2020", "hyundai-hb20s-comfort-2020",
  "jeep-renegade-sport-2019", "nissan-kicks-s-2020", "nissan-march-sv-2018", "nissan-versa-sv-2019", "renault-duster-zen-2020", "renault-logan-zen-2020", "renault-sandero-zen-2020",
  "toyota-corolla-cross-xr-2022", "toyota-corolla-gli-2018", "toyota-etios-xls-2018", "toyota-yaris-xl-2020", "volkswagen-gol-trendline-2019", "volkswagen-polo-msi-2019", "volkswagen-t-cross-200-tsi-2020", "volkswagen-virtus-msi-2019", "volkswagen-voyage-comfortline-2018",
]);
export function cohortImagePath(label) {
  const slug = String(label || "").toLowerCase().replaceAll(" ", "-").replaceAll(".", "");
  return IMAGE_SLUGS.has(slug) ? `/cars/${slug}.svg` : null;
}
export function readableValue(field) {
  if (field?.value === null || field?.value === undefined || field?.value === "") return "Não informado";
  if (typeof field.value === "boolean") return field.value ? "Sim" : "Não";
  if (VALUES[field.value]) return VALUES[field.value];
  const value = Number(field.value);
  if (!Number.isFinite(value)) return String(field.value);
  if (field.unit?.startsWith("BRL")) return formatCurrency(value) + ({ "BRL/month": "/mês", "BRL/l": "/l", "BRL/year": "/ano" }[field.unit] || "");
  const unit = { m2: "m²", "km/l": "km/l", "km/month": "km/mês", month: "meses", "score/100": "/100", mm: "mm", l: "l", count: "", kg: "kg" }[field.unit] ?? field.unit ?? "";
  return value.toLocaleString("pt-BR", { maximumFractionDigits: 2 }) + (unit ? ` ${unit}` : "");
}
export function referenceMonth(value) {
  if (!/^\d{4}-\d{2}$/.test(value || "")) return "Não informada";
  return new Intl.DateTimeFormat("pt-BR", { month: "long", year: "numeric", timeZone: "UTC" }).format(new Date(value + "-01T00:00:00Z"));
}
export function recommendationReasons(item) {
  if (item.multifactor?.status === "ranked") return item.multifactor.components
    .filter((row) => row.available && Number(row.input_weight) > 0)
    .sort((a, b) => Number(b.contribution) - Number(a.contribution)).slice(0, 3)
    .map((row) => `${row.label}: ${Number(row.contribution).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} pontos na comparação.`);
  return [...(item.explanations || [])].sort((a, b) => Number(b.contribution) - Number(a.contribution)).slice(0, 3)
    .map((row) => `${CRITERION_LABELS[row.criterion] || "Critério comprovado"}: ${Number(row.contribution).toLocaleString("pt-BR", { maximumFractionDigits: 2 })} pontos na comparação de referência.`);
}
export function cohortCoverage(rows) {
  const scored = rows.filter((row) => row.multifactor?.status === "ranked" && row.multifactor.final_score != null).length;
  return { scored, original: rows.length - scored };
}
export function criterionCoverage(item) {
  // A profile's documentary coverage is not coverage of the seven user weights.
  const personalized = item.multifactor?.enabled || item.multifactor?.status;
  const coverage = personalized ? item.multifactor.evidence_coverage : item.evaluation?.coverage;
  return { label: personalized ? "Cobertura da personalização" : "Cobertura documental do perfil",
    value: coverage?.weighted == null ? null : Number(coverage.weighted) * 100,
    missingLabels: personalized ? (coverage?.criteria || []).filter((row) => row.requested && !row.available).map((row) => row.label) : [] };
}
export function exclusionExplanation(row) {
  return row.reasons.map((reason) => ({
    PROFILE_DOCUMENTARY_REQUIREMENTS: row.documentary_diagnostic?.message || "As evidências desta versão não estão aprovadas para este perfil.",
    PURCHASE_BUDGET: "preço acima do orçamento de compra", MONTHLY_BUDGET: "custo acima do limite mensal",
    SCENARIO_TCO_INCOMPLETE: "custo estimado incompleto",
  })[reason] || "evidência insuficiente").join("; ");
}
