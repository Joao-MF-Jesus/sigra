import { shutdownE2EEnvironment } from "./environment.js";


export default async function globalTeardown() {
  const backendPort = Number(process.env.SIGRA_E2E_BACKEND_PORT || 8010);
  const frontendPort = Number(process.env.SIGRA_E2E_FRONTEND_PORT || 4183);
  const result = await shutdownE2EEnvironment({
    databasePath: process.env.SIGRA_E2E_DATABASE_PATH,
    ports: [backendPort, frontendPort],
  });
  const processSummary = result.terminatedProcesses.length > 0
    ? result.terminatedProcesses
      .map(({ processName, processId }) => `${processName} (PID ${processId})`)
      .join(", ")
    : "nenhum listener ativo";
  console.info(
    `[SIGRA E2E] Teardown concluído; processos: ${processSummary}; `
    + `portas ${backendPort}/${frontendPort} liberadas; `
    + `${result.removedFiles.length} arquivos SQLite verificados.`,
  );
}
