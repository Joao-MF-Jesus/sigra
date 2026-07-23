import React from "react";

function FieldError({ message }) {
  return message ? <small className="field-error">{message}</small> : null;
}

function MoneyField({ label, name, value, onChange, error, optional = false, disabled = false }) {
  return <label>{label}{optional && <span className="optional-label">Opcional</span>}<input data-testid={`financing-${name}`} type="number" min="0" step="0.01" value={value} disabled={disabled} onChange={(event) => onChange(name, event.target.value)} /><FieldError message={error} /></label>;
}

export default function FinancingForm({ mode, form, errors, vehicles, loading, onChange, onModeChange, onSubmit }) {
  const catalogVehicles = Array.isArray(vehicles) ? vehicles : [];
  const cetIncludesAdditionalCosts = form.rate_mode === "effective" && form.effective_rate_includes_additional_costs === "yes";
  return <form className="financing-form" data-testid="financing-form" onSubmit={onSubmit} noValidate>
    <div className="segmented-control" aria-label="Tipo de simulação">
      <button type="button" className={mode === "direct" ? "active" : ""} onClick={() => onModeChange("direct")}>Simulação direta</button>
      <button type="button" className={mode === "reverse" ? "active" : ""} onClick={() => onModeChange("reverse")}>Simulação reversa</button>
    </div>

    <fieldset><legend>Veículo e aquisição</legend>
      <div className="form-grid">
        <label>Categoria<select data-testid="financing-vehicle-type" value={form.vehicle_type} onChange={(event) => onChange("vehicle_type", event.target.value)}><option value="car">Automóvel</option><option value="motorcycle">Motocicleta</option></select><FieldError message={errors.vehicle_type} /></label>
        {mode === "direct" && <label>Origem do preço<select data-testid="financing-price-mode" value={form.price_mode} onChange={(event) => onChange("price_mode", event.target.value)}><option value="catalog">Veículo do catálogo</option><option value="manual">Preço manual</option></select></label>}
      </div>
      {mode === "direct" && form.price_mode === "catalog" && <label>Veículo<select data-testid="financing-vehicle-id" value={form.vehicle_id} onChange={(event) => onChange("vehicle_id", event.target.value)}><option value="">Selecione</option>{catalogVehicles.map((vehicle) => <option key={vehicle.id} value={vehicle.id}>{vehicle.brand} {vehicle.model} {vehicle.year} - R$ {Number(vehicle.price).toLocaleString("pt-BR")}</option>)}</select><FieldError message={errors.vehicle_id} /></label>}
      {mode === "direct" && form.price_mode === "manual" && <MoneyField label="Preço do veículo" name="vehicle_price" value={form.vehicle_price} onChange={onChange} error={errors.vehicle_price} />}
      {mode === "direct" && form.price_mode === "catalog" && <MoneyField label="Preço negociado" name="negotiated_price" value={form.negotiated_price} onChange={onChange} error={errors.negotiated_price} optional />}
      <div className="form-grid"><MoneyField label="Entrada" name="down_payment" value={form.down_payment} onChange={onChange} error={errors.down_payment} />{mode === "reverse" && <MoneyField label="Parcela máxima" name="maximum_installment" value={form.maximum_installment} onChange={onChange} error={errors.maximum_installment} />}</div>
      <label>Prazo em meses<input data-testid="financing-term-months" type="number" min="1" max="120" step="1" value={form.term_months} onChange={(event) => onChange("term_months", event.target.value)} /><FieldError message={errors.term_months} /></label>
    </fieldset>

    <fieldset><legend>Taxa informada</legend>
      <div className="segmented-control compact" aria-label="Modo da taxa"><button type="button" className={form.rate_mode === "monthly" ? "active" : ""} onClick={() => onChange("rate_mode", "monthly")}>Taxa mensal</button><button type="button" className={form.rate_mode === "effective" ? "active" : ""} onClick={() => onChange("rate_mode", "effective")}>CET informado</button></div>
      <FieldError message={errors.rate_mode} />
      {form.rate_mode === "monthly" ? <label>Taxa efetiva mensal (%)<input data-testid="financing-monthly-rate" type="number" min="0" step="0.01" placeholder="Ex.: 1,80" value={form.monthly_interest_rate_percent} onChange={(event) => onChange("monthly_interest_rate_percent", event.target.value)} /><FieldError message={errors.monthly_interest_rate_percent} /></label> : <div className="form-grid"><label>CET informado (%)<input type="number" min="0" step="0.01" value={form.effective_cost_rate_percent} onChange={(event) => onChange("effective_cost_rate_percent", event.target.value)} /><FieldError message={errors.effective_cost_rate_percent} /></label><label>Período<select value={form.effective_cost_rate_period} onChange={(event) => onChange("effective_cost_rate_period", event.target.value)}><option value="">Selecione</option><option value="monthly">Mensal</option><option value="annual">Anual</option></select><FieldError message={errors.effective_cost_rate_period} /></label><label>O CET inclui custos adicionais?<select value={form.effective_rate_includes_additional_costs} onChange={(event) => onChange("effective_rate_includes_additional_costs", event.target.value)}><option value="">Selecione</option><option value="yes">Sim</option><option value="no">Não</option></select><FieldError message={errors.effective_rate_includes_additional_costs} /></label></div>}
      <p className="form-help">O SIGRA não consulta taxas e não preenche uma taxa padrão. Informe os dados da proposta que deseja analisar.</p>
    </fieldset>

    <fieldset><legend>Tarifas e serviços</legend><div className="form-grid"><MoneyField label="Tarifas pagas à vista" name="upfront_fees" value={form.upfront_fees} onChange={onChange} error={errors.upfront_fees} /><MoneyField label="Tarifas financiadas" name="financed_fees" value={form.financed_fees} onChange={onChange} error={errors.financed_fees} disabled={cetIncludesAdditionalCosts} /><MoneyField label="Seguro financiado" name="financed_insurance" value={form.financed_insurance} onChange={onChange} error={errors.financed_insurance} disabled={cetIncludesAdditionalCosts} /><MoneyField label="Serviços financiados" name="financed_services" value={form.financed_services} onChange={onChange} error={errors.financed_services} disabled={cetIncludesAdditionalCosts} /></div>{cetIncludesAdditionalCosts && <p className="form-help">Esses campos foram zerados e desabilitados porque o CET informado já representa os custos adicionais financiados. Tarifas pagas à vista permanecem separadas.</p>}</fieldset>

    <fieldset><legend>Limites e uso mensal</legend><div className="form-grid">{mode === "direct" && <MoneyField label="Parcela máxima desejada" name="desired_max_installment" value={form.desired_max_installment} onChange={onChange} error={errors.desired_max_installment} optional />}<MoneyField label="Orçamento mensal disponível" name="available_monthly_budget" value={form.available_monthly_budget} onChange={onChange} error={errors.available_monthly_budget} optional /><MoneyField label="Custo mensal estimado do veículo" name="estimated_monthly_vehicle_cost" value={form.estimated_monthly_vehicle_cost} onChange={onChange} error={errors.estimated_monthly_vehicle_cost} optional /></div><p className="form-help">Para calcular o desembolso, informe apenas custos recorrentes de caixa. Se usar o TCO como referência, não inclua a depreciação neste campo.</p></fieldset>

    {mode === "direct" && <fieldset><legend>Identificação da proposta</legend><div className="form-grid"><label>Nome do cenário <span className="optional-label">Opcional</span><input data-testid="financing-offer-name" value={form.offer_name} onChange={(event) => onChange("offer_name", event.target.value)} placeholder="Ex.: Banco A - 36 meses" /></label><label>Instituição <span className="optional-label">Opcional</span><input value={form.institution_name} onChange={(event) => onChange("institution_name", event.target.value)} /></label><label>Referência <span className="optional-label">Opcional</span><input value={form.offer_reference} onChange={(event) => onChange("offer_reference", event.target.value)} /></label><label>Data da oferta <span className="optional-label">Opcional</span><input type="date" value={form.offer_date} onChange={(event) => onChange("offer_date", event.target.value)} /></label></div></fieldset>}
    <button type="submit" data-testid="financing-submit" disabled={loading}>{loading ? "Calculando..." : mode === "direct" ? "Calcular simulação" : "Calcular valor máximo"}</button>
  </form>;
}
