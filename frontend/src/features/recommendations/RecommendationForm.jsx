import React, { useEffect, useMemo, useRef, useState } from "react";
import { useSession } from "../session/SessionContext.jsx";
import MultifactorProfileFields from "./MultifactorProfileFields.jsx";
import { isRecommendationSubmitDisabled } from "./recommendationValidation.js";
import { recommendationPriorityOptions, unavailablePriorityMessage } from "./recommendationPriorityModel.js";
import {
  RECOMMENDATION_WIZARD_STEPS,
  firstStepWithError,
  nextWizardStep,
  previousWizardStep,
  recommendationReview,
  wizardProgress,
} from "./recommendationWizardModel.js";

const FieldError = ({ id, message }) => message ? <small className="field-error" id={id} role="alert">{message}</small> : null;

function Field({ children, error, errorId, hint, hintId, label, htmlFor }) {
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;
  const selectedLabel = children.type === "select"
    ? React.Children.toArray(children.props.children).find((option) => String(option.props.value) === String(children.props.value))?.props.children
    : null;
  return <label className="form-field wizard-field" htmlFor={htmlFor}><span className="field-label">{label}</span>{React.cloneElement(children, {
    id: htmlFor,
    "aria-invalid": Boolean(error),
    "aria-describedby": describedBy,
  })}{selectedLabel && <span className="selected-option" aria-hidden="true" data-testid={`${htmlFor}-selected-label`}>{selectedLabel}</span>}{hint && <small className="field-hint" id={hintId}>{hint}</small>}<FieldError id={errorId} message={error} /></label>;
}

function WizardProgress({ current, maxVisited, onSelect }) {
  const progress = wizardProgress(current);
  return <div className="wizard-progress-wrap">
    <div className="wizard-progress-copy"><span>Etapa {progress.currentNumber} de {progress.total}</span><strong>{RECOMMENDATION_WIZARD_STEPS[current].label}</strong></div>
    <div className="wizard-progress-track" aria-hidden="true"><span style={{ width: `${progress.percentage}%` }} /></div>
    <ol className="wizard-progress" aria-label="Etapas do perfil">
      {RECOMMENDATION_WIZARD_STEPS.map((step, index) => <li key={step.id}>
        <button type="button" className={index === current ? "active" : index < current ? "complete" : ""} disabled={index > maxVisited} aria-current={index === current ? "step" : undefined} aria-label={`${step.label}${index === current ? ", etapa atual" : ""}`} onClick={() => onSelect(index)}>
          <span aria-hidden="true">{index < current ? "✓" : index + 1}</span><em className={index === current ? "wizard-step-name current" : "wizard-step-name"}>{step.label}</em>
        </button>
      </li>)}
    </ol>
  </div>;
}

