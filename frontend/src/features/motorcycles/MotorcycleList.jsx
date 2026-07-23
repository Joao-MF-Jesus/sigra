import React from "react";
import MotorcycleCard from "./MotorcycleCard.jsx";

export default function MotorcycleList({ motorcycles, metadata, showTechnical = false }) {
  const returned = metadata?.returned ?? motorcycles.length;
  const validRecords = metadata?.valid_records ?? motorcycles.length;
  const invalidRecords = metadata?.invalid_records ?? 0;
  const totalFound = metadata?.total_found ?? returned;
  return <>
    <div className="motorcycle-processing" aria-live="polite">
      <p><strong>{validRecords} de {returned} registros desta página estão disponíveis.</strong></p>
      <p>{totalFound} registro(s) encontrado(s) no total.</p>
      {invalidRecords > 0 && <p className="motorcycle-invalid-warning">{invalidRecords} registro(s) foram desconsiderados devido a dados inválidos ou incompletos.</p>}
    </div>
    {motorcycles.length === 0
      ? <div className="recommendation-empty-state"><strong>Nenhuma motocicleta válida disponível nesta página.</strong><p>A carga demonstrativa é opcional e executada manualmente.</p></div>
      : <div className="motorcycle-grid">{motorcycles.map((motorcycle) => <MotorcycleCard key={motorcycle.id} motorcycle={motorcycle} showTechnical={showTechnical} />)}</div>}
  </>;
}
