import React, { useEffect, useRef, useState } from "react";
import { requestAcademicMetadata, requestAcademicCatalog, requestAcademicEvaluation, requestAcademicVehicleDetail } from "../../api/sigraApi.js";
import { ACADEMIC_PROFILES, ACADEMIC_SCENARIOS, DEFAULT_ACADEMIC_FORM, FIELD_LABELS, NATURE_LABELS, academicPayload, academicCurrency, academicNumber, academicValue, academicError, createAcademicRequestGate } from "./academicModel.js";
import "./academic.css";

const PAGE_SIZE = 20;
const profileName = (key) => ACADEMIC_PROFILES.find(([value]) => value === key)?.[1] || key;
const scenarioName = (key) => ACADEMIC_SCENARIOS.find(([value]) => value === key)?.[1] || key;
const LIMITATION_TEXT = {
  "Academic-only preview; not an operational recommendation or Gold activation.": "Preview exclusivamente acadêmico: não é recomendação operacional nem ativação Gold.",
  "TCO is a versioned scenario estimate, not an observed cost.": "TCO é uma estimativa de cenário versionada, não um custo observado.",
  "academic_habitability_proxy is derived, not measured interior space.": "academic_habitability_proxy é derivado; não representa espaço interno medido.",
  "Ranking groups with different evidence/protocols are not comparable.": "Grupos com evidências ou protocolos diferentes não são comparáveis entre si.",
  "Family and road have one eligible configuration each, not sixty.": "Família e Estrada possuem somente uma configuração elegível cada, não sessenta.",
};

function Limitations({ items = [] }) {
  return <details className="academic-limitations"><summary>Limitações documentais e metodológicas</summary>
    <ul>{items.map((item) => <li key={item}>{LIMITATION_TEXT[item] || item}</li>)}</ul>
  </details>;
}

function Evidence({ field, name }) {
  const sources = [...(field?.sources || field?.source_evidence || []),
    ...Object.values(field?.inputs || {}).flatMap((input) => input?.sources || [])];
  const uniqueSources = sources.filter((source, index) => sources.findIndex((item) => item.sha256 === source.sha256 && item.locator === source.locator) === index);
  return <div className="academic-evidence">
    <dt>{FIELD_LABELS[name] || name}</dt>
    <dd>{academicValue(field)} <small>{NATURE_LABELS[field?.nature || field?.kind] || "Natureza não informada"}</small>
      {field?.reason && <small>{field.reason}</small>}
      {field?.formula && <small>Fórmula: {field.formula} · {field.method_version}</small>}
      {field?.inputs && <small>Entradas: {Object.entries(field.inputs).map(([key, input]) => `${FIELD_LABELS[key] || key}: ${academicValue(input)}`).join("; ")}</small>}
      {uniqueSources.map((source, index) => <small key={index}>
        {source.provider} · {source.document} · {source.locator} · {source.collected_at}
        {source.sha256 && <span className="academic-hash">SHA-256: {source.sha256}</span>}
      </small>)}
    </dd>
  </div>;
}

