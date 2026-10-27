import React, { useEffect, useState } from "react";
import { requestStudyMetadata, requestStudyCurrent, requestStudySession } from "../../api/sigraApi.js";
import { beforeRankingPayload, studyPresentation } from "./studyInstrument.js";

export default function StudyBeforeRanking({ onReady }) {
  const [metadata, setMetadata] = useState(null);
  const [context, setContext] = useState(null);
  const [form, setForm] = useState({ scenario_id: "", familiarity: "", priorities: [], presentation_acknowledged: false });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    onReady(false); setError("");
    requestStudyMetadata({ signal: controller.signal }).then(async (meta) => {
      if (controller.signal.aborted) return;
      setMetadata(meta);
      if (meta.mode === "disabled") { onReady(true); return; }
      const data = await requestStudyCurrent({ signal: controller.signal });
      if (controller.signal.aborted) return;
      setContext(data.session); onReady(Boolean(data.session));
    }).catch((failure) => { if (failure.name !== "AbortError" && !controller.signal.aborted) setError("Não foi possível validar o instrumento. Tente novamente antes de registrar um teste."); });
    return () => controller.abort();
  }, [onReady, retry]);
  async function submit(event) {
    event.preventDefault(); if (busy) return;
    setError(""); setBusy(true);
    try { setContext(await requestStudySession(beforeRankingPayload(form))); onReady(true); }
    catch (failure) { setError(failure.status ? "Não foi possível registrar as respostas anteriores ao resultado." : failure.message); }
    finally { setBusy(false); }
  }
  if (metadata?.mode === "disabled") return null;
  const presentation = studyPresentation(metadata);
  return <section className="test-feedback" aria-label="Antes do ranking">
    <h2>{presentation.heading}</h2>
    {!metadata && !error && <p role="status">Conferindo protocolo…</p>}
    {error && <div role="alert"><p>{error}</p><button type="button" onClick={() => setRetry((v) => v + 1)}>Tentar novamente</button></div>}
    {metadata && <>
      <p>{metadata.presentation}</p>
      <p>{presentation.notice}</p>
      {context ? <><p role="status">Cenário {context.scenario_id} registrado antes da execução.</p>
        <button type="button" onClick={() => { setContext(null); onReady(false); }}>Preparar outro cenário antes do ranking</button></> : <form onSubmit={submit}>
        <label>Cenário do roteiro<select required value={form.scenario_id} onChange={(e) => setForm({ ...form, scenario_id: e.target.value })}><option value="">Selecione</option>{metadata.scenarios.map((v) => <option key={v} value={v}>{v}</option>)}</select></label>
        <label>Familiaridade com veículos<select required value={form.familiarity} onChange={(e) => setForm({ ...form, familiarity: e.target.value })}><option value="">Selecione</option>{[["none", "Nenhuma"], ["low", "Baixa"], ["medium", "Média"], ["high", "Alta"]].map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
        <fieldset><legend>Antes do resultado, selecione até três características prioritárias</legend>
          {Object.entries(metadata.priorities).map(([key, label]) => <label className="study-priority" key={key}><input type="checkbox" checked={form.priorities.includes(key)} disabled={!form.priorities.includes(key) && form.priorities.length >= 3} onChange={(e) => setForm({ ...form, priorities: e.target.checked ? [...form.priorities, key] : form.priorities.filter((v) => v !== key) })} />{label}</label>)}
        </fieldset>
        <label className="study-priority"><input type="checkbox" required checked={form.presentation_acknowledged} onChange={(e) => setForm({ ...form, presentation_acknowledged: e.target.checked })} />{presentation.acknowledgement}</label>
        <button type="submit" disabled={busy}>{busy ? "Registrando…" : "Registrar antes do resultado"}</button>
      </form>}
    </>}
  </section>;
}
