import React from "react";
import { multifactorWeightSummary } from "./multifactorRecommendationModel.js";

const FieldError = ({ message }) => message ? <small className="field-error">{message}</small> : null;

export default function MultifactorProfileFields({ profile, errors, onChange, onResetWeights }) {
  const summary = multifactorWeightSummary(profile);
  return <fieldset className="multifactor-profile" data-testid="multifactor-profile-fields">
    <legend>7. Perfil multifator opcional</legend>
    <label className="checkbox-line">
      <input data-testid="multifactor-enabled" type="checkbox" checked={Boolean(profile.multifactor_enabled)} onChange={(event) => onChange("multifactor_enabled", event.target.checked)} />
      Personalizar o ranking com custo e critérios ponderados
    </label>
    {!profile.multifactor_enabled ? <p className="field-hint">Desativado: o ranking histórico permanece exatamente como antes.</p> : <>
      <p className="field-hint">O mesmo cenário será aplicado a todos os veículos comparáveis. Os cálculos financeiros são realizados exclusivamente pelo backend.</p>
      <div className="multifactor-grid">
        <label>Distância mensal (km)<input type="number" min="0" step="0.01" value={profile.multifactor_monthly_distance_km} onChange={(event) => onChange("multifactor_monthly_distance_km", event.target.value)} /><FieldError message={errors.multifactor_monthly_distance_km} /></label>
        <label>Urbano (%)<input type="number" min="0" max="100" step="0.01" value={profile.multifactor_city_percentage} onChange={(event) => onChange("multifactor_city_percentage", event.target.value)} /><FieldError message={errors.multifactor_city_percentage} /></label>
        <label>Rodoviário (%)<input type="number" min="0" max="100" step="0.01" value={profile.multifactor_highway_percentage} onChange={(event) => onChange("multifactor_highway_percentage", event.target.value)} /><FieldError message={errors.multifactor_highway_percentage} /></label>
        <label>Estratégia de combustível<select value={profile.multifactor_fuel_strategy} onChange={(event) => onChange("multifactor_fuel_strategy", event.target.value)}><option value="gasoline_c_common">Gasolina comum</option><option value="ethanol_hydrated">Etanol hidratado</option><option value="lowest_projected_cost">Menor custo projetado</option></select><FieldError message={errors.multifactor_fuel_strategy} /></label>
        <label>Origem do preço<select value={profile.multifactor_price_mode} onChange={(event) => onChange("multifactor_price_mode", event.target.value)}><option value="anp">Gold ANP publicada</option><option value="manual">Preço informado pelo cliente</option></select><FieldError message={errors.multifactor_price_mode} /></label>
        {profile.multifactor_price_mode === "manual" && <label>Preço por litro (R$)<input type="number" min="0" step="0.001" value={profile.multifactor_manual_fuel_price_brl} onChange={(event) => onChange("multifactor_manual_fuel_price_brl", event.target.value)} /><FieldError message={errors.multifactor_manual_fuel_price_brl} /></label>}
        <label>Horizonte (meses)<input type="number" min="1" max="120" step="1" value={profile.multifactor_horizon_months} onChange={(event) => onChange("multifactor_horizon_months", event.target.value)} /><FieldError message={errors.multifactor_horizon_months} /></label>
        <label>UF<input type="text" maxLength="2" value={profile.multifactor_state_code} onChange={(event) => onChange("multifactor_state_code", event.target.value)} /><FieldError message={errors.multifactor_state_code} /></label>
        <label>Município (opcional)<input type="text" value={profile.multifactor_municipality} onChange={(event) => onChange("multifactor_municipality", event.target.value)} /></label>
        <label>Semana ANP<input type="date" value={profile.multifactor_reference_week_start} onChange={(event) => onChange("multifactor_reference_week_start", event.target.value)} /><FieldError message={errors.multifactor_reference_week_start} /></label>
        <label>Consumo urbano manual (opcional)<input type="number" min="0" step="0.01" value={profile.multifactor_city_consumption_km_l} onChange={(event) => onChange("multifactor_city_consumption_km_l", event.target.value)} /></label>
        <label>Consumo rodoviário manual (opcional)<input type="number" min="0" step="0.01" value={profile.multifactor_highway_consumption_km_l} onChange={(event) => onChange("multifactor_highway_consumption_km_l", event.target.value)} /></label>
      </div>
      <FieldError message={errors.multifactor_percentages} />
      <div className="multifactor-weight-heading"><strong>Pesos do ranking</strong><button type="button" className="ghost-button" onClick={onResetWeights}>Restaurar padrão</button></div>
      <div className="multifactor-grid">
        {summary.entries.map((item) => <label key={item.code}>{item.label}<input type="number" min="0" max="100" step="0.01" value={profile[`weight_${item.code}`]} onChange={(event) => onChange(`weight_${item.code}`, event.target.value)} /><small>{item.normalizedPercentage.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}% após normalização</small><FieldError message={errors[`weight_${item.code}`]} /></label>)}
      </div>
      <p className="field-hint">Soma informada: {summary.total.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}. A normalização determinística é feita novamente pelo backend.</p>
      <FieldError message={errors.multifactor_weights} />
      <label className="checkbox-line"><input type="checkbox" checked={Boolean(profile.allow_budget_above_200k)} onChange={(event) => onChange("allow_budget_above_200k", event.target.checked)} />Autorizo explicitamente a análise de orçamento acima de R$ 200 mil.</label>
      <FieldError message={errors.allow_budget_above_200k} />
    </>}
  </fieldset>;
}