export function AcademicDetail({ state, context, onClose, onRetry, liveEvaluation }) {
  const dialog = useRef(null);
  useEffect(() => {
    const node = dialog.current;
    node.showModal();
    return () => node.close();
  }, []);
  const data = state.data;
  const evaluation = liveEvaluation || data?.evaluations?.[context.scenario]?.[context.profile];
  return <dialog ref={dialog} className="academic-dialog" aria-labelledby="academic-detail-title" onCancel={onClose}>
    <header><div><p className="eyebrow">Detalhes acadêmicos · ID {state.id}</p><h2 id="academic-detail-title">{data?.vehicle?.label || "Carregando veículo"}</h2></div>
      <button type="button" onClick={onClose} autoFocus>Fechar detalhes</button></header>
    <div className="academic-dialog-body">
      {state.loading && <p role="status">Carregando evidências e avaliações…</p>}
      {state.error && <div role="alert"><p>{state.error}</p><button type="button" onClick={onRetry}>Tentar detalhes novamente</button></div>}
      {data && <>
        <p>FIPE {data.vehicle.fipe_code} · ano {data.vehicle.year_code} · referência {data.vehicle.price_reference_month} · {academicCurrency(data.vehicle.purchase_price_brl)}</p>
        <p>ID exclusivo do catálogo acadêmico. Não vincula nem cadastra um veículo em “Meu carro” ou Despesas.</p>
        <h3>{profileName(context.profile)} · cenário {scenarioName(context.scenario)}</h3>
        <p>{evaluation?.academic_test_ready ? "Testável academicamente neste perfil." : "Sem cobertura suficiente para este perfil; não recebe nota inventada."}</p>
        <p>TCO mensal — estimativa de cenário: <strong>{academicCurrency(evaluation?.scenario_monthly_tco_brl)}</strong></p>
        {evaluation && <>
          <p>Cobertura ponderada: {academicNumber(evaluation.coverage?.weighted == null ? null : Number(evaluation.coverage.weighted) * 100)}%. Confiança: rastreabilidade descritiva, não calibrada estatisticamente; sem percentual inventado.</p>
          {!!evaluation.blockers?.length && <p>Bloqueios do contrato: {evaluation.blockers.join("; ")}</p>}
          <h3>Composição do TCO — estimativas de cenário</h3>
          <dl className="academic-specs">{Object.entries(evaluation.scenario_costs?.components || {}).map(([key, field]) => <Evidence key={key} name={key} field={field} />)}</dl>
          <p>Contrato: {evaluation.scenario_costs?.contract_version}. Quilometragem e preço por litro {liveEvaluation ? "foram informados pelo usuário nesta recomendação" : "são parâmetros congelados do cenário"}. As taxas de manutenção, IPVA, seguro e depreciação são hipóteses versionadas; não representam despesas observadas ou lançamento tributário.</p>
          <h3>Critérios e natureza da evidência</h3>
          {evaluation.academic_path === "academic_habitability_proxy" && <p>Habitabilidade derivada (academic_habitability_proxy), não espaço interno medido e não certificação para plataformas de transporte.</p>}
          <dl className="academic-specs">{Object.entries(evaluation.criteria || {}).map(([key, field]) => <Evidence key={key} name={key} field={field} />)}</dl>
        </>}
        <h3>Ficha técnica e proveniência</h3>
        <dl className="academic-specs">{Object.entries(data.evidence.fields).map(([key, field]) => <Evidence key={key} name={key} field={field} />)}</dl>
        <Limitations items={data.limitations} />
      </>}
    </div>
  </dialog>;
}

export function AcademicCard({ vehicle, evaluation, position, onDetails, explanations = [] }) {
  return <article className="academic-card" data-catalog-id={vehicle.catalog_id}>
    <p className="eyebrow">{position ? `Posição ${position} neste grupo` : `Catálogo acadêmico · ID ${vehicle.catalog_id}`}</p>
    <h3>{vehicle.label}</h3>
    <dl><div><dt>Preço FIPE</dt><dd>{academicCurrency(vehicle.purchase_price_brl)}</dd></div>
      <div><dt>Referência individual</dt><dd>{vehicle.price_reference_month}</dd></div>
      <div><dt>Código FIPE / ano</dt><dd>{vehicle.fipe_code} / {vehicle.year_code}</dd></div>
      {evaluation && <>
        <div><dt>TCO mensal · estimativa de cenário</dt><dd>{academicCurrency(evaluation.scenario_monthly_tco_brl)}</dd></div>
        <div><dt>{explanations.length ? "Nota calculada pelo motor" : "Nota diagnóstica acadêmica"}</dt><dd>{academicNumber(evaluation.preview_score)} / 100</dd></div>
        <div><dt>Cobertura ponderada</dt><dd>{academicNumber(evaluation.coverage?.weighted == null ? null : Number(evaluation.coverage.weighted) * 100)}%</dd></div>
      </>}
    </dl>
    {evaluation?.academic_path === "academic_habitability_proxy" && <p>Habitabilidade derivada, não espaço interno medido.</p>}
    {explanations.length > 0 && <details><summary>Por que esta posição?</summary><ul>{explanations.map((item) =>
      <li key={item.criterion}>{FIELD_LABELS[item.criterion] || item.criterion}: utilidade {academicNumber(item.utility)} / 100 · peso efetivo {academicNumber(Number(item.effective_weight) * 100)}% · contribuição {academicNumber(item.contribution)} pontos.</li>)}</ul></details>}
    <button type="button" onClick={() => onDetails(vehicle.catalog_id)} aria-label={`Ver detalhes acadêmicos de ${vehicle.label}`}>Ver detalhes acadêmicos</button>
  </article>;
}

