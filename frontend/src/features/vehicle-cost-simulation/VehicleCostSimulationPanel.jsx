import React, { useEffect, useMemo, useState } from "react";
import { requestIntegratedGoldCatalog, requestVehicleCostSimulation } from "../../api/sigraApi.js";
import { useSession } from "../session/SessionContext.jsx";
import { TestFeedback } from "../session/TestHistory.jsx";
import {
  FUEL_OPTIONS,
  buildSimulationPayload,
  catalogErrorPresentation,
  complementPercentage,
  createSimulationForm,
  fuelPriceOriginLabel,
  suggestedGoldVehicleSk,
  simulationErrorPresentation,
  uniqueGoldVehicles,
  validateSimulationForm,
} from "./simulationModel.js";

const currencyFormatter = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
const decimalFormatter = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 4 });

function currency(value) {
  return value === null || value === undefined ? "Não calculado" : currencyFormatter.format(value);
}

function decimal(value, suffix = "") {
  return value === null || value === undefined ? "Não calculado" : `${decimalFormatter.format(value)}${suffix}`;
}

function FieldError({ message }) {
  return message ? <small className="field-error">{message}</small> : null;
}

function GoldVehicleOption({ item }) {
  const version = item.version_name ? ` ${item.version_name}` : "";
  return <>{item.brand_name} {item.model_name}{version} {item.model_year || ""}</>;
}

function SimulationResult({ response, vehicleSk }) {
  const result = response?.results?.find((item) => item.vehicle_sk === Number(vehicleSk));
  const exclusion = response?.exclusions?.find((item) => item.vehicle_sk === Number(vehicleSk));
  if (!result) {
    return <div className="vehicle-simulation-warning" role="status"><strong>Simulação não disponível para este veículo.</strong><p>{exclusion?.detail || "As fontes de referência não possuem dados suficientes para o cenário informado."}</p></div>;
  }
  return <section className="vehicle-simulation-result" aria-live="polite" data-testid="vehicle-cost-simulation-result">
    <div className="vehicle-simulation-result-heading"><div><p className="eyebrow">Projeção personalizada</p><h4>{result.brand_name} {result.model_name}</h4></div><span>{fuelPriceOriginLabel(result.fuel_price_origin)}</span></div>
    <div className="vehicle-simulation-metrics">
      <article><span>Consumo mensal</span><strong>{decimal(result.estimated_monthly_liters, " L")}</strong></article>
      <article><span>Custo mensal</span><strong>{currency(result.monthly_fuel_cost_brl)}</strong></article>
      <article><span>Custo anual</span><strong>{currency(result.annual_fuel_cost_brl)}</strong></article>
      <article><span>Custo no horizonte</span><strong>{currency(result.projected_horizon_cost_brl)}</strong><small>{result.horizon_months} meses</small></article>
      <article><span>Custo por km</span><strong>{currency(result.fuel_cost_per_km_brl)}</strong></article>
      <article><span>Preço por litro</span><strong>{currency(result.fuel_price_per_liter_brl)}</strong></article>
    </div>
    <p className="form-help">Comparação com o cenário analítico de referência: diferença mensal de {currency(result.monthly_cost_difference_brl)}. Essa referência não altera os parâmetros informados por você.</p>
    <details className="data-provenance"><summary>Sobre os dados</summary><p>Fontes de referência: FIPE, PBEV e ANP.</p></details>
    {[...(result.warnings || []), ...(result.limitations || [])].length > 0 && <ul className="vehicle-simulation-warnings">{[...(result.warnings || []), ...(result.limitations || [])].map((message) => <li key={message}>{message}</li>)}</ul>}
    <p className="vehicle-simulation-disclaimer">Resultado somente de simulação. As fontes publicadas permanecem inalteradas.{response?.test_run ? " Esta execução foi registrada no seu histórico privado." : " Execução como visitante, sem registro pessoal."}</p>
  </section>;
}

