import React, { useEffect, useMemo, useRef, useState } from "react";
import { requestFinancingComparison, requestFinancingSimulation, requestMotorcycles, requestReverseFinancingSimulation } from "../../api/sigraApi.js";
import FinancingComparison from "./FinancingComparison.jsx";
import FinancingForm from "./FinancingForm.jsx";
import {
  FINANCING_DISCLAIMER,
  MAX_COMPARISON_SCENARIOS,
  applyFinancingFormChange,
  canAddFinancingScenario,
  removeFinancingScenario,
  validateFinancingForm,
} from "./financingModel.js";
import FinancingResult from "./FinancingResult.jsx";
import { useSession } from "../session/SessionContext.jsx";
import { TestFeedback } from "../session/TestHistory.jsx";

const INITIAL_FORM = {
  vehicle_type: "car", price_mode: "catalog", vehicle_id: "", vehicle_price: "", negotiated_price: "", down_payment: "10000", term_months: "36",
  rate_mode: "monthly", monthly_interest_rate_percent: "", effective_cost_rate_percent: "", effective_cost_rate_period: "", effective_rate_includes_additional_costs: "",
  upfront_fees: "0", financed_fees: "0", financed_insurance: "0", financed_services: "0", desired_max_installment: "", maximum_installment: "",
  available_monthly_budget: "", estimated_monthly_vehicle_cost: "", offer_name: "", institution_name: "", offer_reference: "", offer_date: "", notes: "",
};

export default function FinancingPage({ cars = [] }) {
  const { user } = useSession();
  const [mode, setMode] = useState("direct");
  const [form, setForm] = useState(INITIAL_FORM);
  const [motorcycles, setMotorcycles] = useState([]);
  const [errors, setErrors] = useState({});
  const [requestError, setRequestError] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [lastPayload, setLastPayload] = useState(null);
  const [isResultStale, setIsResultStale] = useState(false);
  const [savedScenarios, setSavedScenarios] = useState([]);
  const [comparison, setComparison] = useState(null);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonNotice, setComparisonNotice] = useState("");
  const controllerRef = useRef(null);
  const requestIdRef = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    requestMotorcycles({ signal: controller.signal }).then(setMotorcycles).catch(() => setMotorcycles([]));
    return () => { controller.abort(); controllerRef.current?.abort(); };
  }, []);

  const availableVehicles = useMemo(() => form.vehicle_type === "car" ? cars : motorcycles, [cars, motorcycles, form.vehicle_type]);

  function updateForm(field, value) {
    controllerRef.current?.abort();
    requestIdRef.current += 1;
    setLoading(false);
    setForm((current) => applyFinancingFormChange(current, field, value));
    setErrors({});
    setRequestError("");
    if (result) setIsResultStale(true);
  }

  async function submit(event) {
    event.preventDefault();
    if (loading) return;
    const validation = validateFinancingForm(form, mode);
    setErrors(validation.errors);
    if (!validation.isValid) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    const requestId = requestIdRef.current + 1;
    requestIdRef.current = requestId;
    controllerRef.current = controller;
    setLoading(true); setRequestError("");
    try {
      const data = mode === "direct"
        ? await requestFinancingSimulation(validation.payload, { signal: controller.signal, recordTest: Boolean(user) })
        : await requestReverseFinancingSimulation(validation.payload, { signal: controller.signal, recordTest: Boolean(user) });
      if (requestId !== requestIdRef.current) return;
      setResult(data); setLastPayload(validation.payload); setIsResultStale(false);
    } catch (error) {
      if (requestId === requestIdRef.current && error?.name !== "AbortError") { setResult(null); setLastPayload(null); setIsResultStale(false); setRequestError(error.message || "Não foi possível calcular a simulação."); }
    } finally { if (requestId === requestIdRef.current) setLoading(false); }
  }

  function changeMode(nextMode) { controllerRef.current?.abort(); requestIdRef.current += 1; setMode(nextMode); setResult(null); setLastPayload(null); setIsResultStale(false); setLoading(false); setErrors({}); setRequestError(""); }

  function addToComparison() {
    if (savedScenarios.length >= MAX_COMPARISON_SCENARIOS) { setComparisonNotice("É possível comparar no máximo 10 cenários."); return; }
    if (!lastPayload || !canAddFinancingScenario(savedScenarios, result, isResultStale)) return;
    const name = lastPayload.offer_name || `Cenário ${savedScenarios.length + 1}`;
    setSavedScenarios((current) => [...current, { name, payload: { ...lastPayload, offer_name: name }, result }]);
    setComparison(null); setComparisonNotice("");
  }

  function removeScenario(index) {
    setSavedScenarios((current) => removeFinancingScenario(current, index));
    setComparison(null); setComparisonError(""); setComparisonNotice("");
  }

  async function compare() {
    if (savedScenarios.length < 2 || comparisonLoading) return;
    setComparisonLoading(true); setComparisonError("");
    try { setComparison(await requestFinancingComparison(savedScenarios.map((item) => item.payload), { recordTest: Boolean(user) })); }
    catch (error) { setComparisonError(error.message || "Não foi possível comparar os cenários."); }
    finally { setComparisonLoading(false); }
  }

  return <section className="financing-page" data-testid="financing-page">
    <div className="section-heading"><p className="eyebrow">Planejamento de aquisição</p><h2>Simulação de financiamento veicular</h2><p className="section-note">Compare o valor financiado, a parcela, o custo total e o desembolso mensal. Financiamento e custo de propriedade permanecem separados.</p></div>
    <div className="financing-layout"><FinancingForm mode={mode} form={form} errors={errors} vehicles={availableVehicles} loading={loading} onChange={updateForm} onModeChange={changeMode} onSubmit={submit} /><div className="financing-output">{requestError && <div className="api-error"><strong>Não foi possível calcular.</strong><p>{requestError}</p><small>Revise os dados da proposta e tente novamente.</small></div>}<FinancingResult mode={mode} result={result} isStale={isResultStale} canAddComparison={canAddFinancingScenario(savedScenarios, result, isResultStale)} comparisonLimitReached={savedScenarios.length >= MAX_COMPARISON_SCENARIOS} onAddComparison={addToComparison} /></div></div>
    <FinancingComparison savedScenarios={savedScenarios} result={comparison} loading={comparisonLoading} error={comparisonError} notice={comparisonNotice} onCompare={compare} onRemove={removeScenario} onClear={() => { setSavedScenarios([]); setComparison(null); setComparisonError(""); setComparisonNotice(""); }} />
    {user && result?.test_run && !isResultStale && <TestFeedback key={result.test_run.id} run={result.test_run} />}
    {user && comparison?.test_run && <TestFeedback key={comparison.test_run.id} run={comparison.test_run} />}
    <p className="financing-disclaimer page-disclaimer">{FINANCING_DISCLAIMER} O SIGRA não consulta bancos, não recomenda instituições e não garante aprovação.</p>
  </section>;
}
