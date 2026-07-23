import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  cleanupE2EEnvironment,
  prepareE2EEnvironment,
  removeFileWithRetries,
  reusePreparedE2EEnvironment,
  shutdownE2EEnvironment,
  waitForPortsReleased,
} from "../e2e/environment.js";


test("ambiente E2E cria tmp, remove banco anterior e produz DATABASE_URL absoluta", () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "sigra-e2e-config-"));
  const expectedDirectory = path.join(rootDir, "tmp");
  const expectedDatabase = path.join(expectedDirectory, "sigra-e2e-controlled.db");
  fs.mkdirSync(expectedDirectory, { recursive: true });
  fs.writeFileSync(expectedDatabase, "stale database");
  fs.writeFileSync(`${expectedDatabase}-wal`, "stale wal");

  const result = prepareE2EEnvironment({ rootDir, runId: "controlled" });

  assert.equal(result.temporaryDirectory, expectedDirectory);
  assert.equal(result.databasePath, expectedDatabase);
  assert.equal(fs.existsSync(expectedDirectory), true);
  assert.equal(fs.existsSync(expectedDatabase), false);
  assert.equal(fs.existsSync(`${expectedDatabase}-wal`), false);
  assert.match(result.databaseUrl, /^sqlite:\/\/\//);
  assert.match(result.databaseUrl, /sigra-e2e-controlled\.db$/);
});


test("execuções concorrentes recebem bancos diferentes", () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "sigra-e2e-concurrency-"));
  const first = prepareE2EEnvironment({ rootDir, runId: "run-1" });
  const second = prepareE2EEnvironment({ rootDir, runId: "run-2" });
  assert.notEqual(first.databasePath, second.databasePath);
});


test("worker reutiliza banco preparado sem tentar removê-lo", () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "sigra-e2e-reuse-"));
  const prepared = prepareE2EEnvironment({ rootDir, runId: "shared-run" });
  fs.writeFileSync(prepared.databasePath, "active database");

  const reused = reusePreparedE2EEnvironment({
    rootDir,
    databasePath: prepared.databasePath,
  });

  assert.equal(reused.databasePath, prepared.databasePath);
  assert.equal(fs.readFileSync(prepared.databasePath, "utf8"), "active database");
});


test("limpeza E2E remove somente banco, WAL e SHM controlados", async () => {
  const rootDir = fs.mkdtempSync(path.join(os.tmpdir(), "sigra-e2e-cleanup-"));
  const result = prepareE2EEnvironment({ rootDir, runId: "cleanup" });
  const unrelatedFile = path.join(result.temporaryDirectory, "keep.txt");
  fs.writeFileSync(result.databasePath, "database");
  fs.writeFileSync(`${result.databasePath}-wal`, "wal");
  fs.writeFileSync(`${result.databasePath}-shm`, "shm");
  fs.writeFileSync(unrelatedFile, "keep");

  await cleanupE2EEnvironment({ databasePath: result.databasePath });

  assert.equal(fs.existsSync(result.databasePath), false);
  assert.equal(fs.existsSync(`${result.databasePath}-wal`), false);
  assert.equal(fs.existsSync(`${result.databasePath}-shm`), false);
  assert.equal(fs.existsSync(unrelatedFile), true);
});


test("remoção E2E repete EPERM e EBUSY com espera progressiva", async () => {
  const attempts = [];
  const waits = [];
  await removeFileWithRetries("temporary.db", {
    removeFile: async () => {
      attempts.push(attempts.length + 1);
      if (attempts.length < 3) {
        const error = new Error("locked");
        error.code = attempts.length === 1 ? "EPERM" : "EBUSY";
        throw error;
      }
    },
    wait: async (milliseconds) => waits.push(milliseconds),
  });

  assert.equal(attempts.length, 3);
  assert.deepEqual(waits, [250, 500]);
});


test("ENOENT é sucesso e EPERM persistente preserva diagnóstico", async () => {
  const missing = new Error("missing");
  missing.code = "ENOENT";
  const result = await removeFileWithRetries("missing.db", {
    removeFile: async () => {
      throw missing;
    },
  });
  assert.equal(result.attempts, 1);

  const locked = new Error("locked");
  locked.code = "EPERM";
  await assert.rejects(
    removeFileWithRetries("locked.db", {
      maxAttempts: 3,
      removeFile: async () => {
        throw locked;
      },
      wait: async () => {},
    }),
    /locked\.db.*3 tentativa.*EPERM.*preservado/,
  );
});


test("teardown Windows libera as duas portas antes de apagar o SQLite", async () => {
  const events = [];
  const result = await shutdownE2EEnvironment({
    databasePath: "temporary.db",
    ports: [8010, 4183],
    platform: "win32",
    terminateServers: ({ ports }) => {
      events.push(`terminate:${ports.join(",")}`);
      return [{ processId: 123, processName: "python.exe", ports: [8010] }];
    },
    waitForPorts: async ({ ports }) => {
      events.push(`ports:${ports.join(",")}`);
    },
    cleanupFiles: async ({ databasePath }) => {
      events.push(`cleanup:${databasePath}`);
      return [];
    },
  });

  assert.deepEqual(events, [
    "terminate:8010,4183",
    "ports:8010,4183",
    "cleanup:temporary.db",
  ]);
  assert.equal(result.terminatedProcesses[0].processName, "python.exe");
});


test("porta persistente bloqueia limpeza e preserva banco temporário", async () => {
  let checks = 0;
  await assert.rejects(
    waitForPortsReleased({
      ports: [8010, 4183],
      maxAttempts: 2,
      checkPort: async (port) => {
        checks += 1;
        return port === 8010;
      },
      wait: async () => {},
    }),
    /8010.*permaneceram.*preservado/,
  );
  assert.equal(checks, 4);
});