export default function VehicleCostSimulationPanel({ vehicle, profile }) {
  const { user } = useSession();
  const [form, setForm] = useState(() => createSimulationForm(profile));
  const [errors, setErrors] = useState({});
  const [catalog, setCatalog] = useState([]);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState("");
  const [catalogAttempt, setCatalogAttempt] = useState(0);
  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    setCatalogLoading(true);
    setCatalogError("");
    requestIntegratedGoldCatalog({ signal: controller.signal })
      .then((items) => {
        if (!active) return;
        const unique = uniqueGoldVehicles(items);
        setCatalog(unique);
        setForm((current) => ({
          ...current,
          vehicle_sk: suggestedGoldVehicleSk(vehicle, unique),
        }));
      })
      .catch((error) => {
        if (active && error.name !== "AbortError") setCatalogError(catalogErrorPresentation(error));
      })
      .finally(() => {
        if (active) setCatalogLoading(false);
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [vehicle?.brand, vehicle?.model, vehicle?.year, catalogAttempt]);

  const selectedGoldVehicle = useMemo(
    () => catalog.find((item) => item.vehicle_sk === Number(form.vehicle_sk)),
    [catalog, form.vehicle_sk],
  );

  function change(field, value) {
    setResponse(null);
    setApiError("");
    setErrors((current) => ({ ...current, [field]: "" }));
    setForm((current) => {
      const next = { ...current, [field]: value };
      if (field === "city_percentage") {
        const complement = complementPercentage(value);
        if (complement !== null) next.highway_percentage = complement;
      }
      if (field === "highway_percentage") {
        const complement = complementPercentage(value);
        if (complement !== null) next.city_percentage = complement;
      }
      if (field === "price_mode" && value === "anp") next.manual_fuel_price_brl = "";
      return next;
    });
  }

  async function submit(event) {
    event.preventDefault();
    const validation = validateSimulationForm(form);
    setErrors(validation.errors);
    setApiError("");
    setResponse(null);
    if (!validation.isValid) return;
    setLoading(true);
    try {
      const data = await requestVehicleCostSimulation(buildSimulationPayload(form), { recordTest: Boolean(user) });
      setResponse(data);
    } catch (error) {
      setApiError(simulationErrorPresentation(error));
    } finally {
      setLoading(false);
    }
  }

  return <section className="modal-section vehicle-simulation" data-testid="vehicle-cost-simulation">
    <div><p className="eyebrow">Simulação configurável</p><h3>Custo de combustível no seu cenário</h3><p>Os valores abaixo são editáveis. O cálculo é realizado no backend com dados de referência publicados.</p></div>
    <form className="vehicle-simulation-form" onSubmit={submit} noValidate>
      <fieldset><legend>Veículo e uso</legend>
        <p className="form-help simulation-selection-scope" data-testid="simulation-selection-scope"><strong>Simular outro veículo com cobertura</strong><br />A escolha abaixo vale somente para esta simulação: não vincula nem substitui {vehicle.brand} {vehicle.model}, cujos detalhes estão abertos. Nenhuma correspondência de identidade será salva.</p>
        <label>Veículo para simulação<select data-testid="simulation-vehicle-sk" value={form.vehicle_sk} disabled={catalogLoading || catalog.length === 0} onChange={(event) => change("vehicle_sk", event.target.value)}><option value="">{catalogLoading ? "Carregando veículos..." : "Selecione"}</option>{catalog.map((item) => <option key={item.vehicle_sk} value={item.vehicle_sk}><GoldVehicleOption item={item} /></option>)}</select><FieldError message={errors.vehicle_sk} /></label>
        {catalogError && <div className="vehicle-simulation-error catalog-feedback" role="alert"><p>{catalogError}</p><button className="ghost-button" type="button" onClick={() => setCatalogAttempt((current) => current + 1)}>Tentar novamente</button></div>}
        {!catalogLoading && !catalogError && catalog.length === 0 && <div className="vehicle-simulation-warning catalog-feedback" role="status"><p>Nenhum veículo está disponível para simulação neste momento. Você pode continuar informando os valores e tentar novamente.</p><button className="ghost-button" type="button" onClick={() => setCatalogAttempt((current) => current + 1)}>Tentar novamente</button></div>}
        {selectedGoldVehicle && <p className="form-help" data-testid="simulation-selected-vehicle">Veículo selecionado apenas para esta simulação: <GoldVehicleOption item={selectedGoldVehicle} />.</p>}
        <div className="vehicle-simulation-grid"><label>Quilometragem mensal<input data-testid="simulation-monthly-distance" inputMode="decimal" value={form.monthly_distance_km} onChange={(event) => change("monthly_distance_km", event.target.value)} /><FieldError message={errors.monthly_distance_km} /></label><label>Horizonte (meses)<input data-testid="simulation-horizon" type="number" min="1" max="120" step="1" value={form.horizon_months} onChange={(event) => change("horizon_months", event.target.value)} /><FieldError message={errors.horizon_months} /></label></div>
        <div className="vehicle-simulation-grid"><label>Uso urbano (%)<input data-testid="simulation-city-percentage" inputMode="decimal" value={form.city_percentage} onChange={(event) => change("city_percentage", event.target.value)} /><FieldError message={errors.city_percentage} /></label><label>Uso rodoviário (%)<input data-testid="simulation-highway-percentage" inputMode="decimal" value={form.highway_percentage} onChange={(event) => change("highway_percentage", event.target.value)} /><FieldError message={errors.highway_percentage} /></label></div>
      </fieldset>

      <fieldset><legend>Combustível e preço</legend>
        <label>Estratégia<select data-testid="simulation-fuel-strategy" value={form.fuel_strategy} onChange={(event) => change("fuel_strategy", event.target.value)}>{FUEL_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select><FieldError message={errors.fuel_strategy} /></label>
        <div className="segmented-control" aria-label="Origem do preço"><button type="button" aria-pressed={form.price_mode === "anp"} className={form.price_mode === "anp" ? "active" : ""} onClick={() => change("price_mode", "anp")}>Usar preço médio de referência</button><button type="button" aria-pressed={form.price_mode === "manual"} className={form.price_mode === "manual" ? "active" : ""} onClick={() => change("price_mode", "manual")}>Preço informado</button></div><FieldError message={errors.price_mode} />
        {form.price_mode === "manual" && <label>Preço por litro (R$)<input data-testid="simulation-manual-price" inputMode="decimal" value={form.manual_fuel_price_brl} onChange={(event) => change("manual_fuel_price_brl", event.target.value)} /><FieldError message={errors.manual_fuel_price_brl} /><small className="form-help">A origem será registrada como preço informado pelo usuário; não haverá fallback ANP.</small></label>}
        <div className="vehicle-simulation-grid"><label>UF<input data-testid="simulation-state-code" maxLength="2" value={form.state_code} onChange={(event) => change("state_code", event.target.value.toUpperCase())} /><FieldError message={errors.state_code} /></label><label>Município <span className="optional-label">Opcional</span><input value={form.municipality} onChange={(event) => change("municipality", event.target.value)} /></label><label>Semana ANP<input data-testid="simulation-reference-week" type="date" value={form.reference_week_start} onInput={(event) => change("reference_week_start", event.target.value)} /><FieldError message={errors.reference_week_start} /></label></div>
      </fieldset>

      <fieldset><legend>Consumo específico <span className="optional-label">Opcional</span></legend><p className="form-help">Deixe em branco para usar exclusivamente a evidência PBEV publicada. Se informar, o valor será identificado como parâmetro do usuário.</p><div className="vehicle-simulation-grid"><label>Consumo urbano (km/l)<input data-testid="simulation-city-consumption" inputMode="decimal" value={form.city_consumption_km_l} onChange={(event) => change("city_consumption_km_l", event.target.value)} /><FieldError message={errors.city_consumption_km_l} /></label><label>Consumo rodoviário (km/l)<input data-testid="simulation-highway-consumption" inputMode="decimal" value={form.highway_consumption_km_l} onChange={(event) => change("highway_consumption_km_l", event.target.value)} /><FieldError message={errors.highway_consumption_km_l} /></label></div></fieldset>
      {apiError && <p className="vehicle-simulation-error" role="alert">{apiError}</p>}
      <button type="submit" disabled={loading || catalogLoading || !form.vehicle_sk}>{loading ? "Calculando..." : "Calcular meu cenário"}</button>
    </form>
    {response && <SimulationResult response={response} vehicleSk={form.vehicle_sk} />}
    {user && response?.test_run && <TestFeedback key={response.test_run.id} run={response.test_run} />}
  </section>;
}
