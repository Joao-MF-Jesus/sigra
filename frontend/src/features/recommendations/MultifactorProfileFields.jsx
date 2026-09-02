import React from "react";
import { multifactorWeightSummary } from "./multifactorRecommendationModel.js";

const FieldError = ({ id, message }) => message ? <small className="field-error" id={id} role="alert">{message}</small> : null;

function a11yError(errors, field) {
  return {
    "aria-invalid": Boolean(errors[field]),
    "aria-describedby": errors[field] ? `${field}-error` : undefined,
  };
}

export default function MultifactorProfileFields({ profile, errors, onChange, onResetWeights }) {
  const summary = multifactorWeightSummary(profile);
  return <fieldset className="multifactor-profile" data-testid="multifactor-profile-fields">
    <legend>Perfil multifator</legend>
    <label className="checkbox-line">
      <input data-testid="multifactor-enabled" type="checkbox" checked={Boolean(profile.multifactor_enabled)} onChange={(event) => onChange("multifactor_enabled", event.target.checked)} />
      Comparar custo, adequação e preferências com pesos próprios
    </label>
    {!profile.multifactor_enabled ? <p className="field-hint">Desativado: o ranking histórico permanece exatamente como antes.</p> : <>
      <p className="field-hint">O mesmo cenário será aplicado a todos os veículos comparáveis. Os cálculos financeiros são realizados exclusivamente pelo backend.</p>
      <h3 className="multifactor-subheading">Necessidade de deslocamento</h3>
      <div className="multifactor-grid">
        <label htmlFor="multifactor_monthly_distance_km">Distância mensal (km)<input id="multifactor_monthly_distance_km" type="number" min="0" step="0.01" {...a11yError(errors, "multifactor_monthly_distance_km")} value={profile.multifactor_monthly_distance_km} onChange={(event) => onChange("multifactor_monthly_distance_km", event.target.value)} /><FieldError id="multifactor_monthly_distance_km-error" message={errors.multifactor_monthly_distance_km} /></label>
        <label htmlFor="multifactor_city_percentage">Urbano (%)<input id="multifactor_city_percentage" type="number" min="0" max="100" step="0.01" {...a11yError(errors, "multifactor_city_percentage")} value={profile.multifactor_city_percentage} onChange={(event) => onChange("multifactor_city_percentage", event.target.value)} /><FieldError id="multifactor_city_percentage-error" message={errors.multifactor_city_percentage} /></label>
        <label htmlFor="multifactor_highway_percentage">Rodoviário (%)<input id="multifactor_highway_percentage" type="number" min="0" max="100" step="0.01" {...a11yError(errors, "multifactor_highway_percentage")} value={profile.multifactor_highway_percentage} onChange={(event) => onChange("multifactor_highway_percentage", event.target.value)} /><FieldError id="multifactor_highway_percentage-error" message={errors.multifactor_highway_percentage} /></label>
        <label htmlFor="multifactor_fuel_strategy">Estratégia de combustível<select id="multifactor_fuel_strategy" {...a11yError(errors, "multifactor_fuel_strategy")} value={profile.multifactor_fuel_strategy} onChange={(event) => onChange("multifactor_fuel_strategy", event.target.value)}><option value="gasoline_c_common">Gasolina comum</option><option value="ethanol_hydrated">Etanol hidratado</option><option value="lowest_projected_cost">Menor custo projetado</option></select><FieldError id="multifactor_fuel_strategy-error" message={errors.multifactor_fuel_strategy} /></label>
        <label htmlFor="multifactor_price_mode">Origem do preço<select id="multifactor_price_mode" {...a11yError(errors, "multifactor_price_mode")} value={profile.multifactor_price_mode} onChange={(event) => onChange("multifactor_price_mode", event.target.value)}><option value="anp">Gold ANP publicada</option><option value="manual">Preço informado pelo cliente</option></select><FieldError id="multifactor_price_mode-error" message={errors.multifactor_price_mode} /></label>
        {profile.multifactor_price_mode === "manual" && <label htmlFor="multifactor_manual_fuel_price_brl">Preço por litro (R$)<input id="multifactor_manual_fuel_price_brl" type="number" min="0" step="0.001" {...a11yError(errors, "multifactor_manual_fuel_price_brl")} value={profile.multifactor_manual_fuel_price_brl} onChange={(event) => onChange("multifactor_manual_fuel_price_brl", event.target.value)} /><FieldError id="multifactor_manual_fuel_price_brl-error" message={errors.multifactor_manual_fuel_price_brl} /></label>}
        <label htmlFor="multifactor_horizon_months">Horizonte (meses)<input id="multifactor_horizon_months" type="number" min="1" max="120" step="1" {...a11yError(errors, "multifactor_horizon_months")} value={profile.multifactor_horizon_months} onChange={(event) => onChange("multifactor_horizon_months", event.target.value)} /><FieldError id="multifactor_horizon_months-error" message={errors.multifactor_horizon_months} /></label>
        <label htmlFor="multifactor_state_code">UF<input id="multifactor_state_code" type="text" maxLength="2" {...a11yError(errors, "multifactor_state_code")} value={profile.multifactor_state_code} onChange={(event) => onChange("multifactor_state_code", event.target.value)} /><FieldError id="multifactor_state_code-error" message={errors.multifactor_state_code} /></label>
        <label htmlFor="multifactor_municipality">Município (opcional)<input id="multifactor_municipality" type="text" value={profile.multifactor_municipality} onChange={(event) => onChange("multifactor_municipality", event.target.value)} /></label>
        <label htmlFor="multifactor_reference_week_start">Semana ANP<input id="multifactor_reference_week_start" type="date" {...a11yError(errors, "multifactor_reference_week_start")} value={profile.multifactor_reference_week_start} onChange={(event) => onChange("multifactor_reference_week_start", event.target.value)} /><FieldError id="multifactor_reference_week_start-error" message={errors.multifactor_reference_week_start} /></label>
        <label htmlFor="multifactor_city_consumption_km_l">Consumo urbano manual (opcional)<input id="multifactor_city_consumption_km_l" type="number" min="0" step="0.01" value={profile.multifactor_city_consumption_km_l} onChange={(event) => onChange("multifactor_city_consumption_km_l", event.target.value)} /></label>
        <label htmlFor="multifactor_highway_consumption_km_l">Consumo rodoviário manual (opcional)<input id="multifactor_highway_consumption_km_l" type="number" min="0" step="0.01" value={profile.multifactor_highway_consumption_km_l} onChange={(event) => onChange("multifactor_highway_consumption_km_l", event.target.value)} /></label>
      </div>
      <FieldError id="multifactor_percentages-error" message={errors.multifactor_percentages} />
      <div className="multifactor-weight-heading"><strong>Pesos do ranking</strong><button type="button" className="ghost-button" onClick={onResetWeights}>Restaurar padrão</button></div>
      <div className="multifactor-grid">
        {summary.entries.map((item) => <label key={item.code} htmlFor={`weight_${item.code}`}>{item.label}<span className="weight-description">{item.description}</span><input id={`weight_${item.code}`} type="number" min="0" max="100" step="0.01" {...a11yError(errors, `weight_${item.code}`)} value={profile[`weight_${item.code}`]} onChange={(event) => onChange(`weight_${item.code}`, event.target.value)} /><small>{item.normalizedPercentage.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}% após normalização</small><FieldError id={`weight_${item.code}-error`} message={errors[`weight_${item.code}`]} /></label>)}
      </div>
      <p className="field-hint">Soma informada: {summary.total.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}. A normalização determinística é feita novamente pelo backend.</p>
      <FieldError id="multifactor_weights-error" message={errors.multifactor_weights} />
      <label className="checkbox-line"><input type="checkbox" checked={Boolean(profile.allow_budget_above_200k)} onChange={(event) => onChange("allow_budget_above_200k", event.target.checked)} />Autorizo explicitamente a análise de orçamento acima de R$ 200 mil.</label>
      <FieldError id="allow_budget_above_200k-error" message={errors.allow_budget_above_200k} />
    </>}
  </fieldset>;
}
