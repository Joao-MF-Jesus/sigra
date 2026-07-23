export const VEHICLE_TYPES = Object.freeze({ CAR: "car", MOTORCYCLE: "motorcycle" });

export function resolveVehicleModule(vehicleType) {
  return vehicleType === VEHICLE_TYPES.MOTORCYCLE ? "motorcycles" : "cars";
}

export function shouldRequestCarRecommendations(vehicleType) {
  return resolveVehicleModule(vehicleType) === "cars";
}
