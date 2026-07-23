import { createServer } from "vite";
import path from "node:path";
import { fileURLToPath } from "node:url";


const backendHealthUrl = process.env.SIGRA_E2E_BACKEND_HEALTH_URL || "http://127.0.0.1:8010/health";
const frontendPort = Number(process.env.SIGRA_E2E_FRONTEND_PORT || 4183);
const deadline = Date.now() + 120_000;
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");


async function waitForBackend() {
  let lastError;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(backendHealthUrl);
      if (response.ok) return;
      lastError = new Error(`health check returned HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Backend E2E did not become healthy at ${backendHealthUrl}: ${lastError?.message || "timeout"}`);
}


await waitForBackend();
const server = await createServer({
  root: frontendRoot,
  server: { host: "127.0.0.1", port: frontendPort, strictPort: true },
});
await server.listen();

const close = async () => {
  await server.close();
  process.exit(0);
};
process.once("SIGINT", close);
process.once("SIGTERM", close);

console.log(`SIGRA E2E frontend ready at http://127.0.0.1:${frontendPort}`);
