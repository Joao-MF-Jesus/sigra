function isEnabled(value) {
  return String(value || "").trim().toLowerCase() === "true";
}

export const API_URL = import.meta.env?.VITE_API_URL || "http://127.0.0.1:8000";
export const PUBLIC_DEMO_MODE = isEnabled(
  import.meta.env?.VITE_PUBLIC_DEMO_MODE,
);

export { isEnabled };
