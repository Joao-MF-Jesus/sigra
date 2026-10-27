import React from "react";
import { multifactorWeightSummary, REFERENCE_PERSONALIZATION, DERIVED_PERSONALIZATION } from "./multifactorRecommendationModel.js";

const FieldError = ({ id, message }) => message ? <small className="field-error" id={id} role="alert">{message}</small> : null;

const fuelOptions = [
  ["gasoline_c_common", "Gasolina comum"],
  ["ethanol_hydrated", "Etanol hidratado"],
  ["lowest_projected_cost", "Menor custo projetado"],
];
const priceOptions = [
  ["anp", "Usar preço médio de referência"],
  ["manual", "Preço informado pelo cliente"],
];

function SelectOptions({ options }) {
  return options.map(([value, label]) => <option key={value} value={value}>{label}</option>);
}

function SelectedOption({ options, value }) {
  return <span className="selected-option" aria-hidden="true">{options.find(([key]) => key === value)?.[1]}</span>;
}

function a11yError(errors, field) {
  return {
    "aria-invalid": Boolean(errors[field]),
    "aria-describedby": errors[field] ? `${field}-error` : undefined,
  };
}

export default function MultifactorProfileFields({ profile, errors, onChange, onResetWeights, candidateSource, alternativeEnabled = false, configurationRegistry }) {
  const summary = multifactorWeightSummary(profile);
  const derived = profile.multifactor_policy_version === DERIVED_PERSONALIZATION;
  const preset = configurationRegistry?.configurations?.[profile.multifactor_configuration_id];
  return <fieldset className="multifactor-profile" data-testid="multifactor-profile-fields">
    <legend>Perfil multifator</legend>
    <label className="checkbox-line multifactor-toggle">
      <input data-testid="multifactor-enabled" type="checkbox" checked={Boolean(profile.multifactor_enabled)} onChange={(event) => onChange("multifactor_enabled", event.target.checked)} />
      <span>Comparar custo, adequação e preferências com pesos próprios</span>
    </label>
    {!profile.multifactor_enabled ? <p className="field-hint">{candidateSource === "academic_v6" ? "Desativado: a classificação de referência da coorte é preservada." : "Desativado: o ranking histórico permanece exatamente como antes."}</p> : <>
      <p className="field-hint">O mesmo cenário será aplicado a todos os veículos comparáveis. Os cálculos financeiros são realizados exclusivamente pelo backend.</p>
      {candidateSource === "academic_v6" && (alternativeEnabled || derived) && <label className="form-field multifactor-field" htmlFor="multifactor_policy_version"><span className="field-label">Método de personalização</span><select id="multifactor_policy_version" value={profile.multifactor_policy_version || REFERENCE_PERSONALIZATION} onChange={(event) => onChange("multifactor_policy_version", event.target.value)} {...a11yError(errors, "multifactor_policy_version")}><option value={REFERENCE_PERSONALIZATION}>Método original — referência</option><option value={DERIVED_PERSONALIZATION} disabled={!alternativeEnabled}>Alternativa acadêmica derivada — v1</option></select><FieldError id="multifactor_policy_version-error" message={errors.multifactor_policy_version} /></label>}
      {candidateSource === "academic_v6" && <p className="field-hint">{derived ? "Alternativa acadêmica derivada v1: os nomes abaixo indicam o significado efetivo de cada dimensão. Não mede conforto, comportamento rodoviário ou confiabilidade. Os pesos históricos são apenas referência; peso zero exclui explicitamente uma dimensão. Combustível e eficiência compartilham a mesma evidência de consumo e não são independentes." : "A personalização mantém os sete critérios originais. Critérios sem evidência não recebem nota; preço ANP e comparação entre combustíveis exigem dados que podem não estar disponíveis nesta base. Nesse caso, a classificação de referência é preservada e o motivo é informado."}</p>}
      {derived && configurationRegistry && <>
        <div className="multifactor-grid" data-testid="derived-configuration-control">
        <div className="multifactor-field"><label className="field-label" htmlFor="multifactor_configuration_id">Configuração da comparação</label>
          <select id="multifactor_configuration_id" value={profile.multifactor_configuration_id || ""} disabled={!alternativeEnabled} onChange={(event) => onChange("multifactor_configuration_id", event.target.value)} {...a11yError(errors, "multifactor_configuration_id")}>
            <option value="">Escolha explicitamente uma configuração</option>
            {Object.entries(configurationRegistry.configurations).map(([id, config]) => <option value={id} key={id}>{config.label}{config.proposed_profiles.includes(profile.use_case) ? " — proposta para este perfil" : " — opção explícita"}</option>)}
          </select><FieldError id="multifactor_configuration_id-error" message={errors.multifactor_configuration_id} />
        </div>
        </div>
        <p className="field-hint">Selecionar uma configuração aplica seu vetor fixo a todos os veículos. Trocar de perfil não altera a seleção nem os pesos. Você pode editar os pesos explicitamente depois.</p>
        {preset && <div className="processing-summary" data-testid="derived-configuration-summary"><strong>{preset.label}</strong><p>Pesos efetivos: {summary.entries.map((item) => `${item.label}: ${item.normalizedPercentage.toLocaleString("pt-BR", { maximumFractionDigits: 4 })}%`).join("; ")}.</p><p>{summary.entries.some((item) => item.value !== Number(preset.weights[item.code])) ? "Pesos ajustados explicitamente; o vetor efetivo será registrado." : "Vetor fixo da configuração selecionada."}</p><p>Pesos zero excluem dimensões da nota, não os requisitos documentais do perfil. Notas de configurações ou pesos diferentes não devem ser comparadas diretamente.</p></div>}
      </>}
      <h3 className="multifactor-subheading">Necessidade de deslocamento</h3>
      <div className="multifactor-grid">
        <label className="form-field multifactor-field" htmlFor="multifactor_monthly_distance_km"><span className="field-label">Distância mensal (km)</span><input id="multifactor_monthly_distance_km" type="number" min="0" step="0.01" {...a11yError(errors, "multifactor_monthly_distance_km")} value={profile.multifactor_monthly_distance_km} onChange={(event) => onChange("multifactor_monthly_distance_km", event.target.value)} /><FieldError id="multifactor_monthly_distance_km-error" message={errors.multifactor_monthly_distance_km} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_city_percentage"><span className="field-label">Urbano (%)</span><input id="multifactor_city_percentage" type="number" min="0" max="100" step="0.01" {...a11yError(errors, "multifactor_city_percentage")} value={profile.multifactor_city_percentage} onChange={(event) => onChange("multifactor_city_percentage", event.target.value)} /><FieldError id="multifactor_city_percentage-error" message={errors.multifactor_city_percentage} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_highway_percentage"><span className="field-label">Rodoviário (%)</span><input id="multifactor_highway_percentage" type="number" min="0" max="100" step="0.01" {...a11yError(errors, "multifactor_highway_percentage")} value={profile.multifactor_highway_percentage} onChange={(event) => onChange("multifactor_highway_percentage", event.target.value)} /><FieldError id="multifactor_highway_percentage-error" message={errors.multifactor_highway_percentage} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_fuel_strategy"><span className="field-label">Estratégia de combustível</span><select id="multifactor_fuel_strategy" {...a11yError(errors, "multifactor_fuel_strategy")} value={profile.multifactor_fuel_strategy} onChange={(event) => onChange("multifactor_fuel_strategy", event.target.value)}><SelectOptions options={fuelOptions} /></select><SelectedOption options={fuelOptions} value={profile.multifactor_fuel_strategy} /><FieldError id="multifactor_fuel_strategy-error" message={errors.multifactor_fuel_strategy} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_price_mode"><span className="field-label">Origem do preço</span><select id="multifactor_price_mode" {...a11yError(errors, "multifactor_price_mode")} value={profile.multifactor_price_mode} onChange={(event) => onChange("multifactor_price_mode", event.target.value)}><SelectOptions options={priceOptions} /></select><SelectedOption options={priceOptions} value={profile.multifactor_price_mode} /><FieldError id="multifactor_price_mode-error" message={errors.multifactor_price_mode} /></label>
        {profile.multifactor_price_mode === "manual" && <label className="form-field multifactor-field" htmlFor="multifactor_manual_fuel_price_brl"><span className="field-label">Preço por litro (R$)</span><input id="multifactor_manual_fuel_price_brl" type="number" min="0" step="0.001" {...a11yError(errors, "multifactor_manual_fuel_price_brl")} value={profile.multifactor_manual_fuel_price_brl} onChange={(event) => onChange("multifactor_manual_fuel_price_brl", event.target.value)} /><FieldError id="multifactor_manual_fuel_price_brl-error" message={errors.multifactor_manual_fuel_price_brl} /></label>}
        <label className="form-field multifactor-field" htmlFor="multifactor_horizon_months"><span className="field-label">Horizonte (meses)</span><input id="multifactor_horizon_months" type="number" min="1" max="120" step="1" {...a11yError(errors, "multifactor_horizon_months")} value={profile.multifactor_horizon_months} onChange={(event) => onChange("multifactor_horizon_months", event.target.value)} /><FieldError id="multifactor_horizon_months-error" message={errors.multifactor_horizon_months} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_state_code"><span className="field-label">UF</span><input id="multifactor_state_code" type="text" maxLength="2" {...a11yError(errors, "multifactor_state_code")} value={profile.multifactor_state_code} onChange={(event) => onChange("multifactor_state_code", event.target.value)} /><FieldError id="multifactor_state_code-error" message={errors.multifactor_state_code} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_municipality"><span className="field-label">Município (opcional)</span><input id="multifactor_municipality" type="text" value={profile.multifactor_municipality} onChange={(event) => onChange("multifactor_municipality", event.target.value)} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_reference_week_start"><span className="field-label">Semana ANP</span><input id="multifactor_reference_week_start" type="date" {...a11yError(errors, "multifactor_reference_week_start")} value={profile.multifactor_reference_week_start} onChange={(event) => onChange("multifactor_reference_week_start", event.target.value)} /><FieldError id="multifactor_reference_week_start-error" message={errors.multifactor_reference_week_start} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_city_consumption_km_l"><span className="field-label">Consumo urbano manual (opcional)</span><input id="multifactor_city_consumption_km_l" type="number" min="0" step="0.01" {...a11yError(errors, "multifactor_city_consumption_km_l")} value={profile.multifactor_city_consumption_km_l} onChange={(event) => onChange("multifactor_city_consumption_km_l", event.target.value)} /><FieldError id="multifactor_city_consumption_km_l-error" message={errors.multifactor_city_consumption_km_l} /></label>
        <label className="form-field multifactor-field" htmlFor="multifactor_highway_consumption_km_l"><span className="field-label">Consumo rodoviário manual (opcional)</span><input id="multifactor_highway_consumption_km_l" type="number" min="0" step="0.01" {...a11yError(errors, "multifactor_highway_consumption_km_l")} value={profile.multifactor_highway_consumption_km_l} onChange={(event) => onChange("multifactor_highway_consumption_km_l", event.target.value)} /><FieldError id="multifactor_highway_consumption_km_l-error" message={errors.multifactor_highway_consumption_km_l} /></label>
      </div>
      <FieldError id="multifactor_percentages-error" message={errors.multifactor_percentages} />
      <div className="multifactor-weight-heading"><strong>Pesos do ranking</strong><button type="button" className="ghost-button" onClick={onResetWeights}>{preset ? "Restaurar pesos da configuração" : "Restaurar padrão"}</button></div>
      <div className="multifactor-grid">
        {summary.entries.map((item) => <label className="form-field multifactor-field weight-field" key={item.code} htmlFor={`weight_${item.code}`}><span className="field-label">{item.label}</span><input id={`weight_${item.code}`} type="number" min="0" max="100" step={derived ? "0.0001" : "0.01"} {...a11yError(errors, `weight_${item.code}`)} value={profile[`weight_${item.code}`]} onChange={(event) => onChange(`weight_${item.code}`, event.target.value)} /><span className="weight-description">{item.description}</span><small className="field-hint">{item.normalizedPercentage.toLocaleString("pt-BR", { maximumFractionDigits: derived ? 4 : 2 })}% após normalização</small><FieldError id={`weight_${item.code}-error`} message={errors[`weight_${item.code}`]} /></label>)}
      </div>
      <p className="field-hint">Soma informada: {summary.total.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}. A normalização determinística é feita novamente pelo backend.</p>
      <FieldError id="multifactor_weights-error" message={errors.multifactor_weights} />
    </>}
  </fieldset>;
}
