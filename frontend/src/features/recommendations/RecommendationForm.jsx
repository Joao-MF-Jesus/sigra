import React from "react";
import { isRecommendationSubmitDisabled } from "./recommendationValidation.js";

const FieldError = ({ message }) => message ? <small className="field-error">{message}</small> : null;

export default function RecommendationForm({ profile, errors, loading, onChange, onSubmit }) {
  const disabled = isRecommendationSubmitDisabled({ loading, vehicleType: profile.vehicle_type });
  return (
    <form className="recommendation-form" onSubmit={onSubmit} noValidate>
      <fieldset>
        <legend>1. Categoria do veículo</legend>
        <label>O que você procura?
          <select data-testid="recommendation-vehicle-type" value={profile.vehicle_type} onChange={(event) => onChange("vehicle_type", event.target.value)}>
            <option value="car">Automóvel</option>
            <option value="motorcycle">Motocicleta — em desenvolvimento</option>
          </select>
          <FieldError message={errors.vehicle_type} />
        </label>
      </fieldset>

      {profile.vehicle_type === "motorcycle" ? (
        <div className="development-state" role="status" data-testid="motorcycle-recommender-unavailable">
          <strong>Módulo de motocicletas em desenvolvimento</strong>
          <p>Nenhuma recomendação de automóvel será usada para esta categoria.</p>
        </div>
      ) : (
        <>
          <fieldset><legend>2. Orçamento</legend><label>Orçamento disponível
            <input type="number" value={profile.budget} onChange={(event) => onChange("budget", event.target.value)} />
            <FieldError message={errors.budget} />
          </label></fieldset>
          <fieldset><legend>3. Limite mensal</legend><label>Limite mensal
            <input type="number" value={profile.monthly_limit} onChange={(event) => onChange("monthly_limit", event.target.value)} />
            <FieldError message={errors.monthly_limit} />
          </label><p className="field-hint">Valor máximo estimado para combustível, manutenção, impostos, seguro e desvalorização. A parcela de financiamento não está incluída nesta versão.</p></fieldset>
          <fieldset><legend>4. Forma de uso</legend><label>Uso principal
            <select value={profile.use_case} onChange={(event) => onChange("use_case", event.target.value)}>
              <option value="cidade">Cidade</option><option value="familia">Família</option><option value="trabalho">Trabalho</option><option value="estrada">Estrada</option><option value="app">Aplicativo</option><option value="suv">SUV/Espaço</option>
            </select><FieldError message={errors.use_case} />
          </label></fieldset>
          <fieldset><legend>5. Prioridade da recomendação</legend><label>Prioridade
            <select value={profile.recommendation_strategy} onChange={(event) => onChange("recommendation_strategy", event.target.value)}>
              <option value="lowest_cost">Menor custo possível</option><option value="budget_economy">Econômico dentro do orçamento</option><option value="cost_benefit">Custo-benefício</option><option value="balanced">Equilibrado</option><option value="comfort_space">Conforto e espaço</option><option value="best_within_budget">Melhor categoria dentro do orçamento</option>
            </select><FieldError message={errors.recommendation_strategy} />
          </label></fieldset>
          <fieldset><legend>6. Quilometragem e combustível</legend><label>Quilometragem mensal
            <input type="number" value={profile.monthly_mileage} onChange={(event) => onChange("monthly_mileage", event.target.value)} />
            <FieldError message={errors.monthly_mileage} />
          </label><label>Preço do combustível
            <input type="number" step="0.01" value={profile.fuel_price} onChange={(event) => onChange("fuel_price", event.target.value)} />
            <FieldError message={errors.fuel_price} />
          </label></fieldset>
          <fieldset><legend>7. Cálculo</legend><button type="submit" disabled={disabled}>{loading ? "Calculando..." : "Calcular recomendação"}</button></fieldset>
        </>
      )}
    </form>
  );
}
