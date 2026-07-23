import React, { useEffect, useState } from "react";
import { requestMotorcycleCatalog } from "../../api/sigraApi.js";
import MotorcycleList from "./MotorcycleList.jsx";

export default function MotorcyclePage() {
  const [motorcycles, setMotorcycles] = useState([]);
  const [metadata, setMetadata] = useState(null);
  const [state, setState] = useState("loading");
  const [showTechnical, setShowTechnical] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setState("loading");
    requestMotorcycleCatalog({ signal: controller.signal, includeLegacy: showTechnical })
      .then((catalog) => { setMotorcycles(catalog.motorcycles); setMetadata(catalog); setState("ready"); })
      .catch((error) => { if (error?.name !== "AbortError") setState("error"); });
    return () => controller.abort();
  }, [showTechnical]);
  return <section className="motorcycle-page" data-testid="motorcycle-development-page">
    <div className="section-heading"><p className="eyebrow">Próxima categoria</p><h2>Motocicletas cadastradas para desenvolvimento</h2><p className="section-note"><strong>Módulo em desenvolvimento.</strong> O cadastro e a estrutura de dados de motocicletas estão disponíveis. O mecanismo de recomendação ainda não foi implementado.</p></div>
    <label className="motorcycle-technical-toggle"><input type="checkbox" checked={showTechnical} onChange={(event) => setShowTechnical(event.target.checked)} /> Exibir dados legados no modo técnico</label>
    {state === "loading" && <div className="recommendation-state">Carregando cadastros técnicos...</div>}
    {state === "error" && <div className="api-error">Não foi possível carregar as motocicletas cadastradas.</div>}
    {state === "ready" && <MotorcycleList motorcycles={motorcycles} metadata={metadata} showTechnical={showTechnical} />}
  </section>;
}
