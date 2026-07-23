import React from "react";
import RecommendationResults from "./RecommendationResults.jsx";
import MotorcyclePage from "../motorcycles/MotorcyclePage.jsx";
import { resolveVehicleModule } from "../motorcycles/motorcycleValidation.js";

export default function RecommendationPage(props) {
  if (resolveVehicleModule(props.vehicleType) === "motorcycles") return <MotorcyclePage />;
  return <><div className="section-heading"><p className="eyebrow">Ranking</p><h2>Melhores opções para o perfil informado</h2><p className="section-note">A Nota SIGRA mede compatibilidade com o perfil. A confiança informa a cobertura e a qualidade dos dados utilizados.</p></div><RecommendationResults {...props} /></>;
}
