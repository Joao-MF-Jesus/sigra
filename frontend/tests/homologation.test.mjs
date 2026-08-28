import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";


const root = path.resolve(import.meta.dirname, "..");


test("Playwright externo nao cria SQLite nem inicia servidores locais", () => {
  const config = fs.readFileSync(path.join(root, "playwright.config.js"), "utf8");
  assert.match(config, /E2E_EXTERNAL_ENVIRONMENT/);
  assert.match(config, /externalEnvironment\s*\?\s*null/);
  assert.match(config, /globalTeardown: externalEnvironment \? undefined/);
  assert.match(config, /webServer: externalEnvironment \? undefined/);
  assert.match(config, /O E2E externo aceita somente URLs HTTPS/);
});


test("suite externa possui seis fluxos seguros sem credenciais administrativas", () => {
  const source = fs.readFileSync(
    path.join(root, "e2e", "homologation.spec.js"),
    "utf8",
  );
  const scenarios = source.match(/\btest\("/g) || [];
  assert.equal(scenarios.length, 6);
  assert.doesNotMatch(source, /admin123|usuario123|password/i);
  assert.match(source, /demo_read_only/);
});
