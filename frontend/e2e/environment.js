import { execFileSync } from "node:child_process";
import fs from "node:fs";
import net from "node:net";
import path from "node:path";

const E2E_DATABASE_SUFFIXES = ["-wal", "-shm", ""];
const RETRYABLE_DELETE_ERRORS = new Set(["EPERM", "EBUSY"]);


function sanitizeRunId(value) {
  const sanitized = String(value).replace(/[^a-zA-Z0-9_-]/g, "-");
  return sanitized || "local";
}


function describeE2EEnvironment({ rootDir, databasePath }) {
  const temporaryDirectory = path.resolve(rootDir, "tmp");
  const resolvedDatabasePath = path.resolve(databasePath);
  if (
    path.dirname(resolvedDatabasePath) !== temporaryDirectory
    || !/^sigra-e2e-[a-zA-Z0-9_-]+\.db$/.test(path.basename(resolvedDatabasePath))
  ) {
    throw new Error(`Invalid E2E database path: ${resolvedDatabasePath}`);
  }

  return {
    temporaryDirectory,
    databasePath: resolvedDatabasePath,
    databaseUrl: `sqlite:///${resolvedDatabasePath.replaceAll("\\", "/")}`,
  };
}


function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}


function portFromEndpoint(endpoint) {
  const separator = endpoint.lastIndexOf(":");
  return separator >= 0 ? Number(endpoint.slice(separator + 1)) : Number.NaN;
}


function getWindowsProcessName(processId) {
  try {
    const output = execFileSync(
      "tasklist.exe",
      ["/FI", `PID eq ${processId}`, "/FO", "CSV", "/NH"],
      { encoding: "utf8", windowsHide: true },
    );
    return output.match(/^"([^"]+)"/m)?.[1] || "processo desconhecido";
  } catch {
    return "processo desconhecido";
  }
}


export function getWindowsPortOwners({ ports } = {}) {
  if (process.platform !== "win32") return [];

  const expectedPorts = new Set((ports || []).map(Number));
  const output = execFileSync("netstat.exe", ["-ano", "-p", "tcp"], {
    encoding: "utf8",
    windowsHide: true,
  });
  const owners = new Map();

  for (const line of output.split(/\r?\n/)) {
    const columns = line.trim().split(/\s+/);
    if (columns.length < 5 || columns[0]?.toUpperCase() !== "TCP") continue;

    const port = portFromEndpoint(columns[1]);
    const processId = Number(columns.at(-1));
    if (!expectedPorts.has(port) || !Number.isInteger(processId) || processId <= 0) continue;

    const existing = owners.get(processId) || {
      processId,
      processName: getWindowsProcessName(processId),
      ports: [],
    };
    if (!existing.ports.includes(port)) existing.ports.push(port);
    owners.set(processId, existing);
  }

  return [...owners.values()];
}


export function terminateWindowsPortOwners({ ports } = {}) {
  const owners = getWindowsPortOwners({ ports });

  for (const owner of owners) {
    console.info(
      `[SIGRA E2E] Encerrando ${owner.processName} (PID ${owner.processId}) `
      + `nas portas ${owner.ports.join(", ")}.`,
    );
    try {
      execFileSync(
        "taskkill.exe",
        ["/PID", String(owner.processId), "/T", "/F"],
        { encoding: "utf8", stdio: "pipe", windowsHide: true },
      );
    } catch (error) {
      const stillListening = getWindowsPortOwners({ ports })
        .some(({ processId }) => processId === owner.processId);
      if (stillListening) {
        const detail = new Error(
          `Não foi possível encerrar ${owner.processName} (PID ${owner.processId}) `
          + `nas portas ${owner.ports.join(", ")}.`,
          { cause: error },
        );
        detail.code = error.code;
        throw detail;
      }
    }
  }

  return owners;
}


export function isPortListening(port, { host = "127.0.0.1", timeoutMs = 500 } = {}) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    let settled = false;
    const finish = (listening) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(listening);
    };

    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}


