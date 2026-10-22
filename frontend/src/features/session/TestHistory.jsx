import React, { useEffect, useState } from "react";
import { downloadTestRecords, requestTestDetail, requestTestFeedback, requestTestQuestionnaire, requestTestHistory } from "../../api/sigraApi.js";
import { QUESTION_LABELS, questionnairePayload } from "./studyInstrument.js";
import FinancingResult from "../financing/FinancingResult.jsx";

const TITLES = { recommendation: "Recomendação", financing: "Financiamento", reverse_financing: "Financiamento reverso", financing_comparison: "Comparação de propostas", fuel_simulation: "Simulação de combustível" };
const FAMILIARITY_LABELS = { none: "Nenhuma", low: "Baixa", medium: "Média", high: "Alta" };
// Declared choices in appendix C v1; these labels are not vehicle scores or weights.
const DECLARED_PRIORITY_LABELS = { total_cost: "Custo no cenário", usage_fit: "Adequação ao uso",
  comfort: "Conforto", safety: "Segurança", performance: "Desempenho rodoviário",
  efficiency: "Economia e eficiência", legacy_quality: "Qualidade histórica" };
const money = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? Number(value).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : "Indisponível";
const date = (value) => new Date(value.endsWith?.("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : value + "Z").toLocaleString("pt-BR");

export function TestFeedback({ run, onSaved }) {
  const [rating, setRating] = useState(run.feedback_rating ? String(run.feedback_rating) : "");
  const [comment, setComment] = useState(run.questionnaire?.comment || run.feedback_comment || "");
  const [answers, setAnswers] = useState(Object.fromEntries(Object.keys(QUESTION_LABELS).map((key) => [key, String(run.questionnaire?.[key] || "")])));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try {
      const saved = run.questionnaire_required
        ? await requestTestQuestionnaire(run.id, questionnairePayload(answers, comment))
        : await requestTestFeedback(run.id, { rating: Number(rating), comment });
      setMessage("Avaliação salva no seu histórico."); onSaved?.(saved);
    } catch { setError("Não foi possível salvar a avaliação. Entre novamente ou tente de novo."); }
    finally { setBusy(false); }
  }
  return <section className="test-feedback" aria-label="Avaliação da execução">
    <p role="status">Teste registrado na sua conta.</p>
    <form onSubmit={submit}>
      {run.questionnaire_required ? <>
        <p>1 — discordo totalmente / muito pouco claro · 5 — concordo totalmente / muito claro.</p>
        {Object.entries(QUESTION_LABELS).map(([key, label]) => <label key={key}>{label}<select required value={answers[key]} onChange={(e) => setAnswers({ ...answers, [key]: e.target.value })}><option value="">Selecione</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</select></label>)}
      </> : <label>Avaliação do teste (1 a 5)<select required value={rating} onChange={(e) => setRating(e.target.value)}>
        <option value="">Selecione</option>{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}
      </select></label>}
      <label>{run.questionnaire_required ? "O que ficou confuso, surpreendeu ou pareceu faltar? (opcional)" : "Comentário sobre o teste"}<textarea maxLength={4000} value={comment} onChange={(e) => setComment(e.target.value)} /></label>
      <small>Não inclua nome, telefone, e-mail ou informações pessoais no comentário.</small>
      <button type="submit" disabled={busy}>{busy ? "Salvando…" : "Salvar avaliação"}</button>
      {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    </form>
  </section>;
}

export function StoredResult({ run }) {
  const result = run.presented_results;
  const configuration = result?.multifactor_profile?.configuration;
  const study = run.study_session;
  return <div className="stored-test-result">
    <h3>Resultado registrado</h3>
    <p>Esta é a resposta daquela execução, não um novo cálculo. Custos de cenário continuam estimados; dados indisponíveis permanecem sem nota.</p>
    {configuration && <p>Configuração registrada: {configuration.label}.{configuration.weights_adjusted ? " Pesos ajustados explicitamente." : ""} {configuration.comparison_warning}</p>}
    {study && <details className="data-provenance"><summary>Escolhas registradas antes do resultado</summary>
      <p>Estas são as escolhas declaradas naquela execução; não substituem os pesos nem as preferências efetivamente usadas no cálculo.</p>
      <dl><dt>Cenário do roteiro</dt><dd>{study.scenario_id || "Não informado"}</dd>
        <dt>Familiaridade com veículos</dt><dd>{FAMILIARITY_LABELS[study.familiarity] || "Não informada"}</dd>
        <dt>Prioridades declaradas</dt><dd>{Array.isArray(study.priorities)
          ? study.priorities.length ? study.priorities.map((key) => DECLARED_PRIORITY_LABELS[key] || "Prioridade não identificada").join(" · ") : "Nenhuma prioridade declarada"
          : "Não disponíveis neste registro"}</dd></dl>
    </details>}
    {["financing", "reverse_financing"].includes(run.kind) && <FinancingResult mode={run.kind === "reverse_financing" ? "reverse" : "direct"} result={result} showComparisonAction={false} />}
    {Array.isArray(result?.recommendations) ? <ul>{result.recommendations.map((item, index) => <li key={item.vehicle?.catalog_id || item.vehicle?.id || index}>
      {item.vehicle?.label || [item.vehicle?.brand, item.vehicle?.model, item.vehicle?.year].filter(Boolean).join(" ")}
      {" — "}{money(item.monthly_total_cost)}/mês
    </li>)}</ul> : <p>Simulação guardada com os parâmetros e resultados originais.</p>}
    {!Array.isArray(result?.recommendations) && <details><summary>Ver resultados completos da simulação registrada</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>}
    <details className="data-provenance"><summary>Parâmetros e metodologia do registro</summary>
      <dl><dt>Sistema</dt><dd>{run.system_version}</dd><dt>Método</dt><dd>{run.method_version}</dd><dt>Data</dt><dd>{date(run.created_at)}</dd></dl>
      <pre>{JSON.stringify(run.parameters, null, 2)}</pre>
    </details>
    <TestFeedback key={run.id} run={run} />
  </div>;
}

export default function TestHistory({ user }) {
  const [page, setPage] = useState(null);
  const [offset, setOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setSelected(null);
    requestTestHistory(offset, { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) setPage(value);
    }).catch((failure) => { if (failure.name !== "AbortError") setError("Não foi possível carregar seu histórico. Entre novamente ou tente de novo."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [offset, retry, user.id]);
  async function open(id) {
    setError("");
    try { setSelected(await requestTestDetail(id)); }
    catch { setError("Não foi possível abrir esse teste no seu histórico."); }
  }
  async function exportCsv() {
    try { await downloadTestRecords(); }
    catch (failure) { setError(failure.message); }
  }
  return <section className="test-history" aria-labelledby="test-history-title">
    <div className="section-heading"><p className="eyebrow">Participação no TCC</p><h2 id="test-history-title">Meus testes</h2>
      <p>Recomendações e simulações realizadas enquanto você está conectado são registradas na sua conta. Seu histórico não é compartilhado com outros participantes.</p>
    </div>
    {user.role === "admin" && <button type="button" onClick={exportCsv}>Exportar registros dos participantes (CSV)</button>}
    {error && <div role="alert"><p>{error}</p><button type="button" onClick={() => setRetry((n) => n + 1)}>Tentar novamente</button></div>}
    {loading && <p role="status">Carregando histórico…</p>}
    {!loading && page?.total === 0 && <p>Nenhum teste registrado. Faça uma recomendação ou simulação enquanto estiver conectado.</p>}
    <ol>{page?.items.map((run) => <li key={run.id}><button type="button" onClick={() => open(run.id)}>{TITLES[run.kind] || "Teste"} · {date(run.created_at)}</button>{run.feedback_rating && <span> Avaliação: {run.feedback_rating}/5</span>}</li>)}</ol>
    {page && page.total > 20 && <div className="hero-actions"><button type="button" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 20))}>Anterior</button><button type="button" disabled={offset + page.items.length >= page.total || loading} onClick={() => setOffset(offset + 20)}>Próxima</button></div>}
    {selected && <StoredResult run={selected} />}
  </section>;
}
