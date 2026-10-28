import manifest from "./vehiclePhotos.json" with { type: "json" };

// IDs from the academic catalog must never alias operational vehicle IDs.
export function resolveVehiclePhoto(vehicle) {
  if (!vehicle || typeof vehicle !== "object") return null;
  let entry;
  if (vehicle.identity_namespace === "academic_v6") {
    entry = manifest.vehicles.find((row) =>
      Number.isInteger(vehicle.catalog_id) && row.catalogId === vehicle.catalog_id
      && row.label === vehicle.label
      && (vehicle.payload_fingerprint === undefined || vehicle.payload_fingerprint === row.payloadFingerprint)
      && (vehicle.year_code === undefined || vehicle.year_code === row.yearCode)
      && (vehicle.canonical_identity_key === undefined || vehicle.canonical_identity_key === row.canonicalIdentityKey));
  } else if (vehicle.identity_namespace === undefined && vehicle.catalog_id === undefined) {
    // Explicit tuples reviewed against local sample_data.py, not fuzzy names or IDs.
    const alias = manifest.operationalAliases.find((row) => row.brand === vehicle.brand
      && row.model === vehicle.model && row.year === vehicle.year);
    if (alias) entry = manifest.vehicles.find((row) => row.catalogId === alias.catalogId);
  }
  const photo = entry && manifest.photos[entry.imageGroup];
  return photo ? { ...photo, imageGroup: entry.imageGroup, catalogId: entry.catalogId } : null;
}

export function vehiclePhotoLabel(vehicle) {
  return vehicle?.label || [vehicle?.brand, vehicle?.model, vehicle?.year].filter(Boolean).join(" ") || "Veículo";
}