export default function RecommendationForm({ profile, errors, loading, onChange, onResetMultifactorWeights, onSubmit, candidateMetadata }) {
  const { user } = useSession();
  const [stepIndex, setStepIndex] = useState(0);
  const [maxVisited, setMaxVisited] = useState(0);
  const formRef = useRef(null);
  const review = useMemo(() => recommendationReview(profile), [profile]);
  const cohort = candidateMetadata?.candidate_source === "academic_v6";
  const priorities = recommendationPriorityOptions(candidateMetadata);
  const priorityError = cohort ? unavailablePriorityMessage(profile.recommendation_strategy, candidateMetadata) : "";
  const disabled = isRecommendationSubmitDisabled({ loading, vehicleType: profile.vehicle_type }) || Boolean(priorityError);
  const visibleReview = cohort ? [...review,
    ["Cenário de custos", ({ low: "Baixo", base: "Base", high: "Alto" })[profile.cost_scenario || "base"]]] : review;

  useEffect(() => {
    const errorStep = firstStepWithError(errors);
    if (errorStep >= 0) {
      setStepIndex(errorStep);
      setMaxVisited((current) => Math.max(current, errorStep));
    }
  }, [errors]);

  useEffect(() => {
    const heading = formRef.current?.querySelector("[data-step-panel]:not([hidden]) h2");
    if (heading && stepIndex > 0) heading.focus();
  }, [stepIndex]);

  function goTo(index) {
    setStepIndex(index);
    setMaxVisited((current) => Math.max(current, index));
  }

  function advance() {
    goTo(nextWizardStep(stepIndex));
  }

  return (
    <form ref={formRef} className="recommendation-form recommendation-wizard" data-testid="recommendation-form" onSubmit={onSubmit} noValidate>
      <WizardProgress current={stepIndex} maxVisited={maxVisited} onSelect={goTo} />

      <section className="wizard-step" data-step-panel="need" hidden={stepIndex !== 0} aria-labelledby="wizard-need-title">
        <p className="eyebrow">Comece pela sua rotina</p>
        <h2 id="wizard-need-title" tabIndex="-1">Que tipo de escolha você quer fazer?</h2>
        <p className="wizard-intro">Conte primeiro o que você precisa. Os detalhes técnicos aparecem só quando forem úteis.</p>
        <fieldset className="choice-fieldset"><legend>Categoria</legend><div className="choice-grid two-options">
          <label className={profile.vehicle_type === "car" ? "choice-card selected" : "choice-card"}><input data-testid="recommendation-vehicle-type-car" type="radio" name="vehicle_type" value="car" checked={profile.vehicle_type === "car"} onChange={(event) => onChange("vehicle_type", event.target.value)} /><span aria-hidden="true">01</span><strong>Automóvel</strong><small>Recomendação completa disponível</small></label>
          <label className={profile.vehicle_type === "motorcycle" ? "choice-card selected" : "choice-card"}><input data-testid="recommendation-vehicle-type-motorcycle" type="radio" name="vehicle_type" value="motorcycle" checked={profile.vehicle_type === "motorcycle"} onChange={(event) => onChange("vehicle_type", event.target.value)} /><span aria-hidden="true">02</span><strong>Motocicleta</strong><small>Catálogo técnico em desenvolvimento</small></label>
        </div><select hidden id="recommendation-vehicle-type" data-testid="recommendation-vehicle-type" value={profile.vehicle_type} onChange={(event) => onChange("vehicle_type", event.target.value)} tabIndex="-1"><option value="car">Automóvel</option><option value="motorcycle">Motocicleta — em desenvolvimento</option></select><FieldError id="recommendation-vehicle-type-error" message={errors.vehicle_type} /></fieldset>

        {profile.vehicle_type === "motorcycle" ? <div className="development-state" role="status" data-testid="motorcycle-recommender-unavailable"><strong>O recomendador de motocicletas ainda está em desenvolvimento.</strong><p>Você pode consultar o catálogo técnico; nenhuma recomendação de automóvel será adaptada ou apresentada como recomendação de moto.</p></div> : <Field label="Uso principal" htmlFor="recommendation-use-case" error={errors.use_case} errorId="recommendation-use-case-error"><select data-testid="recommendation-use-case" value={profile.use_case} onChange={(event) => onChange("use_case", event.target.value)}><option value="cidade">Deslocamentos na cidade</option><option value="familia">Rotina com a família</option><option value="trabalho">Trabalho e compromissos</option><option value="estrada">Viagens e estrada</option><option value="app">Uso por aplicativo</option><option value="suv">Mais espaço e versatilidade</option></select></Field>}
        {profile.vehicle_type === "car" && <div className="wizard-actions"><span /><button data-testid="recommendation-next-need" type="button" onClick={advance}>Continuar</button></div>}
      </section>

      <section className="wizard-step" data-step-panel="budget" hidden={stepIndex !== 1} aria-labelledby="wizard-budget-title">
        <p className="eyebrow">Seus limites</p><h2 id="wizard-budget-title" tabIndex="-1">Quanto cabe na sua decisão?</h2><p className="wizard-intro">Use valores aproximados. Você poderá voltar e ajustar antes de calcular.</p>
        <div className="wizard-field-grid">
          <Field label="Orçamento para compra" htmlFor="recommendation-budget" error={errors.budget} errorId="recommendation-budget-error" hint="Valor máximo que você pretende pagar pelo veículo." hintId="recommendation-budget-hint"><input data-testid="recommendation-budget" type="number" min="1" inputMode="decimal" value={profile.budget} onChange={(event) => onChange("budget", event.target.value)} /></Field>
          <Field label="Limite mensal de uso" htmlFor="recommendation-monthly-limit" error={errors.monthly_limit} errorId="recommendation-monthly-limit-error" hint="Estimativa para combustível, manutenção, impostos, seguro e desvalorização. A parcela de financiamento não entra aqui." hintId="recommendation-monthly-limit-hint"><input data-testid="recommendation-monthly-limit" type="number" min="1" inputMode="decimal" value={profile.monthly_limit} onChange={(event) => onChange("monthly_limit", event.target.value)} /></Field>
        </div>
        <div className="wizard-actions"><button className="ghost-button" data-testid="recommendation-back-budget" type="button" onClick={() => goTo(previousWizardStep(stepIndex))}>Voltar</button><button data-testid="recommendation-next-budget" type="button" onClick={advance}>Continuar</button></div>
      </section>

      <section className="wizard-step" data-step-panel="priorities" hidden={stepIndex !== 2} aria-labelledby="wizard-priorities-title">
        <p className="eyebrow">O que importa</p><h2 id="wizard-priorities-title" tabIndex="-1">Defina a prioridade da análise</h2><p className="wizard-intro">O SIGRA aplica o mesmo perfil a todas as alternativas comparáveis.</p>
        <Field label="O que deve pesar mais?" htmlFor="recommendation-strategy" error={priorityError || errors.recommendation_strategy} errorId="recommendation-strategy-error" hint={cohort ? "Disponíveis nesta coorte: " + priorities.filter((row) => row.available).map((row) => row.label).join(" e ") + ". A escolha é explícita; não há substituição automática." : undefined} hintId="recommendation-strategy-hint"><select data-testid="recommendation-strategy" value={profile.recommendation_strategy} onChange={(event) => onChange("recommendation_strategy", event.target.value)}>{priorities.map((option) => <option key={option.value} value={option.value} disabled={!option.available}>{option.label}{!option.available ? " — indisponível nesta coorte" : ""}</option>)}</select></Field>
        {cohort && <>
          <p className="field-hint">Custo-benefício usa a classificação de referência por critérios documentados do uso escolhido. Menor custo possível ordena pelo TCO estimado dentro de cada grupo comparável. Se você ativar a personalização, sua pontuação passa a ordenar os veículos pontuados; esta prioridade permanece registrada como referência.</p>
          <details className="data-provenance"><summary>Por que as outras prioridades estão indisponíveis?</summary><p>Faltam as avaliações históricas exigidas pelo método original. As configurações Base e Ampliada usam métricas explicitamente derivadas e custos de cenário; não fornecem notas originais de conforto, confiabilidade ou categoria. Nenhuma nota ausente vira zero e nenhuma prioridade alternativa é aplicada.</p></details>
        </>}
        {cohort && <Field label="Cenário de manutenção, impostos, seguro e depreciação" htmlFor="recommendation-cost-scenario" error={errors.cost_scenario}>
          <select value={profile.cost_scenario || "base"} onChange={(event) => onChange("cost_scenario", event.target.value)}><option value="low">Baixo</option><option value="base">Base</option><option value="high">Alto</option></select>
        </Field>}
        <div className="wizard-field-grid">
          <Field label="Quilometragem mensal" htmlFor="recommendation-monthly-mileage" error={errors.monthly_mileage} errorId="recommendation-monthly-mileage-error" hint="Uma estimativa da sua rotina já é suficiente." hintId="recommendation-monthly-mileage-hint"><input data-testid="recommendation-monthly-mileage" type="number" min="0" inputMode="decimal" value={profile.monthly_mileage} onChange={(event) => onChange("monthly_mileage", event.target.value)} /></Field>
          <Field label="Preço do combustível" htmlFor="recommendation-fuel-price" error={errors.fuel_price} errorId="recommendation-fuel-price-error" hint="Valor de referência informado por você para o ranking histórico." hintId="recommendation-fuel-price-hint"><input data-testid="recommendation-fuel-price" type="number" min="0.01" step="0.01" inputMode="decimal" value={profile.fuel_price} onChange={(event) => onChange("fuel_price", event.target.value)} /></Field>
        </div>
        <div className="wizard-actions"><button className="ghost-button" data-testid="recommendation-back-priorities" type="button" onClick={() => goTo(previousWizardStep(stepIndex))}>Voltar</button><button data-testid="recommendation-next-priorities" type="button" onClick={advance} disabled={Boolean(priorityError)}>Continuar</button></div>
      </section>

      <section className="wizard-step" data-step-panel="advanced" hidden={stepIndex !== 3} aria-labelledby="wizard-advanced-title">
        <p className="eyebrow">Opcional</p><h2 id="wizard-advanced-title" tabIndex="-1">Quer personalizar ainda mais?</h2><p className="wizard-intro">Se você não ativar o perfil multifator, a classificação de referência permanece como antes.</p>
        <MultifactorProfileFields profile={profile} errors={errors} onChange={onChange} onResetWeights={onResetMultifactorWeights} candidateSource={candidateMetadata?.candidate_source} alternativeEnabled={candidateMetadata?.alternative_personalization?.available === true} configurationRegistry={candidateMetadata?.alternative_personalization?.configuration_registry} />
        <div className="wizard-actions"><button className="ghost-button" data-testid="recommendation-back-advanced" type="button" onClick={() => goTo(previousWizardStep(stepIndex))}>Voltar</button><button data-testid="recommendation-next-advanced" type="button" onClick={advance}>{profile.multifactor_enabled ? "Revisar cenário" : "Continuar sem ajustes"}</button></div>
      </section>

      <section className="wizard-step wizard-review" data-step-panel="review" hidden={stepIndex !== 4} aria-labelledby="wizard-review-title">
        <p className="eyebrow">Revise antes de calcular</p><h2 id="wizard-review-title" tabIndex="-1">Seu perfil está pronto</h2><p className="wizard-intro">{user ? "Os parâmetros e o resultado serão registrados no seu histórico privado quando você calcular." : "O SIGRA não salva estas preferências no modo visitante. O cenário será enviado ao backend somente quando você calcular."}</p>
        <dl className="review-grid">{visibleReview.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        <div className="privacy-note"><span aria-hidden="true">✓</span><p><strong>Comparação consistente</strong><br />Todas as alternativas recebem os mesmos parâmetros; os dados publicados permanecem somente leitura.</p></div>
        <div className="wizard-actions"><button className="ghost-button" data-testid="recommendation-back-review" type="button" onClick={() => goTo(previousWizardStep(stepIndex))}>Voltar e ajustar</button><button data-testid="recommendation-submit" type="submit" disabled={disabled}>{loading ? "Calculando..." : "Calcular recomendação"}</button></div>
      </section>
    </form>
  );
}