export default function AcademicPage() {
  const [catalog, setCatalog] = useState({ loading: true, metadata: null, vehicles: [], error: "" });
  const [retry, setRetry] = useState(0);
  const [form, setForm] = useState({ ...DEFAULT_ACADEMIC_FORM });
  const [result, setResult] = useState({ loading: false, data: null, error: "" });
  const [detail, setDetail] = useState(null);
  const [page, setPage] = useState(0);
  const loadGate = useRef(createAcademicRequestGate());
  const evaluationGate = useRef(createAcademicRequestGate());
  const detailGate = useRef(createAcademicRequestGate());

  useEffect(() => {
    const request = loadGate.current.begin();
    setCatalog({ loading: true, metadata: null, vehicles: [], error: "" });
    setResult({ loading: false, data: null, error: "" });
    evaluationGate.current.cancel();
    detailGate.current.cancel();
    setDetail(null);
    setPage(0);
    (async () => {
      try {
        const metadata = await requestAcademicMetadata({ signal: request.signal });
        if (!request.isCurrent()) return;
        const vehicles = await requestAcademicCatalog({ signal: request.signal, snapshotId: metadata.snapshot_id, expectedCount: metadata.selected_count, fingerprint: metadata.cohort_fingerprint });
        if (request.isCurrent()) setCatalog({ loading: false, metadata, vehicles, error: "" });
      } catch (error) {
        if (request.isCurrent()) setCatalog({ loading: false, metadata: null, vehicles: [], error: academicError(error) });
      }
    })();
    return () => {
      loadGate.current.cancel();
      evaluationGate.current.cancel();
      detailGate.current.cancel();
    };
  }, [retry]);

  function updateForm(key, value) {
    evaluationGate.current.cancel();
    detailGate.current.cancel();
    setDetail(null);
    setForm((previous) => ({ ...previous, [key]: value }));
    setResult({ loading: false, data: null, error: "" });
  }

  async function evaluate(event) {
    event?.preventDefault();
    if (!catalog.metadata) return;
    const request = evaluationGate.current.begin();
    setResult({ loading: true, data: null, error: "" });
    try {
      const payload = academicPayload(form, catalog.metadata.snapshot_id);
      const data = await requestAcademicEvaluation(payload, { signal: request.signal });
      if (data.cohort_fingerprint !== catalog.metadata.cohort_fingerprint || data.returned_ids.some((id) => !catalog.vehicles.some((vehicle) => vehicle.catalog_id === id))) throw new Error("A avaliação não pertence ao catálogo carregado.");
      if (request.isCurrent()) setResult({ loading: false, data, error: "" });
    } catch (error) {
      if (request.isCurrent()) setResult({ loading: false, data: null, error: academicError(error) });
    }
  }

  async function openDetail(id) {
    const request = detailGate.current.begin();
    setDetail({ id, loading: true, error: "", data: null });
    try {
      const data = await requestAcademicVehicleDetail(id, { snapshotId: catalog.metadata.snapshot_id, signal: request.signal });
      if (data.cohort_fingerprint !== catalog.metadata.cohort_fingerprint) throw new Error("O detalhe não pertence ao catálogo carregado.");
      if (request.isCurrent()) setDetail({ id, loading: false, error: "", data });
    } catch (error) {
      if (request.isCurrent()) setDetail({ id, loading: false, error: academicError(error), data: null });
    }
  }

  const data = result.data;
  const visibleVehicles = catalog.vehicles.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const pages = Math.ceil(catalog.vehicles.length / PAGE_SIZE);
  return <section className="academic-page" aria-labelledby="academic-title">
    <div className="academic-intro"><p className="eyebrow">SIGRA · coorte v6 · ambiente de teste</p><h1 id="academic-title">Teste acadêmico de veículos</h1>
      <p>Explore a coorte publicada para testes do TCC. Este modo não ativa veículos na Gold nem recomenda uma compra operacional.</p>
      <p>TCO: estimativa de cenário. Habitabilidade: indicador derivado, não medição de espaço interno. Os IDs deste catálogo não são IDs de “Meu carro” ou Despesas.</p>
    </div>
    {catalog.loading && <p role="status">Carregando metadados e todas as páginas do catálogo acadêmico…</p>}
    {catalog.error && <div role="alert" className="academic-notice"><p>{catalog.error}</p><button type="button" onClick={() => setRetry((value) => value + 1)}>Tentar carregar novamente</button></div>}
    {catalog.metadata && <>
      <section aria-label="Cobertura dos seis perfis" className="academic-coverage">
        {ACADEMIC_PROFILES.map(([key, name]) => <div key={key}><span>{name}</span><strong>{catalog.metadata.profile_counts[key]} testáveis</strong></div>)}
      </section>
      <Limitations items={catalog.metadata.limitations} />
      <div className="academic-workbench">
        <form onSubmit={evaluate} className="academic-form" aria-label="Avaliação acadêmica">
          <h2>Avaliar cenário</h2>
          <label>Perfil acadêmico<select value={form.profile} onChange={(event) => updateForm("profile", event.target.value)}>{ACADEMIC_PROFILES.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>Cenário de custos<select value={form.scenario} onChange={(event) => updateForm("scenario", event.target.value)}>{ACADEMIC_SCENARIOS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          <label>Limite de compra (R$, opcional)<input type="number" min="0.01" step="0.01" value={form.purchase} onChange={(event) => updateForm("purchase", event.target.value)} /></label>
          <label>Limite de TCO mensal (R$, opcional)<input type="number" min="0.01" step="0.01" value={form.monthly} onChange={(event) => updateForm("monthly", event.target.value)} /></label>
          <label>Resultados por grupo<select value={form.limit} onChange={(event) => updateForm("limit", event.target.value)}>{[10, 20, 60].map((limit) => <option key={limit} value={limit}>{limit}</option>)}</select></label>
          <p>A API utiliza somente esses filtros. Quilometragem, preço por litro e taxas são parâmetros dos cenários versionados; não são alterados por este formulário.</p>
          <button type="submit" disabled={result.loading}>{result.loading ? "Avaliando…" : "Avaliar cenário acadêmico"}</button>
        </form>
        <section className="academic-results" aria-labelledby="academic-results-title" aria-live="polite" aria-busy={result.loading}>
          <h2 id="academic-results-title">Comparação diagnóstica acadêmica</h2>
          {!data && !result.loading && !result.error && <p>Selecione o perfil e cenário, depois avalie. Os grupos comparáveis serão exibidos separadamente, sem ranking entre protocolos incompatíveis.</p>}
          {result.loading && <p role="status">Consultando avaliações do snapshot selecionado…</p>}
          {result.error && <div role="alert"><p>{result.error}</p><button type="button" onClick={evaluate}>Tentar avaliação novamente</button></div>}
          {data && <>
            <p data-testid="academic-evaluation-summary"><strong>{data.eligible_count} elegíveis academicamente</strong> · {data.returned_ids.length} apresentados · {profileName(data.profile)} · cenário {scenarioName(data.scenario)}</p>
            {data.eligible_count === 0 && <p role="status">Nenhum veículo academicamente elegível atende aos limites informados. Ajuste os filtros; não há fallback inelegível.</p>}
            {Object.entries(data.groups).map(([key, group], groupIndex) => <section className="academic-group" key={key} aria-label={`Grupo comparável ${groupIndex + 1}`}>
              <h3>Grupo comparável {groupIndex + 1}</h3><details><summary>Evidências que definem este grupo</summary><p className="academic-hash">{key}</p><p>{group.ties?.length || 0} faixas de empate. As posições são locais a este grupo e definidas pela API.</p></details>
              <div className="academic-grid">{group.ranking.map((row, index) => <AcademicCard key={row.id} vehicle={catalog.vehicles.find((vehicle) => vehicle.catalog_id === row.id)} evaluation={data.evaluations[String(row.id)]} position={index + 1} onDetails={openDetail} />)}</div>
            </section>)}
          </>}
        </section>
      </div>
      <section aria-labelledby="academic-catalog-title" className="academic-catalog">
        <h2 id="academic-catalog-title">Catálogo acadêmico completo</h2>
        <p data-testid="academic-catalog-summary">{catalog.vehicles.length} veículos distintos carregados, sem duplicação. FIPE e mês de referência são individuais.</p>
        {!catalog.vehicles.length && <p role="status">Catálogo vazio neste snapshot.</p>}
        <div className="academic-grid">{visibleVehicles.map((vehicle) => <AcademicCard key={vehicle.catalog_id} vehicle={vehicle} onDetails={openDetail} />)}</div>
        {pages > 0 && <nav className="academic-pagination" aria-label="Páginas do catálogo acadêmico"><button type="button" disabled={page === 0} onClick={() => setPage((value) => value - 1)}>Página anterior</button><span>Página {page + 1} de {pages}</span><button type="button" disabled={page === pages - 1} onClick={() => setPage((value) => value + 1)}>Próxima página</button></nav>}
      </section>
      <details className="academic-snapshot"><summary>Versão e rastreabilidade do snapshot</summary><p>{catalog.metadata.cohort_version}</p><p className="academic-hash">Snapshot: {catalog.metadata.snapshot_id}<br />Coorte: {catalog.metadata.cohort_fingerprint}<br />Método: {catalog.metadata.method_fingerprint}</p><p>{catalog.metadata.holdout_ids?.length} holdouts preservados; zero ativações e zero recomendações operacionais.</p></details>
    </>}
    {detail && <AcademicDetail state={detail} context={form} onClose={() => { detailGate.current.cancel(); setDetail(null); }} onRetry={() => openDetail(detail.id)} />}
  </section>;
}
