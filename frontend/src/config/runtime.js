function isEnabled(value) {
  return String(value || "").trim().toLowerCase() === "true";
}

export const API_URL = import.meta.env?.VITE_API_URL || "http://127.0.0.1:8000";
export const PUBLIC_DEMO_MODE = isEnabled(
  import.meta.env?.VITE_PUBLIC_DEMO_MODE,
);

export const ACADEMIC_TEST_MODE = isEnabled(import.meta.env?.VITE_ACADEMIC_TEST_MODE);
export function initialAcademicMode(hash = "") {
  return ACADEMIC_TEST_MODE || hash === "#academic";
}

// CarPedia is not an active browser integration. The flag exists only so a
// future, contract-backed UI can be introduced without implying availability.
export const CARPEDIA_UI_ENABLED = false;

export { isEnabled };
