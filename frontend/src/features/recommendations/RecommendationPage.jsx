import React from "react";
import RecommendationResults from "./RecommendationResults.jsx";
import MotorcyclePage from "../motorcycles/MotorcyclePage.jsx";
import { resolveVehicleModule } from "../motorcycles/motorcycleValidation.js";
import { getMultifactorCoverage } from "./recommendationModel.js";

export default function RecommendationPage(props) {
  if (resolveVehicleModule(props.vehicleType) === "motorcycles") return <MotorcyclePage />;
  const multifactor = getMultifactorCoverage(props.state?.recommendations, props.state?.metadata).hasScores;
  return <><div className="section-heading result-heading"><p className="eyebrow">Resultado explicado</p><h2>{multifactor ? "Comparação multifator para o cenário informado" : "Opções para o perfil informado"}</h2><p className="section-note">{multifactor ? "O ranking combina critérios do recomendador e custo calculado no backend para o mesmo cenário. A posição original permanece visível para comparação." : "A Nota SIGRA mostra aderência ao perfil; a confiança mostra a cobertura e a qualidade das evidências."}</p></div><ol className="recommendation-journey" aria-label="Jornada da recomendação"><li><strong>Informe</strong><span>necessidade e limites</span></li><li><strong>Entenda</strong><span>ranking e evidências</span></li><li><strong>Aprofunde</strong><span>detalhes e simulação</span></li></ol><RecommendationResults {...props} /></>;
}
