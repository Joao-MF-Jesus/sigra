import React from "react";
import { cohortWeights, CRITERION_LABELS } from "./cohortRecommendationModel.js";

export default function CohortPreferenceFields({ profile, metadata, errors, onChange }) {
  const weights = cohortWeights(profile, metadata);
  return <fieldset className="choice-fieldset"><legend>Pesos dos critérios do perfil</legend>
    <p>O motor recalcula utilidades e contribuições com os mesmos métodos v4. Pesos não removem requisitos documentais. Valores são normalizados sobre evidências disponíveis.</p>
    {profile.recommendation_strategy === "lowest_cost" && <p>Na prioridade de menor custo, TCO ordena os resultados; a nota ponderada desempata TCOs iguais.</p>}
    <div className="wizard-field-grid">{Object.entries(weights).map(([key, value]) =>
      <label className="form-field wizard-field" key={key}>
        <span className="field-label">{CRITERION_LABELS[key] || key}</span>
        <input type="number" min="0" step="0.05" value={value} disabled={key === "transmission"}
          onChange={(event) => onChange("cohort_weights", { ...profile.cohort_weights,
            [profile.use_case]: { ...weights, [key]: event.target.value } })} />
      </label>)}</div>
    {errors.cohort_weights && <p role="alert">{errors.cohort_weights}</p>}
    <button type="button" className="ghost-button" onClick={() => onChange("cohort_weights",
      { ...profile.cohort_weights, [profile.use_case]: metadata.profiles[profile.use_case].weights })}>Restaurar pesos do método</button>
    <p>Habitabilidade é um indicador derivado. Segurança não é estimada: Família e Estrada mantêm suas exigências documentais.</p>
  </fieldset>;
}
