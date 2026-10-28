// Local official builder only: no Vercel CLI, account, upload or deployment.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { checkStaticPhotoSelection } from './check-static-photos.mjs';
const require = createRequire(import.meta.url);
const sdk = require('@vercel/build-utils');
const { build } = require('@vercel/python');
const [projectArg, outputArg] = process.argv.slice(2);
if (!projectArg || !outputArg || process.platform !== 'linux' || process.arch !== 'x64') throw new Error('LINUX_AMD64_PROJECT_AND_NEW_OUTPUT_REQUIRED');
const root = fs.realpathSync(projectArg), output = path.resolve(outputArg);
if (fs.existsSync(output)) throw new Error('NEW_BUILDER_OUTPUT_REQUIRED');
const config = JSON.parse(fs.readFileSync(path.join(root, 'vercel.json')));
const includeFiles = config.functions['api/index.py'].includeFiles;
if (typeof includeFiles !== 'string' || includeFiles.length > 256) throw new Error('EFFECTIVE_INCLUDE_SCHEMA_DIFFERS');
await checkStaticPhotoSelection(root);
const files = await sdk.glob('**', { cwd: root, ignore: [
  'application/frontend/node_modules/**', '**/__pycache__/**',
] });
// skipDownload avoids downloading FileFsRef onto itself. Require every ref to
// be the exact, regular source before enabling this official local-build mode.
for (const [name, ref] of Object.entries(files)) {
  const expected = path.join(root, name);
  if (ref.type !== 'FileFsRef' || path.resolve(ref.fsPath) !== expected ||
      fs.lstatSync(expected).isSymbolicLink() || fs.realpathSync(expected) !== expected) {
    throw new Error('LOCAL_BUILDER_FILE_REFERENCE_DIFFERS');
  }
}
if (!files['pyproject.toml'] || !files['api/index.py']) throw new Error('OUTER_PROJECT_REQUIRED');
fs.mkdirSync(output, { recursive: true });
console.log('OFFICIAL_BUILDER_STARTED');
const result = await build({ workPath: root, repoRootPath: root, files,
  entrypoint: 'api/index.py', meta: { skipDownload: true }, config });
const lambda = result?.result?.output;
if (result.resultVersion !== 3 || lambda?.type !== 'Lambda' || lambda.runtime !== 'python3.12') {
  throw new Error('OFFICIAL_PYTHON312_LAMBDA_REQUIRED');
}
const archive = await lambda.createZip();
const archivePath = path.join(output, 'function.zip');
fs.writeFileSync(archivePath, archive);
const materialized = path.join(output, 'function');
await sdk.download(lambda.files, materialized, {});
const receipt = { status: 'OFFICIAL_FUNCTION_CONSTRUCTED', runtime: lambda.runtime,
  python_builder: '25.1.3', build_utils: '14.21.3', zip_bytes: archive.length,
  zip_sha256: createHash('sha256').update(archive).digest('hex'), network_public_registries_only: true,
  deployment_performed: false, database_contacted: false };
fs.writeFileSync(path.join(output, 'builder-receipt.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt));
