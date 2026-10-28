import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import VehicleCard from '../../src/features/recommendations/VehicleCard.jsx';
import RecommendationDetails from '../../src/features/recommendations/RecommendationDetails.jsx';
import VehiclePhoto from '../../src/features/vehicle-images/VehiclePhoto.jsx';
import manifest from '../../src/features/vehicle-images/vehiclePhotos.json';
import '../../src/styles.css';
import './style.css';

// Presentation fixture only. No API, calculation, session, database or saved run.
const items = manifest.vehicles.map((row) => ({
  vehicle: { identity_namespace: 'academic_v6', catalog_id: row.catalogId, label: row.label,
    year_code: row.yearCode, canonical_identity_key: row.canonicalIdentityKey },
  score: null, monthly_total_cost: null, evaluation: { scenario_costs: { components: {} } },
}));
const unavailableItem = { vehicle: { identity_namespace: 'academic_v6', catalog_id: 999,
  label: 'Veículo de teste sem foto admitida' }, score: null,
  evaluation: { scenario_costs: { components: {} } } };
function Fixture() {
  const [detail, setDetail] = useState(null);
  const [single, setSingle] = useState(items[0]);
  return <main className="photo-fixture">
    <header><p className="eyebrow">SIGRA · fixture visual local</p><h1>Fotografias do catálogo</h1>
      <p>Sem API nem cálculo. Notas e valores indisponíveis nesta fixture não são resultados do motor.</p></header>
    <section aria-label="Recuperação da imagem" className="photo-fixture-switch">
      <button onClick={()=>setSingle(items[0])}>Mostrar Prisma</button>
      <button onClick={()=>setSingle(items[1])}>Mostrar Cobalt</button>
      <button onClick={()=>setDetail(unavailableItem)}>Detalhes sem foto admitida</button>
      <div data-testid="switch-photo"><VehiclePhoto vehicle={single.vehicle} /></div>
    </section>
    <section className="recommendation-grid photo-fixture-grid" aria-label="Catálogo de 60 veículos">
      {items.map((item,index)=><div key={item.vehicle.catalog_id} data-catalog-id={item.vehicle.catalog_id}>
        <VehicleCard item={item} index={index} onDetails={setDetail} />
      </div>)}
    </section>
    <RecommendationDetails item={detail} metadata={{}} profile={{}} onClose={()=>setDetail(null)} />
  </main>;
}
createRoot(document.getElementById('root')).render(<Fixture />);
