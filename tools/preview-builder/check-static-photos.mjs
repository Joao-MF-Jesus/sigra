// Exercise the actual source-file selection protocol of the pinned Python SDK.
// This is not a dependency installation, Lambda construction or remote build.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
const require=createRequire(import.meta.url);
const sdk=require('@vercel/build-utils');
const python=require.resolve('@vercel/python');
const official=fs.readFileSync(python,'utf8');
const declared=official.match(/const predefinedExcludes = (\[[\s\S]*?\]);/g);
if(declared?.length!==1) throw new Error('PINNED_BUILDER_FILE_SELECTION_CHANGED');
const predefined=JSON.parse(declared[0].slice('const predefinedExcludes = '.length,-1));
export async function checkStaticPhotoSelection(project) {
const root=fs.realpathSync(project);
const config=JSON.parse(fs.readFileSync(path.join(root,'vercel.json'),'utf8')).functions['api/index.py'];
const base=await sdk.glob('**',{cwd:root,ignore:[...predefined,config.excludeFiles]});
// The official builder merges these after the ignore-filtered default glob.
const included=await sdk.glob(config.includeFiles,{cwd:root});
const selected={...base,...included};
const photos=Object.keys(selected).filter(name=>name.includes('/vehicle-photos/') && name.endsWith('.webp'));
const report={status:photos.length?'STATIC_PHOTOS_WOULD_ENTER_FUNCTION':'STATIC_PHOTOS_EXCLUDED_BY_OFFICIAL_SELECTION',
  source_files:Object.keys(selected).length,photo_files_in_function_selection:photos.length,
  default_glob_photo_count:Object.keys(base).filter(name=>name.includes('/vehicle-photos/')&&name.endsWith('.webp')).length,
  include_glob_photo_count:Object.keys(included).filter(name=>name.includes('/vehicle-photos/')&&name.endsWith('.webp')).length,
  official_python_source_sha256:createHash('sha256').update(official).digest('hex'),
  function_built:false,database_contacted:false,deployment_performed:false};
console.log(JSON.stringify(report,null,2));
if(photos.length) throw new Error('STATIC_PHOTOS_MUST_NOT_ENTER_FUNCTION');
return report;
}
if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  await checkStaticPhotoSelection(process.argv[2]);
}
