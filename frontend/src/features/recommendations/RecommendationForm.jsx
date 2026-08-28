import React from "react";
import { isRecommendationSubmitDisabled } from "./recommendationValidation.js";
import MultifactorProfileFields from "./MultifactorProfileFields.jsx";

const FieldError = ({ id, message }) => message ? <small className="field-error" id={id} role="alert">{message}</small> : null;

export default function RecommendationForm({ profile, errors, loading, onChange, onResetMultifactorWeights, onSubmit }) {
  const disabled = isRecommendationSubmitDisabled({ loading, vehicleType: profile.vehicle_type });
  return (
    <form className="recommendation-form" data-testid="recommendation-form" onSubmit={onSubmit} noValidate>
      <fieldset>
        <legend>1. Objetivo: categoria do veículo</legend>
        <label htmlFor="recommendation-vehicle-type">O que você procura?</label>
          <select id="recommendation-vehicle-type" data-testid="recommendation-vehicle-type" aria-invalid={Boolean(errors.vehicle_type)} aria-describedby={errors.vehicle_type ? "recommendation-vehicle-type-error" : undefined} value={profile.vehicle_type} onChange={(event) => onChange("vehicle_type", event.target.value)}>
            <option value="car">Automóvel</option>
            <option value="motorcycle">Motocicleta — em desenvolvimento</option>
          </select>
          <FieldError id="recommendation-vehicle-type-error" message={errors.vehicle_type} />
      </fieldset>

      {profile.vehicle_type === "motorcycle" ? (
        <div className="development-state" role="status" data-testid="motorcycle-recommender-unavailable">
          <strong>Módulo de motocicletas em desenvolvimento</strong>
          <p>Nenhuma recomendação de automóvel será usada para esta categoria.</p>
        </div>
      ) : (
        <>
          <fieldset><legend>2. Objetivo: orçamento</legend><label htmlFor="recommendation-budget">Orçamento disponível</label>
            <input id="recommendation-budget" data-testid="recommendation-budget" type="number" aria-invalid={Boolean(errors.budget)} aria-describedby={errors.budget ? "recommendation-budget-error" : undefined} value={profile.budget} onChange={(event) => onChange("budget", event.target.value)} />
            <FieldError id="recommendation-budget-error" message={errors.budget} />
          </fieldset>
          <fieldset><legend>3. Objetivo: limite mensal</legend><label htmlFor="recommendation-monthly-limit">Limite mensal</label>
            <input id="recommendation-monthly-limit" data-testid="recommendation-monthly-limit" type="number" aria-invalid={Boolean(errors.monthly_limit)} aria-describedby={errors.monthly_limit ? "recommendation-monthly-limit-error" : "recommendation-monthly-limit-hint"} value={profile.monthly_limit} onChange={(event) => onChange("monthly_limit", event.target.value)} />
            <FieldError id="recommendation-monthly-limit-error" message={errors.monthly_limit} />
          <p className="field-hint" id="recommendation-monthly-limit-hint">Valor máximo estimado para combustível, manutenção, impostos, seguro e desvalorização. A parcela de financiamento não está incluída nesta versão.</p></fieldset>
          <fieldset><legend>4. Uso: rotina principal</legend><label htmlFor="recommendation-use-case">Uso principal</label>
            <select id="recommendation-use-case" data-testid="recommendation-use-case" aria-invalid={Boolean(errors.use_case)} aria-describedby={errors.use_case ? "recommendation-use-case-error" : undefined} value={profile.use_case} onChange={(event) => onChange("use_case", event.target.value)}>
              <option value="cidade">Cidade</option><option value="familia">Família</option><option value="trabalho">Trabalho</option><option value="estrada">Estrada</option><option value="app">Aplicativo</option><option value="suv">SUV/Espaço</option>
            </select><FieldError id="recommendation-use-case-error" message={errors.use_case} />
          </fieldset>
          <fieldset><legend>5. Preferências: Prioridade da recomendação</legend><label htmlFor="recommendation-strategy">O que deve pesar mais?</label>
            <select id="recommendation-strategy" data-testid="recommendation-strategy" aria-invalid={Boolean(errors.recommendation_strategy)} aria-describedby={errors.recommendation_strategy ? "recommendation-strategy-error" : undefined} value={profile.recommendation_strategy} onChange={(event) => onChange("recommendation_strategy", event.target.value)}>
              <option value="lowest_cost">Menor custo possível</option><option value="budget_economy">Econômico dentro do orçamento</option><option value="cost_benefit">Custo-benefício</option><option value="balanced">Equilibrado</option><option value="comfort_space">Conforto e espaço</option><option value="best_within_budget">Melhor categoria dentro do orçamento</option>
            </select><FieldError id="recommendation-strategy-error" message={errors.recommendation_strategy} />
          </fieldset>
          <fieldset><legend>6. Uso: distância e combustível</legend><label htmlFor="recommendation-monthly-mileage">Quilometragem mensal</label>
            <input id="recommendation-monthly-mileage" data-testid="recommendation-monthly-mileage" type="number" aria-invalid={Boolean(errors.monthly_mileage)} aria-describedby={errors.monthly_mileage ? "recommendation-monthly-mileage-error" : undefined} value={profile.monthly_mileage} onChange={(event) => onChange("monthly_mileage", event.target.value)} />
            <FieldError id="recommendation-monthly-mileage-error" message={errors.monthly_mileage} />
          <label htmlFor="recommendation-fuel-price">Preço do combustível</label>
            <input id="recommendation-fuel-price" data-testid="recommendation-fuel-price" type="number" step="0.01" aria-invalid={Boolean(errors.fuel_price)} aria-describedby={errors.fuel_price ? "recommendation-fuel-price-error" : undefined} value={profile.fuel_price} onChange={(event) => onChange("fuel_price", event.target.value)} />
            <FieldError id="recommendation-fuel-price-error" message={errors.fuel_price} />
          </fieldset>
          <MultifactorProfileFields profile={profile} errors={errors} onChange={onChange} onResetWeights={onResetMultifactorWeights} />
          <fieldset><legend>8. Revisão</legend><p className="field-hint">Ao calcular, o SIGRA usa os mesmos parâmetros para todas as alternativas comparáveis e não persiste suas preferências.</p><button data-testid="recommendation-submit" type="submit" disabled={disabled}>{loading ? "Calculando..." : "Calcular recomendação"}</button></fieldset>
        </>
      )}
    </form>
  );
}