export async function waitForPortsReleased({
  ports,
  maxAttempts = 20,
  baseDelayMs = 250,
  checkPort = isPortListening,
  wait = delay,
} = {}) {
  const expectedPorts = (ports || []).map(Number);

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const states = await Promise.all(
      expectedPorts.map(async (port) => ({ port, listening: await checkPort(port) })),
    );
    const busyPorts = states.filter(({ listening }) => listening).map(({ port }) => port);
    if (busyPorts.length === 0) return;

    if (attempt < maxAttempts) {
      await wait(Math.min(baseDelayMs * attempt, 1_000));
      continue;
    }

    throw new Error(
      `As portas E2E ${busyPorts.join(", ")} permaneceram ocupadas após `
      + `${maxAttempts} verificações. O banco temporário foi preservado para diagnóstico.`,
    );
  }
}


export async function removeFileWithRetries(filePath, {
  maxAttempts = 20,
  baseDelayMs = 250,
  removeFile = fs.promises.rm,
  wait = delay,
} = {}) {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      await removeFile(filePath, { force: true });
      return { filePath, attempts: attempt };
    } catch (error) {
      if (error.code === "ENOENT") return { filePath, attempts: attempt };

      const retryable = RETRYABLE_DELETE_ERRORS.has(error.code);
      if (!retryable || attempt === maxAttempts) {
        const detail = new Error(
          `Falha ao remover ${filePath} após ${attempt} tentativa(s): `
          + `${error.code || error.name}. O arquivo foi preservado para diagnóstico.`,
          { cause: error },
        );
        detail.code = error.code;
        detail.filePath = filePath;
        detail.attempts = attempt;
        throw detail;
      }

      await wait(Math.min(baseDelayMs * attempt, 1_000));
    }
  }
}


export function prepareE2EEnvironment({ rootDir, runId = process.env.SIGRA_E2E_RUN_ID || process.pid } = {}) {
  if (!rootDir) throw new Error("rootDir is required to prepare the E2E environment");

  const temporaryDirectory = path.resolve(rootDir, "tmp");
  fs.mkdirSync(temporaryDirectory, { recursive: true });

  const databasePath = path.join(temporaryDirectory, `sigra-e2e-${sanitizeRunId(runId)}.db`);
  for (const suffix of E2E_DATABASE_SUFFIXES) {
    fs.rmSync(`${databasePath}${suffix}`, { force: true });
  }

  return describeE2EEnvironment({ rootDir, databasePath });
}


export function reusePreparedE2EEnvironment({ rootDir, databasePath } = {}) {
  if (!rootDir) throw new Error("rootDir is required to reuse the E2E environment");
  if (!databasePath) {
    throw new Error("databasePath is required to reuse the E2E environment");
  }
  return describeE2EEnvironment({ rootDir, databasePath });
}


export async function cleanupE2EEnvironment({
  databasePath,
  removeFile = removeFileWithRetries,
} = {}) {
  if (!databasePath) {
    throw new Error("databasePath is required to clean the E2E environment");
  }

  const removedFiles = [];
  for (const suffix of E2E_DATABASE_SUFFIXES) {
    removedFiles.push(await removeFile(`${databasePath}${suffix}`));
  }
  return removedFiles;
}


export async function shutdownE2EEnvironment({
  databasePath,
  ports,
  platform = process.platform,
  terminateServers = terminateWindowsPortOwners,
  waitForPorts = waitForPortsReleased,
  cleanupFiles = cleanupE2EEnvironment,
} = {}) {
  if (!databasePath) {
    throw new Error("databasePath is required to shut down the E2E environment");
  }

  const expectedPorts = (ports || []).map(Number);
  let terminatedProcesses = [];
  if (platform === "win32") {
    terminatedProcesses = terminateServers({ ports: expectedPorts });
    await waitForPorts({ ports: expectedPorts });
  }

  const removedFiles = await cleanupFiles({ databasePath });
  return { terminatedProcesses, removedFiles };
}
